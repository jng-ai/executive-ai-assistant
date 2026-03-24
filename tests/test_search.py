"""
Tests for core/search.py
"""

import pytest
from unittest.mock import MagicMock, patch


class TestSearch:
    def test_returns_empty_list_when_no_api_key(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        from core.search import search
        assert search("test query") == []

    def test_returns_empty_list_when_api_key_blank(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "   ")
        from core.search import search
        assert search("test query") == []

    def test_returns_results_with_valid_api_key(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")
        fake_results = [
            {"title": "Doc 1", "url": "http://a.com", "content": "About A"},
            {"title": "Doc 2", "url": "http://b.com", "description": "About B"},
        ]
        mock_client = MagicMock()
        mock_client.search.return_value = {"results": fake_results}

        with patch("tavily.TavilyClient", return_value=mock_client):
            from core.search import search
            results = search("test query", max_results=2)

        assert len(results) == 2
        assert results[0]["title"] == "Doc 1"
        assert results[0]["url"] == "http://a.com"
        assert results[0]["content"] == "About A"
        # Falls back to "description" field when "content" missing
        assert results[1]["content"] == "About B"

    def test_returns_empty_list_on_exception(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")
        with patch("tavily.TavilyClient", side_effect=Exception("API error")):
            from core.search import search
            assert search("query") == []

    def test_max_results_passed_to_client(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")
        mock_client = MagicMock()
        mock_client.search.return_value = {"results": []}

        with patch("tavily.TavilyClient", return_value=mock_client):
            from core.search import search
            search("my query", max_results=10)

        mock_client.search.assert_called_once_with("my query", max_results=10)


class TestFetchPage:
    def test_returns_empty_string_when_no_api_key_and_requests_fails(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        with patch("requests.get", side_effect=Exception("network error")):
            from core.search import fetch_page
            assert fetch_page("http://example.com") == ""

    def test_tavily_extract_returns_content(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")
        mock_client = MagicMock()
        mock_client.extract.return_value = {
            "results": [{"raw_content": "x" * 5000}]
        }
        with patch("tavily.TavilyClient", return_value=mock_client):
            from core.search import fetch_page
            result = fetch_page("http://example.com", max_chars=100)

        assert len(result) == 100

    def test_falls_back_to_requests_when_tavily_empty(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")
        mock_client = MagicMock()
        mock_client.extract.return_value = {"results": []}

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "page content here"

        with patch("tavily.TavilyClient", return_value=mock_client):
            with patch("requests.get", return_value=mock_resp):
                from core.search import fetch_page
                result = fetch_page("http://example.com")

        assert result == "page content here"

    def test_falls_back_to_requests_when_tavily_raises(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")
        mock_client = MagicMock()
        mock_client.extract.side_effect = Exception("extract failed")

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "fallback content"

        with patch("tavily.TavilyClient", return_value=mock_client):
            with patch("requests.get", return_value=mock_resp):
                from core.search import fetch_page
                result = fetch_page("http://example.com")

        assert result == "fallback content"

    def test_requests_non_200_returns_empty(self, monkeypatch):
        monkeypatch.delenv("TAVILY_API_KEY", raising=False)
        mock_resp = MagicMock()
        mock_resp.status_code = 404
        with patch("requests.get", return_value=mock_resp):
            from core.search import fetch_page
            assert fetch_page("http://example.com") == ""

    def test_tavily_result_with_no_raw_content_falls_through(self, monkeypatch):
        monkeypatch.setenv("TAVILY_API_KEY", "test-key")
        mock_client = MagicMock()
        mock_client.extract.return_value = {"results": [{"raw_content": ""}]}

        mock_resp = MagicMock()
        mock_resp.status_code = 200
        mock_resp.text = "requests fallback"

        with patch("tavily.TavilyClient", return_value=mock_client):
            with patch("requests.get", return_value=mock_resp):
                from core.search import fetch_page
                result = fetch_page("http://example.com")

        assert result == "requests fallback"


class TestFormatResults:
    def test_empty_results_returns_empty_string(self):
        from core.search import format_results
        assert format_results([]) == ""

    def test_formats_single_result(self):
        from core.search import format_results
        results = [{"title": "T1", "url": "http://x.com", "content": "C1"}]
        out = format_results(results)
        assert "TITLE: T1" in out
        assert "URL: http://x.com" in out
        assert "SUMMARY: C1" in out

    def test_formats_multiple_results_separated(self):
        from core.search import format_results
        results = [
            {"title": "A", "url": "http://a.com", "content": "ca"},
            {"title": "B", "url": "http://b.com", "content": "cb"},
        ]
        out = format_results(results)
        assert "TITLE: A" in out
        assert "TITLE: B" in out

    def test_truncates_content_to_400_chars(self):
        from core.search import format_results
        long_content = "x" * 1000
        results = [{"title": "T", "url": "http://u.com", "content": long_content}]
        out = format_results(results)
        # Only first 400 chars of content should appear
        assert "x" * 400 in out
        assert "x" * 401 not in out
