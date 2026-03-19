"""
Google Calendar client — create, list, and update calendar events.
"""

import datetime
from googleapiclient.discovery import build
from integrations.google.auth import get_credentials, is_configured


def _service():
    return build("calendar", "v3", credentials=get_credentials(), cache_discovery=False)


def _get_calendar_ids() -> list[str]:
    """Return all non-holiday calendar IDs."""
    try:
        svc = _service()
        cals = svc.calendarList().list().execute()
        return [
            c["id"] for c in cals.get("items", [])
            if "holiday" not in c.get("id", "").lower()
        ]
    except Exception:
        return ["primary"]


def list_events(days_ahead: int = 7) -> list[dict]:
    """Return upcoming events for the next N days across all calendars."""
    if not is_configured():
        return []
    try:
        svc = _service()
        now = datetime.datetime.now(datetime.timezone.utc).isoformat()
        end = (datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=days_ahead)).isoformat()
        all_events = []
        for cal_id in _get_calendar_ids():
            try:
                result = svc.events().list(
                    calendarId=cal_id,
                    timeMin=now,
                    timeMax=end,
                    maxResults=20,
                    singleEvents=True,
                    orderBy="startTime",
                ).execute()
                all_events.extend(result.get("items", []))
            except Exception:
                continue
        # Sort by start time
        def sort_key(ev):
            s = ev.get("start", {})
            return s.get("dateTime", s.get("date", ""))
        all_events.sort(key=sort_key)
        return all_events[:25]
    except Exception as e:
        print(f"Calendar list error: {e}")
        return []


def create_event(title: str, start: str, end: str = None,
                 description: str = "", location: str = "") -> dict | None:
    """
    Create a calendar event.
    start/end: ISO format strings like '2026-03-17T19:00:00' or '2026-03-17' for all-day.
    """
    if not is_configured():
        return None
    try:
        svc = _service()

        # Determine if all-day or timed event
        if "T" in start:
            start_obj = {"dateTime": start, "timeZone": "America/New_York"}
            if not end:
                # Default 1 hour
                dt = datetime.datetime.fromisoformat(start)
                end = (dt + datetime.timedelta(hours=1)).isoformat()
            end_obj = {"dateTime": end, "timeZone": "America/New_York"}
        else:
            start_obj = {"date": start}
            end_obj = {"date": end or start}

        event = {
            "summary": title,
            "description": description,
            "location": location,
            "start": start_obj,
            "end": end_obj,
        }
        created = svc.events().insert(calendarId="jynpriority@gmail.com", body=event).execute()
        return created
    except Exception as e:
        print(f"Calendar create error: {e}")
        return None


def find_free_slots(date: str, duration_minutes: int = 60) -> list[str]:
    """Find free time slots on a given date (YYYY-MM-DD)."""
    if not is_configured():
        return []
    try:
        svc = _service()
        day_start = f"{date}T00:00:00Z"
        day_end   = f"{date}T23:59:59Z"
        result = svc.events().list(
            calendarId="primary",
            timeMin=day_start,
            timeMax=day_end,
            singleEvents=True,
            orderBy="startTime",
        ).execute()
        busy = []
        for ev in result.get("items", []):
            s = ev.get("start", {})
            e = ev.get("end", {})
            if "dateTime" in s:
                busy.append((s["dateTime"][:16], e["dateTime"][:16]))

        # Simple: list morning/afternoon/evening slots not in busy
        candidate_hours = [9, 10, 11, 13, 14, 15, 16, 17, 18, 19]
        free = []
        for h in candidate_hours:
            slot_start = f"{date}T{h:02d}:00"
            slot_end   = f"{date}T{h + duration_minutes // 60:02d}:{duration_minutes % 60:02d}"
            clash = any(s <= slot_start < e or s < slot_end <= e for s, e in busy)
            if not clash:
                free.append(f"{h % 12 or 12}{'am' if h < 12 else 'pm'}")
        return free[:5]
    except Exception as e:
        print(f"Free slot error: {e}")
        return []


def format_events(events: list[dict]) -> str:
    """Format a list of calendar events for Telegram display."""
    if not events:
        return "No upcoming events."
    lines = []
    for ev in events:
        title = ev.get("summary", "Untitled")
        start = ev.get("start", {})
        dt = start.get("dateTime", start.get("date", ""))
        if "T" in dt:
            # Parse and format nicely
            try:
                d = datetime.datetime.fromisoformat(dt.replace("Z", "+00:00"))
                d = d.astimezone(datetime.timezone(datetime.timedelta(hours=-4)))  # ET
                dt_str = d.strftime("%a %b %-d, %-I:%M%p").lower().replace("am","am").replace("pm","pm")
            except Exception:
                dt_str = dt[:16]
        else:
            dt_str = dt
        location = ev.get("location", "")
        loc_str = f" @ {location}" if location else ""
        lines.append(f"📅 *{title}*\n   {dt_str}{loc_str}")
    return "\n\n".join(lines)
