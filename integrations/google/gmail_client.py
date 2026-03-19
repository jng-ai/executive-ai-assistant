"""
Gmail client — send, draft, and search emails.
"""

import base64
import email as email_lib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from googleapiclient.discovery import build
from integrations.google.auth import get_credentials, is_configured


def _service():
    return build("gmail", "v1", credentials=get_credentials(), cache_discovery=False)


def send_email(to: str, subject: str, body: str, html: bool = False) -> bool:
    """Send an email immediately."""
    if not is_configured():
        return False
    try:
        svc = _service()
        msg = MIMEMultipart("alternative") if html else MIMEText(body, "plain")
        msg["To"] = to
        msg["Subject"] = subject
        if html:
            msg.attach(MIMEText(body, "html"))

        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        svc.users().messages().send(userId="me", body={"raw": raw}).execute()
        return True
    except Exception as e:
        print(f"Gmail send error: {e}")
        return False


def create_draft(to: str, subject: str, body: str) -> dict | None:
    """Create a draft email (doesn't send)."""
    if not is_configured():
        return None
    try:
        svc = _service()
        msg = MIMEText(body, "plain")
        msg["To"] = to
        msg["Subject"] = subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        draft = svc.users().drafts().create(
            userId="me", body={"message": {"raw": raw}}
        ).execute()
        return draft
    except Exception as e:
        print(f"Gmail draft error: {e}")
        return None


def list_unread(max_results: int = 10) -> list[dict]:
    """Return recent unread emails with sender, subject, snippet."""
    if not is_configured():
        return []
    try:
        svc = _service()
        result = svc.users().messages().list(
            userId="me", q="is:unread", maxResults=max_results
        ).execute()
        messages = result.get("messages", [])
        emails = []
        for m in messages[:max_results]:
            msg = svc.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"]
            ).execute()
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            emails.append({
                "id": m["id"],
                "from": headers.get("From", ""),
                "subject": headers.get("Subject", ""),
                "date": headers.get("Date", ""),
                "snippet": msg.get("snippet", ""),
            })
        return emails
    except Exception as e:
        print(f"Gmail list error: {e}")
        return []


def search_emails(query: str, max_results: int = 5) -> list[dict]:
    """Search emails with Gmail query syntax."""
    if not is_configured():
        return []
    try:
        svc = _service()
        result = svc.users().messages().list(
            userId="me", q=query, maxResults=max_results
        ).execute()
        messages = result.get("messages", [])
        emails = []
        for m in messages:
            msg = svc.users().messages().get(
                userId="me", id=m["id"], format="metadata",
                metadataHeaders=["From", "Subject", "Date"]
            ).execute()
            headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
            emails.append({
                "id": m["id"],
                "from": headers.get("From", ""),
                "subject": headers.get("Subject", ""),
                "date": headers.get("Date", ""),
                "snippet": msg.get("snippet", ""),
            })
        return emails
    except Exception as e:
        print(f"Gmail search error: {e}")
        return []


def get_email_body(msg_id: str) -> dict:
    """Fetch the full body of an email by message ID."""
    if not is_configured():
        return {}
    try:
        svc = _service()
        msg = svc.users().messages().get(
            userId="me", id=msg_id, format="full"
        ).execute()
        headers = {h["name"]: h["value"] for h in msg.get("payload", {}).get("headers", [])}
        body = _extract_body(msg.get("payload", {}))
        return {
            "id": msg_id,
            "from": headers.get("From", ""),
            "subject": headers.get("Subject", ""),
            "date": headers.get("Date", ""),
            "body": body,
            "thread_id": msg.get("threadId", ""),
        }
    except Exception as e:
        print(f"Gmail get body error: {e}")
        return {}


def _extract_body(payload: dict) -> str:
    """Recursively extract plain text body from a Gmail payload."""
    mime_type = payload.get("mimeType", "")
    if mime_type == "text/plain":
        data = payload.get("body", {}).get("data", "")
        if data:
            return base64.urlsafe_b64decode(data + "==").decode("utf-8", errors="replace")
    elif mime_type.startswith("multipart/"):
        for part in payload.get("parts", []):
            text = _extract_body(part)
            if text:
                return text
    return ""


def reply_to_email(thread_id: str, to: str, subject: str, body: str) -> bool:
    """Send a reply within an existing email thread."""
    if not is_configured():
        return False
    try:
        svc = _service()
        msg = MIMEText(body, "plain")
        msg["To"] = to
        msg["Subject"] = f"Re: {subject}" if not subject.startswith("Re:") else subject
        raw = base64.urlsafe_b64encode(msg.as_bytes()).decode()
        svc.users().messages().send(
            userId="me",
            body={"raw": raw, "threadId": thread_id}
        ).execute()
        return True
    except Exception as e:
        print(f"Gmail reply error: {e}")
        return False


def list_needs_reply(max_results: int = 10) -> list[dict]:
    """Return emails that likely need a reply (sent to me, not replied to)."""
    if not is_configured():
        return []
    # Search: is unread OR not in sent, not newsletters
    return search_emails(
        "is:inbox -is:sent -from:noreply -from:no-reply -unsubscribe newer_than:7d",
        max_results=max_results
    )


def format_emails(emails: list[dict], triage: bool = False) -> str:
    if not emails:
        return "No emails found."
    lines = []
    for i, e in enumerate(emails, 1):
        sender = e["from"].split("<")[0].strip() or e["from"]
        snippet = e.get("snippet", "")[:160]
        if triage:
            urgency = _triage_urgency(e.get("subject", ""), snippet, sender)
            lines.append(f"{urgency} *{e['subject']}*\n   From: {sender}\n   _{snippet}_")
        else:
            lines.append(f"*{i}.* 📧 *{e['subject']}*\n   From: {sender}\n   _{snippet}_")
    return "\n\n".join(lines)


def _triage_urgency(subject: str, snippet: str, sender: str) -> str:
    """Return urgency emoji: 🔴 urgent, 🟡 needs reply, ⚪ FYI."""
    text = f"{subject} {snippet}".lower()
    urgent_keywords = ["urgent", "asap", "immediately", "action required", "time sensitive",
                       "deadline", "please respond", "need your", "approval needed"]
    reply_keywords = ["can you", "could you", "please", "following up", "let me know",
                      "thoughts?", "feedback", "would you", "are you"]
    noise_keywords = ["unsubscribe", "newsletter", "noreply", "no-reply", "notification",
                      "do not reply", "automated", "alert", "confirm your"]

    sender_lower = sender.lower()
    if any(k in noise_keywords for k in noise_keywords if k in sender_lower or k in text):
        return "⚪"
    if any(k in text for k in urgent_keywords):
        return "🔴"
    if any(k in text for k in reply_keywords):
        return "🟡"
    return "⚪"
