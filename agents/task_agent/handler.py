"""
Task & Reminder Agent — create, list, complete, delete tasks and timed reminders.

Features:
  - Natural language create: "remind me to call dentist tomorrow at 10am"
  - List open tasks: "what are my tasks", "show reminders"
  - Complete: "done #3", "mark task 2 complete"
  - Delete: "delete task 4", "remove reminder 1"
  - Snooze: "snooze #2 by 2 days"
  - Timed push notifications: run_reminder_check() fires due reminders via APScheduler
"""

import datetime
import json
import logging
import re
from pathlib import Path
from zoneinfo import ZoneInfo

from core.llm import chat

logger = logging.getLogger(__name__)
_ET = ZoneInfo("America/New_York")

DATA_DIR = Path(__file__).parent.parent.parent / "data"
TASKS_FILE = DATA_DIR / "tasks.json"

SYSTEM = """You are a task and reminder assistant for Justin Ngai.
Parse task/reminder requests and return structured JSON. Be precise with dates and times.
Today's date in ET will be provided in the prompt."""


# ── Storage helpers ────────────────────────────────────────────────────────────

def _load() -> list[dict]:
    try:
        with open(TASKS_FILE) as f:
            return json.load(f)
    except Exception:
        return []


def _save(tasks: list[dict]) -> None:
    DATA_DIR.mkdir(exist_ok=True)
    with open(TASKS_FILE, "w") as f:
        json.dump(tasks, f, indent=2)


def _next_id() -> int:
    tasks = _load()
    return max((t.get("id", 0) for t in tasks), default=0) + 1


def _et_now() -> datetime.datetime:
    return datetime.datetime.now(tz=_ET)


# ── Core CRUD ──────────────────────────────────────────────────────────────────

def add_task(
    title: str,
    due_date: str = "",
    due_time: str = "",
    priority: str = "normal",
    notify: bool = True,
) -> dict:
    """Add a task/reminder. due_date: YYYY-MM-DD, due_time: HH:MM (24h ET)."""
    tasks = _load()
    entry = {
        "id": _next_id(),
        "title": title,
        "due_date": due_date,
        "due_time": due_time,
        "priority": priority,
        "notify": notify,
        "status": "open",
        "notified": False,
        "created": _et_now().isoformat(),
    }
    tasks.append(entry)
    _save(tasks)
    return entry


def list_tasks(status: str = "open") -> list[dict]:
    tasks = _load()
    result = [t for t in tasks if t.get("status") == status]
    result.sort(key=lambda t: (t.get("due_date", "9999"), t.get("due_time", "23:59")))
    return result


def complete_task(task_id: int) -> bool:
    tasks = _load()
    for t in tasks:
        if t.get("id") == task_id:
            t["status"] = "done"
            t["completed"] = _et_now().isoformat()
            _save(tasks)
            return True
    return False


def delete_task(task_id: int) -> bool:
    tasks = _load()
    new = [t for t in tasks if t.get("id") != task_id]
    if len(new) < len(tasks):
        _save(new)
        return True
    return False


def snooze_task(task_id: int, days: int) -> bool:
    tasks = _load()
    for t in tasks:
        if t.get("id") == task_id:
            due = t.get("due_date", "")
            if due:
                d = datetime.date.fromisoformat(due) + datetime.timedelta(days=days)
                t["due_date"] = d.isoformat()
            else:
                t["due_date"] = (datetime.date.today() + datetime.timedelta(days=days)).isoformat()
            t["notified"] = False  # reset so it fires again
            _save(tasks)
            return True
    return False


# ── LLM parsing ───────────────────────────────────────────────────────────────

def _parse_request(message: str) -> dict:
    """Use LLM to parse a task/reminder message into structured intent."""
    now = _et_now()
    today = now.date().isoformat()
    # Compute named dates
    tomorrow = (now.date() + datetime.timedelta(days=1)).isoformat()
    day_names = {
        "monday": 0, "tuesday": 1, "wednesday": 2, "thursday": 3,
        "friday": 4, "saturday": 5, "sunday": 6,
    }
    # Next occurrence of each weekday
    weekday_dates = {}
    for name, wd in day_names.items():
        delta = (wd - now.weekday()) % 7 or 7
        weekday_dates[name] = (now.date() + datetime.timedelta(days=delta)).isoformat()

    weekday_context = "\n".join(f"  next {k}: {v}" for k, v in weekday_dates.items())

    prompt = (
        f"Today is {today} ({now.strftime('%A')}). Current time ET: {now.strftime('%H:%M')}.\n"
        f"Named dates for reference:\n  tomorrow: {tomorrow}\n{weekday_context}\n\n"
        f"Parse this message and return ONLY valid JSON with these fields:\n"
        f'{{"action": "create|list|done|delete|snooze|unknown", '
        f'"title": "task description (for create)", '
        f'"task_id": null_or_number, '
        f'"due_date": "YYYY-MM-DD or empty", '
        f'"due_time": "HH:MM 24h or empty", '
        f'"priority": "high|normal|low", '
        f'"notify": true, '
        f'"snooze_days": null_or_number, '
        f'"status_filter": "open|done|all"}}\n\n'
        f'Message: "{message}"\n\n'
        f"Rules:\n"
        f"- 'remind me', 'reminder', 'don't forget' → create with notify:true\n"
        f"- 'add task', 'todo', 'to-do', 'to do' → create with notify:true\n"
        f"- 'show tasks', 'my tasks', 'what do I have', 'list' → list\n"
        f"- 'done #N', 'complete N', 'finished N', 'mark N done' → done with task_id\n"
        f"- 'delete', 'remove', 'cancel task' → delete with task_id\n"
        f"- 'snooze', 'push back', 'delay' → snooze with snooze_days\n"
        f"- Extract time like '10am' → '10:00', '2:30pm' → '14:30', 'noon' → '12:00', 'eod' → '17:00'\n"
        f"- 'tonight' → current date, '8pm' time; 'this evening' → current date\n"
        f"- If no time given for a reminder, leave due_time empty (will notify at 9am)\n"
        f"- 'urgent', 'asap', 'important' → priority: high"
    )
    raw = chat(SYSTEM, prompt, max_tokens=200)
    # Strip markdown fences
    raw = re.sub(r"```json?\s*|\s*```", "", raw.strip())
    try:
        return json.loads(raw)
    except Exception:
        return {"action": "unknown"}


# ── Format helpers ─────────────────────────────────────────────────────────────

def _format_task(t: dict) -> str:
    status_icon = "✅" if t.get("status") == "done" else (
        "🔴" if t.get("priority") == "high" else "📋"
    )
    due = t.get("due_date", "")
    due_time = t.get("due_time", "")
    due_str = ""
    if due:
        try:
            d = datetime.date.fromisoformat(due)
            today = datetime.date.today()
            delta = (d - today).days
            if delta == 0:
                label = "today"
            elif delta == 1:
                label = "tomorrow"
            elif delta < 0:
                label = f"overdue ({abs(delta)}d ago)"
            elif delta <= 7:
                label = d.strftime("%A")
            else:
                label = d.strftime("%b %-d")
            if due_time:
                h, m = map(int, due_time.split(":"))
                ampm = "am" if h < 12 else "pm"
                h12 = h % 12 or 12
                time_str = f" at {h12}:{m:02d}{ampm}"
            else:
                time_str = ""
            due_str = f" — _{label}{time_str}_"
        except Exception:
            due_str = f" — _{due}_"
    notify_icon = "🔔" if t.get("notify") and t.get("status") == "open" else ""
    return f"{status_icon} #{t['id']} {t['title']}{due_str} {notify_icon}".strip()


def _format_task_list(tasks: list[dict], label: str = "open") -> str:
    if not tasks:
        return f"No {label} tasks."
    lines = [f"📋 *Tasks ({label}):*\n"]
    today = datetime.date.today().isoformat()
    overdue = [t for t in tasks if t.get("due_date", "9999") < today]
    due_today = [t for t in tasks if t.get("due_date") == today]
    upcoming = [t for t in tasks if t.get("due_date", "") > today or not t.get("due_date")]

    if overdue:
        lines.append("⚠️ *Overdue:*")
        for t in overdue:
            lines.append(f"  {_format_task(t)}")
        lines.append("")
    if due_today:
        lines.append("📅 *Due today:*")
        for t in due_today:
            lines.append(f"  {_format_task(t)}")
        lines.append("")
    if upcoming:
        lines.append("🗓 *Upcoming:*")
        for t in upcoming:
            lines.append(f"  {_format_task(t)}")

    lines.append("\n_Say 'done #N' to complete, 'delete #N' to remove, 'snooze #N 2 days' to postpone._")
    return "\n".join(lines)


# ── Main handler ───────────────────────────────────────────────────────────────

def handle(message: str) -> str:
    parsed = _parse_request(message)
    action = parsed.get("action", "unknown")

    if action == "create":
        title = parsed.get("title", "").strip()
        if not title:
            return "What should I remind you about? Give me a title or description."

        due_date = parsed.get("due_date", "")
        due_time = parsed.get("due_time", "")
        priority = parsed.get("priority", "normal")
        notify = parsed.get("notify", True)

        entry = add_task(
            title=title,
            due_date=due_date,
            due_time=due_time,
            priority=priority,
            notify=notify,
        )

        # Build confirmation
        due_str = ""
        if due_date:
            d = datetime.date.fromisoformat(due_date)
            today = datetime.date.today()
            delta = (d - today).days
            if delta == 0:
                label = "today"
            elif delta == 1:
                label = "tomorrow"
            else:
                label = d.strftime("%A, %b %-d")
            if due_time:
                h, m = map(int, due_time.split(":"))
                ampm = "am" if h < 12 else "pm"
                h12 = h % 12 or 12
                due_str = f" — {label} at {h12}:{m:02d}{ampm}"
            else:
                due_str = f" — {label}"

        notify_str = " 🔔 I'll remind you." if notify and due_date else ""
        priority_str = " 🔴 *High priority.*" if priority == "high" else ""
        return (
            f"✅ Added: *{title}*{due_str}{notify_str}{priority_str}\n"
            f"_Task #{entry['id']}_"
        )

    elif action == "list":
        status = parsed.get("status_filter", "open")
        if status == "all":
            tasks = _load()
        else:
            tasks = list_tasks(status)
        return _format_task_list(tasks, label=status)

    elif action == "done":
        task_id = parsed.get("task_id")
        if not task_id:
            # Try to extract from message directly
            m = re.search(r'#?(\d+)', message)
            task_id = int(m.group(1)) if m else None
        if task_id and complete_task(int(task_id)):
            return f"✅ Task #{task_id} marked complete!"
        return f"Couldn't find task #{task_id}. Say 'my tasks' to see your list."

    elif action == "delete":
        task_id = parsed.get("task_id")
        if not task_id:
            m = re.search(r'#?(\d+)', message)
            task_id = int(m.group(1)) if m else None
        if task_id and delete_task(int(task_id)):
            return f"🗑 Task #{task_id} deleted."
        return f"Couldn't find task #{task_id}."

    elif action == "snooze":
        task_id = parsed.get("task_id")
        days = parsed.get("snooze_days") or 1
        if not task_id:
            m = re.search(r'#?(\d+)', message)
            task_id = int(m.group(1)) if m else None
        if task_id and snooze_task(int(task_id), int(days)):
            return f"😴 Task #{task_id} snoozed by {days} day{'s' if days != 1 else ''}."
        return f"Couldn't find task #{task_id}."

    else:
        return (
            "I can manage your tasks and reminders. Try:\n"
            "• _'Remind me to call dentist tomorrow at 10am'_\n"
            "• _'Add task: review contract by Friday'_\n"
            "• _'Show my tasks'_\n"
            "• _'Done #3'_ or _'Delete #2'_\n"
            "• _'Snooze #1 by 2 days'_"
        )


# ── Scheduled reminder check ───────────────────────────────────────────────────

def run_reminder_check() -> list[str]:
    """
    Check for due reminders. Called by APScheduler every 30 min.
    Returns list of notification messages to send to Telegram.
    Fires a reminder if: notify=True, status=open, due_date=today,
    due_time within the next 30 min window (or no time and it's 9am window).
    """
    now = _et_now()
    today = now.date().isoformat()
    current_min = now.hour * 60 + now.minute
    window_end = current_min + 31  # 31-min lookahead

    tasks = _load()
    messages = []
    updated = False

    for t in tasks:
        if t.get("status") != "open":
            continue
        if not t.get("notify"):
            continue
        if t.get("notified"):
            continue
        due_date = t.get("due_date", "")
        if not due_date or due_date > today:
            continue

        due_time = t.get("due_time", "")
        should_fire = False

        if due_date < today:
            # Overdue — fire immediately (once)
            should_fire = True
        elif due_time:
            h, m = map(int, due_time.split(":"))
            task_min = h * 60 + m
            if current_min <= task_min < window_end:
                should_fire = True
        else:
            # No time set — fire at 9am window
            if 9 * 60 <= current_min < 9 * 60 + 31:
                should_fire = True

        if should_fire:
            if due_date < today:
                time_str = f"was due {due_date}"
            elif due_time:
                h, m = map(int, due_time.split(":"))
                ampm = "am" if h < 12 else "pm"
                h12 = h % 12 or 12
                time_str = f"due today at {h12}:{m:02d}{ampm}"
            else:
                time_str = "due today"

            priority_prefix = "🔴 " if t.get("priority") == "high" else ""
            messages.append(
                f"🔔 *Reminder:* {priority_prefix}{t['title']}\n"
                f"_{time_str}_ — Task #{t['id']}\n"
                f"_Say 'done #{t['id']}' when finished._"
            )
            t["notified"] = True
            updated = True

    if updated:
        _save(tasks)

    return messages
