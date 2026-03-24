"""
Tests for core/memory.py
"""

import json
import datetime
import pytest
from pathlib import Path
from unittest.mock import patch


# ── _load / _save internal helpers ───────────────────────────────────────────

class TestLoadSave:
    def test_load_returns_empty_list_for_missing_file(self, tmp_data_dir):
        from core.memory import _load
        result = _load(tmp_data_dir / "nonexistent.json")
        assert result == []

    def test_load_returns_parsed_json(self, tmp_data_dir):
        f = tmp_data_dir / "data.json"
        f.write_text(json.dumps([{"id": 1}]))
        from core.memory import _load
        assert _load(f) == [{"id": 1}]

    def test_load_returns_empty_list_on_corrupt_json(self, tmp_data_dir):
        f = tmp_data_dir / "bad.json"
        f.write_text("not json {{{")
        from core.memory import _load
        assert _load(f) == []

    def test_save_creates_file(self, tmp_data_dir):
        from core.memory import _save
        f = tmp_data_dir / "out.json"
        _save(f, [{"a": 1}])
        assert f.exists()
        assert json.loads(f.read_text()) == [{"a": 1}]


# ── Tasks ─────────────────────────────────────────────────────────────────────

class TestTasks:
    def test_add_task_creates_entry(self, tmp_data_dir, notion_not_configured):
        from core.memory import add_task
        entry = add_task("Buy milk", due="2026-01-01", priority="high")
        assert entry["task"] == "Buy milk"
        assert entry["due"] == "2026-01-01"
        assert entry["priority"] == "high"
        assert entry["status"] == "open"
        assert "id" in entry
        assert "created" in entry

    def test_add_task_persists_to_file(self, tmp_data_dir, notion_not_configured):
        from core.memory import add_task, TASKS_FILE
        add_task("Task A")
        add_task("Task B")
        data = json.loads(TASKS_FILE.read_text())
        assert len(data) == 2
        assert data[0]["task"] == "Task A"
        assert data[1]["task"] == "Task B"

    def test_add_task_auto_increments_id(self, tmp_data_dir, notion_not_configured):
        from core.memory import add_task
        t1 = add_task("First")
        t2 = add_task("Second")
        assert t2["id"] == t1["id"] + 1

    def test_add_task_default_priority(self, tmp_data_dir, notion_not_configured):
        from core.memory import add_task
        entry = add_task("Task")
        assert entry["priority"] == "normal"

    def test_list_tasks_open(self, tmp_data_dir, notion_not_configured):
        from core.memory import add_task, list_tasks
        add_task("Open task")
        tasks = list_tasks("open")
        assert len(tasks) == 1
        assert tasks[0]["status"] == "open"

    def test_list_tasks_filters_by_status(self, tmp_data_dir, notion_not_configured):
        from core.memory import add_task, complete_task, list_tasks
        add_task("A")
        t = add_task("B")
        complete_task(t["id"])
        assert len(list_tasks("open")) == 1
        assert len(list_tasks("done")) == 1

    def test_list_tasks_empty(self, tmp_data_dir):
        from core.memory import list_tasks
        assert list_tasks("open") == []

    def test_complete_task_returns_true(self, tmp_data_dir, notion_not_configured):
        from core.memory import add_task, complete_task
        t = add_task("Do thing")
        assert complete_task(t["id"]) is True

    def test_complete_task_marks_done(self, tmp_data_dir, notion_not_configured):
        from core.memory import add_task, complete_task, list_tasks
        t = add_task("Do thing")
        complete_task(t["id"])
        done = list_tasks("done")
        assert len(done) == 1
        assert done[0]["task"] == "Do thing"
        assert "completed" in done[0]

    def test_complete_task_returns_false_for_nonexistent(self, tmp_data_dir):
        from core.memory import complete_task
        assert complete_task(9999) is False


# ── Health ─────────────────────────────────────────────────────────────────────

class TestHealth:
    def test_log_health_creates_entry(self, tmp_data_dir, notion_not_configured):
        from core.memory import log_health
        entry = log_health("weight", "175", note="morning weight")
        assert entry["metric"] == "weight"
        assert entry["value"] == "175"
        assert entry["note"] == "morning weight"
        assert "date" in entry
        assert "timestamp" in entry

    def test_log_health_persists(self, tmp_data_dir, notion_not_configured):
        from core.memory import log_health, HEALTH_FILE
        log_health("sleep", "7.5")
        data = json.loads(HEALTH_FILE.read_text())
        assert len(data) == 1
        assert data[0]["metric"] == "sleep"

    def test_get_health_summary_returns_recent(self, tmp_data_dir, notion_not_configured):
        from core.memory import log_health, get_health_summary
        log_health("weight", "175")
        log_health("sleep", "7.0")
        summary = get_health_summary(7)
        assert len(summary) == 2

    def test_get_health_summary_filters_old(self, tmp_data_dir, notion_not_configured, monkeypatch):
        from core.memory import HEALTH_FILE, get_health_summary
        old_date = (datetime.date.today() - datetime.timedelta(days=30)).isoformat()
        HEALTH_FILE.write_text(json.dumps([
            {"metric": "weight", "value": "180", "date": old_date},
        ]))
        summary = get_health_summary(7)
        assert summary == []

    def test_get_health_summary_empty_file(self, tmp_data_dir):
        from core.memory import get_health_summary
        assert get_health_summary(7) == []

    def test_unit_for_known_metrics(self):
        from core.memory import _unit_for
        assert _unit_for("weight") == "lbs"
        assert _unit_for("sleep") == "hours"
        assert _unit_for("workout") == "session"
        assert _unit_for("meal") == "food log"

    def test_unit_for_unknown_metric(self):
        from core.memory import _unit_for
        assert _unit_for("unknown_metric") == ""


# ── Notes ──────────────────────────────────────────────────────────────────────

class TestNotes:
    def test_add_note_creates_entry(self, tmp_data_dir):
        from core.memory import add_note
        entry = add_note("Remember to call doctor", category="health")
        assert entry["content"] == "Remember to call doctor"
        assert entry["category"] == "health"
        assert "id" in entry
        assert "created" in entry

    def test_add_note_default_category(self, tmp_data_dir):
        from core.memory import add_note
        entry = add_note("Just a note")
        assert entry["category"] == "general"

    def test_add_note_persists(self, tmp_data_dir):
        from core.memory import add_note, NOTES_FILE
        add_note("Note 1")
        add_note("Note 2")
        data = json.loads(NOTES_FILE.read_text())
        assert len(data) == 2


# ── Notion shortcuts ───────────────────────────────────────────────────────────

class TestNotionShortcuts:
    def test_save_mortgage_deal_with_notion_unconfigured(self, notion_not_configured):
        from core.memory import save_mortgage_deal
        result = save_mortgage_deal("TX", 50000, 40000, "12%", "A", "http://example.com", "nice deal")
        assert result is False

    def test_save_investment_idea_with_notion_unconfigured(self, notion_not_configured):
        from core.memory import save_investment_idea
        result = save_investment_idea("Apple", "AAPL", "Strong brand", "AI growth", "Tech slowdown", "Buy", "High")
        assert result is False

    def test_save_consulting_lead_with_notion_unconfigured(self, notion_not_configured):
        from core.memory import save_consulting_lead
        result = save_consulting_lead("NYP Hospital", "Expansion signal", "High", "Infusion ops", "Cold email")
        assert result is False

    def test_save_mortgage_deal_discount_calculation(self, notion_not_configured):
        from core.memory import save_mortgage_deal
        # Just tests it doesn't crash (notion disabled → returns False)
        result = save_mortgage_deal("FL", 100000, 75000, "10%", "B")
        assert result is False

    def test_save_mortgage_deal_zero_upb_no_divide_by_zero(self, notion_not_configured):
        from core.memory import save_mortgage_deal
        # upb=0 → discount should be 0, not ZeroDivisionError
        result = save_mortgage_deal("TX", 0, 0, "N/A", "C")
        assert result is False

    def test_notion_sync_fails_silently(self, tmp_data_dir):
        """_notion_sync should never raise even if notion raises."""
        from core.memory import _notion_sync
        with patch("integrations.notion.client.add_row", side_effect=Exception("boom")):
            with patch("integrations.notion.client.is_configured", return_value=True):
                # Should not raise
                _notion_sync("tasks", "test", {})
