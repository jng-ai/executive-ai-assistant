"""
Tests for integrations/telegram/dashboard.py
"""

import json
import datetime
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ── Helpers ────────────────────────────────────────────────────────────────────

class TestDaysAgo:
    def test_today(self):
        from integrations.telegram.dashboard import _days_ago
        today = datetime.date.today().isoformat()
        assert _days_ago(today) == "today"

    def test_yesterday(self):
        from integrations.telegram.dashboard import _days_ago
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        assert _days_ago(yesterday) == "yesterday"

    def test_n_days_ago(self):
        from integrations.telegram.dashboard import _days_ago
        five_days = (datetime.date.today() - datetime.timedelta(days=5)).isoformat()
        assert _days_ago(five_days) == "5d ago"

    def test_invalid_date_returns_dash(self):
        from integrations.telegram.dashboard import _days_ago
        assert _days_ago("not-a-date") == "—"

    def test_empty_string_returns_dash(self):
        from integrations.telegram.dashboard import _days_ago
        assert _days_ago("") == "—"


class TestLoadJson:
    def test_returns_empty_list_for_missing_file(self, tmp_path):
        from integrations.telegram.dashboard import _load_json
        assert _load_json(tmp_path / "nonexistent.json") == []

    def test_returns_parsed_data(self, tmp_path):
        f = tmp_path / "data.json"
        f.write_text(json.dumps([{"key": "value"}]))
        from integrations.telegram.dashboard import _load_json
        assert _load_json(f) == [{"key": "value"}]

    def test_returns_empty_list_on_corrupt_json(self, tmp_path):
        f = tmp_path / "bad.json"
        f.write_text("not json{{{")
        from integrations.telegram.dashboard import _load_json
        assert _load_json(f) == []


# ── One-liners ─────────────────────────────────────────────────────────────────

class TestHealthOneliner:
    def test_no_data_returns_no_data(self, tmp_path, monkeypatch):
        import integrations.telegram.dashboard as d
        monkeypatch.setattr(d, "DATA_DIR", tmp_path)
        result = d._health_oneliner()
        assert "No data" in result

    def test_with_health_data(self, tmp_path, monkeypatch):
        import integrations.telegram.dashboard as d
        monkeypatch.setattr(d, "DATA_DIR", tmp_path)
        today = datetime.date.today().isoformat()
        health_data = [
            {"metric": "meal", "value": "chicken", "date": today},
            {"metric": "weight", "value": "174", "date": today},
        ]
        (tmp_path / "health.json").write_text(json.dumps(health_data))
        result = d._health_oneliner()
        assert "1 meals" in result
        assert "174" in result


class TestMarketOneliner:
    def test_weekend_shows_closed(self, monkeypatch):
        import integrations.telegram.dashboard as d
        # Saturday
        fake_dt = datetime.datetime(2026, 3, 21, 12, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-5)))
        monkeypatch.setattr(d, "_et_now", lambda: fake_dt)
        result = d._market_oneliner()
        assert "closed" in result.lower() or "weekend" in result.lower()

    def test_pre_market(self, monkeypatch):
        import integrations.telegram.dashboard as d
        # Monday 8 AM ET
        fake_dt = datetime.datetime(2026, 3, 23, 8, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-5)))
        monkeypatch.setattr(d, "_et_now", lambda: fake_dt)
        result = d._market_oneliner()
        assert "pre-market" in result.lower() or "opens" in result.lower()

    def test_market_open(self, monkeypatch):
        import integrations.telegram.dashboard as d
        # Monday 11 AM ET
        fake_dt = datetime.datetime(2026, 3, 23, 11, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-5)))
        monkeypatch.setattr(d, "_et_now", lambda: fake_dt)
        result = d._market_oneliner()
        assert "open" in result.lower()

    def test_after_hours(self, monkeypatch):
        import integrations.telegram.dashboard as d
        # Monday 17 AM ET
        fake_dt = datetime.datetime(2026, 3, 23, 17, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-5)))
        monkeypatch.setattr(d, "_et_now", lambda: fake_dt)
        result = d._market_oneliner()
        assert "after" in result.lower()


class TestBonusOneliner:
    def test_no_data_returns_default(self, tmp_path, monkeypatch):
        import integrations.telegram.dashboard as d
        monkeypatch.setattr(d, "DATA_DIR", tmp_path)
        result = d._bonus_oneliner()
        assert "8 AM" in result or "daily" in result.lower()

    def test_with_last_scan_date(self, tmp_path, monkeypatch):
        import integrations.telegram.dashboard as d
        monkeypatch.setattr(d, "DATA_DIR", tmp_path)
        today = datetime.date.today().isoformat()
        (tmp_path / "bonus_alerts_sent.json").write_text(json.dumps({"last_scan": today}))
        result = d._bonus_oneliner()
        assert "today" in result or "scan" in result.lower()


class TestFinanceOneliner:
    def test_with_profile_last_updated(self, tmp_path, monkeypatch):
        import integrations.telegram.dashboard as d
        monkeypatch.setattr(d, "DATA_DIR", tmp_path)
        # Disable Origin scraper so we fall through to profile-based text
        monkeypatch.setattr(d, "_load_origin_snapshot", lambda: None, raising=False)
        today = datetime.date.today().isoformat()
        (tmp_path / "financial_profile.json").write_text(json.dumps({"last_updated": today}))
        # Patch the origin import inside _finance_oneliner
        with patch("integrations.origin.scraper.load_snapshot", return_value=None):
            result = d._finance_oneliner()
        assert "today" in result or "Profile" in result or "updated" in result.lower()

    def test_no_profile_falls_back_to_bonus_scan(self, tmp_path, monkeypatch):
        import integrations.telegram.dashboard as d
        monkeypatch.setattr(d, "DATA_DIR", tmp_path)
        result = d._finance_oneliner()
        assert isinstance(result, str)


# ── Static oneliners ───────────────────────────────────────────────────────────

class TestStaticOneliners:
    def test_social_oneliner(self):
        from integrations.telegram.dashboard import _social_oneliner
        assert "Tue" in _social_oneliner() or "scan" in _social_oneliner().lower()

    def test_travel_oneliner(self):
        from integrations.telegram.dashboard import _travel_oneliner
        assert isinstance(_travel_oneliner(), str)

    def test_mortgage_oneliner(self):
        from integrations.telegram.dashboard import _mortgage_oneliner
        assert "Paperstac" in _mortgage_oneliner()

    def test_infusion_oneliner(self):
        from integrations.telegram.dashboard import _infusion_oneliner
        assert isinstance(_infusion_oneliner(), str)


# ── build_main_dashboard / build_agent_dashboard ──────────────────────────────

class TestBuildMainDashboard:
    def test_returns_text_and_keyboard(self, tmp_path, monkeypatch):
        import integrations.telegram.dashboard as d
        monkeypatch.setattr(d, "DATA_DIR", tmp_path)
        # Patch all Google-dependent oneliners to not make real calls
        monkeypatch.setattr(d, "_calendar_oneliner", lambda: "calendar status")
        monkeypatch.setattr(d, "_email_oneliner", lambda: "email status")
        monkeypatch.setattr(d, "_followup_oneliner", lambda: "no followups")
        text, keyboard = d.build_main_dashboard()
        assert "Dashboard" in text
        assert keyboard is not None

    def test_contains_all_agent_labels(self, tmp_path, monkeypatch):
        import integrations.telegram.dashboard as d
        monkeypatch.setattr(d, "DATA_DIR", tmp_path)
        monkeypatch.setattr(d, "_calendar_oneliner", lambda: "ok")
        monkeypatch.setattr(d, "_email_oneliner", lambda: "ok")
        monkeypatch.setattr(d, "_followup_oneliner", lambda: "ok")
        text, _ = d.build_main_dashboard()
        for agent in ["Health", "Finance", "Market", "Calendar", "Email"]:
            assert agent in text

    def test_oneliner_exception_doesnt_crash(self, tmp_path, monkeypatch):
        import integrations.telegram.dashboard as d
        monkeypatch.setattr(d, "DATA_DIR", tmp_path)
        monkeypatch.setattr(d, "_calendar_oneliner", lambda: (_ for _ in ()).throw(Exception("boom")))
        monkeypatch.setattr(d, "_email_oneliner", lambda: "ok")
        monkeypatch.setattr(d, "_followup_oneliner", lambda: "ok")
        # Should not raise
        text, keyboard = d.build_main_dashboard()
        assert "Dashboard" in text


class TestBuildAgentDashboard:
    def test_health_dashboard(self, tmp_path, monkeypatch):
        import integrations.telegram.dashboard as d
        monkeypatch.setattr(d, "DATA_DIR", tmp_path)
        text, keyboard = d.build_agent_dashboard("health")
        assert "Health" in text
        assert keyboard is not None

    def test_finance_dashboard(self, tmp_path, monkeypatch):
        import integrations.telegram.dashboard as d
        monkeypatch.setattr(d, "DATA_DIR", tmp_path)
        text, keyboard = d.build_agent_dashboard("finance")
        assert "Finance" in text

    def test_market_dashboard(self, tmp_path, monkeypatch):
        import integrations.telegram.dashboard as d
        fake_dt = datetime.datetime(2026, 3, 23, 11, 0, tzinfo=datetime.timezone(datetime.timedelta(hours=-5)))
        monkeypatch.setattr(d, "_et_now", lambda: fake_dt)
        text, keyboard = d.build_agent_dashboard("market")
        assert "Market" in text

    def test_unknown_agent_returns_warning(self, tmp_path, monkeypatch):
        import integrations.telegram.dashboard as d
        text, keyboard = d.build_agent_dashboard("nonexistent_agent")
        assert "Unknown agent" in text or "⚠️" in text

    def test_calendar_dashboard_when_not_configured(self, monkeypatch):
        import integrations.telegram.dashboard as d
        with patch("integrations.google.auth.is_configured", return_value=False):
            text, keyboard = d.build_agent_dashboard("calendar")
        assert "Calendar" in text

    def test_social_dashboard(self):
        from integrations.telegram.dashboard import build_agent_dashboard
        text, keyboard = build_agent_dashboard("social")
        assert "Social" in text or "NYC" in text

    def test_travel_dashboard(self):
        from integrations.telegram.dashboard import build_agent_dashboard
        text, keyboard = build_agent_dashboard("travel")
        assert "Travel" in text

    def test_mortgage_dashboard(self):
        from integrations.telegram.dashboard import build_agent_dashboard
        text, keyboard = build_agent_dashboard("mortgage")
        assert "Mortgage" in text

    def test_infusion_dashboard(self):
        from integrations.telegram.dashboard import build_agent_dashboard
        text, keyboard = build_agent_dashboard("infusion")
        assert "Infusion" in text

    def test_bonus_dashboard(self, tmp_path, monkeypatch):
        import integrations.telegram.dashboard as d
        monkeypatch.setattr(d, "DATA_DIR", tmp_path)
        text, keyboard = d.build_agent_dashboard("bonus")
        assert "Bonus" in text

    def test_followup_dashboard_no_pending(self, tmp_data_dir):
        from integrations.telegram.dashboard import build_agent_dashboard
        text, keyboard = build_agent_dashboard("followup")
        assert "Follow-up" in text or "follow" in text.lower()

    def test_back_keyboard_has_main_callback(self):
        from integrations.telegram.dashboard import build_agent_dashboard
        _, keyboard = build_agent_dashboard("health")
        # Back button callback_data should route back to __main__
        buttons = keyboard.inline_keyboard
        back = buttons[0][0]
        assert "dash:__main__" in back.callback_data

    def test_main_keyboard_has_dash_callbacks(self):
        from integrations.telegram.dashboard import build_main_keyboard
        keyboard = build_main_keyboard()
        for row in keyboard.inline_keyboard:
            for btn in row:
                assert btn.callback_data.startswith("dash:")
