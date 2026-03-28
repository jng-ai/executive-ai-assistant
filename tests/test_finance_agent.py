"""
Tests for agents/finance_agent/handler.py

All LLM, search, and HTTP calls are mocked.
File operations are redirected to tmp_path.
"""

import json
import datetime
from pathlib import Path
from unittest.mock import patch, MagicMock


# ── Fixtures ──────────────────────────────────────────────────────────────────

import pytest

@pytest.fixture
def finance_tmp(tmp_path, monkeypatch):
    """Redirect all finance data files to tmp_path."""
    import agents.finance_agent.handler as h
    monkeypatch.setattr(h, "DATA_DIR", tmp_path)
    monkeypatch.setattr(h, "BONUS_DATA_FILE", tmp_path / "finance_bonuses.json")
    monkeypatch.setattr(h, "BUDGET_FILE", tmp_path / "budget_log.json")
    monkeypatch.setattr(h, "PROFILE_FILE", tmp_path / "financial_profile.json")
    monkeypatch.setattr(h, "SIDE_HUSTLE_FILE", tmp_path / "side_hustle_ideas.json")
    return tmp_path


# ── Data helpers ──────────────────────────────────────────────────────────────

class TestDataHelpers:
    def test_load_profile_missing_file(self, finance_tmp):
        from agents.finance_agent.handler import _load_profile
        assert _load_profile() == {}

    def test_load_profile_with_data(self, finance_tmp):
        import agents.finance_agent.handler as h
        h.PROFILE_FILE.write_text(json.dumps({"net_worth": "500k"}))
        assert h._load_profile() == {"net_worth": "500k"}

    def test_load_profile_corrupt_returns_empty(self, finance_tmp):
        import agents.finance_agent.handler as h
        h.PROFILE_FILE.write_text("bad json {{{")
        assert h._load_profile() == {}

    def test_save_and_load_profile(self, finance_tmp):
        from agents.finance_agent.handler import _save_profile, _load_profile
        _save_profile({"salary": "200k"})
        assert _load_profile()["salary"] == "200k"

    def test_profile_context_empty(self, finance_tmp):
        from agents.finance_agent.handler import _profile_context
        assert _profile_context() == ""

    def test_profile_context_with_data(self, finance_tmp):
        import agents.finance_agent.handler as h
        h.PROFILE_FILE.write_text(json.dumps({"income": "200k", "goal": "retire early"}))
        ctx = h._profile_context()
        assert "income" in ctx
        assert "200k" in ctx

    def test_load_bonuses_missing(self, finance_tmp):
        from agents.finance_agent.handler import _load_bonuses
        assert _load_bonuses() == []

    def test_save_and_load_bonuses(self, finance_tmp):
        from agents.finance_agent.handler import _save_bonuses, _load_bonuses
        _save_bonuses([{"card": "Chase Sapphire", "bonus": 80000}])
        result = _load_bonuses()
        assert len(result) == 1
        assert result[0]["card"] == "Chase Sapphire"

    def test_load_bonuses_corrupt_returns_empty(self, finance_tmp):
        import agents.finance_agent.handler as h
        h.BONUS_DATA_FILE.write_text("bad json")
        assert h._load_bonuses() == []

    def test_load_budget_missing(self, finance_tmp):
        from agents.finance_agent.handler import _load_budget
        assert _load_budget() == []

    def test_save_and_load_budget(self, finance_tmp):
        from agents.finance_agent.handler import _save_budget, _load_budget
        _save_budget([{"amount": 100, "category": "groceries", "type": "expense"}])
        result = _load_budget()
        assert result[0]["category"] == "groceries"

    def test_load_side_hustles_missing(self, finance_tmp):
        from agents.finance_agent.handler import _load_side_hustles
        assert _load_side_hustles() == []

    def test_save_and_load_side_hustles(self, finance_tmp):
        from agents.finance_agent.handler import _save_side_hustles, _load_side_hustles
        _save_side_hustles([{"name": "consulting course", "status": "idea"}])
        result = _load_side_hustles()
        assert result[0]["name"] == "consulting course"


# ── Reddit fetch ───────────────────────────────────────────────────────────────

class TestFetchRedditPosts:
    def test_returns_empty_on_import_error(self, monkeypatch):
        import agents.finance_agent.handler as h
        with patch.dict("sys.modules", {"requests": None}):
            # simulate ImportError
            with patch("builtins.__import__", side_effect=ImportError("no requests")):
                result = h._fetch_reddit_posts()
        # Should return [] or not raise
        assert isinstance(result, list)

    def test_skips_unknown_subreddits(self):
        from agents.finance_agent.handler import _fetch_reddit_posts
        # Subreddit not in url_map → silently skipped
        with patch("requests.get") as mock_get:
            result = _fetch_reddit_posts(["r/nonexistent_subreddit_xyz"])
        assert result == []
        assert not mock_get.called

    def test_handles_http_error_gracefully(self):
        from agents.finance_agent.handler import _fetch_reddit_posts
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        with patch("requests.get", return_value=mock_resp):
            result = _fetch_reddit_posts(["r/churning"])
        assert result == []

    def test_parses_posts_with_bonus_keywords(self):
        from agents.finance_agent.handler import _fetch_reddit_posts
        data = {
            "data": {"children": [
                {"data": {"title": "Amex elevated bonus offer", "selftext": "100k offer live",
                          "score": 150, "permalink": "/r/churning/123"}},
            ]}
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = data
        with patch("requests.get", return_value=mock_resp):
            result = _fetch_reddit_posts(["r/churning"])
        assert any("bonus" in p["title"].lower() for p in result)

    def test_handles_exception_per_subreddit(self):
        from agents.finance_agent.handler import _fetch_reddit_posts
        with patch("requests.get", side_effect=Exception("timeout")):
            result = _fetch_reddit_posts(["r/churning"])
        assert result == []


# ── _parse_intent ─────────────────────────────────────────────────────────────

class TestParseIntent:
    def test_valid_json_response(self):
        payload = {"type": "bank_bonuses", "query": "best bank bonuses", "card_or_bank": None, "idea": None}
        with patch("agents.finance_agent.handler.chat", return_value=json.dumps(payload)):
            from agents.finance_agent.handler import _parse_intent
            result = _parse_intent("best bank bonuses right now")
        assert result["type"] == "bank_bonuses"

    def test_strips_markdown_fences(self):
        payload = {"type": "cc_bonuses", "query": "Chase SUB", "card_or_bank": "Chase Sapphire", "idea": None}
        wrapped = f"```json\n{json.dumps(payload)}\n```"
        with patch("agents.finance_agent.handler.chat", return_value=wrapped):
            from agents.finance_agent.handler import _parse_intent
            result = _parse_intent("Chase Sapphire elevated offer?")
        assert result["type"] == "cc_bonuses"

    def test_falls_back_on_invalid_json(self):
        with patch("agents.finance_agent.handler.chat", return_value="not json"):
            from agents.finance_agent.handler import _parse_intent
            result = _parse_intent("random question")
        assert result["type"] == "finance_general"


# ── handle() dispatch paths ────────────────────────────────────────────────────

class TestHandleDispatch:
    """Test all 15+ routing paths in handle() via mocked _parse_intent."""

    def _mock_parse(self, type_, card=None, idea=None, query=""):
        return {"type": type_, "query": query, "card_or_bank": card, "idea": idea}

    def test_bank_bonuses_route(self, finance_tmp):
        with patch("agents.finance_agent.handler._parse_intent", return_value=self._mock_parse("bank_bonuses")):
            with patch("agents.finance_agent.handler._find_bank_bonuses", return_value="bank results") as m:
                from agents.finance_agent.handler import handle
                result = handle("best bank bonuses")
        assert result == "bank results"
        m.assert_called_once()

    def test_cc_bonuses_route(self, finance_tmp):
        with patch("agents.finance_agent.handler._parse_intent", return_value=self._mock_parse("cc_bonuses", card="Amex Gold")):
            with patch("agents.finance_agent.handler._find_cc_bonuses", return_value="cc results") as m:
                from agents.finance_agent.handler import handle
                handle("Amex Gold bonus?")
        m.assert_called_once()

    def test_eligibility_route(self, finance_tmp):
        with patch("agents.finance_agent.handler._parse_intent", return_value=self._mock_parse("eligibility", card="Chase Sapphire")):
            with patch("agents.finance_agent.handler._check_eligibility_specific", return_value="eligible") as m:
                from agents.finance_agent.handler import handle
                handle("am I eligible for Chase Sapphire?")
        m.assert_called_once()

    def test_re_eligibility_route(self, finance_tmp):
        with patch("agents.finance_agent.handler._parse_intent", return_value=self._mock_parse("re_eligibility_check")):
            with patch("agents.finance_agent.handler._check_re_eligibility", return_value="re-eligibility") as m:
                from agents.finance_agent.handler import handle
                handle("what cards can I apply for?")
        m.assert_called_once()

    def test_log_application_route(self, finance_tmp):
        with patch("agents.finance_agent.handler._parse_intent", return_value=self._mock_parse("log_application", card="Chase Ink")):
            with patch("agents.finance_agent.handler._log_application", return_value="logged") as m:
                from agents.finance_agent.handler import handle
                handle("I just opened Chase Ink")
        m.assert_called_once()

    def test_log_bonus_route(self, finance_tmp):
        with patch("agents.finance_agent.handler._parse_intent", return_value=self._mock_parse("log_bonus", card="Amex Gold")):
            with patch("agents.finance_agent.handler._log_bonus", return_value="bonus logged") as m:
                from agents.finance_agent.handler import handle
                handle("I got the Amex Gold bonus")
        m.assert_called_once()

    def test_track_bonus_route(self, finance_tmp):
        with patch("agents.finance_agent.handler._parse_intent", return_value=self._mock_parse("track_bonus")):
            with patch("agents.finance_agent.handler._show_tracker", return_value="tracker") as m:
                from agents.finance_agent.handler import handle
                handle("show my tracker")
        m.assert_called_once()

    def test_budget_log_route(self, finance_tmp):
        with patch("agents.finance_agent.handler._parse_intent", return_value=self._mock_parse("budget_log")):
            with patch("agents.finance_agent.handler._log_budget", return_value="budget logged") as m:
                from agents.finance_agent.handler import handle
                handle("spent $50 on groceries")
        m.assert_called_once()

    def test_budget_summary_route(self, finance_tmp):
        with patch("agents.finance_agent.handler._parse_intent", return_value=self._mock_parse("budget_summary")):
            with patch("agents.finance_agent.handler._budget_summary", return_value="summary") as m:
                from agents.finance_agent.handler import handle
                handle("what did I spend this month?")
        m.assert_called_once()

    def test_tax_strategy_route(self, finance_tmp):
        with patch("agents.finance_agent.handler._parse_intent", return_value=self._mock_parse("tax_strategy")):
            with patch("agents.finance_agent.handler._get_tax_strategy", return_value="tax tips") as m:
                from agents.finance_agent.handler import handle
                handle("how do I reduce my tax bill?")
        m.assert_called_once()

    def test_side_hustle_scan_route(self, finance_tmp):
        with patch("agents.finance_agent.handler._parse_intent", return_value=self._mock_parse("side_hustle_scan")):
            with patch("agents.finance_agent.handler._scan_side_hustles", return_value="hustle ideas") as m:
                from agents.finance_agent.handler import handle
                handle("any good side hustle ideas?")
        m.assert_called_once()

    def test_side_hustle_develop_route(self, finance_tmp):
        with patch("agents.finance_agent.handler._parse_intent", return_value=self._mock_parse("side_hustle_develop", idea="consulting course")):
            with patch("agents.finance_agent.handler._develop_side_hustle", return_value="hustle plan") as m:
                from agents.finance_agent.handler import handle
                handle("develop the consulting course idea")
        m.assert_called_once()

    def test_finance_review_route(self, finance_tmp):
        with patch("agents.finance_agent.handler._parse_intent", return_value=self._mock_parse("finance_review")):
            with patch("agents.finance_agent.handler._financial_intelligence_report", return_value="review") as m:
                from agents.finance_agent.handler import handle
                handle("review my finances")
        m.assert_called_once()

    def test_update_profile_route(self, finance_tmp):
        with patch("agents.finance_agent.handler._parse_intent", return_value=self._mock_parse("update_profile")):
            with patch("agents.finance_agent.handler._update_profile", return_value="profile updated") as m:
                from agents.finance_agent.handler import handle
                handle("I got a raise to $220k")
        m.assert_called_once()

    def test_finance_general_fallback(self, finance_tmp):
        with patch("agents.finance_agent.handler._parse_intent", return_value=self._mock_parse("finance_general", query="interest rates")):
            with patch("agents.finance_agent.handler.search", return_value=[]):
                with patch("agents.finance_agent.handler.chat", return_value="general finance answer"):
                    from agents.finance_agent.handler import handle
                    result = handle("what are interest rates right now?")
        assert result == "general finance answer"

    def test_side_hustle_list_exact_shortcut(self, finance_tmp):
        dummy_intent = {"type": "finance_general", "query": "", "card_or_bank": None, "idea": None}
        with patch("agents.finance_agent.handler._parse_intent", return_value=dummy_intent):
            with patch("agents.finance_agent.handler._list_side_hustles", return_value="my hustle list") as mock_list:
                from agents.finance_agent.handler import handle
                result = handle("side hustle list")
        assert result == "my hustle list"
        mock_list.assert_called_once()


# ── Budget summary ────────────────────────────────────────────────────────────

class TestBudgetSummary:
    def test_empty_budget_returns_no_data(self, finance_tmp):
        from agents.finance_agent.handler import _budget_summary
        import agents.finance_agent.handler as h
        # Prevent Origin API call when budget is empty
        with patch.object(h, "_origin_finance_context", return_value=""):
            result = _budget_summary()
        assert "Nothing logged" in result or "Budget" in result

    def test_with_expenses_shows_totals(self, finance_tmp):
        from agents.finance_agent.handler import _save_budget, _budget_summary
        today = datetime.date.today().isoformat()
        _save_budget([
            {"type": "expense", "amount": 150, "category": "groceries", "date": today, "description": "Whole Foods"},
            {"type": "expense", "amount": 80, "category": "dining", "date": today, "description": "Dinner"},
            {"type": "income", "amount": 5000, "category": "salary", "date": today, "description": "Paycheck"},
        ])
        result = _budget_summary()
        assert "groceries" in result.lower() or "Groceries" in result
        assert "230" in result or "$230" in result  # total expenses

    def test_old_entries_excluded(self, finance_tmp):
        import agents.finance_agent.handler as h
        from agents.finance_agent.handler import _save_budget, _budget_summary
        old_date = "2020-01-15"
        _save_budget([{"type": "expense", "amount": 9999, "category": "old", "date": old_date}])
        with patch.object(h, "_origin_finance_context", return_value=""):
            result = _budget_summary()
        assert "9999" not in result


# ── _find_bank_bonuses and _find_cc_bonuses ────────────────────────────────────

class TestBonusSearch:
    def test_find_bank_bonuses_calls_chat(self, finance_tmp):
        with patch("agents.finance_agent.handler.search", return_value=[]):
            with patch("agents.finance_agent.handler._fetch_reddit_posts", return_value=[]):
                with patch("agents.finance_agent.handler.chat", return_value="bank bonuses list") as m:
                    from agents.finance_agent.handler import _find_bank_bonuses
                    result = _find_bank_bonuses("best bank bonuses 2026")
        assert result == "bank bonuses list"

    def test_find_cc_bonuses_with_card_name(self, finance_tmp):
        with patch("agents.finance_agent.handler.search", return_value=[]):
            with patch("agents.finance_agent.handler._fetch_reddit_posts", return_value=[]):
                with patch("agents.finance_agent.handler.chat", return_value="Amex Gold 90k offer") as m:
                    from agents.finance_agent.handler import _find_cc_bonuses
                    result = _find_cc_bonuses("Amex Gold elevated", card_name="Amex Gold")
        assert result == "Amex Gold 90k offer"
        # Prompt should include card name
        prompt_arg = m.call_args[0][1]
        assert "Amex Gold" in prompt_arg

    def test_find_cc_bonuses_no_card(self, finance_tmp):
        with patch("agents.finance_agent.handler.search", return_value=[]):
            with patch("agents.finance_agent.handler._fetch_reddit_posts", return_value=[]):
                with patch("agents.finance_agent.handler.chat", return_value="top cc bonuses"):
                    from agents.finance_agent.handler import _find_cc_bonuses
                    result = _find_cc_bonuses("best cc bonuses 2026")
        assert result == "top cc bonuses"


# ── Corrupt file edge cases ────────────────────────────────────────────────────

class TestCorruptFiles:
    def test_load_budget_corrupt_returns_empty(self, finance_tmp):
        import agents.finance_agent.handler as h
        h.BUDGET_FILE.write_text("invalid {{{")
        assert h._load_budget() == []

    def test_load_side_hustles_corrupt_returns_empty(self, finance_tmp):
        import agents.finance_agent.handler as h
        h.SIDE_HUSTLE_FILE.write_text("not json")
        assert h._load_side_hustles() == []


# ── _parse_re_eligibility_months ──────────────────────────────────────────────

class TestParseReEligibilityMonths:
    def test_empty_returns_none(self):
        from agents.finance_agent.handler import _parse_re_eligibility_months
        assert _parse_re_eligibility_months("") is None

    def test_lifetime_returns_none(self):
        from agents.finance_agent.handler import _parse_re_eligibility_months
        assert _parse_re_eligibility_months("lifetime limit") is None

    def test_once_per_returns_none(self):
        from agents.finance_agent.handler import _parse_re_eligibility_months
        assert _parse_re_eligibility_months("once per lifetime") is None

    def test_months(self):
        from agents.finance_agent.handler import _parse_re_eligibility_months
        assert _parse_re_eligibility_months("24 months from close") == 24

    def test_years(self):
        from agents.finance_agent.handler import _parse_re_eligibility_months
        assert _parse_re_eligibility_months("2 years") == 24

    def test_unparseable_returns_none(self):
        from agents.finance_agent.handler import _parse_re_eligibility_months
        assert _parse_re_eligibility_months("some random text") is None


# ── _check_re_eligibility ──────────────────────────────────────────────────────

class TestCheckReEligibility:
    def test_sheets_unavailable_returns_response(self, finance_tmp):
        with patch("agents.finance_agent.handler.chat", return_value="re-eligibility result"):
            from agents.finance_agent.handler import _check_re_eligibility
            result = _check_re_eligibility("what can I apply for?")
        assert isinstance(result, str)

    def test_with_sheet_data(self, finance_tmp):
        sheet_data = {
            "CC Tracker": [
                {"Card Name": "Chase Sapphire Preferred", "Date Opened": "2024-01-15",
                 "Re-eligibility": "48 months", "SUB Status": "Received", "Date Closed": ""},
            ],
            "Bank Tracker": []
        }
        with patch("integrations.google_sheets.client.read_bonus_tracker", return_value=sheet_data):
            with patch("agents.finance_agent.handler.chat", return_value="result"):
                from agents.finance_agent.handler import _check_re_eligibility
                result = _check_re_eligibility()
        assert isinstance(result, str)


# ── _check_eligibility_specific ───────────────────────────────────────────────

class TestCheckEligibilitySpecific:
    def test_returns_chat_response(self, finance_tmp):
        with patch("agents.finance_agent.handler.search", return_value=[]):
            with patch("agents.finance_agent.handler.chat", return_value="eligibility info"):
                from agents.finance_agent.handler import _check_eligibility_specific
                result = _check_eligibility_specific("am I eligible?", card_name="Chase Sapphire")
        assert result == "eligibility info"

    def test_no_card_name(self, finance_tmp):
        with patch("agents.finance_agent.handler.search", return_value=[]):
            with patch("agents.finance_agent.handler.chat", return_value="general eligibility"):
                from agents.finance_agent.handler import _check_eligibility_specific
                result = _check_eligibility_specific("am I eligible?")
        assert result == "general eligibility"


# ── _log_application ──────────────────────────────────────────────────────────

class TestLogApplication:
    def test_cc_log_sheet_fails_gracefully(self, finance_tmp):
        parsed_json = '{"account_type": "credit_card", "card_or_account_name": "Chase Ink", "issuer_or_bank": "Chase", "date_opened": "2026-03-01", "sign_up_bonus": "90k", "min_spend": "$6000", "annual_fee": "$95", "re_eligibility": "24 months", "notes": "", "spend_deadline_months": 3}'
        with patch("agents.finance_agent.handler.chat", return_value=parsed_json):
            from agents.finance_agent.handler import _log_application
            result = _log_application("I just opened Chase Ink", card_name="Chase Ink")
        assert "✅" in result or "CC Application" in result

    def test_bank_log_path(self, finance_tmp):
        parsed_json = '{"account_type": "bank", "card_or_account_name": "Sofi Checking", "issuer_or_bank": "Sofi", "date_opened": "2026-03-01", "bonus_amount": "300", "sign_up_bonus": "$300", "min_deposit": "$10", "days_to_qualify": "60", "apy": "4.5%", "re_eligibility": "24 months", "notes": ""}'
        with patch("agents.finance_agent.handler.chat", return_value=parsed_json):
            from agents.finance_agent.handler import _log_application
            result = _log_application("opened Sofi checking")
        assert "✅" in result or "Bank Account" in result

    def test_invalid_json_fallback(self, finance_tmp):
        with patch("agents.finance_agent.handler.chat", return_value="not json"):
            from agents.finance_agent.handler import _log_application
            result = _log_application("I opened something", card_name="SomeCard")
        assert isinstance(result, str)

    def test_spend_deadline_calculation(self, finance_tmp):
        parsed_json = '{"account_type": "credit_card", "card_or_account_name": "Amex Gold", "issuer_or_bank": "Amex", "date_opened": "2026-01-01", "spend_deadline_months": 3, "sign_up_bonus": "60k", "min_spend": "$4000", "annual_fee": "$250", "re_eligibility": "lifetime", "notes": ""}'
        with patch("agents.finance_agent.handler.chat", return_value=parsed_json):
            from agents.finance_agent.handler import _log_application
            result = _log_application("opened Amex Gold")
        assert isinstance(result, str)


# ── _log_bonus ────────────────────────────────────────────────────────────────

class TestLogBonus:
    def test_logs_and_returns_confirm(self, finance_tmp):
        from agents.finance_agent.handler import _log_bonus, _load_bonuses
        result = _log_bonus("I got the Chase Sapphire bonus", card_name="Chase Sapphire Preferred")
        assert "✅" in result or "Bonus Received" in result
        bonuses = _load_bonuses()
        assert len(bonuses) == 1

    def test_no_card_name_uses_message(self, finance_tmp):
        from agents.finance_agent.handler import _log_bonus, _load_bonuses
        result = _log_bonus("got my 90k Amex bonus")
        bonuses = _load_bonuses()
        assert bonuses[0]["card_or_bank"].startswith("got my")


# ── _show_tracker ─────────────────────────────────────────────────────────────

class TestShowTracker:
    def test_empty_tracker(self, finance_tmp):
        from agents.finance_agent.handler import _show_tracker
        result = _show_tracker()
        assert "Empty" in result or "Bonus Tracker" in result

    def test_tracker_with_entries(self, finance_tmp):
        from agents.finance_agent.handler import _save_bonuses, _show_tracker
        _save_bonuses([
            {"card_or_bank": "Chase Sapphire", "date_logged": "2026-01-01", "status": "received"},
            {"card_or_bank": "Amex Gold", "date_logged": "2026-02-01", "status": "applied"},
        ])
        result = _show_tracker()
        assert "Chase Sapphire" in result
        assert "Amex Gold" in result


# ── _get_tax_strategy ─────────────────────────────────────────────────────────

class TestGetTaxStrategy:
    def test_returns_chat_response(self, finance_tmp):
        with patch("agents.finance_agent.handler.search", return_value=[]):
            with patch("agents.finance_agent.handler.chat", return_value="tax advice"):
                from agents.finance_agent.handler import _get_tax_strategy
                result = _get_tax_strategy("Solo 401k contributions")
        assert result == "tax advice"


# ── _scan_side_hustles ────────────────────────────────────────────────────────

class TestScanSideHustles:
    def test_returns_chat_response(self, finance_tmp):
        with patch("agents.finance_agent.handler.search", return_value=[]):
            with patch("agents.finance_agent.handler._fetch_reddit_posts", return_value=[]):
                with patch("agents.finance_agent.handler.chat", return_value="hustle ideas"):
                    from agents.finance_agent.handler import _scan_side_hustles
                    result = _scan_side_hustles("passive income ideas")
        assert result == "hustle ideas"


# ── _develop_side_hustle ──────────────────────────────────────────────────────

class TestDevelopSideHustle:
    def test_new_idea_saved(self, finance_tmp):
        with patch("agents.finance_agent.handler.search", return_value=[]):
            with patch("agents.finance_agent.handler.chat", return_value="full plan here"):
                from agents.finance_agent.handler import _develop_side_hustle, _load_side_hustles
                result = _develop_side_hustle("develop consulting course", idea="consulting course")
        assert "full plan here" in result
        ideas = _load_side_hustles()
        assert any(i["idea"] == "consulting course" for i in ideas)

    def test_existing_idea_updated(self, finance_tmp):
        from agents.finance_agent.handler import _save_side_hustles, _load_side_hustles
        _save_side_hustles([{"id": 1, "idea": "consulting course", "status": "exploring",
                              "date_added": "2026-01-01", "last_updated": "2026-01-01", "analysis": "old"}])
        with patch("agents.finance_agent.handler.search", return_value=[]):
            with patch("agents.finance_agent.handler.chat", return_value="updated plan"):
                from agents.finance_agent.handler import _develop_side_hustle
                _develop_side_hustle("refine the course", idea="consulting course")
        ideas = _load_side_hustles()
        assert ideas[0]["analysis"] == "updated plan"


# ── _list_side_hustles ────────────────────────────────────────────────────────

class TestListSideHustles:
    def test_empty_list(self, finance_tmp):
        from agents.finance_agent.handler import _list_side_hustles
        result = _list_side_hustles()
        assert "Empty" in result or "Side Hustle Tracker" in result

    def test_with_ideas(self, finance_tmp):
        from agents.finance_agent.handler import _save_side_hustles, _list_side_hustles
        _save_side_hustles([
            {"id": 1, "idea": "YouTube channel", "status": "exploring", "last_updated": "2026-01-01"},
            {"id": 2, "idea": "SaaS tool", "status": "active", "last_updated": "2026-02-01"},
        ])
        result = _list_side_hustles()
        assert "YouTube channel" in result
        assert "SaaS tool" in result


# ── _finance_review ───────────────────────────────────────────────────────────

class TestFinanceReview:
    def test_returns_chat_response(self, finance_tmp):
        with patch("agents.finance_agent.handler.search", return_value=[]):
            with patch("agents.finance_agent.handler.chat", return_value="holistic review"):
                from agents.finance_agent.handler import _finance_review
                result = _finance_review("review my finances")
        assert result == "holistic review"

    def test_with_budget_and_hustles(self, finance_tmp):
        import datetime as dt
        from agents.finance_agent.handler import _save_budget, _save_side_hustles, _finance_review
        today = dt.date.today().isoformat()
        _save_budget([{"type": "expense", "amount": 200, "category": "dining", "date": today}])
        _save_side_hustles([{"id": 1, "idea": "consulting", "status": "active", "last_updated": today}])
        with patch("agents.finance_agent.handler.search", return_value=[]):
            with patch("agents.finance_agent.handler.chat", return_value="full review"):
                result = _finance_review("full review")
        assert result == "full review"


# ── _update_profile ───────────────────────────────────────────────────────────

class TestUpdateProfile:
    def test_valid_update(self, finance_tmp):
        fact_json = '{"key": "w2_salary", "value": "$220k"}'
        with patch("agents.finance_agent.handler.chat", return_value=fact_json):
            from agents.finance_agent.handler import _update_profile, _load_profile
            result = _update_profile("I got a raise to $220k")
        assert "✅" in result or "updated" in result.lower()
        assert _load_profile()["w2_salary"] == "$220k"

    def test_invalid_json_returns_error(self, finance_tmp):
        with patch("agents.finance_agent.handler.chat", return_value="not json"):
            from agents.finance_agent.handler import _update_profile
            result = _update_profile("something weird")
        assert "⚠️" in result or "Couldn't" in result


# ── _log_budget ───────────────────────────────────────────────────────────────

class TestLogBudget:
    def test_valid_expense(self, finance_tmp):
        parsed_json = '{"type": "expense", "amount": 50, "category": "groceries", "description": "Whole Foods"}'
        with patch("agents.finance_agent.handler.chat", return_value=parsed_json):
            from agents.finance_agent.handler import _log_budget, _load_budget
            result = _log_budget("spent $50 on groceries")
        assert "💸" in result or "expense" in result.lower()
        assert _load_budget()[0]["category"] == "groceries"

    def test_valid_income(self, finance_tmp):
        parsed_json = '{"type": "income", "amount": 5000, "category": "salary", "description": "Paycheck"}'
        with patch("agents.finance_agent.handler.chat", return_value=parsed_json):
            from agents.finance_agent.handler import _log_budget
            result = _log_budget("got paid $5000")
        assert "💰" in result or "income" in result.lower()

    def test_unparseable_returns_warning(self, finance_tmp):
        with patch("agents.finance_agent.handler.chat", return_value='{"type": null}'):
            from agents.finance_agent.handler import _log_budget
            result = _log_budget("blah blah blah")
        assert "⚠️" in result or "Couldn't" in result

    def test_invalid_json_fallback(self, finance_tmp):
        with patch("agents.finance_agent.handler.chat", return_value="not json"):
            from agents.finance_agent.handler import _log_budget
            result = _log_budget("some text")
        assert "⚠️" in result or "Couldn't" in result

    def test_log_budget_markdown_fence(self, finance_tmp):
        parsed = '{"type": "expense", "amount": 30, "category": "dining", "description": "lunch"}'
        fenced = f"```json\n{parsed}\n```"
        with patch("agents.finance_agent.handler.chat", return_value=fenced):
            from agents.finance_agent.handler import _log_budget
            result = _log_budget("had lunch for $30")
        assert "💸" in result or "expense" in result.lower()


# ── Markdown fence stripping in _update_profile ───────────────────────────────

class TestUpdateProfileFence:
    def test_markdown_fenced_response(self, finance_tmp):
        fact = '{"key": "solo_401k", "value": "Opened at Fidelity"}'
        fenced = f"```json\n{fact}\n```"
        with patch("agents.finance_agent.handler.chat", return_value=fenced):
            from agents.finance_agent.handler import _update_profile
            result = _update_profile("I opened a Solo 401k at Fidelity")
        assert "✅" in result or "updated" in result.lower()


# ── Markdown fence in _log_application ───────────────────────────────────────

class TestLogApplicationFence:
    def test_markdown_fenced_response(self, finance_tmp):
        parsed = '{"account_type": "credit_card", "card_or_account_name": "Chase Ink", "issuer_or_bank": "Chase", "date_opened": null, "sign_up_bonus": "90k", "min_spend": "$6000", "spend_deadline_months": null, "annual_fee": "$95", "re_eligibility": "24 months", "notes": ""}'
        fenced = f"```json\n{parsed}\n```"
        with patch("agents.finance_agent.handler.chat", return_value=fenced):
            from agents.finance_agent.handler import _log_application
            result = _log_application("I just opened Chase Ink")
        assert isinstance(result, str)


# ── Reddit digest in _find_bank_bonuses ───────────────────────────────────────

class TestFindBankBonusesWithReddit:
    def test_reddit_posts_with_bank_keywords(self, finance_tmp):
        posts = [
            {"title": "Chase bank bonus $400", "summary": "checking account bonus", "source": "r/churning", "link": "http://x"},
            {"title": "Unrelated post", "summary": "no match here", "source": "r/churning", "link": "http://y"},
        ]
        with patch("agents.finance_agent.handler.search", return_value=[]):
            with patch("agents.finance_agent.handler._fetch_reddit_posts", return_value=posts):
                with patch("agents.finance_agent.handler.chat", return_value="bank results"):
                    from agents.finance_agent.handler import _find_bank_bonuses
                    result = _find_bank_bonuses("bank bonuses")
        assert result == "bank results"

    def test_reddit_posts_for_cc_bonuses(self, finance_tmp):
        posts = [
            {"title": "Amex Gold elevated", "summary": "90k bonus live now", "source": "r/churning", "link": "http://x"},
        ]
        with patch("agents.finance_agent.handler.search", return_value=[]):
            with patch("agents.finance_agent.handler._fetch_reddit_posts", return_value=posts):
                with patch("agents.finance_agent.handler.chat", return_value="cc results"):
                    from agents.finance_agent.handler import _find_cc_bonuses
                    result = _find_cc_bonuses("cc bonuses")
        assert result == "cc results"
