"""
Email Agent — natural language interface to Gmail.
Draft, send, search, and summarize emails via Telegram.
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
- Signs emails as: Justin Ngai

When drafting emails:
- Match the appropriate tone (formal for clients/execs, casual for friends)
- Keep emails concise — he's a busy person who values brevity
- Always confirm recipient and subject before sending
- For infusion consulting: frame as independent consultant, never mention employer

When showing emails:
- Summarize clearly: who, what, urgency
- Flag anything that needs a reply or action"""


PARSE_PROMPT = """Extract email action from this message. Return JSON only.

Return:
{
  "action": "draft" | "send" | "list_unread" | "search" | "question",
  "to": "recipient email or name if known",
  "subject": "email subject",
  "body_request": "what the email should say",
  "search_query": "gmail search query if searching",
  "send_immediately": false
}

Examples:
"Draft an email to John saying I'll be late to the meeting" → {"action":"draft","to":"John","subject":"Running Late","body_request":"Tell him I'll be late to our meeting, apologize briefly"}
"Send an email to alex@company.com confirming Thursday's call at 2pm" → {"action":"send","to":"alex@company.com","subject":"Confirming Thursday Call","body_request":"Confirm call Thursday 2pm","send_immediately":true}
"Check my unread emails" → {"action":"list_unread"}
"Any emails from Marcus this week?" → {"action":"search","search_query":"from:Marcus newer_than:7d"}
"""


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
    """Use LLM to write the actual email."""
    prompt = (
        f"Write a professional email from Justin Ngai.\n"
        f"To: {to}\n"
        f"Subject: {subject}\n"
        f"Instructions: {body_request}\n\n"
        f"Write ONLY the email body (no subject line, no 'To:' header). "
        f"Sign off as 'Justin'. Keep it concise."
    )
    return chat(SYSTEM, prompt, max_tokens=400)


def handle(message: str) -> str:
    if not is_configured():
        return (
            "⚠️ Gmail not connected yet.\n\n"
            "Run `python scripts/google_auth.py` to authorize."
        )

    from integrations.google.gmail_client import (
        send_email, create_draft, list_unread, search_emails, format_emails
    )

    parsed = _parse_request(message)
    action = parsed.get("action", "question")

    if action == "list_unread":
        emails = list_unread(max_results=8)
        if not emails:
            return "📭 No unread emails — inbox zero!"
        formatted = format_emails(emails)
        return f"📬 *Unread emails ({len(emails)}):*\n\n{formatted}"

    elif action == "search":
        query = parsed.get("search_query", message)
        emails = search_emails(query, max_results=5)
        if not emails:
            return f"📭 No emails found for: _{query}_"
        formatted = format_emails(emails)
        return f"🔍 *Search results:*\n\n{formatted}"

    elif action in ("draft", "send"):
        to = parsed.get("to", "")
        subject = parsed.get("subject", "")
        body_request = parsed.get("body_request", message)
        send_immediately = parsed.get("send_immediately", False)

        if not to:
            return "Who should I send this to? (name or email address)"

        if not subject:
            subject = chat(SYSTEM, f"Generate a short email subject line for: {body_request}", max_tokens=20).strip().strip('"')

        # Draft the email body with LLM
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
            # Create draft and show preview — user can confirm to send
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

    else:
        # General question — use AI with email context
        emails = list_unread(max_results=5)
        email_summary = format_emails(emails) if emails else "Inbox is clear"
        context = f"Justin's recent unread emails:\n{email_summary}\n\nQuestion: {message}"
        return chat(SYSTEM, context, max_tokens=400)
