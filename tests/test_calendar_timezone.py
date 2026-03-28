"""
Tests for calendar timezone correctness (EDT vs EST).

These tests verify that:
1. _et_day_window() builds correct ET-aware timestamps (not hardcoded -05:00)
2. get_todays_events() query window covers midnight-to-midnight ET
3. check_conflicts() uses dynamic ET offset
4. format_events() displays times in correct ET timezone

Requires: integrations/google/calendar_client.py with ZoneInfo-based helpers.
"""

import datetime
import pytest
from unittest.mock import MagicMock, patch
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")


# ── _et_day_window() ──────────────────────────────────────────────────────────

class TestEtDayWindow:
    """_et_day_window() must return isoformat strings with the correct ET offset."""

    def test_edt_date_uses_minus_four(self):
        """A date during EDT (summer) should have -04:00 offset in the output."""
        from integrations.google.calendar_client import _et_day_window
        edt_date = datetime.date(2026, 7, 15)  # July → EDT
        start, end = _et_day_window(edt_date)
        assert "-04:00" in start, f"Expected -04:00 in EDT start, got: {start}"
        assert "-04:00" in end,   f"Expected -04:00 in EDT end, got: {end}"

    def test_est_date_uses_minus_five(self):
        """A date during EST (winter) should have -05:00 offset in the output."""
        from integrations.google.calendar_client import _et_day_window
        est_date = datetime.date(2026, 1, 15)  # January → EST
        start, end = _et_day_window(est_date)
        assert "-05:00" in start, f"Expected -05:00 in EST start, got: {start}"
        assert "-05:00" in end,   f"Expected -05:00 in EST end, got: {end}"

    def test_window_spans_full_day(self):
        """Start must be midnight and end must be 23:59:59 in ET."""
        from integrations.google.calendar_client import _et_day_window
        date = datetime.date(2026, 6, 21)
        start, end = _et_day_window(date)
        # Parse back and verify
        start_dt = datetime.datetime.fromisoformat(start)
        end_dt   = datetime.datetime.fromisoformat(end)
        assert start_dt.hour == 0 and start_dt.minute == 0 and start_dt.second == 0
        assert end_dt.hour == 23 and end_dt.minute == 59 and end_dt.second == 59

    def test_window_date_matches_requested_date(self):
        """The date in the returned isoformat strings must match the input date."""
        from integrations.google.calendar_client import _et_day_window
        date = datetime.date(2026, 8, 10)
        start, end = _et_day_window(date)
        start_dt = datetime.datetime.fromisoformat(start)
        end_dt   = datetime.datetime.fromisoformat(end)
        assert start_dt.date() == date
        assert end_dt.date() == date

    def test_no_hardcoded_minus_five_during_edt(self):
        """Regression: old code always used -05:00. Verify EDT dates don't use it."""
        from integrations.google.calendar_client import _et_day_window
        # March 24, 2026 = EDT (DST started March 8, 2026)
        mar24 = datetime.date(2026, 3, 24)
        start, _ = _et_day_window(mar24)
        assert "-05:00" not in start, (
            "Regression: -05:00 (EST) used during EDT season — "
            "use ZoneInfo('America/New_York') instead of hardcoded offset"
        )


# ── _et_now() ─────────────────────────────────────────────────────────────────

class TestEtNow:
    def test_returns_et_aware_datetime(self):
        from integrations.google.calendar_client import _et_now
        now = _et_now()
        assert now.tzinfo is not None
        # Offset should be -4h (EDT) or -5h (EST)
        offset_hours = now.utcoffset().total_seconds() / 3600
        assert offset_hours in (-4.0, -5.0), f"Unexpected ET offset: {offset_hours}"


# ── get_todays_events() timezone window ────────────────────────────────────────

class TestGetTodaysEventsTimezone:
    """Verify get_todays_events() passes a DST-correct window to the Google API."""

    def _make_mock_service(self):
        svc = MagicMock()
        svc.calendarList().list().execute.return_value = {
            "items": [{"id": "primary"}]
        }
        svc.events().list().execute.return_value = {"items": []}
        return svc

    @patch("integrations.google.calendar_client.is_configured", return_value=True)
    @patch("integrations.google.calendar_client._service")
    def test_edt_window_uses_minus_four(self, mock_svc, mock_cfg):
        """During EDT, the Google API call must receive -04:00 timestamps."""
        from integrations.google.calendar_client import get_todays_events

        svc = self._make_mock_service()
        mock_svc.return_value = svc

        # Pin today to an EDT date
        with patch("integrations.google.calendar_client._et_now") as mock_now:
            edt_dt = datetime.datetime(2026, 7, 1, 10, 0, tzinfo=ET)
            mock_now.return_value = edt_dt

            get_todays_events()

        # Check the timeMin kwarg passed to events().list()
        call_kwargs = svc.events().list.call_args_list[-1][1]
        time_min = call_kwargs.get("timeMin", "")
        assert "-04:00" in time_min, f"Expected -04:00 in timeMin, got: {time_min}"

    @patch("integrations.google.calendar_client.is_configured", return_value=True)
    @patch("integrations.google.calendar_client._service")
    def test_est_window_uses_minus_five(self, mock_svc, mock_cfg):
        """During EST, the Google API call must receive -05:00 timestamps."""
        from integrations.google.calendar_client import get_todays_events

        svc = self._make_mock_service()
        mock_svc.return_value = svc

        with patch("integrations.google.calendar_client._et_now") as mock_now:
            est_dt = datetime.datetime(2026, 1, 10, 10, 0, tzinfo=ET)
            mock_now.return_value = est_dt

            get_todays_events()

        call_kwargs = svc.events().list.call_args_list[-1][1]
        time_min = call_kwargs.get("timeMin", "")
        assert "-05:00" in time_min, f"Expected -05:00 in timeMin, got: {time_min}"

    @patch("integrations.google.calendar_client.is_configured", return_value=False)
    def test_not_configured_returns_empty(self, _):
        from integrations.google.calendar_client import get_todays_events
        assert get_todays_events() == []


# ── check_conflicts() timezone ────────────────────────────────────────────────

class TestCheckConflictsTimezone:
    """check_conflicts() must build slot times using dynamic ET offset."""

    def _make_mock_service(self):
        svc = MagicMock()
        svc.calendarList().list().execute.return_value = {"items": [{"id": "primary"}]}
        svc.events().list().execute.return_value = {"items": []}
        return svc

    @patch("integrations.google.calendar_client._service")
    def test_edt_slot_uses_minus_four(self, mock_svc):
        from integrations.google.calendar_client import check_conflicts
        svc = self._make_mock_service()
        mock_svc.return_value = svc

        check_conflicts("2026-07-15", "10:00", 60)

        call_kwargs = svc.events().list.call_args_list[-1][1]
        time_min = call_kwargs.get("timeMin", "")
        assert "-04:00" in time_min, f"Expected EDT offset in slot start, got: {time_min}"

    @patch("integrations.google.calendar_client._service")
    def test_est_slot_uses_minus_five(self, mock_svc):
        from integrations.google.calendar_client import check_conflicts
        svc = self._make_mock_service()
        mock_svc.return_value = svc

        check_conflicts("2026-01-15", "10:00", 60)

        call_kwargs = svc.events().list.call_args_list[-1][1]
        time_min = call_kwargs.get("timeMin", "")
        assert "-05:00" in time_min, f"Expected EST offset in slot start, got: {time_min}"

    @patch("integrations.google.calendar_client._service")
    def test_slot_end_respects_duration(self, mock_svc):
        """60-min meeting at 10:00 should end at 11:00."""
        from integrations.google.calendar_client import check_conflicts
        svc = self._make_mock_service()
        mock_svc.return_value = svc

        check_conflicts("2026-07-15", "10:00", 60)

        call_kwargs = svc.events().list.call_args_list[-1][1]
        time_max = call_kwargs.get("timeMax", "")
        end_dt = datetime.datetime.fromisoformat(time_max)
        assert end_dt.hour == 11 and end_dt.minute == 0


# ── format_events() ────────────────────────────────────────────────────────────

class TestFormatEventsTimezone:
    """format_events() must display event times in correct ET (not hardcoded EDT)."""

    def test_event_displays_in_et(self):
        """A UTC event should display in the correct local ET time."""
        from integrations.google.calendar_client import format_events
        # 14:00 UTC on a winter day = 9:00 AM EST
        events = [{
            "summary": "Morning Meeting",
            "start": {"dateTime": "2026-01-15T14:00:00Z"},
            "location": "",
        }]
        result = format_events(events)
        # Should show 9:00am or 9am EST, NOT 10:00am
        assert "9:" in result or "9am" in result.lower(), (
            f"Expected 9am EST display for 14:00 UTC in January, got: {result}"
        )

    def test_all_day_event_shows_date_not_time(self):
        """All-day events (date, not dateTime) should display without a time."""
        from integrations.google.calendar_client import format_events
        events = [{
            "summary": "Conference Day",
            "start": {"date": "2026-07-15"},
            "location": "",
        }]
        result = format_events(events)
        assert "Conference Day" in result
