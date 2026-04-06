"""
Message-level deduplication for scheduled Telegram jobs.

Prevents duplicate messages when APScheduler fires a job more than once
(e.g. bot restart during a job window, clock skew, or timezone edge cases).

Storage: data/sent_messages.json — keyed by (job_name, message_hash).
Entries expire after `window_hours` (default 4 h) so the same content can
be sent again on the next natural cycle.
"""

import hashlib
import json
import datetime
import os
import tempfile
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
SENT_FILE = DATA_DIR / "sent_messages.json"

# Default dedup window — generous enough to cover any double-fire scenario
# but short enough that the same job can fire again tomorrow.
DEFAULT_WINDOW_HOURS = 4


def _compute_hash(text: str) -> str:
    """SHA-256 fingerprint of message content (first 2 KB is enough for dedup)."""
    return hashlib.sha256(text[:2048].encode()).hexdigest()[:16]


def _load() -> list:
    DATA_DIR.mkdir(exist_ok=True)
    if not SENT_FILE.exists():
        return []
    try:
        return json.loads(SENT_FILE.read_text())
    except Exception:
        return []


def _save_atomic(records: list) -> None:
    """Write to a temp file then atomically rename — safe against partial writes."""
    DATA_DIR.mkdir(exist_ok=True)
    fd, tmp_path = tempfile.mkstemp(dir=DATA_DIR, suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            json.dump(records, f, indent=2)
        os.replace(tmp_path, SENT_FILE)
    except Exception:
        try:
            os.unlink(tmp_path)
        except OSError:
            pass


def _cleanup(records: list, max_age_hours: int = 24) -> list:
    """Remove entries older than max_age_hours to keep the file small."""
    cutoff = datetime.datetime.now() - datetime.timedelta(hours=max_age_hours)
    return [
        r for r in records
        if datetime.datetime.fromisoformat(r["sent_at"]) > cutoff
    ]


def is_duplicate(job_name: str, message: str, window_hours: int = DEFAULT_WINDOW_HOURS) -> bool:
    """
    Return True if this (job_name, message) was already sent within `window_hours`.

    Usage in a scheduled handler::

        if message_dedup.is_duplicate("daily_bonus_scan", result):
            logger.info("[Dedup] Skipping duplicate bonus alert")
            return
        await context.bot.send_message(...)
        message_dedup.record_sent("daily_bonus_scan", result)
    """
    msg_hash = _compute_hash(message)
    cutoff = datetime.datetime.now() - datetime.timedelta(hours=window_hours)
    for r in _load():
        if r.get("job_name") == job_name and r.get("msg_hash") == msg_hash:
            try:
                if datetime.datetime.fromisoformat(r["sent_at"]) > cutoff:
                    return True
            except ValueError:
                pass
    return False


def record_sent(job_name: str, message: str) -> None:
    """Record that `message` was sent for `job_name` right now."""
    msg_hash = _compute_hash(message)
    records = _load()
    records = _cleanup(records)
    records.append({
        "job_name": job_name,
        "msg_hash": msg_hash,
        "sent_at": datetime.datetime.now().isoformat(),
    })
    _save_atomic(records)
