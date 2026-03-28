"""
Email Agent v2 — natural language interface to Gmail.

v2 additions:
- Read full email body (not just snippet)
- Urgency triage on unread list (🔴 / 🟡 / ⚪)
- Reply to existing thread
- "Needs reply" action — surface emails awaiting response
- run_morning_digest() for proactive 7:50 AM push
- Draft confirm "send it" flow
"""

import json
import logging
import os
from pathlib import Path
from core.llm import chat
from integrations.google.auth import is_configured

logger = logging.getLogger(__name__)

_DRAFT_STATE_PATH = Path(__file__).parent.parent.parent / "data" / "email_draft_state.json"


def _save_draft_state(state: dict) -> None:
    """Persist the last draft/reply so 'send it' can retrieve it."""
    try:
        _DRAFT_STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        _DRAFT_STATE_PATH.write_text(json.dumps(state))
    except Exception:
        pass


def _load_draft_state() -> dict:
    """Load the last saved draft/reply state."""
    try:
        if _DRAFT_STATE_PATH.exists():
            return json.loads(_DRAFT_STATE_PATH.read_text())
    except Exception:
        pass
    return {}

SYSTEM = """You are Justin Ngai's executive email assistant. You help draft, send, and manage his Gmail.

Justin's context:
- Healthcare operations professional (day job — keep work emails professional)
- Has a hospital infusion consulting side business (keep SEPARATE from day job employer)
- Also does: mortgage note investing, stock investing, award travel
- Tone: professional but direct, not overly formal
- Signs emails as: Justin

When drafting emails:
- Match appropriate tone (formal for clients/execs, casual for friends)
- Keep emails concise — he values brevity
- For infusion consulting: frame as independent consultant, never mention employer
- Always confirm recipient + subject before sending

When summarizing emails:
- Lead with who and what, then urgency
- Flag: needs reply, urgent, or FYI"""


PARSE_PROMPT = """Extract email action from this message. Return JSON only.

Return:
{
  "action": "draft" | "send" | "list_unread" | "search" | "read" | "reply" | "needs_reply" | "followup_scan" | "calendar_invite" | "confirm_scan" | "question",
  "to": "recipient email or name",
  "title": "event title if calendar_invite",
  "subject": "email subject",
  "body_request": "what the email should say",
  "search_query": "gmail search query if searching",
  "email_ref": "keyword or number to identify which email",
  "date": "YYYY-MM-DD if mentioned",
  "time": "HH:MM 24h if mentioned",
  "duration_minutes": 60,
  "send_immediately": false
}

Today is DATE_PLACEHOLDER. Timezone: Eastern Time.

Date resolution: "today"→today, "tomorrow"→tomorrow, day names→next occurrence.

Examples:
"Check my unread emails" → {"action":"list_unread"}
"Read the email from Marcus" → {"action":"read","email_ref":"Marcus"}
"Read email 2" → {"action":"read","email_ref":"2"}
"Who needs a reply?" → {"action":"needs_reply"}
"Any emails I should follow up on?" → {"action":"followup_scan"}
"What emails need follow up?" → {"action":"followup_scan"}
"Reply to the Acme email saying I'll call Thursday" → {"action":"reply","email_ref":"Acme","body_request":"I'll call Thursday"}
"Draft an email to John saying I'll be late" → {"action":"draft","to":"John","subject":"Running Late","body_request":"Tell him I'll be late"}
"Send a calendar invite to Alex for dinner Friday 7pm" → {"action":"calendar_invite","to":"Alex","title":"Dinner","date":"FRIDAY_DATE","time":"19:00","duration_minutes":120}
"Send Marcus a meeting invite for Monday 10am" → {"action":"calendar_invite","to":"Marcus","title":"Meeting with Marcus","date":"MONDAY_DATE","time":"10:00"}
"Any emails I should follow up on?" → {"action":"followup_scan"}
"Scan for confirmation emails" → {"action":"confirm_scan"}
"Any confirmations in my inbox?" → {"action":"confirm_scan"}
"Any emails from Marcus this week?" → {"action":"search","search_query":"from:Marcus newer_than:7d"}
"""


# Stores last unread list for "read email 2" style references
_last_email_list: list[dict] = []


def _parse_request(message: str) -> dict:
    import datetime
    today = datetime.date.today()
    prompt = PARSE_PROMPT.replace("DATE_PLACEHOLDER", today.strftime("%Y-%m-%d (%A)"))
    # Also replace day name placeholders like FRIDAY_DATE, MONDAY_DATE
    for i in range(7):
        d = today + datetime.timedelta(days=i)
        day_name = d.strftime("%A").upper() + "_DATE"
        prompt = prompt.replace(day_name, d.strftime("%Y-%m-%d"))
    for i in range(7):
        d = today + datetime.timedelta(days=7 + i)
        day_name = "NEXT_" + d.strftime("%A").upper() + "_DATE"
        prompt = prompt.replace(day_name, d.strftime("%Y-%m-%d"))

    raw = chat(prompt, message, max_tokens=300)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    try:
        return json.loads(raw)
    except Exception:
        return {"action": "question"}


def _draft_email_body(to: str, subject: str, body_request: str) -> str:
    """Use LLM to write the actual email body."""
    prompt = (
        f"Write a professional email from Justin Ngai.\n"
        f"To: {to}\n"
        f"Subject: {subject}\n"
        f"Instructions: {body_request}\n\n"
        f"Write ONLY the email body (no subject line, no 'To:' header). "
        f"Sign off as 'Justin'. Keep it concise."
    )
    return chat(SYSTEM, prompt, max_tokens=400)


def _resolve_email_ref(ref: str, emails: list[dict]) -> dict | None:
    """Resolve 'email 2' or 'email from Marcus' to an actual email dict."""
    if not emails:
        return None
    # Numeric reference
    try:
        idx = int(ref.strip()) - 1
        if 0 <= idx < len(emails):
            return emails[idx]
    except ValueError:
        pass
    # Keyword match
    ref_lower = ref.lower()
    for e in emails:
        if (ref_lower in e.get("from", "").lower() or
                ref_lower in e.get("subject", "").lower()):
            return e
    return None


def _find_contact_email(name: str) -> list[dict]:
    """Look up a person's email by searching both Gmail accounts."""
    from integrations.google.gmail_client import find_contact_emails
    return find_contact_emails(name)


def _send_calendar_invite(state: dict) -> str:
    """Create a Google Calendar event with attendee from saved state."""
    from integrations.google.calendar_client import create_event
    import datetime

    to_email = state.get("to_email", "")
    to_name = state.get("to_name", to_email)
    title = state.get("title", f"Meeting with {to_name}")
    date = state.get("date", "")
    time_str = state.get("time", "")
    duration = state.get("duration", 60)

    if not date:
        return "⚠️ I need a date for the invite. What date works?"

    if time_str and ":" in time_str:
        start_iso = f"{date}T{time_str}:00"
        h, m = int(time_str[:2]), int(time_str[3:5])
        total_min = h * 60 + m + duration
        end_iso = f"{date}T{total_min // 60:02d}:{total_min % 60:02d}:00"
    else:
        start_iso = date
        end_iso = date

    event = create_event(
        title=title,
        start=start_iso,
        end=end_iso,
        description=f"Calendar invite for {to_name}",
        attendees=[to_email],
    )

    if event:
        import datetime as _dt
        try:
            d = _dt.date.fromisoformat(date)
            day_str = d.strftime("%A, %B %-d")
        except Exception:
            day_str = date
        time_display = ""
        if time_str:
            try:
                h, m = int(time_str[:2]), int(time_str[3:5])
                period = "am" if h < 12 else "pm"
                h12 = h % 12 or 12
                time_display = f" at {h12}:{m:02d}{period}"
            except Exception:
                time_display = f" at {time_str}"
        _DRAFT_STATE_PATH.unlink(missing_ok=True)
        return (
            f"✅ *Calendar invite sent!*\n\n"
            f"📅 {title}\n"
            f"👤 {to_name} ({to_email})\n"
            f"🗓 {day_str}{time_display}\n\n"
            f"_They'll receive a Google Calendar invite via email_"
        )
    return "⚠️ Couldn't create the calendar event. Check Google Calendar permissions."


def handle(message: str) -> str:
    global _last_email_list

    if not is_configured():
        return (
            "⚠️ Gmail not connected yet.\n\n"
            "Run `python scripts/google_auth.py` to authorize."
        )

    from integrations.google.gmail_client import (
        send_email, create_draft, list_unread, list_unread_all_accounts,
        scan_confirmation_emails, search_emails, format_emails,
        get_email_body, reply_to_email, list_needs_reply, _triage_urgency,
        is_confirmation_email
    )
    from integrations.google.auth import is_configured as google_is_configured

    parsed = _parse_request(message)
    action = parsed.get("action", "question")

    # ── List unread across both accounts ─────────────────────────────────────
    if action == "list_unread":
        emails = list_unread_all_accounts(max_results=10)
        _last_email_list = emails
        if not emails:
            return "📭 Inbox zero across both accounts — nothing unread!"

        # Group by account for display
        jyn = [e for e in emails if "jynpriority" in e.get("account", "")]
        j53 = [e for e in emails if "jngai5.3" in e.get("account", "")]

        lines = [f"📬 *Unread ({len(emails)} total)*\n"]

        if jyn:
            lines.append(f"*jynpriority@gmail.com ({len(jyn)}):*")
            lines.append(format_emails(jyn, triage=True))

        if j53:
            lines.append(f"\n*jngai5.3@gmail.com ({len(j53)}):*")
            lines.append(format_emails(j53, triage=True))

        lines.append("\n_🔴 urgent · 🟡 needs reply · ⚪ FYI_")
        lines.append("_Reply 'read 2' to open any email_")
        return "\n".join(lines)

    # ── Read full email body ─────────────────────────────────────────────────
    elif action == "read":
        ref = parsed.get("email_ref", "")
        if not ref:
            return "Which email? Give me a number (e.g. 'read 2') or keyword (e.g. 'read the Marcus email')."
        if not _last_email_list:
            _last_email_list = list_unread(max_results=8)
        match = _resolve_email_ref(ref, _last_email_list)
        if not match:
            # Try searching both accounts
            for acct in ["primary", "secondary"]:
                results = search_emails(ref, max_results=1, account=acct)
                if results:
                    results[0].setdefault("account", "jynpriority@gmail.com" if acct == "primary" else "jngai5.3@gmail.com")
                    match = results[0]
                    break
        if not match:
            return f"Couldn't find an email matching '{ref}'. Try 'check unread' first."
        acct = "secondary" if "jngai5.3" in match.get("account", "") else "primary"
        full = get_email_body(match["id"], account=acct)
        if not full:
            return "⚠️ Couldn't retrieve that email."
        sender = full["from"].split("<")[0].strip() or full["from"]
        body = full.get("body", "").strip()[:1200]
        if len(full.get("body", "")) > 1200:
            body += "\n\n_[truncated — showing first 1200 chars]_"
        return (
            f"📧 *{full['subject']}*\n"
            f"From: {sender}\n"
            f"─────────────────\n"
            f"{body}"
        )

    # ── Needs reply ──────────────────────────────────────────────────────────
    elif action == "needs_reply":
        emails = list_needs_reply(max_results=6)
        _last_email_list = emails
        if not emails:
            return "✅ No emails appear to be waiting on a reply. Inbox is clear!"
        formatted = format_emails(emails, triage=True)
        return f"🟡 *Possibly needs a reply:*\n\n{formatted}"

    # ── Search ───────────────────────────────────────────────────────────────
    elif action == "search":
        query = parsed.get("search_query", message)
        emails = search_emails(query, max_results=5)
        _last_email_list = emails
        if not emails:
            return f"📭 No emails found for: _{query}_"
        formatted = format_emails(emails)
        return f"🔍 *Search results:*\n\n{formatted}"

    # ── Reply to thread ──────────────────────────────────────────────────────
    elif action == "reply":
        ref = parsed.get("email_ref", "")
        body_request = parsed.get("body_request", "")
        if not _last_email_list:
            _last_email_list = list_unread(max_results=8)
        match = _resolve_email_ref(ref, _last_email_list)
        if not match:
            for acct in ["primary", "secondary"]:
                results = search_emails(ref, max_results=1, account=acct)
                if results:
                    results[0].setdefault("account", "jynpriority@gmail.com" if acct == "primary" else "jngai5.3@gmail.com")
                    match = results[0]
                    break
        if not match:
            return f"Couldn't find email matching '{ref}'. Try 'check unread' first."
        # Get full email to get thread_id and sender
        acct = "secondary" if "jngai5.3" in match.get("account", "") else "primary"
        full = get_email_body(match["id"], account=acct)
        if not full:
            return "⚠️ Couldn't load that email to reply."
        to = full["from"]
        subject = full["subject"]
        thread_id = full["thread_id"]
        # Draft the reply body
        reply_body = _draft_email_body(to, subject, body_request)
        sender = to.split("<")[0].strip() or to
        # Persist state so "send it" can retrieve it
        _save_draft_state({
            "type": "reply",
            "to": to,
            "subject": subject,
            "body": reply_body,
            "thread_id": thread_id,
            "account": acct,
        })
        return (
            f"📝 *Reply draft:*\n\n"
            f"To: {sender}\n"
            f"Re: {subject}\n\n"
            f"{reply_body}\n\n"
            f"_Reply 'send it' to send, or tell me what to change_"
        )

    # ── Calendar invite ─────────────────────────────────────────────────────
    elif action == "calendar_invite":
        to_name = parsed.get("to", "")
        title = parsed.get("title", "")
        date = parsed.get("date", "")
        time_str = parsed.get("time", "")
        duration = parsed.get("duration_minutes", 60)

        if not to_name:
            return "Who should I send the invite to?"

        # Already have an email address
        if "@" in to_name:
            contacts = [{"email": to_name, "display_name": to_name,
                         "recent_subject": "", "found_in": ""}]
        else:
            contacts = _find_contact_email(to_name)

        if not contacts:
            _save_draft_state({
                "type": "calendar_invite_needs_email",
                "to_name": to_name,
                "title": title,
                "date": date,
                "time": time_str,
                "duration": duration,
            })
            return (
                f"I couldn't find *{to_name}*'s email in your inbox.\n\n"
                f"What's their email address?"
            )

        if len(contacts) == 1:
            contact = contacts[0]
            _save_draft_state({
                "type": "calendar_invite",
                "to_email": contact["email"],
                "to_name": contact["display_name"],
                "title": title or f"Meeting with {contact['display_name'].split()[0]}",
                "date": date,
                "time": time_str,
                "duration": duration,
            })
            subject_ctx = f"\n   _(found via: {contact['recent_subject'][:50]})_" if contact["recent_subject"] else ""
            date_display = date if date else "_date TBD_"
            time_display = time_str if time_str else "_time TBD_"
            return (
                f"📧 Found *{contact['display_name']}* → `{contact['email']}`{subject_ctx}\n\n"
                f"📅 *Invite preview:*\n"
                f"  Event: {title or 'Meeting'}\n"
                f"  To: {contact['email']}\n"
                f"  When: {date_display} {time_display}\n\n"
                f"_Reply 'send it' to send the invite, or correct any details_"
            )

        # Multiple matches — ask to clarify
        options = "\n".join(
            f"  {i+1}. {c['display_name']} — `{c['email']}` _(via {c['found_in']})_"
            for i, c in enumerate(contacts[:4])
        )
        return (
            f"Found {len(contacts)} contacts matching '{to_name}':\n\n"
            f"{options}\n\n"
            f"Reply with their number to confirm."
        )

    # ── Follow-up scan ──────────────────────────────────────────────────────
    elif action == "followup_scan":
        lines = ["🔍 *Follow-up scan across both accounts:*\n"]
        all_emails = []

        for acct, label in [("primary", "jynpriority"), ("secondary", "jngai5.3")]:
            if not is_configured(acct):
                continue
            try:
                # Inbox emails likely needing reply
                inbox = search_emails(
                    "is:inbox -from:noreply -from:no-reply newer_than:7d",
                    max_results=8, account=acct,
                )
                for e in inbox:
                    e["_acct"] = label
                    e["_dir"] = "inbox"
                all_emails.extend(inbox)

                # Sent emails potentially awaiting a response
                sent = search_emails(
                    "in:sent newer_than:5d",
                    max_results=5, account=acct,
                )
                for e in sent:
                    e["_acct"] = label
                    e["_dir"] = "sent"
                all_emails.extend(sent)
            except Exception:
                pass

        if not all_emails:
            return "✅ Inbox is clean — no obvious follow-ups needed."

        email_text = "\n".join(
            f"{i+1}. [{e['_dir'].upper()} | {e['_acct']}] "
            f"{e.get('subject', '(no subject)')} | "
            f"From: {e.get('from', '?').split('<')[0].strip()[:30]} | "
            f"{e.get('snippet', '')[:80]}"
            for i, e in enumerate(all_emails[:15])
        )
        _last_email_list = all_emails

        analysis = chat(
            "You are Justin Ngai's executive assistant reviewing emails for follow-up.",
            f"Review these emails. Identify:\n"
            f"1. Received emails where Justin should reply (mention who + why)\n"
            f"2. Sent emails that may need a follow-up if no reply yet\n"
            f"3. Any time-sensitive items\n\n"
            f"Be concise — one line per item. Skip newsletters/notifications.\n\n"
            f"Emails:\n{email_text}",
            max_tokens=500,
        )
        lines.append(analysis)
        lines.append("\n_Reply 'read N' to open any email_")
        return "\n".join(lines)

    # ── Confirmation email scan (on demand) ─────────────────────────────────
    elif action == "confirm_scan":
        result = scan_and_triage_confirmations()
        return result or "📭 No confirmation emails found in the last 2 weeks."

    # ── Draft / Send ─────────────────────────────────────────────────────────
    elif action in ("draft", "send"):
        to = parsed.get("to", "")
        subject = parsed.get("subject", "")
        body_request = parsed.get("body_request", message)
        send_immediately = parsed.get("send_immediately", False)

        # Handle "send it" confirmation from previous draft/reply/calendar_invite
        if "send it" in message.lower() or "yes" == message.lower().strip():
            state = _load_draft_state()
            if not state:
                return "No pending draft or invite found. Create one first, then reply 'send it'."

            # Calendar invite confirmation
            if state.get("type") in ("calendar_invite", "calendar_invite_needs_email"):
                if state["type"] == "calendar_invite_needs_email":
                    # The message IS the email address
                    import re
                    m = re.search(r"[\w.+-]+@[\w.-]+\.\w+", message)
                    if m:
                        state["to_email"] = m.group(0)
                        state["to_name"] = state.get("to_name", state["to_email"])
                        state["type"] = "calendar_invite"
                        _save_draft_state(state)
                        return (
                            f"Got it — *{state['to_email']}*.\n\n"
                            f"📅 *Invite preview:*\n"
                            f"  Event: {state.get('title', 'Meeting')}\n"
                            f"  To: {state['to_email']}\n"
                            f"  When: {state.get('date', 'TBD')} {state.get('time', '')}\n\n"
                            f"_Reply 'send it' to confirm_"
                        )
                    return "That doesn't look like an email address. Try again (e.g. alex@gmail.com)."
                return _send_calendar_invite(state)

            if state.get("type") == "reply":
                success = reply_to_email(
                    state["thread_id"], state["to"], state["subject"], state["body"],
                    account=state.get("account", "primary")
                )
            else:
                success = send_email(state["to"], state["subject"], state["body"])

            if success:
                _DRAFT_STATE_PATH.unlink(missing_ok=True)
                return (
                    f"✅ *Sent!*\n\n"
                    f"To: {state['to']}\n"
                    f"Subject: {state['subject']}\n\n"
                    f"_{state['body'][:200]}{'...' if len(state['body']) > 200 else ''}_"
                )
            return "⚠️ Failed to send. Check Gmail permissions."

        if not to:
            return "Who should I send this to? (name or email address)"

        if not subject:
            subject = chat(SYSTEM,
                f"Generate a short email subject line for: {body_request}",
                max_tokens=20).strip().strip('"')

        body = _draft_email_body(to, subject, body_request)

        if send_immediately and "@" in to:
            success = send_email(to, subject, body)
            if success:
                return (
                    f"✅ *Email sent!*\n\n"
                    f"To: {to}\n"
                    f"Subject: {subject}\n\n"
                    f"_{body[:200]}{'...' if len(body) > 200 else ''}_"
                )
            else:
                return "⚠️ Failed to send. Check Gmail permissions."
        else:
            draft = create_draft(to if "@" in to else "", subject, body)
            draft_note = "_Draft saved to Gmail_" if draft else "_Could not save draft (no email address)_"
            # Persist state so "send it" can retrieve it
            _save_draft_state({"type": "draft", "to": to, "subject": subject, "body": body})
            return (
                f"📝 *Draft ready:*\n\n"
                f"To: {to}\n"
                f"Subject: {subject}\n\n"
                f"{body}\n\n"
                f"{draft_note}\n"
                f"_Reply 'send it' to send, or tell me what to change_"
            )

    # ── General question ─────────────────────────────────────────────────────
    else:
        from core.conversation import get_history_for_llm
        emails = list_unread(max_results=5)
        _last_email_list = emails
        email_summary = format_emails(emails, triage=True) if emails else "Inbox is clear"
        context = f"Justin's recent unread emails:\n{email_summary}\n\nQuestion: {message}"
        history = get_history_for_llm(n=3)
        return chat(SYSTEM, context, max_tokens=400, history=history)


def run_morning_digest() -> str:
    """
    Proactive 7:50 AM email digest.
    Returns empty string if inbox is clean (silent mode).
    """
    if not is_configured():
        return ""
    try:
        from integrations.google.gmail_client import (
            list_unread_all_accounts, format_emails, _triage_urgency
        )
        unread = list_unread_all_accounts(max_results=10)
        if not unread:
            return ""

        urgent, needs_reply, fyi = [], [], []
        for e in unread:
            sender = e["from"].split("<")[0].strip()
            urg = _triage_urgency(e.get("subject", ""), e.get("snippet", ""), sender)
            if urg == "🔴":
                urgent.append(e)
            elif urg == "🟡":
                needs_reply.append(e)
            else:
                fyi.append(e)

        # Silent if only FYI/newsletters
        if not urgent and not needs_reply:
            return ""

        lines = ["📬 *Morning Email Digest*\n"]

        if urgent:
            lines.append("🔴 *Needs immediate attention:*")
            for e in urgent:
                sender = e["from"].split("<")[0].strip()
                acct = " _(jngai5.3)_" if "jngai5.3" in e.get("account", "") else ""
                lines.append(f"  • *{e['subject']}* — {sender}{acct}")

        if needs_reply:
            lines.append("\n🟡 *Waiting on your reply:*")
            for e in needs_reply[:4]:
                sender = e["from"].split("<")[0].strip()
                acct = " _(jngai5.3)_" if "jngai5.3" in e.get("account", "") else ""
                lines.append(f"  • *{e['subject']}* — {sender}{acct}")

        if fyi:
            lines.append(f"\n⚪ {len(fyi)} other unread")

        lines.append("\n_Reply 'check email' to open inbox_")
        return "\n".join(lines)
    except Exception as e:
        logger.warning("Morning email digest error: %s", e)
        return ""


def run_eod_email_summary() -> str:
    """
    Evening email summary — unread count + who still needs a reply.
    Returns empty string if inbox is clean.
    """
    if not is_configured():
        return ""
    try:
        from integrations.google.gmail_client import list_unread, format_emails, _triage_urgency
        unread = list_unread(max_results=10)
        if not unread:
            return "📭 *Email:* Inbox zero — nothing unread 🎉"

        urgent, needs_reply, fyi = [], [], []
        for e in unread:
            sender = e["from"].split("<")[0].strip()
            urg = _triage_urgency(e.get("subject", ""), e.get("snippet", ""), sender)
            if urg == "🔴":
                urgent.append(e)
            elif urg == "🟡":
                needs_reply.append(e)
            else:
                fyi.append(e)

        lines = [f"📬 *Email:* {len(unread)} unread"]

        if urgent:
            lines.append("🔴 *Still needs attention:*")
            for e in urgent:
                sender = e["from"].split("<")[0].strip()
                lines.append(f"  • *{e['subject']}* — {sender}")

        if needs_reply:
            lines.append("🟡 *Waiting on reply:*")
            for e in needs_reply[:3]:
                sender = e["from"].split("<")[0].strip()
                lines.append(f"  • *{e['subject']}* — {sender}")

        if fyi:
            lines.append(f"⚪ {len(fyi)} FYI / newsletters")

        return "\n".join(lines)
    except Exception as e:
        logger.warning("EOD email summary error: %s", e)
        return ""


def scan_and_triage_confirmations() -> str:
    """
    Scan both Gmail accounts for unread confirmation/RSVP emails.
    For each one found: extract event details and auto-create a Google Calendar event.
    Called by the scheduled morning digest AND on-demand.
    Returns a formatted summary or empty string if nothing found.
    """
    if not is_configured():
        return ""
    try:
        from integrations.google.gmail_client import scan_confirmation_emails, get_email_body
        from integrations.google.calendar_client import create_event
        import datetime, re

        confirmations = scan_confirmation_emails(max_results=20)
        if not confirmations:
            return ""

        lines = ["📨 *Confirmation emails found:*\n"]
        created_events = []

        for email in confirmations:
            subject = email.get("subject", "")
            sender  = email.get("from", "").split("<")[0].strip()
            snippet = email.get("snippet", "")
            account = email.get("account", "")

            # Try to extract full body for better event parsing
            # Use the correct account for the email
            acct = "secondary" if "jngai5.3" in email.get("account", "") else "primary"
            full_body = ""
            try:
                from integrations.google.gmail_client import get_email_body as _get_body
                full = _get_body(email["id"], account=acct)
                full_body = full.get("body", "")[:2000]
            except Exception:
                full_body = snippet

            # Use LLM to extract event details
            extract_prompt = (
                f"Extract event details from this confirmation email. Return JSON only.\n\n"
                f"Subject: {subject}\nFrom: {sender}\nBody: {full_body}\n\n"
                "Return:\n"
                '{"is_event": true/false, "name": "event name", "date": "YYYY-MM-DD or empty", '
                '"start_time": "HH:MM 24h or empty", "end_time": "HH:MM 24h or empty", '
                '"location": "address or venue name or empty", "notes": "any key details"}\n\n'
                "If this is not a calendar event (e.g. a product order, newsletter), return {\"is_event\": false}"
            )
            try:
                raw = chat("You are a calendar event extractor. Return valid JSON only.", extract_prompt, max_tokens=200)
                raw = raw.strip().strip("```json").strip("```").strip()
                event_data = json.loads(raw)
            except Exception:
                event_data = {"is_event": False}

            line = f"• *{subject}* — {sender} _(via {account})_"

            # Skip events in the past
            import datetime as _dt
            event_date_str = event_data.get("date", "")
            try:
                event_date = _dt.date.fromisoformat(event_date_str)
                if event_date < _dt.date.today():
                    line += "\n  _(event date is in the past — skipped)_"
                    lines.append(line)
                    continue
            except Exception:
                pass  # if date is invalid, let the create_event attempt handle it

            if event_data.get("is_event") and event_data.get("date"):
                try:
                    date_str  = event_data["date"]
                    start_str = event_data.get("start_time") or "19:00"  # default 7 PM if unknown
                    end_str   = event_data.get("end_time") or ""
                    name      = event_data.get("name") or subject
                    location  = event_data.get("location") or ""
                    notes     = event_data.get("notes") or ""

                    # Validate start_str format — must be HH:MM
                    if not start_str or ":" not in start_str:
                        start_str = "19:00"

                    # Build ISO datetimes
                    start_iso = f"{date_str}T{start_str}:00"
                    if end_str and ":" in end_str:
                        end_iso = f"{date_str}T{end_str}:00"
                    else:
                        # Default to 2h duration if no end time
                        sh, sm = map(int, start_str.split(":"))
                        end_h = (sh + 2) % 24
                        end_iso = f"{date_str}T{end_h:02d}:{sm:02d}:00"

                    result = create_event(
                        title=name,
                        start=start_iso,
                        end=end_iso,
                        location=location,
                        description=f"Auto-imported from confirmation email\n{notes}\nFrom: {sender}",
                    )
                    if result:
                        line += f"\n  ✅ Added to calendar: *{name}* on {date_str}"
                        created_events.append(name)
                    else:
                        line += f"\n  ⚠️ Could not create calendar event"
                except Exception as ce:
                    line += f"\n  ⚠️ Calendar error: {ce}"
            else:
                line += "\n  _(no event date found — review manually)_"

            lines.append(line)

        if created_events:
            lines.append(f"\n🗓 *{len(created_events)} event(s) auto-added to your calendar*")

        return "\n".join(lines)

    except Exception as e:
        logger.warning("Confirmation scan error: %s", e)
        return ""
