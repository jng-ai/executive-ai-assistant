"""
Podcast Agent — News Sources
Aggregates RSS feeds + Tavily search results for daily podcast generation.
"""

import json
import re
import ssl
import feedparser
from core.search import search, format_results

ssl._create_default_https_context = ssl._create_unverified_context

RSS_FEEDS = {
    "Doctor of Credit":   "https://www.doctorofcredit.com/feed/",
    "FrequentMiler":      "https://www.frequentmiler.com/feed/",
    "One Mile at a Time": "https://onemileatatime.com/feed/",
    "Planet Money":       "https://feeds.npr.org/510289/podcast.xml",
    "Bigger Pockets":     "https://www.biggerpockets.com/blog/feed",
}

SEARCH_QUERIES = [
    "340B drug pricing program news 2026",
    "hospital infusion center operations technology 2026",
    "AI artificial intelligence healthcare scaling 2026",
    "US stock market economy news today",
    "real estate investing mortgage rates 2026",
    "tech AI agents innovation news today",
    "credit card bonus deals today",
]


def _strip_html(text: str) -> str:
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", text).strip()


def fetch_rss() -> dict:
    results = {}
    for name, url in RSS_FEEDS.items():
        try:
            feed = feedparser.parse(url)
            items = []
            for entry in feed.entries[:4]:
                summary = (
                    getattr(entry, "summary", "")
                    or getattr(entry, "description", "")
                    or ""
                )
                items.append({
                    "title": entry.title,
                    "summary": _strip_html(summary)[:500],
                    "link": getattr(entry, "link", ""),
                })
            results[name] = items
        except Exception as e:
            results[name] = []
    return results


def fetch_search() -> dict:
    results = {}
    for query in SEARCH_QUERIES:
        try:
            res = search(query, max_results=4)
            results[query] = format_results(res)
        except Exception:
            results[query] = ""
    return results


def gather_all() -> dict:
    return {
        "rss": fetch_rss(),
        "search": fetch_search(),
    }
