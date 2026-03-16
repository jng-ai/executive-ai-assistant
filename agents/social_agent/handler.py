"""
NYC Social & Events Agent — finds free events, networking, and things to do.

Searches: Eventbrite, Meetup, NYC.gov events, startup/finance/healthcare meetups.
Focus: free events, networking, professional development, cultural events.
"""

import os
import time
import datetime
import requests
from core.llm import chat

SYSTEM = """You are Justin Ngai's NYC social and events scout.

Justin's profile:
- Lives in NYC
- Interested in: startup/tech networking, finance/investing meetups,
  healthcare industry events, cultural events, free things to do
- Goal: expand professional network, meet interesting people, enjoy the city
- Prefers: free or low-cost events, weeknight and weekend

When given search results, identify the best 3-5 events and format as:

🗓 *[Event Name]*
📍 [Location / Neighborhood]
🕐 [Date & Time]
💰 [Free / $X]
👥 [Who's it for]
🔗 [Link]

At the end, add a one-line recommendation for which to attend first."""


def _get_this_week_dates() -> tuple[str, str]:
    today = datetime.date.today()
    end = today + datetime.timedelta(days=7)
    return today.strftime("%B %d"), end.strftime("%B %d")


def search(query: str) -> list:
    api_key = os.environ.get("BRAVE_API_KEY", "").strip()
    if not api_key:
        return []
    try:
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            params={"q": query, "count": 6},
            timeout=12,
        )
        resp.raise_for_status()
        return [
            {"title": r.get("title", ""), "url": r.get("url", ""), "description": r.get("description", "")}
            for r in resp.json().get("web", {}).get("results", [])
        ]
    except Exception:
        return []


def handle(message: str = "") -> str:
    msg_lower = message.lower()
    start, end = _get_this_week_dates()

    # Determine event type from message
    if any(w in msg_lower for w in ["startup", "tech", "founder"]):
        focus = "startup tech networking"
    elif any(w in msg_lower for w in ["invest", "finance", "stock", "real estate"]):
        focus = "finance investing networking"
    elif any(w in msg_lower for w in ["health", "medical", "pharma"]):
        focus = "healthcare industry networking"
    elif any(w in msg_lower for w in ["free", "cheap", "low cost"]):
        focus = "free things to do"
    else:
        focus = "professional networking startup finance"

    queries = [
        f"free NYC events {focus} this week {start} 2026",
        f"site:eventbrite.com NYC {focus} free 2026",
        f"site:meetup.com NYC {focus} events this week",
        f"NYC networking events {focus} {start} {end} 2026 free",
    ]

    all_results = []
    for q in queries[:3]:
        all_results.extend(search(q))
        time.sleep(0.3)

    # Deduplicate by URL
    seen, unique = set(), []
    for r in all_results:
        if r["url"] not in seen:
            seen.add(r["url"])
            unique.append(r)

    if not unique:
        return (
            "🗓 *NYC Events*\n\n"
            "No Brave Search key set — can't search live events.\n\n"
            "Add `BRAVE_API_KEY` to your `.env` to enable live event search.\n"
            "Get a free key at brave.com/search/api (2,000 searches/month free)"
        )

    context = "\n\n".join(
        f"TITLE: {r['title']}\nURL: {r['url']}\nSUMMARY: {r['description']}"
        for r in unique[:18]
    )

    prompt = (
        f"Find the best free or low-cost NYC events this week ({start}–{end}) "
        f"from these search results. Focus on {focus}.\n\n{context}"
    )

    return chat(SYSTEM, prompt, max_tokens=600)
