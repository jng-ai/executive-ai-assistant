# tests/test_events_notion.py
import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


@pytest.fixture
def mock_notion_env(monkeypatch):
    monkeypatch.setenv("NOTION_API_KEY", "test-key")
    monkeypatch.setenv("NOTION_PARENT_PAGE_ID", "test-parent-id")
    monkeypatch.setenv("NOTION_EVENTS_DB_ID", "test-events-db-id")


@pytest.fixture
def sample_event():
    return {
        "name": "Brooklyn 5K Run",
        "date": "2026-04-05T10:00:00",
        "end_time": "2026-04-05T12:00:00",
        "venue": "Prospect Park",
        "address": "110 Eastern Pkwy, Brooklyn, NY 11238",
        "neighborhood": "Brooklyn",
        "category": "Fitness & Outdoors",
        "price": 0,
        "source": "Luma",
        "rsvp_link": "https://lu.ma/bk5k",
    }


class TestPushEvent:
    def test_push_event_returns_page_id(self, mock_notion_env, sample_event):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": "page-abc-123"}
        mock_resp.raise_for_status = MagicMock()
        with patch("integrations.notion.client.requests.post", return_value=mock_resp):
            with patch("integrations.notion.client.get_event_by_rsvp_link", return_value=None):
                from integrations.notion import client
                result = client.push_event(sample_event)
        assert result == "page-abc-123"

    def test_push_event_skips_duplicate(self, mock_notion_env, sample_event):
        """If RSVP link already exists in Notion, returns None without posting."""
        with patch("integrations.notion.client.get_event_by_rsvp_link", return_value={"id": "existing"}):
            from integrations.notion import client
            result = client.push_event(sample_event)
        assert result is None

    def test_push_event_no_api_key_returns_none(self, monkeypatch, sample_event):
        monkeypatch.delenv("NOTION_API_KEY", raising=False)
        monkeypatch.delenv("NOTION_EVENTS_DB_ID", raising=False)
        from integrations.notion import client
        result = client.push_event(sample_event)
        assert result is None


class TestGetEvents:
    def test_get_events_returns_list(self, mock_notion_env):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {
                    "id": "page-1",
                    "properties": {
                        "Name": {"title": [{"plain_text": "Test Event"}]},
                        "Date": {"date": {"start": "2026-04-05T10:00:00"}},
                        "Status": {"select": {"name": "New"}},
                        "Category": {"select": {"name": "Fitness & Outdoors"}},
                        "Price": {"number": 0},
                        "RSVP Link": {"url": "https://lu.ma/test"},
                        "Address": {"rich_text": [{"plain_text": "123 Main St"}]},
                        "Venue": {"rich_text": [{"plain_text": "Prospect Park"}]},
                        "Source": {"select": {"name": "Luma"}},
                        "End Time": {"date": {"start": "2026-04-05T12:00:00"}},
                        "Friends Going": {"rich_text": [{"plain_text": ""}]},
                        "Registered": {"checkbox": False},
                        "Neighborhood": {"select": {"name": "Brooklyn"}},
                        "Cal Event ID": {"rich_text": []},
                        "Notes": {"rich_text": []},
                    },
                }
            ],
            "has_more": False,
        }
        mock_resp.raise_for_status = MagicMock()
        with patch("integrations.notion.client.requests.post", return_value=mock_resp):
            from integrations.notion import client
            events = client.get_events()
        assert len(events) == 1
        assert events[0]["name"] == "Test Event"
        assert events[0]["notion_id"] == "page-1"

    def test_get_events_no_db_id_returns_empty(self, monkeypatch):
        monkeypatch.delenv("NOTION_EVENTS_DB_ID", raising=False)
        import integrations.notion.client as c
        events = c.get_events()
        assert events == []


class TestUpdateEventStatus:
    def test_update_status_patches_correct_page(self, mock_notion_env):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        with patch("integrations.notion.client.requests.patch", return_value=mock_resp) as m:
            from integrations.notion import client
            client.update_event_status("page-abc", "Attended")
        call_url = m.call_args[0][0]
        assert "page-abc" in call_url

    def test_update_status_no_key_is_noop(self, monkeypatch):
        monkeypatch.delenv("NOTION_API_KEY", raising=False)
        from integrations.notion import client
        result = client.update_event_status("page-abc", "Attended")
        assert result is False


class TestGetProgress:
    def test_get_progress_counts_attended(self, mock_notion_env):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {"id": "p1", "properties": {
                    "Name": {"title": [{"plain_text": "Event A"}]},
                    "Status": {"select": {"name": "Attended"}},
                    "Category": {"select": {"name": "Fitness & Outdoors"}},
                    "Date": {"date": {"start": "2026-03-10T10:00:00"}},
                    "Price": {"number": 0}, "RSVP Link": {"url": "https://x.com/a"},
                    "Address": {"rich_text": [{"plain_text": ""}]},
                    "Venue": {"rich_text": [{"plain_text": ""}]},
                    "Source": {"select": {"name": "Luma"}},
                    "End Time": {"date": None},
                    "Friends Going": {"rich_text": [{"plain_text": ""}]},
                    "Registered": {"checkbox": False},
                    "Neighborhood": {"select": None},
                    "Cal Event ID": {"rich_text": []},
                    "Notes": {"rich_text": []},
                }},
            ],
            "has_more": False,
        }
        mock_resp.raise_for_status = MagicMock()
        with patch("integrations.notion.client.requests.post", return_value=mock_resp):
            from integrations.notion import client
            progress = client.get_progress()
        assert progress["total_attended"] == 1
        assert progress["by_category"]["Fitness & Outdoors"] == 1
        assert progress["goal"] == 20


class TestAddFriendRsvp:
    def test_add_friend_appends_name(self, mock_notion_env):
        # First GET to read current Friends Going
        get_resp = MagicMock()
        get_resp.json.return_value = {"properties": {
            "Friends Going": {"rich_text": [{"plain_text": "Alice"}]}
        }}
        get_resp.raise_for_status = MagicMock()
        patch_resp = MagicMock()
        patch_resp.raise_for_status = MagicMock()
        with patch("integrations.notion.client.requests.get", return_value=get_resp):
            with patch("integrations.notion.client.requests.patch", return_value=patch_resp) as m:
                from integrations.notion import client
                client.add_friend_rsvp("page-abc", "Bob")
        patched_body = m.call_args[1]["json"]
        friends_text = patched_body["properties"]["Friends Going"]["rich_text"][0]["text"]["content"]
        assert "Alice" in friends_text
        assert "Bob" in friends_text

    def test_add_friend_rejects_url_in_name(self, mock_notion_env):
        from integrations.notion import client
        result = client.add_friend_rsvp("page-abc", "http://spam.com")
        assert result is False

    def test_add_friend_rejects_empty_name(self, mock_notion_env):
        from integrations.notion import client
        result = client.add_friend_rsvp("page-abc", "")
        assert result is False

    def test_add_friend_rejects_when_max_friends_reached(self, mock_notion_env):
        get_resp = MagicMock()
        # 10 friends already — should reject
        get_resp.json.return_value = {"properties": {
            "Friends Going": {"rich_text": [{"plain_text": "A, B, C, D, E, F, G, H, I, J"}]}
        }}
        get_resp.raise_for_status = MagicMock()
        with patch("integrations.notion.client.requests.get", return_value=get_resp):
            from integrations.notion import client
            result = client.add_friend_rsvp("page-abc", "NewPerson")
        assert result is False


class TestGetEventByRsvpLink:
    def test_returns_parsed_event_when_found(self, mock_notion_env):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [{
                "id": "page-xyz",
                "properties": {
                    "Name": {"title": [{"plain_text": "Brooklyn 5K Run"}]},
                    "Date": {"date": {"start": "2026-04-05T10:00:00"}},
                    "Status": {"select": {"name": "New"}},
                    "Category": {"select": {"name": "Fitness & Outdoors"}},
                    "Price": {"number": 0},
                    "RSVP Link": {"url": "https://lu.ma/bk5k"},
                    "Address": {"rich_text": [{"plain_text": "Prospect Park"}]},
                    "Venue": {"rich_text": [{"plain_text": "Prospect Park"}]},
                    "Source": {"select": {"name": "Luma"}},
                    "End Time": {"date": None},
                    "Friends Going": {"rich_text": []},
                    "Registered": {"checkbox": False},
                    "Neighborhood": {"select": {"name": "Brooklyn"}},
                    "Cal Event ID": {"rich_text": []},
                    "Notes": {"rich_text": []},
                }
            }]
        }
        mock_resp.raise_for_status = MagicMock()
        with patch("integrations.notion.client.requests.post", return_value=mock_resp):
            from integrations.notion import client
            result = client.get_event_by_rsvp_link("https://lu.ma/bk5k")
        assert result is not None
        assert result["notion_id"] == "page-xyz"
        assert result["name"] == "Brooklyn 5K Run"

    def test_returns_none_when_not_found(self, mock_notion_env):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"results": []}
        mock_resp.raise_for_status = MagicMock()
        with patch("integrations.notion.client.requests.post", return_value=mock_resp):
            from integrations.notion import client
            result = client.get_event_by_rsvp_link("https://lu.ma/notfound")
        assert result is None


class TestGetFriendsGoing:
    def test_returns_list_of_names(self, mock_notion_env):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"properties": {
            "Friends Going": {"rich_text": [{"plain_text": "Alice, Bob, Carol"}]}
        }}
        mock_resp.raise_for_status = MagicMock()
        with patch("integrations.notion.client.requests.get", return_value=mock_resp):
            from integrations.notion import client
            result = client.get_friends_going("page-abc")
        assert result == ["Alice", "Bob", "Carol"]

    def test_returns_empty_list_when_no_api_key(self, monkeypatch):
        monkeypatch.delenv("NOTION_API_KEY", raising=False)
        from integrations.notion import client
        result = client.get_friends_going("page-abc")
        assert result == []
