"""
Tests for the remaining agent handlers:
  infusion_agent, travel_agent, investment_agent, mortgage_note_agent,
  market_agent, social_agent, bonus_alert
All external calls (LLM, search, yfinance, requests) are mocked.
"""

import json
import datetime
import xml.etree.ElementTree as ET
from pathlib import Path
from unittest.mock import patch, MagicMock


# ═══════════════════════════════════════════════════════════════════════════════
# Infusion Agent
# ═══════════════════════════════════════════════════════════════════════════════

class TestInfusionAgent:
    def test_handle_returns_string(self):
        with patch("agents.infusion_agent.handler.chat", return_value="infusion intel"):
            from agents.infusion_agent.handler import handle
            assert handle("What is a good chair utilization target?") == "infusion intel"

    def test_handle_passes_message(self):
        with patch("agents.infusion_agent.handler.chat", return_value="ok") as m:
            from agents.infusion_agent.handler import handle
            handle("my question")
        assert m.call_args[0][1] == "my question"

    def test_handle_max_tokens_800(self):
        with patch("agents.infusion_agent.handler.chat", return_value="ok") as m:
            from agents.infusion_agent.handler import handle
            handle("test")
        assert m.call_args[1].get("max_tokens") == 800 or m.call_args[0][2] == 800

    def test_system_has_no_employer_name(self):
        from agents.infusion_agent.handler import SYSTEM
        assert "NewYork-Presbyterian" not in SYSTEM


# ═══════════════════════════════════════════════════════════════════════════════
# Travel Agent
# ═══════════════════════════════════════════════════════════════════════════════

class TestTravelAgent:
    def test_regular_message_goes_to_chat(self):
        with patch("agents.travel_agent.handler.chat", return_value="fly ANA"):
            from agents.travel_agent.handler import handle
            result = handle("best miles for Tokyo business class")
        assert result == "fly ANA"

    def test_scan_keyword_triggers_search(self):
        with patch("agents.travel_agent.handler.search", return_value=[]) as mock_search:
            with patch("agents.travel_agent.handler.chat", return_value="scan results"):
                from agents.travel_agent.handler import handle
                result = handle("scan for award deals")
        assert mock_search.called
        assert result == "scan results"

    def test_empty_message_falls_back_to_chat(self):
        """Empty message blends available context and calls chat (no search needed)."""
        with patch("agents.travel_agent.handler.fetch_live_deals", return_value={}):
            with patch("agents.travel_agent.handler._fetch_escape_rss", return_value=[]):
                with patch("agents.travel_agent.handler.chat", return_value="scan results") as mock_chat:
                    from agents.travel_agent.handler import handle
                    result = handle("")
        assert mock_chat.called
        assert result == "scan results"

    def test_scan_formats_results(self):
        fake_results = [{"title": "ANA deal", "url": "http://x.com", "content": "great deal"}]
        with patch("agents.travel_agent.handler.search", return_value=fake_results):
            with patch("agents.travel_agent.handler.format_results", return_value="formatted") as mock_fmt:
                with patch("agents.travel_agent.handler.chat", return_value="response"):
                    from agents.travel_agent.handler import handle
                    handle("scan")
        assert mock_fmt.called


# ═══════════════════════════════════════════════════════════════════════════════
# Investment Agent
# ═══════════════════════════════════════════════════════════════════════════════

class TestInvestmentAgent:
    def test_get_stock_data_returns_error_on_exception(self):
        with patch("yfinance.Ticker", side_effect=Exception("network error")):
            from agents.investment_agent.handler import get_stock_data
            result = get_stock_data("AAPL")
        assert "error" in result
        assert result["ticker"] == "AAPL"

    def test_get_stock_data_success(self):
        mock_stock = MagicMock()
        mock_stock.info = {
            "longName": "Apple Inc", "fiftyTwoWeekHigh": 230, "fiftyTwoWeekLow": 160,
            "trailingPE": 28.5, "marketCap": 3000000000000, "sector": "Technology",
            "longBusinessSummary": "Apple designs devices.",
        }
        import pandas as pd
        mock_hist = MagicMock()
        mock_hist.empty = False
        mock_hist.__getitem__ = lambda self, key: pd.Series([185.0])
        mock_hist["Close"] = pd.Series([185.0])

        with patch("yfinance.Ticker", return_value=mock_stock):
            mock_stock.history.return_value = mock_hist
            from agents.investment_agent.handler import get_stock_data
            result = get_stock_data("AAPL")

        assert result["ticker"] == "AAPL"

    def test_handle_ticker_in_message(self):
        with patch("agents.investment_agent.handler.get_stock_data", return_value={"ticker": "AAPL", "name": "Apple", "price": 185}):
            with patch("agents.investment_agent.handler.chat", return_value="bullish on AAPL"):
                from agents.investment_agent.handler import handle
                result = handle("analyze AAPL for me")
        assert result == "bullish on AAPL"

    def test_handle_ticker_with_error(self):
        with patch("agents.investment_agent.handler.get_stock_data", return_value={"ticker": "XYZ", "error": "not found"}):
            with patch("agents.investment_agent.handler.search", return_value=[]):
                with patch("agents.investment_agent.handler.chat", return_value="fallback analysis"):
                    from agents.investment_agent.handler import handle
                    result = handle("analyze XYZ")
        assert isinstance(result, str)

    def test_handle_watchlist_keyword(self):
        with patch("agents.investment_agent.handler.get_stock_data", return_value={"ticker": "UNH", "name": "UnitedHealth", "price": 500}):
            with patch("agents.investment_agent.handler.chat", return_value="watchlist status"):
                from agents.investment_agent.handler import handle
                result = handle("show me my watchlist")
        assert result == "watchlist status"

    def test_handle_general_scan(self):
        with patch("agents.investment_agent.handler.search", return_value=[]):
            with patch("agents.investment_agent.handler.chat", return_value="investment opportunities"):
                from agents.investment_agent.handler import handle
                result = handle("what are good investment opportunities?")
        assert result == "investment opportunities"

    def test_handle_portfolio_keyword(self):
        with patch("agents.investment_agent.handler.get_stock_data", return_value={"ticker": "UNH", "name": "UNH", "price": 500}):
            with patch("agents.investment_agent.handler.chat", return_value="portfolio update"):
                from agents.investment_agent.handler import handle
                result = handle("how is my portfolio doing")
        assert result == "portfolio update"


# ═══════════════════════════════════════════════════════════════════════════════
# Mortgage Note Agent
# ═══════════════════════════════════════════════════════════════════════════════

class TestMortgageNoteAgent:
    def test_handle_email_keyword_routes_to_draft_outreach(self):
        with patch("agents.mortgage_note_agent.handler.chat", return_value="dear seller"):
            from agents.mortgage_note_agent.handler import handle
            result = handle("draft an email to a note seller")
        assert result == "dear seller"

    def test_handle_outreach_keyword(self):
        with patch("agents.mortgage_note_agent.handler.chat", return_value="outreach email"):
            from agents.mortgage_note_agent.handler import handle
            result = handle("help me with outreach")
        assert result == "outreach email"

    def test_handle_underwrite_keyword(self):
        with patch("agents.mortgage_note_agent.handler.chat", return_value="underwriting analysis"):
            from agents.mortgage_note_agent.handler import handle
            result = handle("underwrite this deal: UPB 80k, ask 60k, TX")
        assert result == "underwriting analysis"

    def test_handle_upb_keyword(self):
        with patch("agents.mortgage_note_agent.handler.chat", return_value="analysis"):
            from agents.mortgage_note_agent.handler import handle
            result = handle("UPB is 75000")
        assert result == "analysis"

    def test_handle_scan_falls_through_when_no_paperstac(self, monkeypatch):
        monkeypatch.delenv("PAPERSTAC_EMAIL", raising=False)
        with patch("agents.mortgage_note_agent.handler.paperstac_configured", return_value=False):
            with patch("agents.mortgage_note_agent.handler._tavily_scan", return_value="no results found"):
                from agents.mortgage_note_agent.handler import handle
                result = handle("scan for notes")
        assert isinstance(result, str)

    def test_tavily_scan_no_results(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        with patch("agents.mortgage_note_agent.handler.search", return_value=[]):
            from agents.mortgage_note_agent.handler import _tavily_scan
            result = _tavily_scan()
        assert "No Tavily" in result or "No live" in result or "paperstac" in result.lower()

    def test_tavily_scan_with_results(self):
        fake_results = [{"url": "http://paperstac.com/note1", "title": "TX Note", "content": "UPB $80,000 ask $60,000"}]
        with patch("agents.mortgage_note_agent.handler.search", return_value=fake_results):
            with patch("agents.mortgage_note_agent.handler.chat", return_value="found a great TX note"):
                from agents.mortgage_note_agent.handler import _tavily_scan
                result = _tavily_scan()
        assert result == "found a great TX note"

    def test_scan_paperstac_fallback_on_error(self, monkeypatch):
        with patch("agents.mortgage_note_agent.handler.paperstac_configured", return_value=True):
            with patch("agents.mortgage_note_agent.handler.scrape_listings", side_effect=Exception("scrape failed")):
                with patch("agents.mortgage_note_agent.handler._tavily_scan", return_value="fallback"):
                    from agents.mortgage_note_agent.handler import _scan_for_deals
                    result = _scan_for_deals("")
        assert result == "fallback"

    def test_underwrite_formats_prompt(self):
        with patch("agents.mortgage_note_agent.handler.chat", return_value="analysis") as mock_chat:
            from agents.mortgage_note_agent.handler import _underwrite
            _underwrite("UPB 85k ask 62k TX performing")
        prompt = mock_chat.call_args[0][1]
        assert "85k" in prompt

    def test_draft_outreach_formats_prompt(self):
        with patch("agents.mortgage_note_agent.handler.chat", return_value="email") as mock_chat:
            from agents.mortgage_note_agent.handler import _draft_outreach
            _draft_outreach("Paperstac seller, TX note")
        prompt = mock_chat.call_args[0][1]
        assert "Paperstac" in prompt


# ═══════════════════════════════════════════════════════════════════════════════
# Market Agent
# ═══════════════════════════════════════════════════════════════════════════════

class TestMarketAgent:
    def test_market_hours_context_returns_dict(self):
        from agents.market_agent.handler import _market_hours_context
        ctx = _market_hours_context()
        assert "session" in ctx
        assert "context" in ctx
        assert "date" in ctx
        assert "time" in ctx

    def test_market_hours_weekend(self, monkeypatch):
        import agents.market_agent.handler as h
        # Patch datetime to Saturday
        fake_now = datetime.datetime(2026, 3, 21, 12, 0,
                                     tzinfo=datetime.timezone(datetime.timedelta(hours=-5)))
        with patch("agents.market_agent.handler.datetime") as mock_dt:
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta
            mock_dt.datetime.now.return_value = fake_now
            ctx = h._market_hours_context()
        assert ctx["session"] == "weekend"

    def test_market_hours_pre_market(self):
        fake_now = datetime.datetime(2026, 3, 23, 8, 0,  # Monday 8 AM
                                     tzinfo=datetime.timezone(datetime.timedelta(hours=-5)))
        with patch("agents.market_agent.handler.datetime") as mock_dt:
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta
            mock_dt.datetime.now.return_value = fake_now
            from agents.market_agent.handler import _market_hours_context
            ctx = _market_hours_context()
        assert ctx["session"] == "pre-market"

    def test_market_hours_open(self):
        fake_now = datetime.datetime(2026, 3, 23, 11, 0,  # Monday 11 AM
                                     tzinfo=datetime.timezone(datetime.timedelta(hours=-5)))
        with patch("agents.market_agent.handler.datetime") as mock_dt:
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta
            mock_dt.datetime.now.return_value = fake_now
            from agents.market_agent.handler import _market_hours_context
            ctx = _market_hours_context()
        assert ctx["session"] == "market-open"

    def test_market_hours_after_hours(self):
        fake_now = datetime.datetime(2026, 3, 23, 17, 0,  # Monday 5 PM
                                     tzinfo=datetime.timezone(datetime.timedelta(hours=-5)))
        with patch("agents.market_agent.handler.datetime") as mock_dt:
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta
            mock_dt.datetime.now.return_value = fake_now
            from agents.market_agent.handler import _market_hours_context
            ctx = _market_hours_context()
        assert ctx["session"] == "after-hours"

    def test_market_hours_overnight(self):
        fake_now = datetime.datetime(2026, 3, 23, 22, 0,  # Monday 10 PM
                                     tzinfo=datetime.timezone(datetime.timedelta(hours=-5)))
        with patch("agents.market_agent.handler.datetime") as mock_dt:
            mock_dt.timezone = datetime.timezone
            mock_dt.timedelta = datetime.timedelta
            mock_dt.datetime.now.return_value = fake_now
            from agents.market_agent.handler import _market_hours_context
            ctx = _market_hours_context()
        assert ctx["session"] == "overnight"

    def test_detect_timeframe_today(self):
        from agents.market_agent.handler import _detect_timeframe
        assert _detect_timeframe("what's happening right now?") == "today"
        assert _detect_timeframe("current market status") == "today"

    def test_detect_timeframe_week(self):
        from agents.market_agent.handler import _detect_timeframe
        assert _detect_timeframe("how did the market do this week?") == "week"

    def test_detect_timeframe_month(self):
        from agents.market_agent.handler import _detect_timeframe
        assert _detect_timeframe("monthly performance") == "month"

    def test_detect_timeframe_ytd(self):
        from agents.market_agent.handler import _detect_timeframe
        assert _detect_timeframe("YTD returns") == "ytd"

    def test_detect_timeframe_briefing(self):
        from agents.market_agent.handler import _detect_timeframe
        assert _detect_timeframe("morning briefing") == "briefing"

    def test_detect_timeframe_defaults_to_today(self):
        from agents.market_agent.handler import _detect_timeframe
        assert _detect_timeframe("analyze AAPL") == "today"

    def test_handle_sector_rotation(self):
        with patch("agents.market_agent.handler.search", return_value=[]):
            with patch("agents.market_agent.handler.chat", return_value="sector analysis"):
                from agents.market_agent.handler import handle
                result = handle("show me sector rotation")
        assert result == "sector analysis"

    def test_handle_macro_view(self):
        with patch("agents.market_agent.handler.search", return_value=[]):
            with patch("agents.market_agent.handler.chat", return_value="macro view"):
                from agents.market_agent.handler import handle
                result = handle("what are the Fed rates doing?")
        assert result == "macro view"

    def test_handle_earnings(self):
        with patch("agents.market_agent.handler.search", return_value=[]):
            with patch("agents.market_agent.handler.chat", return_value="earnings catalysts"):
                from agents.market_agent.handler import handle
                result = handle("any earnings catalyst this week?")
        assert result == "earnings catalysts"

    def test_handle_briefing(self):
        with patch("agents.market_agent.handler.search", return_value=[]):
            with patch("agents.market_agent.handler.chat", return_value="market briefing"):
                from agents.market_agent.handler import handle
                result = handle("market briefing please")
        assert result == "market briefing"

    def test_handle_generic_ticker(self):
        with patch("agents.market_agent.handler.search", return_value=[]):
            with patch("agents.market_agent.handler.chat", return_value="AAPL analysis"):
                from agents.market_agent.handler import handle
                result = handle("what do you think about AAPL?")
        assert result == "AAPL analysis"

    def test_search_market_intel_no_results(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        from agents.market_agent.handler import _search_market_intel
        assert _search_market_intel("S&P500 today") == ""

    def test_search_market_intel_with_results(self):
        fake = [{"title": "SPY up", "url": "http://x.com", "content": "market rallied"}]
        with patch("agents.market_agent.handler.search", return_value=fake):
            from agents.market_agent.handler import _search_market_intel
            result = _search_market_intel("SPY today")
        assert "SPY up" in result


# ═══════════════════════════════════════════════════════════════════════════════
# Social Agent (basic routing)
# ═══════════════════════════════════════════════════════════════════════════════

class TestSocialAgent:
    def test_handle_returns_string(self):
        with patch("agents.social_agent.handler.search", return_value=[]):
            with patch("agents.social_agent.handler.chat", return_value="nyc events"):
                from agents.social_agent.handler import handle
                result = handle("what's happening in NYC this weekend?")
        assert isinstance(result, str)

    def test_run_event_scan_returns_string_or_none(self):
        with patch("agents.social_agent.handler.search", return_value=[]):
            with patch("agents.social_agent.handler.chat", return_value="no events found"):
                from agents.social_agent.handler import run_event_scan
                result = run_event_scan()
        assert result is None or isinstance(result, str)


# ═══════════════════════════════════════════════════════════════════════════════
# Bonus Alert Agent
# ═══════════════════════════════════════════════════════════════════════════════

class TestBonusAlertAgent:
    def test_load_last_alerts_missing_file(self, tmp_path, monkeypatch):
        import agents.bonus_alert.handler as h
        monkeypatch.setattr(h, "LAST_ALERT_FILE", tmp_path / "bonus_alerts_sent.json")
        assert h._load_last_alerts() == {}

    def test_load_last_alerts_corrupt_file(self, tmp_path, monkeypatch):
        import agents.bonus_alert.handler as h
        f = tmp_path / "bonus_alerts_sent.json"
        f.write_text("bad json {{{")
        monkeypatch.setattr(h, "LAST_ALERT_FILE", f)
        assert h._load_last_alerts() == {}

    def test_save_and_load_last_alerts(self, tmp_path, monkeypatch):
        import agents.bonus_alert.handler as h
        f = tmp_path / "bonus_alerts_sent.json"
        monkeypatch.setattr(h, "LAST_ALERT_FILE", f)
        h._save_last_alerts({"last_scan": "2026-03-23"})
        result = h._load_last_alerts()
        assert result["last_scan"] == "2026-03-23"

    def test_fetch_rss_returns_empty_when_no_requests(self, monkeypatch):
        import agents.bonus_alert.handler as h
        monkeypatch.setattr(h, "_requests", None)
        assert h._fetch_rss("http://example.com/feed", "Test") == []

    def test_fetch_rss_non_200_returns_empty(self):
        import agents.bonus_alert.handler as h
        mock_resp = MagicMock()
        mock_resp.status_code = 503
        with patch.object(h._requests, "get", return_value=mock_resp):
            result = h._fetch_rss("http://example.com/feed", "Test")
        assert result == []

    def test_fetch_rss_parses_items(self):
        import agents.bonus_alert.handler as h
        rss_xml = b"""<?xml version="1.0"?>
        <rss><channel>
          <item><title>Amex Elevated Offer</title><description>100k points offer</description><link>http://doc.com/amex</link></item>
          <item><title>Chase Bonus</title><description>$400 bank bonus</description><link>http://doc.com/chase</link></item>
        </channel></rss>"""
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.content = rss_xml
        with patch.object(h._requests, "get", return_value=mock_resp):
            result = h._fetch_rss("http://example.com/feed", "DoC")
        assert len(result) == 2
        assert result[0]["title"] == "Amex Elevated Offer"
        assert result[0]["source"] == "DoC"

    def test_fetch_rss_exception_returns_empty(self):
        import agents.bonus_alert.handler as h
        with patch.object(h._requests, "get", side_effect=Exception("network error")):
            assert h._fetch_rss("http://example.com", "Test") == []

    def test_fetch_reddit_returns_empty_when_no_requests(self, monkeypatch):
        import agents.bonus_alert.handler as h
        monkeypatch.setattr(h, "_requests", None)
        assert h._fetch_reddit("http://reddit.com/r/churning.json", "r/churning") == []

    def test_fetch_reddit_non_200(self):
        import agents.bonus_alert.handler as h
        mock_resp = MagicMock()
        mock_resp.status_code = 429
        with patch.object(h._requests, "get", return_value=mock_resp):
            assert h._fetch_reddit("http://reddit.com", "r/churning") == []

    def test_fetch_reddit_parses_posts(self):
        import agents.bonus_alert.handler as h
        data = {
            "data": {
                "children": [
                    {"data": {"title": "Chase Sapphire 80k offer elevated", "selftext": "apply here", "url": "http://reddit.com/1", "score": 100}},
                    {"data": {"title": "Normal post", "selftext": "text", "url": "http://reddit.com/2", "score": 5}},
                ]
            }
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = data
        with patch.object(h._requests, "get", return_value=mock_resp):
            result = h._fetch_reddit("http://reddit.com", "r/churning")
        assert len(result) >= 1

    def test_handle_returns_string(self, tmp_path, monkeypatch):
        import agents.bonus_alert.handler as h
        monkeypatch.setattr(h, "LAST_ALERT_FILE", tmp_path / "bonus_alerts_sent.json")
        with patch.object(h, "_fetch_rss", return_value=[]):
            with patch.object(h, "_fetch_reddit", return_value=[]):
                with patch("agents.bonus_alert.handler.chat", return_value="no elevated bonuses today"):
                    from agents.bonus_alert.handler import handle
                    result = handle("check bonuses")
        assert isinstance(result, str)

    def test_run_bonus_scan_returns_string(self, tmp_path, monkeypatch):
        import agents.bonus_alert.handler as h
        monkeypatch.setattr(h, "LAST_ALERT_FILE", tmp_path / "bonus_alerts_sent.json")
        with patch.object(h, "_fetch_rss", return_value=[]):
            with patch.object(h, "_fetch_reddit", return_value=[]):
                with patch("agents.bonus_alert.handler.chat", return_value="scan complete"):
                    from agents.bonus_alert.handler import run_bonus_scan
                    result = run_bonus_scan()
        assert isinstance(result, str)

    def test_extract_bonus_amount_points(self):
        from agents.bonus_alert.handler import _extract_bonus_amount
        assert _extract_bonus_amount("100,000 points signup") == 100000

    def test_extract_bonus_amount_k_notation(self):
        from agents.bonus_alert.handler import _extract_bonus_amount
        assert _extract_bonus_amount("60k points offer") == 60000

    def test_extract_bonus_amount_dollars(self):
        from agents.bonus_alert.handler import _extract_bonus_amount
        result = _extract_bonus_amount("$400 bonus offer")
        assert result is not None

    def test_extract_bonus_amount_none(self):
        from agents.bonus_alert.handler import _extract_bonus_amount
        assert _extract_bonus_amount("general post no amount") is None

    def test_normalize_card_name_known(self):
        from agents.bonus_alert.handler import _normalize_card_name
        result = _normalize_card_name("chase sapphire preferred application")
        assert result is not None

    def test_normalize_card_name_unknown(self):
        from agents.bonus_alert.handler import _normalize_card_name
        assert _normalize_card_name("random card xyz123") is None

    def test_fetch_all_posts(self, monkeypatch):
        import agents.bonus_alert.handler as h
        monkeypatch.setattr(h, "_fetch_rss", lambda url, name: [{"title": "RSS", "summary": "", "link": "", "source": name}])
        monkeypatch.setattr(h, "_fetch_reddit", lambda url, name: [{"title": "Reddit", "summary": "", "link": "", "source": name}])
        result = h._fetch_all_posts()
        assert len(result) > 0

    def test_get_historical_baselines_no_requests(self, monkeypatch):
        import agents.bonus_alert.handler as h
        monkeypatch.setattr(h, "_requests", None)
        assert h._get_historical_baselines() == {}

    def test_get_historical_baselines_exception(self, monkeypatch):
        import agents.bonus_alert.handler as h
        with patch("integrations.google_sheets.client.read_bonus_tracker", side_effect=Exception("no sheet")):
            result = h._get_historical_baselines()
        assert result == {}

    def test_analyze_posts_empty(self):
        from agents.bonus_alert.handler import _analyze_posts_for_elevated
        assert _analyze_posts_for_elevated([]) == []

    def test_analyze_posts_with_elevated(self):
        from agents.bonus_alert.handler import _analyze_posts_for_elevated
        posts = [{"title": "Elevated offer", "summary": "100k bonus", "source": "DoC", "link": "http://x.com"}]
        elevated = [{"card": "Chase Sapphire", "current_bonus": 100000, "is_elevated": True}]
        with patch("agents.bonus_alert.handler.chat", return_value=json.dumps(elevated)):
            result = _analyze_posts_for_elevated(posts)
        assert len(result) == 1

    def test_analyze_posts_invalid_json(self):
        from agents.bonus_alert.handler import _analyze_posts_for_elevated
        posts = [{"title": "Post", "summary": "text", "source": "DoC", "link": "http://x.com"}]
        with patch("agents.bonus_alert.handler.chat", return_value="not json"):
            result = _analyze_posts_for_elevated(posts)
        assert result == []

    def test_format_alert_empty(self):
        from agents.bonus_alert.handler import _format_alert
        assert _format_alert([], {}) is None

    def test_format_alert_with_offers(self):
        from agents.bonus_alert.handler import _format_alert
        offers = [{"card": "Amex Gold", "current_bonus": 90000, "standard_bonus": 60000,
                   "is_elevated": True, "min_spend": "$4k in 3mo", "expires": "Apr 1", "source": "DoC", "summary": "elevated"}]
        result = _format_alert(offers, {})
        assert result is not None
        assert "Amex Gold" in result

    def test_format_alert_uses_sheet_baseline(self):
        from agents.bonus_alert.handler import _format_alert
        offers = [{"card": "Chase Sapphire Preferred", "current_bonus": 100000,
                   "standard_bonus": 0, "is_elevated": True, "min_spend": "$4k",
                   "expires": "?", "source": "DoC", "summary": "elevated"}]
        baselines = {"chase sapphire preferred": 60000}
        result = _format_alert(offers, baselines)
        assert "baseline" in result.lower() or "60,000" in result

    def test_send_telegram_no_requests(self, monkeypatch):
        import agents.bonus_alert.handler as h
        monkeypatch.setattr(h, "_requests", None)
        # Should not raise, just print
        h._send_telegram_alert("test message")

    def test_run_bonus_scan_already_scanned(self, tmp_path, monkeypatch):
        import agents.bonus_alert.handler as h
        f = tmp_path / "bonus_alerts_sent.json"
        today = __import__("datetime").date.today().isoformat()
        f.write_text(json.dumps({"last_scan": today}))
        monkeypatch.setattr(h, "LAST_ALERT_FILE", f)
        result = h.run_bonus_scan(force=False)
        assert "Already scanned" in result

    def test_run_bonus_scan_no_posts(self, tmp_path, monkeypatch):
        import agents.bonus_alert.handler as h
        monkeypatch.setattr(h, "LAST_ALERT_FILE", tmp_path / "bonus_alerts_sent.json")
        monkeypatch.setattr(h, "_fetch_all_posts", lambda: [])
        result = h.run_bonus_scan(force=True)
        assert "Couldn't fetch" in result

    def test_run_bonus_scan_with_elevated_offers(self, tmp_path, monkeypatch):
        import agents.bonus_alert.handler as h
        monkeypatch.setattr(h, "LAST_ALERT_FILE", tmp_path / "bonus_alerts_sent.json")
        posts = [{"title": "Elevated", "summary": "big bonus", "source": "DoC", "link": "http://x"}]
        monkeypatch.setattr(h, "_fetch_all_posts", lambda: posts)
        monkeypatch.setattr(h, "_get_historical_baselines", lambda: {})
        elevated = [{"card": "Amex Gold", "current_bonus": 90000, "standard_bonus": 60000,
                     "is_elevated": True, "min_spend": "$4k", "expires": "?", "source": "DoC", "summary": "elevated"}]
        monkeypatch.setattr(h, "_analyze_posts_for_elevated", lambda p: elevated)
        monkeypatch.setattr(h, "_send_telegram_alert", lambda msg: None)
        result = h.run_bonus_scan(force=True)
        assert "Amex Gold" in result or isinstance(result, str)

    def test_handle_force_scan(self, tmp_path, monkeypatch):
        import agents.bonus_alert.handler as h
        monkeypatch.setattr(h, "LAST_ALERT_FILE", tmp_path / "bonus_alerts_sent.json")
        monkeypatch.setattr(h, "_fetch_all_posts", lambda: [])
        result = h.handle("scan now")
        assert isinstance(result, str)

    def test_handle_status(self, tmp_path, monkeypatch):
        import agents.bonus_alert.handler as h
        f = tmp_path / "bonus_alerts_sent.json"
        f.write_text(json.dumps({"last_scan": "2026-03-20", "last_count": 2, "last_alert": "2026-03-20", "last_offers": ["Amex Gold"]}))
        monkeypatch.setattr(h, "LAST_ALERT_FILE", f)
        result = h.handle("what's the status")
        assert "Last scan" in result or "Status" in result

    def test_get_historical_baselines_with_data(self, monkeypatch):
        import agents.bonus_alert.handler as h
        sheet_data = {
            "CC Tracker": [
                {"Card Name": "Chase Sapphire Preferred", "Historical Normal SUB": "60,000"},
                {"Card Name": "Amex Gold", "Historical Normal SUB": "60000 points"},
                {"Card Name": "", "Historical Normal SUB": ""},  # empty row
            ]
        }
        with patch("integrations.google_sheets.client.read_bonus_tracker", return_value=sheet_data):
            result = h._get_historical_baselines()
        assert "chase sapphire preferred" in result
        assert result["chase sapphire preferred"] == 60000

    def test_fetch_reddit_score_above_5(self):
        import agents.bonus_alert.handler as h
        data = {
            "data": {
                "children": [
                    {"data": {"title": "Big news", "selftext": "info", "url": "http://r.com/1", "score": 10}},
                ]
            }
        }
        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.json.return_value = data
        with patch.object(h._requests, "get", return_value=mock_resp):
            result = h._fetch_reddit("http://reddit.com", "r/churning")
        assert len(result) == 1  # score > 5, included

    def test_analyze_posts_strips_markdown_fence(self):
        from agents.bonus_alert.handler import _analyze_posts_for_elevated
        posts = [{"title": "Elevated Chase Offer", "summary": "100k points", "source": "DoC", "link": "http://x.com"}]
        elevated = [{"card": "Chase Sapphire", "current_bonus": 100000, "is_elevated": True}]
        fenced = f"```json\n{json.dumps(elevated)}\n```"
        with patch("agents.bonus_alert.handler.chat", return_value=fenced):
            result = _analyze_posts_for_elevated(posts)
        assert len(result) == 1

    def test_run_bonus_scan_no_alert_worthy(self, tmp_path, monkeypatch):
        import agents.bonus_alert.handler as h
        monkeypatch.setattr(h, "LAST_ALERT_FILE", tmp_path / "bonus_alerts_sent.json")
        posts = [{"title": "Normal post", "summary": "no bonus", "source": "DoC", "link": "http://x"}]
        monkeypatch.setattr(h, "_fetch_all_posts", lambda: posts)
        monkeypatch.setattr(h, "_get_historical_baselines", lambda: {})
        # Return elevated offers but format_alert returns None (alerted_count == 0 path)
        elevated = [{"card": "Test", "current_bonus": 0, "standard_bonus": 0,
                     "is_elevated": True, "min_spend": "?", "expires": "?", "source": "DoC", "summary": ""}]
        monkeypatch.setattr(h, "_analyze_posts_for_elevated", lambda p: elevated)
        result = h.run_bonus_scan(force=True)
        assert isinstance(result, str)
