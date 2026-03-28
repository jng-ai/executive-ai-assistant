"""
Google Calendar client — create, list, and update calendar events.
"""

import datetime
import logging
from zoneinfo import ZoneInfo
from googleapiclient.discovery import build
from integrations.google.auth import get_credentials, is_configured

logger = logging.getLogger(__name__)

_ET = ZoneInfo("America/New_York")


def _et_now() -> datetime.datetime:
    """Current time in ET (handles EDT/EST automatically)."""
    return datetime.datetime.now(tz=_ET)


def _et_day_window(date: datetime.date) -> tuple[str, str]:
    """Return (start_iso, end_iso) for a full ET calendar day — correct for EDT or EST."""
    start = datetime.datetime(date.year, date.month, date.day, 0, 0, 0, tzinfo=_ET)
    end   = datetime.datetime(date.year, date.month, date.day, 23, 59, 59, tzinfo=_ET)
    return start.isoformat(), end.isoformat()


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
        logger.error("Calendar list error: %s", e)
        return []


def create_event(title: str, start: str, end: str = None,
                 description: str = "", location: str = "",
                 attendees: list[str] | None = None) -> dict | None:
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
        if attendees:
            event["attendees"] = [{"email": a} for a in attendees]
        created = svc.events().insert(
            calendarId="jynpriority@gmail.com",
            body=event,
            sendUpdates="all",
        ).execute()
        return created
    except Exception as e:
        logger.error("Calendar create error: %s", e)
        return None


def find_free_slots(date: str, duration_minutes: int = 60) -> list[str]:
    """Find free time slots on a given date (YYYY-MM-DD), checking ALL calendars."""
    if not is_configured():
        return []
    try:
        svc = _service()
        # Use ET offset — convert date to UTC range covering full ET day
        day_start = f"{date}T04:00:00Z"   # midnight ET = 4AM UTC (or 5AM during EST)
        day_end   = f"{date}T23:59:59Z"
        busy = []
        for cal_id in _get_calendar_ids():
            try:
                result = svc.events().list(
                    calendarId=cal_id,
                    timeMin=day_start,
                    timeMax=day_end,
                    singleEvents=True,
                    orderBy="startTime",
                ).execute()
                for ev in result.get("items", []):
                    s = ev.get("start", {})
                    e = ev.get("end", {})
                    if "dateTime" in s:
                        busy.append((s["dateTime"][:16], e["dateTime"][:16]))
            except Exception:
                continue

        # Candidate slots: 9am–7pm ET
        candidate_hours = [9, 10, 11, 13, 14, 15, 16, 17, 18, 19]
        free = []
        for h in candidate_hours:
            slot_start = f"{date}T{h:02d}:00"
            end_h = h + duration_minutes // 60
            end_m = duration_minutes % 60
            slot_end = f"{date}T{end_h:02d}:{end_m:02d}"
            clash = any(s <= slot_start < e or s < slot_end <= e for s, e in busy)
            if not clash:
                free.append(f"{h % 12 or 12}{'am' if h < 12 else 'pm'}")
        return free[:5]
    except Exception as e:
        logger.error("Free slot error: %s", e)
        return []


def get_todays_events() -> list[dict]:
    """Return only today's events (midnight to midnight ET, DST-aware)."""
    if not is_configured():
        return []
    try:
        today = _et_now().date()
        svc = _service()
        day_start, day_end = _et_day_window(today)
        all_events = []
        for cal_id in _get_calendar_ids():
            try:
                result = svc.events().list(
                    calendarId=cal_id,
                    timeMin=day_start,
                    timeMax=day_end,
                    singleEvents=True,
                    orderBy="startTime",
                ).execute()
                all_events.extend(result.get("items", []))
            except Exception:
                continue
        all_events.sort(key=lambda ev: ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", "")))
        return all_events
    except Exception as e:
        logger.error("Today events error: %s", e)
        return []


def get_events_for_date(date: datetime.date) -> list[dict]:
    """Return events for any specific date (midnight to midnight ET, DST-aware)."""
    if not is_configured():
        return []
    try:
        svc = _service()
        day_start, day_end = _et_day_window(date)
        all_events = []
        for cal_id in _get_calendar_ids():
            try:
                result = svc.events().list(
                    calendarId=cal_id,
                    timeMin=day_start,
                    timeMax=day_end,
                    singleEvents=True,
                    orderBy="startTime",
                ).execute()
                all_events.extend(result.get("items", []))
            except Exception:
                continue
        all_events.sort(key=lambda ev: ev.get("start", {}).get("dateTime", ev.get("start", {}).get("date", "")))
        return all_events
    except Exception as e:
        logger.error("get_events_for_date error: %s", e)
        return []


def delete_event(keyword: str) -> str:
    """Delete the first upcoming event whose title contains keyword. Returns result message."""
    if not is_configured():
        return "Google Calendar not connected."
    try:
        events = list_events(days_ahead=30)
        matches = [ev for ev in events if keyword.lower() in ev.get("summary", "").lower()]
        if not matches:
            return f"No upcoming events matching '{keyword}' found."
        ev = matches[0]
        title = ev.get("summary", "Untitled")
        # Determine which calendar owns this event
        cal_id = ev.get("organizer", {}).get("email", "primary")
        svc = _service()
        # Try deletion across all calendars
        deleted = False
        for cid in _get_calendar_ids():
            try:
                svc.events().delete(calendarId=cid, eventId=ev["id"]).execute()
                deleted = True
                break
            except Exception:
                continue
        if deleted:
            return f"🗑 Deleted: *{title}*"
        return f"⚠️ Couldn't delete '{title}' — may not have edit access."
    except Exception as e:
        logger.error("Delete event error: %s", e)
        return "⚠️ Error deleting event."


def check_conflicts(date: str, time: str, duration_minutes: int = 60) -> list[str]:
    """Return titles of events that overlap a proposed time slot (DST-aware)."""
    try:
        svc = _service()
        h, m = int(time[:2]), int(time[3:5])
        date_obj  = datetime.date.fromisoformat(date)
        slot_dt   = datetime.datetime(date_obj.year, date_obj.month, date_obj.day, h, m, 0, tzinfo=_ET)
        slot_end_dt = slot_dt + datetime.timedelta(minutes=duration_minutes)
        slot_start = slot_dt.isoformat()
        slot_end   = slot_end_dt.isoformat()
        conflicts = []
        for cal_id in _get_calendar_ids():
            try:
                result = svc.events().list(
                    calendarId=cal_id,
                    timeMin=slot_start,
                    timeMax=slot_end,
                    singleEvents=True,
                ).execute()
                for ev in result.get("items", []):
                    title = ev.get("summary", "Untitled")
                    if title not in conflicts:
                        conflicts.append(title)
            except Exception:
                continue
        return conflicts
    except Exception as e:
        logger.error("Conflict check error: %s", e)
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
                d = d.astimezone(_ET)  # Always correct: handles EDT and EST automatically
                dt_str = d.strftime("%a %b %-d, %-I:%M%p").lower().replace("am","am").replace("pm","pm")
            except Exception:
                dt_str = dt[:16]
        else:
            dt_str = dt
        location = ev.get("location", "")
        loc_str = f" @ {location}" if location else ""
        lines.append(f"📅 *{title}*\n   {dt_str}{loc_str}")
    return "\n\n".join(lines)
