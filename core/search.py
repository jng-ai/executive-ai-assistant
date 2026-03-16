"""
Search helper — uses Tavily (free tier: 1,000 searches/month).
Get your free API key at: app.tavily.com

All agents use this instead of calling search APIs directly.
"""

import os


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


def format_results(results: list[dict]) -> str:
    """Format search results into a string for the LLM."""
    if not results:
        return ""
    return "\n\n".join(
        f"TITLE: {r['title']}\nURL: {r['url']}\nSUMMARY: {r['content'][:300]}"
        for r in results
    )
