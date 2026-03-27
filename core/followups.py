"""
Follow-ups — scheduled email or meeting follow-ups.
Stores pending follow-ups in data/followups.json.
The scheduler checks each morning and fires when due.
"""

import json
import logging
import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
FOLLOWUPS_FILE = DATA_DIR / "followups.json"


def _load() -> list:
    DATA_DIR.mkdir(exist_ok=True)
    if not FOLLOWUPS_FILE.exists():
        return []
    try:
        return json.loads(FOLLOWUPS_FILE.read_text())
    except Exception:
        return []


def _save(data: list):
    DATA_DIR.mkdir(exist_ok=True)
    FOLLOWUPS_FILE.write_text(json.dumps(data, indent=2))


def add_followup(
    follow_type: str,   # "email" | "meeting"
    contact: str,       # name or email
    context: str,       # what this is about
    body_request: str,  # what to say / subject of meeting
    due_iso: str,       # ISO datetime string when to fire
    email: str = "",    # email address if known
) -> dict:
    followups = _load()
    entry = {
        "id": len(followups) + 1,
        "type": follow_type,
        "contact": contact,
        "email": email,
        "context": context,
        "body_request": body_request,
        "due": due_iso,
        "status": "pending",
        "created": datetime.datetime.now().isoformat(),
    }
    followups.append(entry)
    _save(followups)
    return entry


def list_pending() -> list:
    """Return all pending follow-ups due today or earlier."""
    followups = _load()
    now_iso = datetime.datetime.now().isoformat()
    return [f for f in followups if f["status"] == "pending" and f["due"] <= now_iso]


def list_all_pending() -> list:
    """Return all pending follow-ups regardless of due date."""
    followups = _load()
    return [f for f in followups if f["status"] == "pending"]


def mark_done(followup_id: int) -> bool:
    followups = _load()
    for f in followups:
        if f["id"] == followup_id:
            f["status"] = "done"
            f["fired_at"] = datetime.datetime.now().isoformat()
            _save(followups)
            return True
    return False


def cancel_followup(followup_id: int) -> bool:
    followups = _load()
    for f in followups:
        if f["id"] == followup_id:
            f["status"] = "cancelled"
            _save(followups)
            return True
    return False
