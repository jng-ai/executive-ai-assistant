"""
Memory — stores tasks, health logs, notes, and preferences.
Uses a local JSON file now; swap Supabase URL in .env to upgrade later.
"""

import json
import os
import datetime
from pathlib import Path

DATA_DIR = Path(__file__).parent.parent / "data"
TASKS_FILE = DATA_DIR / "tasks.json"
HEALTH_FILE = DATA_DIR / "health.json"
NOTES_FILE = DATA_DIR / "notes.json"


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

def log_health(metric: str, value: str, note: str = "") -> dict:
    logs = _load(HEALTH_FILE)
    entry = {
        "metric": metric,
        "value": value,
        "note": note,
        "date": datetime.date.today().isoformat(),
        "timestamp": datetime.datetime.now().isoformat(),
    }
    logs.append(entry)
    _save(HEALTH_FILE, logs)
    return entry


def get_health_summary(days: int = 7) -> list:
    logs = _load(HEALTH_FILE)
    cutoff = (datetime.date.today() - datetime.timedelta(days=days)).isoformat()
    return [l for l in logs if l.get("date", "") >= cutoff]


# ── Notes ──────────────────────────────────────────────────────────────────────

def add_note(content: str, category: str = "general") -> dict:
    notes = _load(NOTES_FILE)
    entry = {
        "id": len(notes) + 1,
        "content": content,
        "category": category,
        "created": datetime.datetime.now().isoformat(),
    }
    notes.append(entry)
    _save(NOTES_FILE, notes)
    return entry
