"""
Tests for calendar agent 'tomorrow' and specific-date query routing.

These tests verify that:
1. "do I have plans tomorrow?" routes to the 'tomorrow' action (not 'today')
2. "what's on Thursday?" routes to the 'date' action with the correct date
3. The 'tomorrow' and 'date' action handlers call get_events_for_date() correctly
4. Empty results return user-friendly messages (not silent blanks)

Requires: agents/calendar_agent/handler.py with 'tomorrow' + 'date' actions.
"""

import datetime
import pytest
from unittest.mock import patch, MagicMock


# ── Routing: 'tomorrow' action ─────────────────────────────────────────────────

class TestTomorrowRouting:
    """
    When user asks about tomorrow, the calendar agent must:
    1. Call get_events_for_date(tomorrow) — NOT get_todays_events()
    2. Return a message scoped to tomorrow's date
    """

    def _stub_parse(self, action):
        """Return a parse stub for a given action."""
        return {"action": action}

    @patch("agents.calendar_agent.handler._parse_request")
    @patch("agents.calendar_agent.handler.is_configured", return_value=True)
    def test_tomorrow_action_calls_get_events_for_date(self, mock_cfg, mock_parse):
        """'tomorrow' action must call get_events_for_date with tomorrow's date."""
        mock_parse.return_value = {"action": "tomorrow"}
        import agents.calendar_agent.handler as h

        with patch("agents.calendar_agent.handler.get_events_for_date", return_value=[]) as mock_gef, \
             patch("agents.calendar_agent.handler.get_todays_events") as mock_gte:
            h.handle("do I have plans tomorrow?")

        mock_gef.assert_called_once()
        date_arg = mock_gef.call_args[0][0]
        expected = datetime.date.today() + datetime.timedelta(days=1)
        assert date_arg == expected, f"Expected tomorrow ({expected}), got {date_arg}"
        mock_gte.assert_not_called()

    @patch("agents.calendar_agent.handler._parse_request")
    @patch("agents.calendar_agent.handler.is_configured", return_value=True)
    def test_tomorrow_action_does_not_call_get_todays_events(self, mock_cfg, mock_parse):
        """'tomorrow' action must NOT fall through to the 'today' code path."""
        mock_parse.return_value = {"action": "tomorrow"}
        import agents.calendar_agent.handler as h

        with patch("agents.calendar_agent.handler.get_events_for_date", return_value=[]), \
             patch("agents.calendar_agent.handler.get_todays_events") as mock_gte:
            h.handle("am I busy tomorrow?")

        mock_gte.assert_not_called()

    @patch("agents.calendar_agent.handler._parse_request")
    @patch("agents.calendar_agent.handler.is_configured", return_value=True)
    def test_tomorrow_empty_returns_free_message(self, mock_cfg, mock_parse):
        """Empty tomorrow → 'free day' message, not silent blank."""
        mock_parse.return_value = {"action": "tomorrow"}
        import agents.calendar_agent.handler as h

        with patch("agents.calendar_agent.handler.get_events_for_date", return_value=[]):
            result = h.handle("do I have plans tomorrow?")

        # Should mention tomorrow and no events
        assert any(w in result.lower() for w in ["tomorrow", "free", "nothing", "clear"]), (
            f"Expected a 'free tomorrow' message, got: {result}"
        )

    @patch("agents.calendar_agent.handler._parse_request")
    @patch("agents.calendar_agent.handler.is_configured", return_value=True)
    def test_tomorrow_with_events_shows_them(self, mock_cfg, mock_parse):
        """When tomorrow has events, they should appear in the response."""
        mock_parse.return_value = {"action": "tomorrow"}
        import agents.calendar_agent.handler as h

        events = [{"summary": "Team Standup", "start": {"dateTime": "2026-03-25T09:00:00-04:00"}}]

        with patch("agents.calendar_agent.handler.get_events_for_date", return_value=events), \
             patch("agents.calendar_agent.handler.format_events", return_value="📅 *Team Standup*\n   9:00am"):
            result = h.handle("do I have plans tomorrow?")

        assert "Team Standup" in result or "Standup" in result, (
            f"Expected event name in response, got: {result}"
        )


# ── Routing: 'date' action ─────────────────────────────────────────────────────

class TestSpecificDateRouting:
    """
    When user asks about a specific date (Thursday, next Monday, etc.),
    the agent must call get_events_for_date() with the resolved date.
    """

    @patch("agents.calendar_agent.handler._parse_request")
    @patch("agents.calendar_agent.handler.is_configured", return_value=True)
    def test_date_action_calls_get_events_for_date(self, mock_cfg, mock_parse):
        """'date' action must call get_events_for_date with the parsed date."""
        target = "2026-03-27"  # Friday
        mock_parse.return_value = {"action": "date", "date": target}
        import agents.calendar_agent.handler as h

        with patch("agents.calendar_agent.handler.get_events_for_date", return_value=[]) as mock_gef:
            h.handle("what's on Friday?")

        mock_gef.assert_called_once()
        date_arg = mock_gef.call_args[0][0]
        assert str(date_arg) == target

    @patch("agents.calendar_agent.handler._parse_request")
    @patch("agents.calendar_agent.handler.is_configured", return_value=True)
    def test_date_action_empty_returns_clear_message(self, mock_cfg, mock_parse):
        """Empty date → 'clear schedule' message, not silent blank."""
        mock_parse.return_value = {"action": "date", "date": "2026-03-27"}
        import agents.calendar_agent.handler as h

        with patch("agents.calendar_agent.handler.get_events_for_date", return_value=[]):
            result = h.handle("any events Friday?")

        assert any(w in result.lower() for w in ["nothing", "clear", "free", "friday"]), (
            f"Expected a 'free day' message, got: {result}"
        )

    @patch("agents.calendar_agent.handler._parse_request")
    @patch("agents.calendar_agent.handler.is_configured", return_value=True)
    def test_date_action_invalid_date_falls_back(self, mock_cfg, mock_parse):
        """Malformed date string should not crash — fall back to tomorrow."""
        mock_parse.return_value = {"action": "date", "date": "not-a-date"}
        import agents.calendar_agent.handler as h

        with patch("agents.calendar_agent.handler.get_events_for_date", return_value=[]):
            result = h.handle("anything on blurnsday?")
        # Should not raise; should return a string
        assert isinstance(result, str)

    @patch("agents.calendar_agent.handler._parse_request")
    @patch("agents.calendar_agent.handler.is_configured", return_value=True)
    def test_date_action_missing_date_key_falls_back(self, mock_cfg, mock_parse):
        """Missing 'date' key in parsed result should not crash."""
        mock_parse.return_value = {"action": "date"}  # no date key
        import agents.calendar_agent.handler as h

        with patch("agents.calendar_agent.handler.get_events_for_date", return_value=[]):
            result = h.handle("any events?")
        assert isinstance(result, str)


# ── Regression: 'today' action must NOT handle tomorrow queries ────────────────

class TestTodayActionRegression:
    """Verify the old regression doesn't sneak back in."""

    @patch("agents.calendar_agent.handler._parse_request")
    @patch("agents.calendar_agent.handler.is_configured", return_value=True)
    def test_today_action_calls_get_todays_events_not_tomorrow(self, mock_cfg, mock_parse):
        """'today' action must call get_todays_events() — never get_events_for_date()."""
        mock_parse.return_value = {"action": "today"}
        import agents.calendar_agent.handler as h

        with patch("agents.calendar_agent.handler.get_todays_events", return_value=[]) as mock_gte, \
             patch("agents.calendar_agent.handler.get_events_for_date") as mock_gef:
            h.handle("what's on today?")

        mock_gte.assert_called_once()
        mock_gef.assert_not_called()


# ── get_events_for_date() window ──────────────────────────────────────────────

class TestGetEventsForDate:
    """get_events_for_date() must query the full ET day window for the given date."""

    def _make_mock_service(self):
        svc = MagicMock()
        svc.calendarList().list().execute.return_value = {"items": [{"id": "primary"}]}
        svc.events().list().execute.return_value = {"items": []}
        return svc

    @patch("integrations.google.calendar_client.is_configured", return_value=True)
    @patch("integrations.google.calendar_client._service")
    def test_queries_requested_date(self, mock_svc, mock_cfg):
        """The Google API call must use the requested date, not today."""
        from integrations.google.calendar_client import get_events_for_date
        svc = self._make_mock_service()
        mock_svc.return_value = svc

        target = datetime.date(2026, 6, 15)
        get_events_for_date(target)

        call_kwargs = svc.events().list.call_args_list[-1][1]
        time_min = call_kwargs.get("timeMin", "")
        assert "2026-06-15" in time_min, f"Expected date 2026-06-15 in timeMin, got: {time_min}"

    @patch("integrations.google.calendar_client.is_configured", return_value=True)
    @patch("integrations.google.calendar_client._service")
    def test_tomorrow_date_queries_tomorrow(self, mock_svc, mock_cfg):
        """Querying tomorrow returns tomorrow's date in the API call."""
        from integrations.google.calendar_client import get_events_for_date
        svc = self._make_mock_service()
        mock_svc.return_value = svc

        tomorrow = datetime.date.today() + datetime.timedelta(days=1)
        get_events_for_date(tomorrow)

        call_kwargs = svc.events().list.call_args_list[-1][1]
        time_min = call_kwargs.get("timeMin", "")
        assert str(tomorrow) in time_min

    @patch("integrations.google.calendar_client.is_configured", return_value=False)
    def test_not_configured_returns_empty(self, _):
        from integrations.google.calendar_client import get_events_for_date
        assert get_events_for_date(datetime.date.today()) == []
