"""
Search helper — uses Tavily (free tier: 1,000 searches/month).
Get your free API key at: app.tavily.com

All agents use this instead of calling search APIs directly.
"""

import logging
import os

logger = logging.getLogger(__name__)


def search(query: str, max_results: int = 5) -> list[dict]:
    """
    Search the web. Returns list of {title, url, content} dicts.
    Falls back gracefully if no API key is set.
    """
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()
    if not api_key:
        return []

    try:
        from tavily import TavilyClient
        client = TavilyClient(api_key=api_key)
        resp = client.search(query, max_results=max_results)
        return [
            {
                "title":   r.get("title", ""),
                "url":     r.get("url", ""),
                "content": r.get("content", r.get("description", "")),
            }
            for r in resp.get("results", [])
        ]
    except Exception as e:
        return []


def fetch_page(url: str, max_chars: int = 3000) -> str:
    """
    Directly extract content from a URL using Tavily's extract endpoint.
    Returns raw page content — useful for crawling event listing pages directly
    rather than relying on search indexes.
    Falls back to requests if Tavily extract fails.
    """
    api_key = os.environ.get("TAVILY_API_KEY", "").strip()

    # Try Tavily extract first
    if api_key:
        try:
            from tavily import TavilyClient
            client = TavilyClient(api_key=api_key)
            resp = client.extract(urls=[url])
            results = resp.get("results", [])
            if results:
                content = results[0].get("raw_content", "")
                if content:
                    return content[:max_chars]
        except Exception:
            pass

    # Fallback: plain HTTP fetch
    try:
        import requests
        headers = {"User-Agent": "Mozilla/5.0 (compatible; EventBot/1.0)"}
        resp = requests.get(url, headers=headers, timeout=8)
        if resp.status_code == 200:
            return resp.text[:max_chars]
    except Exception:
        pass

    return ""


def format_results(results: list[dict]) -> str:
    """Format search results into a string for the LLM."""
    if not results:
        return ""
    return "\n\n".join(
        f"TITLE: {r['title']}\nURL: {r['url']}\nSUMMARY: {r['content'][:400]}"
        for r in results
    )
