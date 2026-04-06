"""
Memory — stores tasks, health logs, notes, and preferences.
Local JSON is the primary store (fast, offline).
Notion is synced in the background when configured.
"""

import json
import logging
import os
import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
TASKS_FILE  = DATA_DIR / "tasks.json"
HEALTH_FILE = DATA_DIR / "health.json"
NOTES_FILE  = DATA_DIR / "notes.json"


def _load(path: Path) -> list:
    path.parent.mkdir(exist_ok=True)
    if not path.exists():
        return []
    try:
        return json.loads(path.read_text())
    except Exception:
        return []


def _save(path: Path, data: list):
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def _notion_sync(db_key: str, name: str, props: dict):
    """Fire-and-forget Notion sync — fails silently so it never blocks the bot."""
    try:
        from integrations.notion.client import add_row, is_configured
        if is_configured():
            add_row(db_key, name, props)
    except Exception:
        pass


# ── Tasks ──────────────────────────────────────────────────────────────────────

def add_task(task: str, due: str = "", priority: str = "normal") -> dict:
    tasks = _load(TASKS_FILE)
    entry = {
        "id": len(tasks) + 1,
        "task": task,
        "due": due,
        "priority": priority,
        "status": "open",
        "created": datetime.datetime.now().isoformat(),
    }
    tasks.append(entry)
    _save(TASKS_FILE, tasks)

    # Sync to Notion
    _notion_sync("tasks", task, {
        "Due Date": due or datetime.date.today().isoformat(),
        "Priority": priority,
        "Status":   "open",
        "Source":   "Telegram bot",
    })

    return entry


def list_tasks(status: str = "open") -> list:
    tasks = _load(TASKS_FILE)
    return [t for t in tasks if t.get("status") == status]


def complete_task(task_id: int) -> bool:
    tasks = _load(TASKS_FILE)
    for t in tasks:
        if t.get("id") == task_id:
            t["status"] = "done"
            t["completed"] = datetime.datetime.now().isoformat()
            _save(TASKS_FILE, tasks)
            return True
    return False


# ── Health ─────────────────────────────────────────────────────────────────────

def log_health(metric: str, value: str, note: str = "", vs_target: str = "") -> dict:
    logs = _load(HEALTH_FILE)
    today = datetime.date.today().isoformat()
    entry = {
        "metric":    metric,
        "value":     value,
        "note":      note,
        "date":      today,
        "timestamp": datetime.datetime.now().isoformat(),
    }
    logs.append(entry)
    _save(HEALTH_FILE, logs)

    # Sync to Notion
    _notion_sync("health_log", f"{metric}: {value}", {
        "Date":      today,
        "Metric":    metric,
        "Value":     value,
        "Unit":      _unit_for(metric),
        "Notes":     note,
        "vs Target": vs_target,
    })

    return entry


def update_last_food_log(additional_info: str) -> dict | None:
    """
    Append correction/detail to the most recent meal/snack/drink log entry today.
    Returns the updated entry, or None if no food log found today.
    """
    logs = _load(HEALTH_FILE)
    today = datetime.date.today().isoformat()
    food_metrics = {"meal", "snack", "drink"}
    for i in range(len(logs) - 1, -1, -1):
        entry = logs[i]
        if entry.get("date") == today and entry.get("metric") in food_metrics:
            old_value = entry.get("value", "")
            entry["value"] = f"{old_value} ({additional_info})"
            entry["corrected"] = datetime.datetime.now().isoformat()
            _save(HEALTH_FILE, logs)
            return entry
    return None


def get_health_summary(days: int = 7) -> list:
    logs = _load(HEALTH_FILE)
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    return [l for l in logs if l.get("date", "") >= cutoff]


def _unit_for(metric: str) -> str:
    return {
        "weight": "lbs", "sleep": "hours", "workout": "session",
        "meal": "food log", "snack": "food log", "drink": "beverage log",
    }.get(metric, "")


# ── Notes ──────────────────────────────────────────────────────────────────────

def add_note(content: str, category: str = "general") -> dict:
    notes = _load(NOTES_FILE)
    entry = {
        "id":       len(notes) + 1,
        "content":  content,
        "category": category,
        "created":  datetime.datetime.now().isoformat(),
    }
    notes.append(entry)
    _save(NOTES_FILE, notes)
    return entry


# ── Notion shortcuts for agents ────────────────────────────────────────────────

def save_mortgage_deal(state: str, upb: float, ask: float, est_yield: str,
                        rating: str, link: str = "", notes: str = "") -> bool:
    discount = round((upb - ask) / upb, 4) if upb > 0 else 0
    name = f"{state} | UPB ${upb:,.0f} | Ask ${ask:,.0f}"
    return _notion_sync_direct("mortgage_deals", name, {
        "State":      state,
        "UPB":        upb,
        "Ask Price":  ask,
        "Discount %": discount,
        "Est Yield":  est_yield,
        "Rating":     rating,
        "Status":     "New",
        "Link":       link,
        "Notes":      notes,
    })


def save_investment_idea(company: str, ticker: str, thesis: str, catalyst: str,
                          risk: str, action: str, urgency: str) -> bool:
    name = f"{ticker} — {company}"
    return _notion_sync_direct("investment_ideas", name, {
        "Ticker":   ticker,
        "Thesis":   thesis,
        "Catalyst": catalyst,
        "Risk":     risk,
        "Action":   action,
        "Urgency":  urgency,
        "Date":     datetime.date.today().isoformat(),
    })


def save_consulting_lead(org: str, signal: str, priority: str, angle: str,
                          outreach: str, link: str = "") -> bool:
    return _notion_sync_direct("consulting_leads", org, {
        "Organization":   org,
        "Signal":         signal,
        "Priority":       priority,
        "Infusion Angle": angle,
        "Outreach":       outreach,
        "Status":         "New",
        "Link":           link,
        "Date":           datetime.date.today().isoformat(),
    })


def _notion_sync_direct(db_key: str, name: str, props: dict) -> bool:
    try:
        from integrations.notion.client import add_row, is_configured
        if is_configured():
            return add_row(db_key, name, props)
    except Exception:
        pass
    return False
