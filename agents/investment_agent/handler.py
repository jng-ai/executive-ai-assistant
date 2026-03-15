"""
Investment Agent — Wall Street-style research and portfolio ideas.

Monitors: undervalued stocks, healthcare AI, earnings surprises, macro trends.
"""

import os
import time
import requests
from anthropic import Anthropic

SYSTEM = """You are Justin Ngai's personal Wall Street research analyst.

Justin's profile:
- Risk tolerance: moderate
- Sectors of interest: healthcare AI, biotechnology, small-cap value
- Style: long-term value with growth catalysts
- Dislikes: pure speculation, meme stocks, highly leveraged companies

When analyzing, provide:
**[Company / Ticker]**
- Thesis: [1-2 sentence investment case]
- Catalyst: [what could drive the move]
- Risk: [main downside]
- Action: BUY / WATCH / PASS
- Urgency: HIGH / MEDIUM / LOW

Keep it concise — Justin reads this on his phone."""

SEARCH_QUERIES = [
    "undervalued healthcare AI stocks 2026 earnings growth",
    "small cap biotech catalyst upcoming FDA approval 2026",
    "hedge fund 13F healthcare technology conviction buys 2026",
    "value stock below book value healthcare sector 2026",
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
        for q in SEARCH_QUERIES[:3]:
            all_results.extend(search(q))
            time.sleep(0.3)

        context = "\n\n".join(
            f"TITLE: {r['title']}\nURL: {r['url']}\nSUMMARY: {r['description']}"
            for r in all_results[:20]
        )
        prompt = f"Identify the top 3 investment opportunities from these signals:\n\n{context}"
    else:
        prompt = message

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=800,
        system=SYSTEM,
        messages=[{"role": "user", "content": prompt}],
    )
    return resp.content[0].text
