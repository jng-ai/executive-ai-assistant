"""
Tests for core/followups.py
"""

import json
import datetime
import pytest


class TestAddFollowup:
    def test_creates_entry(self, tmp_data_dir):
        from core.followups import add_followup
        entry = add_followup(
            follow_type="email",
            contact="Alice",
            context="project update",
            body_request="Check on status",
            due_iso="2026-04-01T09:00:00",
        )
        assert entry["type"] == "email"
        assert entry["contact"] == "Alice"
        assert entry["context"] == "project update"
        assert entry["body_request"] == "Check on status"
        assert entry["due"] == "2026-04-01T09:00:00"
        assert entry["status"] == "pending"
        assert "id" in entry
        assert "created" in entry

    def test_persists_to_file(self, tmp_data_dir):
        from core.followups import add_followup, FOLLOWUPS_FILE
        add_followup("email", "Bob", "ctx", "body", "2026-04-01T09:00:00")
        data = json.loads(FOLLOWUPS_FILE.read_text())
        assert len(data) == 1
        assert data[0]["contact"] == "Bob"

    def test_auto_increments_id(self, tmp_data_dir):
        from core.followups import add_followup
        f1 = add_followup("email", "A", "c", "b", "2026-04-01T09:00:00")
        f2 = add_followup("meeting", "B", "c", "b", "2026-04-02T09:00:00")
        assert f2["id"] == f1["id"] + 1

    def test_stores_email_field(self, tmp_data_dir):
        from core.followups import add_followup
        entry = add_followup("email", "Charlie", "ctx", "body", "2026-04-01T09:00:00", email="charlie@example.com")
        assert entry["email"] == "charlie@example.com"

    def test_default_email_is_empty(self, tmp_data_dir):
        from core.followups import add_followup
        entry = add_followup("email", "Dan", "ctx", "body", "2026-04-01T09:00:00")
        assert entry["email"] == ""


class TestListPending:
    def test_returns_due_followups(self, tmp_data_dir):
        from core.followups import add_followup, list_pending
        past_due = (datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat()
        add_followup("email", "Alice", "ctx", "body", past_due)
        result = list_pending()
        assert len(result) == 1
        assert result[0]["contact"] == "Alice"

    def test_excludes_future_followups(self, tmp_data_dir):
        from core.followups import add_followup, list_pending
        future = (datetime.datetime.now() + datetime.timedelta(days=7)).isoformat()
        add_followup("email", "Future Person", "ctx", "body", future)
        assert list_pending() == []

    def test_excludes_cancelled_followups(self, tmp_data_dir):
        from core.followups import add_followup, cancel_followup, list_pending
        past = (datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat()
        f = add_followup("email", "Alice", "ctx", "body", past)
        cancel_followup(f["id"])
        assert list_pending() == []

    def test_excludes_done_followups(self, tmp_data_dir):
        from core.followups import add_followup, mark_done, list_pending
        past = (datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat()
        f = add_followup("email", "Alice", "ctx", "body", past)
        mark_done(f["id"])
        assert list_pending() == []

    def test_empty_file_returns_empty(self, tmp_data_dir):
        from core.followups import list_pending
        assert list_pending() == []


class TestListAllPending:
    def test_includes_future_pending(self, tmp_data_dir):
        from core.followups import add_followup, list_all_pending
        future = (datetime.datetime.now() + datetime.timedelta(days=30)).isoformat()
        add_followup("meeting", "Someone", "ctx", "body", future)
        result = list_all_pending()
        assert len(result) == 1

    def test_excludes_cancelled(self, tmp_data_dir):
        from core.followups import add_followup, cancel_followup, list_all_pending
        future = (datetime.datetime.now() + datetime.timedelta(days=7)).isoformat()
        f = add_followup("email", "Bob", "ctx", "body", future)
        cancel_followup(f["id"])
        assert list_all_pending() == []

    def test_excludes_done(self, tmp_data_dir):
        from core.followups import add_followup, mark_done, list_all_pending
        future = (datetime.datetime.now() + datetime.timedelta(days=7)).isoformat()
        f = add_followup("email", "Eve", "ctx", "body", future)
        mark_done(f["id"])
        assert list_all_pending() == []


class TestMarkDone:
    def test_marks_followup_done(self, tmp_data_dir):
        from core.followups import add_followup, mark_done, FOLLOWUPS_FILE
        f = add_followup("email", "X", "ctx", "body", "2026-04-01T09:00:00")
        assert mark_done(f["id"]) is True
        data = json.loads(FOLLOWUPS_FILE.read_text())
        assert data[0]["status"] == "done"
        assert "fired_at" in data[0]

    def test_returns_false_for_nonexistent_id(self, tmp_data_dir):
        from core.followups import mark_done
        assert mark_done(9999) is False


class TestCancelFollowup:
    def test_cancels_followup(self, tmp_data_dir):
        from core.followups import add_followup, cancel_followup, FOLLOWUPS_FILE
        f = add_followup("email", "Y", "ctx", "body", "2026-04-01T09:00:00")
        assert cancel_followup(f["id"]) is True
        data = json.loads(FOLLOWUPS_FILE.read_text())
        assert data[0]["status"] == "cancelled"

    def test_returns_false_for_nonexistent_id(self, tmp_data_dir):
        from core.followups import cancel_followup
        assert cancel_followup(9999) is False


class TestLoadCorrupt:
    def test_corrupt_file_returns_empty(self, tmp_data_dir):
        from core.followups import FOLLOWUPS_FILE, list_all_pending
        FOLLOWUPS_FILE.write_text("bad json {{{")
        assert list_all_pending() == []
