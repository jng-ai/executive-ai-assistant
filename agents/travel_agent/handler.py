"""
Travel Hacker Agent — award flight alerts and miles optimization.

Justin's focus:
- Business class to Asia (Tokyo, Bangkok, Singapore)
- Best redemption programs: Alaska Mileage Plan, AAdvantage, Chase UR
- Airlines: ANA, Singapore, Qatar, Cathay
"""

import os
import requests
from anthropic import Anthropic

SYSTEM = """You are Justin Ngai's personal travel hacker and award flight advisor.

Justin's profile:
- Base: New York City (JFK/EWR/LGA)
- Goals: Business class to Asia (Japan, Thailand, Singapore, Hong Kong)
- Preferred programs: Alaska Mileage Plan, AAdvantage, Chase Ultimate Rewards
- Preferred airlines: ANA, Singapore Airlines, Cathay Pacific, Qatar Airways
- Budget: points/miles only for flights, open to cash hotels

When advising, include:
- Program to use and miles required
- Transfer partners if relevant
- Typical availability windows
- Tips for finding award space
- Any current transfer bonuses

Keep it actionable and phone-friendly."""

SEARCH_QUERIES = [
    "Alaska Mileage Plan ANA business class award availability 2026",
    "credit card transfer bonus points miles Asia business class 2026",
    "award flight NYC Tokyo business class miles redemption 2026",
    "Singapore Airlines business class award space tips 2026",
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
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    if "scan" in message.lower() or message.strip() == "":
        all_results = []
        for q in SEARCH_QUERIES[:2]:
            all_results.extend(search(q))

        context = "\n\n".join(
            f"TITLE: {r['title']}\nURL: {r['url']}\nSUMMARY: {r['description']}"
            for r in all_results[:15]
        )
        prompt = f"What are the best award travel opportunities and tips right now?\n\n{context}"
    else:
        prompt = message

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text
