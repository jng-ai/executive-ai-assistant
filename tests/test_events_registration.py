# tests/test_events_registration.py
import pytest
from unittest.mock import patch, MagicMock


SAMPLE_EVENT = {
    "notion_id": "page-abc",
    "name": "Brooklyn 5K Run",
    "date": "2026-04-05T10:00:00",
    "end_time": "2026-04-05T12:00:00",
    "address": "110 Eastern Pkwy, Brooklyn",
    "rsvp_link": "https://lu.ma/bk5k",
    "category": "Fitness & Outdoors",
    "price": 0,
}


class TestRegisterForEvent:
    def test_register_success_updates_notion_status(self):
        mock_page = MagicMock()
        mock_page.content.return_value = "<html><input name='email'/></html>"
        mock_page.goto = MagicMock()
        mock_page.fill = MagicMock()
        mock_page.click = MagicMock()
        mock_browser = MagicMock()
        mock_browser.new_page.return_value = mock_page
        mock_playwright = MagicMock()
        mock_playwright.__enter__ = MagicMock(return_value=mock_playwright)
        mock_playwright.__exit__ = MagicMock(return_value=False)
        mock_playwright.chromium.launch.return_value = mock_browser

        with patch("agents.social_agent.handler.sync_playwright", return_value=mock_playwright):
            with patch("agents.social_agent.handler.update_event_status") as mock_update:
                with patch("agents.social_agent.handler._check_calendar_conflict", return_value=None):
                    from agents.social_agent.handler import _register_for_event
                    result = _register_for_event(SAMPLE_EVENT)
        assert "success" in result.lower() or "registered" in result.lower() or "going" in result.lower()
        mock_update.assert_called_once()
        # Verify it was called with "Going" and registered=True
        call_args = mock_update.call_args
        assert call_args[0][1] == "Going"
        assert call_args[1].get("registered") is True

    def test_register_captcha_detected_returns_link(self):
        mock_page = MagicMock()
        mock_page.content.return_value = "<html>recaptcha hcaptcha</html>"
        mock_page.goto = MagicMock()
        mock_browser = MagicMock()
        mock_browser.new_page.return_value = mock_page
        mock_playwright = MagicMock()
        mock_playwright.__enter__ = MagicMock(return_value=mock_playwright)
        mock_playwright.__exit__ = MagicMock(return_value=False)
        mock_playwright.chromium.launch.return_value = mock_browser

        with patch("agents.social_agent.handler.sync_playwright", return_value=mock_playwright):
            with patch("agents.social_agent.handler._check_calendar_conflict", return_value=None):
                from agents.social_agent.handler import _register_for_event
                result = _register_for_event(SAMPLE_EVENT)
        assert "captcha" in result.lower() or "manually" in result.lower() or "link" in result.lower()

    def test_register_no_fields_found_returns_manual_link(self):
        mock_page = MagicMock()
        # Page has no CAPTCHA but no fillable inputs (locator.count() returns 0)
        mock_page.content.return_value = "<html><p>Register here</p></html>"
        mock_page.goto = MagicMock()
        mock_locator = MagicMock()
        mock_locator.count.return_value = 0
        mock_page.locator.return_value = mock_locator
        mock_browser = MagicMock()
        mock_browser.new_page.return_value = mock_page
        mock_playwright = MagicMock()
        mock_playwright.__enter__ = MagicMock(return_value=mock_playwright)
        mock_playwright.__exit__ = MagicMock(return_value=False)
        mock_playwright.chromium.launch.return_value = mock_browser

        with patch("agents.social_agent.handler.sync_playwright", return_value=mock_playwright):
            with patch("agents.social_agent.handler.update_event_status") as mock_update:
                with patch("agents.social_agent.handler._check_calendar_conflict", return_value=None):
                    from agents.social_agent.handler import _register_for_event
                    result = _register_for_event(SAMPLE_EVENT)
        assert "manually" in result.lower() or "couldn't find" in result.lower()
        mock_update.assert_called_once()

    def test_register_calendar_conflict_noted_in_result(self):
        with patch("agents.social_agent.handler._check_calendar_conflict", return_value="Work meeting"):
            from agents.social_agent.handler import _register_for_event
            result = _register_for_event(SAMPLE_EVENT, skip_playwright=True)
        assert "conflict" in result.lower() or "work meeting" in result.lower() or "calendar" in result.lower()


class TestCheckCalendarConflict:
    def test_no_conflict_returns_none(self):
        with patch("agents.social_agent.handler.list_events", return_value=[]):
            from agents.social_agent.handler import _check_calendar_conflict
            result = _check_calendar_conflict("2026-04-05T10:00:00", "2026-04-05T12:00:00")
        assert result is None

    def test_conflict_returns_event_name(self):
        mock_cal_event = {
            "summary": "Work meeting",
            "start": {"dateTime": "2026-04-05T10:30:00"},
            "end":   {"dateTime": "2026-04-05T11:30:00"},
        }
        with patch("agents.social_agent.handler.list_events", return_value=[mock_cal_event]):
            from agents.social_agent.handler import _check_calendar_conflict
            result = _check_calendar_conflict("2026-04-05T10:00:00", "2026-04-05T12:00:00")
        assert result == "Work meeting"
