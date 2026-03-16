"""
Travel Hacker Agent — award flight alerts and miles optimization.
Uses Tavily for live search.
"""

from core.llm import chat
from core.search import search, format_results

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


def handle(message: str) -> str:
    if "scan" in message.lower() or message.strip() == "":
        all_results = []
        for q in SEARCH_QUERIES:
            all_results.extend(search(q, max_results=5))
        context = format_results(all_results[:15])
        prompt = f"What are the best award travel opportunities right now?\n\n{context}" if context else "What are the best award travel strategies for NYC to Asia business class right now?"
    else:
        prompt = message

    return chat(SYSTEM, prompt, max_tokens=800)
