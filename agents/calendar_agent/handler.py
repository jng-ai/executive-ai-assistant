"""
Calendar Agent v2 — natural language interface to Google Calendar.

v2 additions:
- Today's agenda quick view
- Conflict check before creating
- Delete event by keyword
- run_morning_briefing() for scheduled 7:45 AM push
- find_free_slots now checks ALL calendars
- Multi-week date parsing (next week, in 2 weeks, etc.)
"""

import datetime
import logging
import re
import json
from core.llm import chat
from integrations.google.auth import is_configured

logger = logging.getLogger(__name__)

# Module-level imports so tests can patch these symbols directly.
# These will fail gracefully if Google credentials aren't configured.
try:
    from integrations.google.calendar_client import (
        list_events, create_event, find_free_slots, format_events,
        get_todays_events, delete_event, check_conflicts, get_events_for_date,
    )
except Exception:
    list_events = create_event = find_free_slots = format_events = None  # type: ignore
    get_todays_events = delete_event = check_conflicts = get_events_for_date = None  # type: ignore

SYSTEM = """You are Justin Ngai's executive calendar assistant. You help schedule, manage, and optimize his time.

Justin's context:
- Lives in NYC, works Eastern Time
- Has a day job (healthcare operations) — weekdays typically busy 9am–6pm
- Side businesses: infusion consulting, mortgage notes, investing
- Likes to work out 3-4x/week, swim in apartment pool
- Prefers mornings for deep work, evenings free when possible

When scheduling:
- Default to 1-hour blocks unless specified
- Warn about conflicts before confirming
- Suggest efficient times (batch similar activities)

When showing calendar:
- Lead with today/tomorrow first, grouped by day
- Flag anything needing prep, travel, or action

Keep responses concise and phone-friendly."""


PARSE_PROMPT = """Extract calendar intent from this message. Return JSON only.

Return:
{
  "action": "today" | "tomorrow" | "date" | "list" | "create" | "free_slots" | "delete" | "question",
  "title": "event title if creating/deleting",
  "date": "YYYY-MM-DD if mentioned",
  "time": "HH:MM in 24h format if mentioned",
  "duration_minutes": 60,
  "location": "location if mentioned",
  "description": "any notes",
  "days_ahead": 7
}

Today is DATE_PLACEHOLDER. Timezone: Eastern Time.

Date resolution rules:
- "today" → TODAY
- "tomorrow" → TOMORROW
- Day names (Monday, Tuesday...) → next occurrence of that day
- "next week" → 7 days from today
- "in 2 weeks" → 14 days from today

Action rules:
- "today" → use action "today" (no date needed)
- Any question about tomorrow → use action "tomorrow" (no date needed)
- Any question about a specific named day or date → use action "date" with the resolved date
- Listing multiple days/weeks → use action "list" with days_ahead

Examples:
"What's on my calendar today?" → {"action":"today"}
"Do I have plans tomorrow?" → {"action":"tomorrow"}
"What's on tomorrow?" → {"action":"tomorrow"}
"Am I busy tomorrow?" → {"action":"tomorrow"}
"What's on Thursday?" → {"action":"date","date":"THURSDAY_DATE"}
"Any events Friday?" → {"action":"date","date":"FRIDAY_DATE"}
"Schedule dinner with Alex Friday 7pm" → {"action":"create","title":"Dinner with Alex","date":"FRIDAY_DATE","time":"19:00","duration_minutes":120}
"What's on my calendar this week?" → {"action":"list","days_ahead":7}
"Am I free Thursday afternoon?" → {"action":"free_slots","date":"THURSDAY_DATE"}
"Cancel my call with Dr. Smith" → {"action":"delete","title":"call with Dr. Smith"}
"Add a meeting next Monday at 10am" → {"action":"create","date":"NEXT_MONDAY_DATE","time":"10:00"}
"""


def _parse_request(message: str) -> dict:
    today = datetime.date.today()
    prompt = PARSE_PROMPT.replace("DATE_PLACEHOLDER", today.strftime("%Y-%m-%d (%A)"))

    # Build date lookup including day names and relative offsets
    days = {
        "today": today,
        "tomorrow": today + datetime.timedelta(days=1),
        "next week": today + datetime.timedelta(days=7),
        "in 2 weeks": today + datetime.timedelta(days=14),
        "in two weeks": today + datetime.timedelta(days=14),
    }
    # Next occurrence of each weekday
    for i in range(7):
        d = today + datetime.timedelta(days=i)
        day_name = d.strftime("%A").lower()
        if day_name not in days:
            days[day_name] = d

    # "next Monday/Tuesday..." = next week's occurrence
    for i in range(7):
        d = today + datetime.timedelta(days=7 + i)
        day_name = f"next {d.strftime('%A').lower()}"
        days[day_name] = d

    raw = chat(prompt, message, max_tokens=300)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        parsed = json.loads(raw)
        date_str = parsed.get("date", "")
        if date_str:
            for keyword, date_obj in days.items():
                if keyword in date_str.lower():
                    parsed["date"] = date_obj.strftime("%Y-%m-%d")
                    break
        return parsed
    except Exception:
        return {"action": "question"}


def handle(message: str) -> str:
    if not is_configured():
        return (
            "⚠️ Google Calendar not connected yet.\n\n"
            "Run `python scripts/google_auth.py` to authorize."
        )

    parsed = _parse_request(message)
    action = parsed.get("action", "question")

    # ── Today's quick agenda ────────────────────────────────────────────────
    if action == "today":
        events = get_todays_events()
        if not events:
            return "📅 Nothing on the calendar today — clean slate. Want to schedule something?"
        formatted = format_events(events)
        return f"📅 *Today's agenda:*\n\n{formatted}"

    # ── Tomorrow's agenda ───────────────────────────────────────────────────
    elif action == "tomorrow":
        tomorrow = datetime.date.today() + datetime.timedelta(days=1)
        events = get_events_for_date(tomorrow)
        if not events:
            return f"📅 Nothing on the calendar tomorrow ({tomorrow.strftime('%A, %b %-d')}) — free day!"
        formatted = format_events(events)
        return f"📅 *Tomorrow ({tomorrow.strftime('%A, %b %-d')}):*\n\n{formatted}"

    # ── Specific date agenda ─────────────────────────────────────────────────
    elif action == "date":
        date_str = parsed.get("date", "")
        try:
            date_obj = datetime.date.fromisoformat(date_str)
        except (ValueError, TypeError):
            date_obj = datetime.date.today() + datetime.timedelta(days=1)
        events = get_events_for_date(date_obj)
        day_str = date_obj.strftime("%A, %B %-d")
        if not events:
            return f"📅 Nothing on {day_str} — clear schedule."
        formatted = format_events(events)
        return f"📅 *{day_str}:*\n\n{formatted}"

    # ── List events ─────────────────────────────────────────────────────────
    elif action == "list":
        days = parsed.get("days_ahead", 7)
        # If a specific date was given, fetch just that date
        date_str = parsed.get("date", "")
        if date_str:
            try:
                date_obj = datetime.date.fromisoformat(date_str)
                events = get_events_for_date(date_obj)
                day_str = date_obj.strftime("%A, %B %-d")
                if not events:
                    return f"📅 Nothing on {day_str} — free."
                return f"📅 *{day_str}:*\n\n{format_events(events)}"
            except (ValueError, TypeError):
                pass
        events = list_events(days_ahead=days)
        if not events:
            return f"📅 Nothing scheduled in the next {days} days. Want to add something?"
        formatted = format_events(events)
        label = "week" if days == 7 else f"{days} days"
        return f"📅 *Next {label}:*\n\n{formatted}"

    # ── Find free slots ─────────────────────────────────────────────────────
    elif action == "free_slots":
        date = parsed.get("date", datetime.date.today().strftime("%Y-%m-%d"))
        duration = parsed.get("duration_minutes", 60)
        slots = find_free_slots(date, duration)
        d = datetime.date.fromisoformat(date)
        day_str = d.strftime("%A, %B %-d")
        if slots:
            slot_list = " · ".join(slots)
            return f"🕐 *Free on {day_str}:*\n{slot_list}\n\nWant me to block one of these?"
        else:
            return f"📵 {day_str} looks fully booked. Want me to check another day?"

    # ── Delete event ────────────────────────────────────────────────────────
    elif action == "delete":
        keyword = parsed.get("title", "")
        if not keyword:
            return "Which event should I delete? Give me the name or keyword."
        result = delete_event(keyword)
        return result

    # ── Create event ────────────────────────────────────────────────────────
    elif action == "create":
        title = parsed.get("title", "")
        date = parsed.get("date", "")
        time = parsed.get("time", "")
        duration = parsed.get("duration_minutes", 60)
        location = parsed.get("location", "")
        description = parsed.get("description", "")

        if not title or not date:
            return chat(SYSTEM,
                f"User wants to schedule something but details are missing. Message: {message}\n\n"
                "Ask for what's missing (title, date, or time) in 1–2 sentences.",
                max_tokens=100)

        # Conflict check
        if time:
            conflicts = check_conflicts(date, time, duration)
            if conflicts:
                conflict_list = ", ".join(f"*{c}*" for c in conflicts)
                return (
                    f"⚠️ *Heads up — conflict detected:*\n"
                    f"You already have: {conflict_list} at that time.\n\n"
                    f"Still want to create *{title}*? Reply 'yes schedule it anyway' or pick a different time."
                )
            start_dt = f"{date}T{time}:00"
            h, m = int(time[:2]), int(time[3:])
            total_min = h * 60 + m + duration
            end_dt = f"{date}T{total_min // 60:02d}:{total_min % 60:02d}:00"
        else:
            start_dt = date
            end_dt = date

        event = create_event(title, start_dt, end_dt, description=description, location=location)

        if event:
            d = datetime.date.fromisoformat(date)
            day_str = d.strftime("%A, %B %-d")
            time_str = f" at {_fmt_time(time)}" if time else " (all day)"
            loc_str = f"\n📍 {location}" if location else ""
            link = event.get("htmlLink", "")
            link_str = f"\n[Open in Calendar]({link})" if link else ""
            return (
                f"✅ *Scheduled!*\n\n"
                f"📅 {title}\n"
                f"🗓 {day_str}{time_str}{loc_str}{link_str}\n\n"
                f"_Added to your Google Calendar_"
            )
        else:
            return "⚠️ Couldn't create the event. Check Google Calendar permissions."

    # ── General question ────────────────────────────────────────────────────
    else:
        from core.conversation import get_history_for_llm
        events = list_events(days_ahead=14)
        event_summary = format_events(events[:10]) if events else "No upcoming events"
        context = f"Justin's upcoming calendar:\n{event_summary}\n\nQuestion: {message}"
        history = get_history_for_llm(n=3)
        return chat(SYSTEM, context, max_tokens=400, history=history)


def run_morning_briefing() -> str:
    """
    Proactive 7:45 AM calendar briefing.
    Returns None/empty if nothing notable today or tomorrow.
    """
    if not is_configured():
        return ""
    try:
        from integrations.google.calendar_client import get_todays_events, list_events, format_events
        today = datetime.date.today()
        tomorrow = today + datetime.timedelta(days=1)

        today_events = get_todays_events()
        tomorrow_events = list_events(days_ahead=2)
        tomorrow_only = [
            ev for ev in tomorrow_events
            if ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", ""))[:10]
            == tomorrow.isoformat()
        ]

        if not today_events and not tomorrow_only:
            return ""   # Silent — nothing to report

        parts = ["🗓 *Morning Calendar Briefing*\n"]

        if today_events:
            parts.append(f"*Today ({today.strftime('%A %b %-d')}):*")
            parts.append(format_events(today_events))
        else:
            parts.append(f"*Today:* Clear schedule ✨")

        if tomorrow_only:
            parts.append(f"\n*Tomorrow ({tomorrow.strftime('%A %b %-d')}):*")
            parts.append(format_events(tomorrow_only[:3]))

        return "\n".join(parts)
    except Exception as e:
        logger.warning("Morning briefing error: %s", e)
        return ""


def run_eod_calendar() -> str:
    """
    Evening calendar summary — remaining events today + full tomorrow preview.
    Called at 6 PM ET. Returns empty string if nothing to report.
    """
    if not is_configured():
        return ""
    try:
        from integrations.google.calendar_client import get_todays_events, list_events, format_events
        now = datetime.datetime.now()
        today = datetime.date.today()
        tomorrow = today + datetime.timedelta(days=1)

        # Remaining events today (start time > now)
        all_today = get_todays_events()
        remaining_today = []
        for ev in all_today:
            dt_str = ev.get("start", {}).get("dateTime", "")
            if dt_str:
                try:
                    ev_dt = datetime.datetime.fromisoformat(dt_str.replace("Z", "+00:00"))
                    ev_dt_local = ev_dt.astimezone(datetime.timezone(datetime.timedelta(hours=-4)))
                    if ev_dt_local > now.astimezone(datetime.timezone(datetime.timedelta(hours=-4))):
                        remaining_today.append(ev)
                except Exception:
                    pass
            # All-day events always count
            elif ev.get("start", {}).get("date"):
                remaining_today.append(ev)

        # Tomorrow events
        all_next = list_events(days_ahead=2)
        tomorrow_events = [
            ev for ev in all_next
            if ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", ""))[:10]
            == tomorrow.isoformat()
        ]

        parts = []

        if remaining_today:
            parts.append(f"*Still today:*\n{format_events(remaining_today)}")

        if tomorrow_events:
            parts.append(f"*Tomorrow ({tomorrow.strftime('%A %b %-d')}):*\n{format_events(tomorrow_events[:5])}")
        else:
            parts.append(f"*Tomorrow:* Nothing scheduled — free day ✨")

        # Pending follow-ups due tomorrow
        try:
            from core.followups import list_all_pending
            due_tomorrow = [
                f for f in list_all_pending()
                if f["due"][:10] == tomorrow.isoformat()
            ]
            if due_tomorrow:
                fu_lines = "\n".join(
                    f"  • {f['type'].title()} → {f['contact']} re: {f['context']}"
                    for f in due_tomorrow
                )
                parts.append(f"*Follow-ups firing tomorrow:*\n{fu_lines}")
        except Exception:
            pass

        return "\n\n".join(parts) if parts else ""
    except Exception as e:
        logger.warning("EOD calendar error: %s", e)
        return ""


def _fmt_time(time_str: str) -> str:
    """Convert '19:00' to '7:00pm'."""
    try:
        h, m = int(time_str[:2]), int(time_str[3:5])
        period = "am" if h < 12 else "pm"
        h12 = h % 12 or 12
        return f"{h12}:{m:02d}{period}"
    except Exception:
        return time_str
