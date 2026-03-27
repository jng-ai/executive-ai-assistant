"""
Gmail client — send, draft, and search emails.
"""

import base64
import email as email_lib
import logging
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from googleapiclient.discovery import build
from integrations.google.auth import get_credentials, is_configured

logger = logging.getLogger(__name__)


def _service(account: str = "primary"):
    return build("gmail", "v1", credentials=get_credentials(account), cache_discovery=False)


# Senders / subject patterns that indicate event/booking confirmations
_CONFIRMATION_PATTERNS = [
    "you're registered", "you're going", "you're in", "registration confirmed",
    "booking confirmed", "reservation confirmed", "rsvp confirmed", "you're attending",
    "ticket confirmed", "order confirmed", "your ticket", "your reservation",
    "confirmation for", "confirmed:", "see you there", "you've registered",
    "luma", "eventbrite", "partiful", "meetup", "resy", "opentable", "tock",
    "your flight", "your hotel", "itinerary", "check-in", "boarding pass",
]


def is_confirmation_email(subject: str, snippet: str, sender: str) -> bool:
    """Return True if this email looks like an event/booking confirmation."""
    text = f"{subject} {snippet} {sender}".lower()
    return any(p in text for p in _CONFIRMATION_PATTERNS)


def list_unread_all_accounts(max_results: int = 10) -> list[dict]:
    """
    Return recent unread emails from BOTH Gmail accounts.
    Each result includes an 'account' field: 'jynpriority' or 'jngai53'.
    """
    results = []

    # Primary: jynpriority@gmail.com
    try:
        primary = list_unread(max_results=max_results, account="primary")
        for e in primary:
            e["account"] = "jynpriority@gmail.com"
        results.extend(primary)
    except Exception as e:
        pass

    # Secondary: jngai5.3@gmail.com
    if is_configured("secondary"):
        try:
            secondary = list_unread(max_results=max_results, account="secondary")
            for e in secondary:
                e["account"] = "jngai5.3@gmail.com"
            results.extend(secondary)
        except Exception:
            pass

    # Sort by date descending (most recent first)
    results.sort(key=lambda x: x.get("date", ""), reverse=True)
    return results[:max_results * 2]


def scan_confirmation_emails(max_results: int = 30) -> list[dict]:
    """
    Scan both accounts for confirmation/RSVP emails from the last 7 days.
    Returns emails flagged as confirmations with is_confirmation=True.
    """
    # Search last 7 days across both accounts (not just unread)
    results = []
    for account, label in [("primary", "jynpriority@gmail.com"), ("secondary", "jngai5.3@gmail.com")]:
        if not is_configured(account):
            continue
        try:
            emails = search_emails("newer_than:7d", max_results=max_results, account=account)
            for e in emails:
                e["account"] = label
            results.extend(emails)
        except Exception:
            pass
    all_emails = results
    return [
        {**e, "is_confirmation": True}
        for e in all_emails
        if is_confirmation_email(e.get("subject",""), e.get("snippet",""), e.get("from",""))
    ]


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
        logger.error("Gmail send error: %s", e)
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
        logger.error("Gmail draft error: %s", e)
        return None


def list_unread(max_results: int = 10, account: str = "primary") -> list[dict]:
    """Return recent unread emails with sender, subject, snippet."""
    if not is_configured(account):
        return []
    try:
        svc = _service(account)
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
        logger.error("Gmail list error: %s", e)
        return []


def search_emails(query: str, max_results: int = 5, account: str = "primary") -> list[dict]:
    """Search emails with Gmail query syntax."""
    if not is_configured(account):
        return []
    try:
        svc = _service(account)
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
        logger.error("Gmail search error: %s", e)
        return []


def get_email_body(msg_id: str, account: str = "primary") -> dict:
    """Fetch the full body of an email by message ID."""
    if not is_configured(account):
        return {}
    try:
        svc = _service(account)
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
        logger.error("Gmail get body error: %s", e)
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


def reply_to_email(thread_id: str, to: str, subject: str, body: str, account: str = "primary") -> bool:
    """Send a reply within an existing email thread."""
    if not is_configured(account):
        return False
    try:
        svc = _service(account)
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
        logger.error("Gmail reply error: %s", e)
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
