"""
NYC Social & Events Agent — finds free events, networking, and things to do.

Searches: Eventbrite, Meetup, NYC.gov events, startup/finance/healthcare meetups.
Focus: free events, networking, professional development, cultural events.
Uses Tavily for live search.
"""

import time
import datetime
from core.llm import chat
from core.search import search, format_results

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
        all_results.extend(search(q, max_results=6))
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
            "No Tavily API key set — can't search live events.\n\n"
            "Add `TAVILY_API_KEY` to your `.env` to enable live event search.\n"
            "Get a free key at app.tavily.com (1,000 searches/month free)"
        )

    context = format_results(unique[:18])

    prompt = (
        f"Find the best free or low-cost NYC events this week ({start}–{end}) "
        f"from these search results. Focus on {focus}.\n\n{context}"
    )

    return chat(SYSTEM, prompt, max_tokens=600)
