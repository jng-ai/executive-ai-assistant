# tests/test_events_api.py
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from integrations.web.server import app
    return TestClient(app)


SAMPLE_EVENTS = [
    {
        "notion_id": "page-1",
        "name": "Brooklyn 5K Run",
        "date": "2026-04-05T10:00:00",
        "end_time": "2026-04-05T12:00:00",
        "venue": "Prospect Park",
        "address": "110 Eastern Pkwy, Brooklyn",
        "neighborhood": "Brooklyn",
        "category": "Fitness & Outdoors",
        "price": 0,
        "source": "Luma",
        "rsvp_link": "https://lu.ma/bk5k",
        "status": "New",
        "registered": False,
        "friends_going": "",
        "cal_event_id": "",
        "notes": "",
    }
]

SAMPLE_PROGRESS = {
    "total_attended": 3,
    "goal": 20,
    "by_category": {"Fitness & Outdoors": 2, "Food & Drinks": 1},
    "heatmap": {"2026-03-10": "Fitness & Outdoors"},
    "categories_tried": ["Fitness & Outdoors", "Food & Drinks"],
    "categories_not_tried": ["Dating & Meetups"],
    "all_categories": ["Fitness & Outdoors", "Dating & Meetups", "Food & Drinks"],
}


class TestGetEvents:
    def test_returns_200_with_events_list(self, client):
        with patch("integrations.web.server.get_events", return_value=SAMPLE_EVENTS):
            resp = client.get("/api/events")
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data
        assert data["events"][0]["name"] == "Brooklyn 5K Run"

    def test_category_filter_passed_through(self, client):
        with patch("integrations.web.server.get_events", return_value=[]) as mock:
            client.get("/api/events?category=Fitness+%26+Outdoors")
        mock.assert_called_once_with(category_filter="Fitness & Outdoors", upcoming_only=True)

    def test_status_filter_passed_through(self, client):
        with patch("integrations.web.server.get_events", return_value=[]) as mock:
            client.get("/api/events?status=Going")
        mock.assert_called_once_with(status_filter="Going", upcoming_only=True)


class TestGetProgress:
    def test_returns_progress_data(self, client):
        with patch("integrations.web.server.get_progress", return_value=SAMPLE_PROGRESS):
            resp = client.get("/api/events/progress")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_attended"] == 3
        assert data["goal"] == 20


class TestEventIntakeEndpoint:
    def test_valid_url_returns_success(self, client):
        with patch("integrations.web.server.handle_intake", return_value="✅ Added: Brooklyn 5K Run"):
            resp = client.post("/api/events/intake", json={"url": "https://lu.ma/bk5k"})
        assert resp.status_code == 200
        assert "Brooklyn" in resp.json()["message"]

    def test_missing_url_returns_422(self, client):
        resp = client.post("/api/events/intake", json={})
        assert resp.status_code == 422

    def test_non_url_returns_400(self, client):
        resp = client.post("/api/events/intake", json={"url": "not a url"})
        assert resp.status_code == 400


class TestThemeSearch:
    def test_valid_theme_returns_results(self, client):
        with patch("integrations.web.server.run_theme_search", return_value=[SAMPLE_EVENTS[0]]):
            resp = client.post("/api/events/theme-search", json={"theme": "salsa dancing"})
        assert resp.status_code == 200
        assert "results" in resp.json()

    def test_empty_theme_returns_400(self, client):
        resp = client.post("/api/events/theme-search", json={"theme": ""})
        assert resp.status_code == 400


class TestEventsRsvpEndpoint:
    def test_event_not_found_returns_404(self, client):
        with patch("integrations.web.server.get_events", return_value=[]):
            resp = client.post("/api/events/rsvp/nonexistent-id")
        assert resp.status_code == 404

    def test_valid_event_triggers_registration(self, client):
        from agents.social_agent.handler import _register_for_event
        with patch("integrations.web.server.get_events", return_value=SAMPLE_EVENTS):
            with patch("agents.social_agent.handler._register_for_event", return_value="✅ Registered!"):
                resp = client.post("/api/events/rsvp/page-1")
        assert resp.status_code == 200
        assert resp.json()["ok"] is True


class TestFriendRsvpEndpoint:
    def test_valid_rsvp_returns_success(self, client):
        with patch("integrations.web.server.add_friend_rsvp", return_value=True):
            resp = client.post("/api/events/friend-rsvp/page-1", json={"name": "Mike"})
        assert resp.status_code == 200

    def test_invalid_name_returns_400(self, client):
        with patch("integrations.web.server.add_friend_rsvp", return_value=False):
            resp = client.post("/api/events/friend-rsvp/page-1", json={"name": "http://spam.com"})
        assert resp.status_code == 400
