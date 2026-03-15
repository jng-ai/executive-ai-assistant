"""
Travel Hacker Agent — award flight alerts and miles optimization.
"""

import os
import requests
from core.llm import chat

SYSTEM = """You are Justin Ngai's personal travel hacker and award flight advisor.

Justin's profile:
- Base: New York City (JFK/EWR/LGA)
- Goals: Business class to Asia (Japan, Thailand, Singapore, Hong Kong)
- Preferred programs: Alaska Mileage Plan, AAdvantage, Chase Ultimate Rewards
- Preferred airlines: ANA, Singapore Airlines, Cathay Pacific, Qatar Airways

When advising, include:
- Program to use and miles required
- Transfer partners if relevant
- Tips for finding award space
- Any current transfer bonuses

Keep it actionable and phone-friendly."""

SEARCH_QUERIES = [
    "Alaska Mileage Plan ANA business class award availability 2026",
    "award flight NYC Tokyo business class miles redemption 2026",
]


def search(query: str) -> list:
    api_key = os.environ.get("BRAVE_API_KEY", "").strip()
    if not api_key:
        return []
    try:
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            params={"q": query, "count": 5},
            timeout=12,
        )
        resp.raise_for_status()
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""), "description": r.get("description", "")}
            for r in resp.json().get("web", {}).get("results", [])
        ]
    except Exception:
        return []


def handle(message: str) -> str:
    if "scan" in message.lower() or message.strip() == "":
        all_results = []
        for q in SEARCH_QUERIES:
            all_results.extend(search(q))
        context = "\n\n".join(
            f"TITLE: {r['title']}\nURL: {r['url']}\nSUMMARY: {r['description']}"
            for r in all_results[:15]
        )
        prompt = f"What are the best award travel opportunities right now?\n\n{context}" if context else "What are the best award travel strategies for NYC to Asia business class right now?"
    else:
        prompt = message

    return chat(SYSTEM, prompt, max_tokens=800)
