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


def format_emails(emails: list[dict]) -> str:
    if not emails:
        return "No emails found."
    lines = []
    for e in emails:
        sender = e["from"].split("<")[0].strip() or e["from"]
        lines.append(f"📧 *{e['subject']}*\n   From: {sender}\n   _{e['snippet'][:120]}_")
    return "\n\n".join(lines)
