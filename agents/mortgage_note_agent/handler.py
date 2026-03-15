"""
Mortgage Note Agent — scans for discounted performing notes.

Justin's criteria:
- Performing first lien
- UPB < $200k
- Discount > 20%
"""

import os
import time
import requests
from core.llm import chat

SYSTEM = """You are Justin Ngai's mortgage note deal analyst.

Justin's criteria:
- Performing first lien notes only
- UPB under $200,000
- Discount to UPB greater than 20%
- Estimated yield target > 10%

When given search results, identify real deals or signals and format as:
**[Source / Platform]**
- UPB: $X
- Price: $X (X% discount)
- Estimated yield: X%
- Note type: performing/non-performing
- Lien position: first/second
- Outreach: [how to contact]
- Link: [URL]

Rate each: HIGH / MEDIUM / LOW opportunity."""

SEARCH_QUERIES = [
    "performing mortgage notes for sale first lien 2026",
    "discounted mortgage notes performing first lien under 200k",
    "mortgage note marketplace investor performing",
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


def handle(message: str = "scan") -> str:
    if "scan" in message.lower() or message.strip() == "":
        all_results = []
        for q in SEARCH_QUERIES:
            all_results.extend(search(q))
            time.sleep(0.3)
        context = "\n\n".join(
            f"TITLE: {r['title']}\nURL: {r['url']}\nSUMMARY: {r['description']}"
            for r in all_results[:20]
        )
        prompt = f"Analyze these search results for mortgage note deal opportunities:\n\n{context}" if context else "Explain what types of mortgage note deals Justin should look for and where to find them."
    else:
        prompt = message

    return chat(SYSTEM, prompt, max_tokens=800)
