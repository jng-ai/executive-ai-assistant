"""
Follow-up Agent — schedule email or meeting follow-ups at a future time.

Handles requests like:
  "Follow up with Marcus about the infusion proposal in 3 days"
  "Send a follow-up email to alex@company.com in 1 week about our call"
  "Schedule a follow-up meeting with Dr. Kim next Thursday"
  "What follow-ups do I have pending?"
  "Cancel follow-up 2"

When the follow-up fires (via scheduler):
  - Email type → drafts + sends the email
  - Meeting type → creates a Google Calendar event
"""

import datetime
import json
import re
from core.llm import chat
from core.followups import add_followup, list_all_pending, cancel_followup, mark_done

SYSTEM = """You are Justin Ngai's follow-up assistant. You help him remember to circle back with people via email or meeting.

Justin's context:
- Healthcare operations consultant, infusion consulting side business
- Investors, hospital contacts, mortgage note sellers, travel/finance contacts
- Professional but direct tone
- Signs emails as: Justin

When scheduling follow-ups:
- Be specific about timing (1 day = tomorrow, 1 week = 7 days, etc.)
- For emails: draft concise, professional follow-up
- For meetings: suggest 30–60 min blocks

When listing pending follow-ups: show contact, type, context, due date."""


PARSE_PROMPT = """Extract follow-up details from this message. Return JSON only.

Return:
{
  "action": "create" | "list" | "cancel",
  "type": "email" | "meeting",
  "contact": "person's name or email",
  "email": "email address if given",
  "context": "what this is about",
  "body_request": "what the follow-up should say or the meeting purpose",
  "delay_days": 3,
  "followup_id": null
}

Today is DATE_PLACEHOLDER.

Examples:
"Follow up with Marcus about the infusion RFP in 3 days via email" → {"action":"create","type":"email","contact":"Marcus","context":"infusion RFP","body_request":"Check in on the RFP status","delay_days":3}
"Schedule a follow-up meeting with Dr. Kim next week" → {"action":"create","type":"meeting","contact":"Dr. Kim","context":"follow-up meeting","body_request":"Follow-up discussion","delay_days":7}
"What follow-ups do I have?" → {"action":"list"}
"Cancel follow-up 2" → {"action":"cancel","followup_id":2}
"Remind me to email alex@company.com in 5 days about Thursday's call" → {"action":"create","type":"email","contact":"Alex","email":"alex@company.com","context":"Thursday's call","body_request":"Follow up on our call","delay_days":5}
"""


def _parse_request(message: str) -> dict:
    today = datetime.date.today()
    prompt = PARSE_PROMPT.replace("DATE_PLACEHOLDER", today.strftime("%Y-%m-%d (%A)"))
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
        return {"action": "list"}


def handle(message: str) -> str:
    parsed = _parse_request(message)
    action = parsed.get("action", "list")

    # ── List pending follow-ups ──────────────────────────────────────────────
    if action == "list":
        pending = list_all_pending()
        if not pending:
            return "✅ No pending follow-ups — you're all caught up!"
        lines = ["📋 *Pending Follow-ups:*\n"]
        for f in pending:
            due = f["due"][:10]
            ftype = "📧 Email" if f["type"] == "email" else "📅 Meeting"
            lines.append(
                f"*{f['id']}.* {ftype} → *{f['contact']}*\n"
                f"   Re: {f['context']}\n"
                f"   Due: {due}"
            )
        lines.append("\n_Reply 'cancel follow-up [#]' to remove one_")
        return "\n\n".join(lines)

    # ── Cancel a follow-up ───────────────────────────────────────────────────
    elif action == "cancel":
        fid = parsed.get("followup_id")
        if not fid:
            # Try to extract number from raw message
            nums = re.findall(r"\d+", message)
            fid = int(nums[0]) if nums else None
        if fid and cancel_followup(int(fid)):
            return f"🗑 Follow-up #{fid} cancelled."
        return "Couldn't find that follow-up. Try 'what follow-ups do I have?' to see the list."

    # ── Create a follow-up ───────────────────────────────────────────────────
    elif action == "create":
        contact = parsed.get("contact", "")
        email = parsed.get("email", "")
        context = parsed.get("context", "follow-up")
        body_request = parsed.get("body_request", "Check in")
        follow_type = parsed.get("type", "email")
        delay_days = parsed.get("delay_days", 3)

        if not contact:
            return "Who should I follow up with? Give me a name or email."

        # Calculate due datetime — default 9 AM on the due day
        due_date = datetime.date.today() + datetime.timedelta(days=delay_days)
        due_iso = f"{due_date.isoformat()}T09:00:00"

        entry = add_followup(
            follow_type=follow_type,
            contact=contact,
            context=context,
            body_request=body_request,
            due_iso=due_iso,
            email=email,
        )

        due_str = due_date.strftime("%A, %B %-d")
        ftype = "email" if follow_type == "email" else "meeting invite"
        return (
            f"⏰ *Follow-up scheduled!*\n\n"
            f"{'📧' if follow_type == 'email' else '📅'} *{follow_type.title()}* → {contact}\n"
            f"Re: {context}\n"
            f"📅 Fires: {due_str} at 9 AM\n\n"
            f"_I'll automatically draft and {'send' if follow_type == 'email' else 'schedule'} the {ftype} for you._"
        )

    return chat(SYSTEM, message, max_tokens=300)


def run_pending_followups() -> list[str]:
    """
    Called by scheduler — fires all due follow-ups.
    Returns list of result messages to send to Telegram.
    """
    from core.followups import list_pending
    due = list_pending()
    if not due:
        return []

    results = []
    for f in due:
        try:
            if f["type"] == "email":
                msg = _fire_email_followup(f)
            else:
                msg = _fire_meeting_followup(f)
            mark_done(f["id"])
            results.append(msg)
        except Exception as e:
            results.append(f"⚠️ Follow-up #{f['id']} failed: {e}")

    return results


def _fire_email_followup(f: dict) -> str:
    """Draft and send a follow-up email."""
    from integrations.google.gmail_client import send_email
    from integrations.google.auth import is_configured

    contact = f["contact"]
    email_addr = f.get("email", "")
    context = f["context"]
    body_request = f["body_request"]

    # Draft email with LLM
    draft_prompt = (
        f"Write a brief follow-up email from Justin Ngai.\n"
        f"To: {contact}\n"
        f"Context: {context}\n"
        f"Instructions: {body_request}\n\n"
        f"Write ONLY the email body. Keep it to 3-4 sentences. Sign off as 'Justin'."
    )
    body = chat(SYSTEM, draft_prompt, max_tokens=300)
    subject = f"Following up — {context}"

    if email_addr and is_configured():
        success = send_email(email_addr, subject, body)
        if success:
            return (
                f"📤 *Follow-up email sent!*\n\n"
                f"To: {contact} ({email_addr})\n"
                f"Re: {context}\n\n"
                f"_{body[:300]}_"
            )
        else:
            return (
                f"⚠️ *Follow-up email draft ready (couldn't auto-send — no email address stored):*\n\n"
                f"To: {contact}\n"
                f"Re: {context}\n\n"
                f"_{body}_\n\n"
                f"_Copy and send manually, or tell me their email address._"
            )
    else:
        return (
            f"⏰ *Follow-up reminder:*\n\n"
            f"📧 Email → *{contact}*\n"
            f"Re: {context}\n\n"
            f"_Draft:_\n{body}\n\n"
            f"_Reply with their email and I'll send it._"
        )


def _fire_meeting_followup(f: dict) -> str:
    """Create a calendar event for the follow-up meeting."""
    from integrations.google.calendar_client import create_event, is_configured
    from integrations.google.auth import is_configured as gcal_ok

    contact = f["contact"]
    context = f["context"]
    body_request = f["body_request"]

    # Schedule 7 days from now at 10 AM as default slot
    import datetime
    meeting_date = (datetime.date.today() + datetime.timedelta(days=7)).isoformat()
    start_dt = f"{meeting_date}T10:00:00"
    end_dt = f"{meeting_date}T11:00:00"
    title = f"Follow-up: {contact} — {context}"

    if gcal_ok():
        event = create_event(title, start_dt, end_dt, description=body_request)
        if event:
            link = event.get("htmlLink", "")
            link_str = f"\n[Open in Calendar]({link})" if link else ""
            return (
                f"📅 *Follow-up meeting created!*\n\n"
                f"With: {contact}\n"
                f"Re: {context}\n"
                f"📅 {meeting_date} at 10 AM (1hr block){link_str}\n\n"
                f"_Adjust time in Google Calendar if needed._"
            )
    return (
        f"⏰ *Follow-up meeting reminder:*\n\n"
        f"📅 Schedule time with *{contact}*\n"
        f"Re: {context}\n\n"
        f"_Google Calendar not connected — schedule manually._"
    )
