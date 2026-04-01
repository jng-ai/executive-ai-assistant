# tests/test_events_scanner.py
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


SAMPLE_EXTRACTED = [
    {
        "name": "Brooklyn 5K Run",
        "date": "2026-04-05T10:00:00",
        "end_time": "2026-04-05T12:00:00",
        "venue": "Prospect Park",
        "address": "110 Eastern Pkwy, Brooklyn, NY",
        "neighborhood": "Brooklyn",
        "category": "Fitness & Outdoors",
        "price": 0,
        "source": "Luma",
        "rsvp_link": "https://lu.ma/bk5k",
    }
]


class TestExtractEventsFromResults:
    def test_extract_returns_list_of_dicts(self):
        with patch("agents.social_agent.handler.chat", return_value=json.dumps(SAMPLE_EXTRACTED)):
            from agents.social_agent.handler import _extract_events_from_results
            results = _extract_events_from_results("some search text", "Fitness & Outdoors")
        assert isinstance(results, list)
        assert results[0]["name"] == "Brooklyn 5K Run"

    def test_extract_filters_over_80(self):
        expensive = [{**SAMPLE_EXTRACTED[0], "price": 100, "rsvp_link": "https://lu.ma/exp"}]
        with patch("agents.social_agent.handler.chat", return_value=json.dumps(expensive)):
            from agents.social_agent.handler import _extract_events_from_results
            results = _extract_events_from_results("text", "Fitness & Outdoors")
        assert results == []

    def test_extract_handles_invalid_json_gracefully(self):
        with patch("agents.social_agent.handler.chat", return_value="not json at all"):
            from agents.social_agent.handler import _extract_events_from_results
            results = _extract_events_from_results("text", "Fitness & Outdoors")
        assert results == []

    def test_extract_requires_rsvp_link(self):
        no_link = [{**SAMPLE_EXTRACTED[0], "rsvp_link": ""}]
        with patch("agents.social_agent.handler.chat", return_value=json.dumps(no_link)):
            from agents.social_agent.handler import _extract_events_from_results
            results = _extract_events_from_results("text", "Fitness & Outdoors")
        assert results == []


class TestHandleIntake:
    def test_intake_url_extracts_and_pushes(self):
        extracted = SAMPLE_EXTRACTED[0]
        with patch("agents.social_agent.handler.fetch_page", return_value="event page html"):
            with patch("agents.social_agent.handler.chat", return_value=json.dumps(extracted)):
                with patch("agents.social_agent.handler.push_event", return_value="page-id-123") as mock_push:
                    from agents.social_agent.handler import handle_intake
                    result = handle_intake("https://lu.ma/bk5k")
        mock_push.assert_called_once()
        assert "Brooklyn 5K Run" in result

    def test_intake_duplicate_returns_already_tracked(self):
        with patch("agents.social_agent.handler.fetch_page", return_value="html"):
            with patch("agents.social_agent.handler.chat", return_value=json.dumps(SAMPLE_EXTRACTED[0])):
                with patch("agents.social_agent.handler.push_event", return_value=None):
                    with patch("agents.social_agent.handler.get_event_by_rsvp_link", return_value={"name": "Brooklyn 5K Run", "date": "2026-04-05T10:00:00"}):
                        from agents.social_agent.handler import handle_intake
                        result = handle_intake("https://lu.ma/bk5k")
        assert "already" in result.lower()

    def test_intake_fetch_failure_returns_error(self):
        with patch("agents.social_agent.handler.fetch_page", side_effect=Exception("timeout")):
            from agents.social_agent.handler import handle_intake
            result = handle_intake("https://lu.ma/bk5k")
        assert "couldn't" in result.lower() or "error" in result.lower()


class TestRunThemeSearch:
    def test_theme_search_returns_list(self):
        with patch("agents.social_agent.handler.search", return_value=[{"url": "x", "content": "event"}]):
            with patch("agents.social_agent.handler.chat", return_value=json.dumps(SAMPLE_EXTRACTED)):
                from agents.social_agent.handler import run_theme_search
                results = run_theme_search("salsa dancing")
        assert isinstance(results, list)

    def test_theme_search_empty_query_returns_empty(self):
        from agents.social_agent.handler import run_theme_search
        results = run_theme_search("")
        assert results == []
