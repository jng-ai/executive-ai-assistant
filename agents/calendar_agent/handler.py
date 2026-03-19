"""
Calendar Agent — natural language interface to Google Calendar.
Handles scheduling, viewing events, finding free time, and smart suggestions.
"""

import datetime
import re
import json
from core.llm import chat
from integrations.google.auth import is_configured

SYSTEM = """You are Justin Ngai's executive calendar assistant. You help schedule, manage, and optimize his time.

Justin's context:
- Lives in NYC, works Eastern Time
- Has a day job (healthcare operations) — weekdays are typically busy 9am-6pm
- Side businesses: infusion consulting, mortgage notes, investing
- Likes to work out 3-4x/week, swim in apartment pool
- Prefers mornings for deep work, evenings free when possible

When scheduling:
- Default to 1-hour blocks unless specified
- Always confirm date, time, and title before creating
- Suggest efficient times (batch similar activities)
- Flag conflicts or tight schedules

When showing calendar:
- Lead with today/tomorrow first
- Group by day
- Flag anything that needs prep or travel

Keep responses concise and phone-friendly."""


PARSE_PROMPT = """Extract calendar event details from this message. Return JSON only.

Return:
{
  "action": "create" | "list" | "free_slots" | "question",
  "title": "event title if creating",
  "date": "YYYY-MM-DD if mentioned",
  "time": "HH:MM in 24h format if mentioned",
  "duration_minutes": 60,
  "location": "location if mentioned",
  "description": "any notes",
  "days_ahead": 7
}

Today is DATE_PLACEHOLDER. Timezone: Eastern Time.

Examples:
"Schedule dinner with Alex Friday 7pm" → {"action":"create","title":"Dinner with Alex","date":"FRIDAY_DATE","time":"19:00","duration_minutes":120}
"What's on my calendar this week?" → {"action":"list","days_ahead":7}
"Am I free Thursday afternoon?" → {"action":"free_slots","date":"THURSDAY_DATE"}
"Add a call with Dr. Smith tomorrow at 2pm for 30 min" → {"action":"create","title":"Call with Dr. Smith","date":"TOMORROW","time":"14:00","duration_minutes":30}
"""


def _parse_request(message: str) -> dict:
    today = datetime.date.today()
    prompt = PARSE_PROMPT.replace("DATE_PLACEHOLDER", today.strftime("%Y-%m-%d (%A)"))

    # Add day offsets for common references
    days = {
        "today": today,
        "tomorrow": today + datetime.timedelta(days=1),
    }
    for i in range(7):
        d = today + datetime.timedelta(days=i)
        days[d.strftime("%A").lower()] = d  # "monday", "tuesday", etc.

    raw = chat(prompt, message, max_tokens=300)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        parsed = json.loads(raw)
        # Resolve relative dates
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

    from integrations.google.calendar_client import (
        list_events, create_event, find_free_slots, format_events
    )

    parsed = _parse_request(message)
    action = parsed.get("action", "question")

    if action == "list":
        days = parsed.get("days_ahead", 7)
        events = list_events(days_ahead=days)
        if not events:
            return f"📅 No events in the next {days} days. Want me to schedule something?"
        formatted = format_events(events)
        return f"📅 *Your next {days} days:*\n\n{formatted}"

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

    elif action == "create":
        title = parsed.get("title", "")
        date = parsed.get("date", "")
        time = parsed.get("time", "")
        duration = parsed.get("duration_minutes", 60)
        location = parsed.get("location", "")
        description = parsed.get("description", "")

        if not title or not date:
            # Ask LLM to clarify
            return chat(SYSTEM, f"The user wants to schedule something but I need more details. Message: {message}\n\nAsk for what's missing (title, date, or time) in 1-2 sentences.", max_tokens=100)

        if time:
            start_dt = f"{date}T{time}:00"
            # Calculate end
            h, m = int(time[:2]), int(time[3:])
            total_min = h * 60 + m + duration
            end_dt = f"{date}T{total_min // 60:02d}:{total_min % 60:02d}:00"
        else:
            start_dt = date  # all-day
            end_dt = date

        event = create_event(title, start_dt, end_dt, description=description, location=location)

        if event:
            d = datetime.date.fromisoformat(date)
            day_str = d.strftime("%A, %B %-d")
            time_str = f" at {_fmt_time(time)}" if time else " (all day)"
            loc_str = f"\n📍 {location}" if location else ""
            return (
                f"✅ *Scheduled!*\n\n"
                f"📅 {title}\n"
                f"🗓 {day_str}{time_str}{loc_str}\n\n"
                f"_Added to your Google Calendar_"
            )
        else:
            return "⚠️ Couldn't create the event. Check Google Calendar permissions."

    else:
        # General calendar question — use AI with calendar context
        events = list_events(days_ahead=14)
        event_summary = format_events(events[:10]) if events else "No upcoming events"
        context = f"Justin's upcoming calendar:\n{event_summary}\n\nQuestion: {message}"
        return chat(SYSTEM, context, max_tokens=400)


def _fmt_time(time_str: str) -> str:
    """Convert '19:00' to '7:00pm'."""
    try:
        h, m = int(time_str[:2]), int(time_str[3:5])
        period = "am" if h < 12 else "pm"
        h12 = h % 12 or 12
        return f"{h12}:{m:02d}{period}"
    except Exception:
        return time_str
