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
from core.llm import chat
from integrations.google.auth import is_configured

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
  "action": "draft" | "send" | "list_unread" | "search" | "read" | "reply" | "needs_reply" | "question",
  "to": "recipient email or name if known",
  "subject": "email subject",
  "body_request": "what the email should say",
  "search_query": "gmail search query if searching",
  "email_ref": "keyword or number to identify which email to read/reply to",
  "send_immediately": false
}

Examples:
"Check my unread emails" → {"action":"list_unread"}
"Read the email from Marcus" → {"action":"read","email_ref":"Marcus"}
"Read email 2" → {"action":"read","email_ref":"2"}
"Who needs a reply?" → {"action":"needs_reply"}
"Reply to the Acme email saying I'll call Thursday" → {"action":"reply","email_ref":"Acme","body_request":"I'll call Thursday"}
"Draft an email to John saying I'll be late" → {"action":"draft","to":"John","subject":"Running Late","body_request":"Tell him I'll be late to our meeting"}
"Send an email to alex@company.com confirming Thursday's call at 2pm" → {"action":"send","to":"alex@company.com","subject":"Confirming Thursday Call","body_request":"Confirm call Thursday 2pm","send_immediately":true}
"Any emails from Marcus this week?" → {"action":"search","search_query":"from:Marcus newer_than:7d"}
"""


# Stores last unread list for "read email 2" style references
_last_email_list: list[dict] = []


def _parse_request(message: str) -> dict:
    raw = chat(PARSE_PROMPT, message, max_tokens=300)
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


def handle(message: str) -> str:
    global _last_email_list

    if not is_configured():
        return (
            "⚠️ Gmail not connected yet.\n\n"
            "Run `python scripts/google_auth.py` to authorize."
        )

    from integrations.google.gmail_client import (
        send_email, create_draft, list_unread, search_emails, format_emails,
        get_email_body, reply_to_email, list_needs_reply, _triage_urgency
    )

    parsed = _parse_request(message)
    action = parsed.get("action", "question")

    # ── List unread with urgency triage ─────────────────────────────────────
    if action == "list_unread":
        emails = list_unread(max_results=8)
        _last_email_list = emails
        if not emails:
            return "📭 Inbox zero — nothing unread!"
        formatted = format_emails(emails, triage=True)
        return (
            f"📬 *Unread ({len(emails)}):*\n\n"
            f"{formatted}\n\n"
            f"_🔴 urgent · 🟡 needs reply · ⚪ FYI_\n"
            f"_Reply 'read 2' to open any email_"
        )

    # ── Read full email body ─────────────────────────────────────────────────
    elif action == "read":
        ref = parsed.get("email_ref", "")
        if not ref:
            return "Which email? Give me a number (e.g. 'read 2') or keyword (e.g. 'read the Marcus email')."
        if not _last_email_list:
            _last_email_list = list_unread(max_results=8)
        match = _resolve_email_ref(ref, _last_email_list)
        if not match:
            # Try searching
            results = search_emails(ref, max_results=1)
            match = results[0] if results else None
        if not match:
            return f"Couldn't find an email matching '{ref}'. Try 'check unread' first."
        full = get_email_body(match["id"])
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
            results = search_emails(ref, max_results=1)
            match = results[0] if results else None
        if not match:
            return f"Couldn't find email matching '{ref}'. Try 'check unread' first."
        # Get full email to get thread_id and sender
        full = get_email_body(match["id"])
        if not full:
            return "⚠️ Couldn't load that email to reply."
        to = full["from"]
        subject = full["subject"]
        thread_id = full["thread_id"]
        # Draft the reply body
        reply_body = _draft_email_body(to, subject, body_request)
        sender = to.split("<")[0].strip() or to
        # Show preview + confirm
        return (
            f"📝 *Reply draft:*\n\n"
            f"To: {sender}\n"
            f"Re: {subject}\n\n"
            f"{reply_body}\n\n"
            f"_Reply 'send it' to send, or tell me what to change_\n"
            f"_thread:{thread_id}|to:{to}|subj:{subject}_"
        )

    # ── Draft / Send ─────────────────────────────────────────────────────────
    elif action in ("draft", "send"):
        to = parsed.get("to", "")
        subject = parsed.get("subject", "")
        body_request = parsed.get("body_request", message)
        send_immediately = parsed.get("send_immediately", False)

        # Handle "send it" confirmation from previous draft/reply
        if "send it" in message.lower():
            return "Which draft should I send? Reply with a recipient or paste the draft."

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
        emails = list_unread(max_results=5)
        _last_email_list = emails
        email_summary = format_emails(emails, triage=True) if emails else "Inbox is clear"
        context = f"Justin's recent unread emails:\n{email_summary}\n\nQuestion: {message}"
        return chat(SYSTEM, context, max_tokens=400)


def run_morning_digest() -> str:
    """
    Proactive 7:50 AM email digest.
    Returns empty string if inbox is clean (silent mode).
    """
    if not is_configured():
        return ""
    try:
        from integrations.google.gmail_client import list_unread, list_needs_reply, format_emails
        unread = list_unread(max_results=8)
        if not unread:
            return ""   # Inbox zero — stay silent

        # Triage into buckets
        urgent = []
        needs_reply = []
        fyi = []

        from integrations.google.gmail_client import _triage_urgency
        for e in unread:
            sender = e["from"].split("<")[0].strip()
            urg = _triage_urgency(e.get("subject", ""), e.get("snippet", ""), sender)
            if urg == "🔴":
                urgent.append(e)
            elif urg == "🟡":
                needs_reply.append(e)
            else:
                fyi.append(e)

        lines = ["📬 *Morning Email Digest*\n"]

        if urgent:
            lines.append("🔴 *Needs immediate attention:*")
            for e in urgent:
                sender = e["from"].split("<")[0].strip()
                lines.append(f"  • *{e['subject']}* — {sender}")

        if needs_reply:
            lines.append("\n🟡 *Waiting on your reply:*")
            for e in needs_reply[:3]:
                sender = e["from"].split("<")[0].strip()
                lines.append(f"  • *{e['subject']}* — {sender}")

        if fyi:
            lines.append(f"\n⚪ {len(fyi)} other unread")

        lines.append("\n_Reply 'check email' to open inbox_")
        return "\n".join(lines)
    except Exception as e:
        print(f"Morning email digest error: {e}")
        return ""
