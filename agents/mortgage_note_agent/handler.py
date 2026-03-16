"""
Mortgage Note Agent — performing first lien note deal finder and advisor.

Justin's criteria:
- Performing first lien notes ONLY
- UPB under $100,000
- Discount to UPB: 20%+ preferred
- Non-judicial foreclosure states (faster process if needed)
- Sources: Paperstac, NoteXchange, Notes Direct, direct bank/hedge fund sellers

Non-judicial states: TX, GA, FL, NC, TN, AZ, CO, MI, VA, MO, WA, OR, NV,
                    AL, AR, CA, ID, MN, MS, MT, NE, NH, NM, OK, SD, UT, WY
"""

import os
import time
import requests
from core.llm import chat

NON_JUDICIAL_STATES = [
    "TX", "GA", "FL", "NC", "TN", "AZ", "CO", "MI", "VA", "MO",
    "WA", "OR", "NV", "AL", "AR", "CA", "ID", "MN", "MS", "MT",
    "NE", "NH", "NM", "OK", "SD", "UT", "WY"
]

SYSTEM = """You are Justin Ngai's mortgage note investment analyst.

Justin's buying criteria (strict):
- Note type: Performing first lien ONLY
- UPB: Under $100,000
- Purchase price: At least 20% discount to UPB (target yield 10%+)
- States: Non-judicial foreclosure states only
  (TX, GA, FL, NC, TN, AZ, CO, MI, VA, MO, WA, OR, NV, AL, AR, CA, ID, MN,
   MS, MT, NE, NH, NM, OK, SD, UT, WY)
- Avoid: judicial states (NY, NJ, IL, OH, PA)

When analyzing deals, format each as:

🏠 *[Property State] | UPB: $X | Ask: $X*
📊 Discount: X% | Est. Yield: ~X%
✅ Type: Performing First Lien
📍 State: [State] — Non-Judicial ✓
👤 Seller: [platform or seller type]
⭐ Rating: STRONG / GOOD / PASS
💬 Notes: [key factors, red flags, or opportunity]
🔗 [Link if available]

For underwriting questions, use these benchmarks:
- Yield = (Annual payment) / Purchase price
- Good yield: 10-15%+ on performing notes
- Ask about: payment history, LTV, property condition, borrower credit
- Red flags: recent missed payments, high LTV, judicial state, 2nd lien

For outreach emails, be professional but direct. Justin is a private investor
buying for his portfolio, not a broker. Keep emails under 150 words."""

SEARCH_QUERIES = [
    "site:paperstac.com performing mortgage notes first lien",
    "performing first lien mortgage notes for sale discount 2026",
    "NoteXchange performing notes first lien under 100k",
    "mortgage notes direct seller performing first lien non-judicial state",
    '"performing note" "first lien" for sale investor 2026 discount',
    "paperstac.com mortgage note listing performing",
    "notes direct mortgage note marketplace performing first lien",
]


def brave_search(query: str, count: int = 6) -> list:
    api_key = os.environ.get("BRAVE_API_KEY", "").strip()
    if not api_key:
        return []
    try:
        resp = requests.get(
            "https://api.search.brave.com/res/v1/web/search",
            headers={"X-Subscription-Token": api_key, "Accept": "application/json"},
            params={"q": query, "count": count},
            timeout=12,
        )
        resp.raise_for_status()
        return [
            {
                "title": r.get("title", ""),
                "url": r.get("url", ""),
                "description": r.get("description", ""),
            }
            for r in resp.json().get("web", {}).get("results", [])
        ]
    except Exception:
        return []


def handle(message: str = "") -> str:
    msg_lower = message.lower().strip()

    # ── Outreach email drafting ───────────────────────────────────────────────
    if any(w in msg_lower for w in ["email", "outreach", "contact", "reach out", "draft", "message"]):
        return _draft_outreach(message)

    # ── Underwriting a specific deal ──────────────────────────────────────────
    if any(w in msg_lower for w in ["upb", "yield", "underwrite", "analyze", "evaluate",
                                     "calculate", "lien", "ltv", "worth it", "good deal"]):
        return _underwrite(message)

    # ── Deal scan ─────────────────────────────────────────────────────────────
    return _scan_for_deals(message)


def _scan_for_deals(message: str) -> str:
    """Search marketplaces for deals matching Justin's criteria."""
    all_results = []

    for q in SEARCH_QUERIES[:5]:
        results = brave_search(q)
        all_results.extend(results)
        time.sleep(0.3)

    # Deduplicate
    seen, unique = set(), []
    for r in all_results:
        if r["url"] not in seen:
            seen.add(r["url"])
            unique.append(r)

    if not unique:
        return (
            "🔍 *Mortgage Note Scan*\n\n"
            "No Brave Search key set — can't scan live listings.\n\n"
            "Add `BRAVE_API_KEY` to your `.env` (free at brave.com/search/api)\n\n"
            "In the meantime I can:\n"
            "• Underwrite a deal: `underwrite UPB $85k, asking $62k, TX, performing`\n"
            "• Draft seller outreach: `draft email to note seller on Paperstac`"
        )

    context = "\n\n".join(
        f"TITLE: {r['title']}\nURL: {r['url']}\nSUMMARY: {r['description']}"
        for r in unique[:20]
    )

    state_list = ", ".join(NON_JUDICIAL_STATES)
    prompt = (
        f"Scan these search results for mortgage note deals matching Justin's criteria:\n"
        f"- Performing first lien only\n"
        f"- UPB under $100,000\n"
        f"- 20%+ discount preferred\n"
        f"- Non-judicial states only: {state_list}\n\n"
        f"Results:\n{context}\n\n"
        f"User request: {message}\n\n"
        f"Identify real deal listings or strong lead sources. Skip generic articles."
    )

    return chat(SYSTEM, prompt, max_tokens=900)


def _underwrite(message: str) -> str:
    """Help evaluate a specific note deal."""
    prompt = (
        f"Justin found a potential note deal. Help him underwrite it.\n\n"
        f"Deal details: {message}\n\n"
        f"Calculate:\n"
        f"1. Discount to UPB (%)\n"
        f"2. Estimated yield (annual payment / purchase price)\n"
        f"3. Does it meet Justin's criteria? (performing 1st lien, UPB<$100k, 20%+ discount, non-judicial)\n"
        f"4. What to verify before buying\n"
        f"5. STRONG / GOOD / PASS rating with reasoning"
    )
    return chat(SYSTEM, prompt, max_tokens=600)


def _draft_outreach(message: str) -> str:
    """Draft a professional outreach email to a note seller."""
    prompt = (
        f"Draft a short professional email from Justin Ngai to a mortgage note seller.\n\n"
        f"Context: {message}\n\n"
        f"Justin is a private investor buying performing first lien notes for his own portfolio. "
        f"He is NOT a broker. Under 150 words. Be direct and credible.\n"
        f"Include: who he is, what he buys (performing 1st liens, UPB<$100k, non-judicial states), "
        f"and a clear call to action.\n"
        f"Format: Subject line, then email body."
    )
    return chat(SYSTEM, prompt, max_tokens=400)
