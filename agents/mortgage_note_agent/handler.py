"""
Mortgage Note Agent — performing first lien note deal finder and advisor.
Uses Tavily for live marketplace searches.

Justin's criteria:
- Performing first lien notes ONLY
- UPB under $100,000
- Discount to UPB: 20%+ preferred
- Non-judicial foreclosure states (faster process if needed)
- Sources: Paperstac, NoteXchange, Notes Direct, direct bank/hedge fund sellers

Non-judicial states: TX, GA, FL, NC, TN, AZ, CO, MI, VA, MO, WA, OR, NV,
                    AL, AR, CA, ID, MN, MS, MT, NE, NH, NM, OK, SD, UT, WY
"""

from concurrent.futures import ThreadPoolExecutor, as_completed
from core.llm import chat
from core.search import search, format_results

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
    # Paperstac public listing pages (some are indexed)
    'site:paperstac.com/listings performing first lien note',
    'paperstac.com "performing" "first lien" "UPB" "$" note for sale 2026',
    # NotesDirect — public listings
    'site:notesdirect.com performing first lien note for sale "$"',
    # NoteXchange public listings
    'site:notexchange.com performing note "first lien" "$" for sale',
    # FCI Exchange — public note marketplace
    'site:fciexchange.com performing mortgage note first lien for sale',
    # American Note Buyers / note broker sites
    '"performing first lien" "note for sale" "UPB" "$" (TX OR FL OR GA OR TN OR NC OR AZ OR CO OR VA) 2025 OR 2026',
    # Reddit r/MortgageNotes — real deals posted publicly
    'site:reddit.com/r/MortgageNotes "for sale" "first lien" "UPB" "$" performing',
    # BiggerPockets marketplace
    'site:biggerpockets.com/marketplace "note" "first lien" performing "UPB" "$"',
    # Direct seller signals — hedge funds liquidating notes
    '"performing note" "first lien" "UPB" "$" "asking" (TX OR FL OR GA OR TN OR CO OR NC) seller 2026',
]


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
    """Search marketplaces for deals matching Justin's criteria — parallel searches."""
    all_results = []

    with ThreadPoolExecutor(max_workers=4) as executor:
        futures = {executor.submit(search, q, 5): q for q in SEARCH_QUERIES}
        for future in as_completed(futures):
            try:
                all_results.extend(future.result())
            except Exception:
                pass

    # Deduplicate
    seen, unique = set(), []
    for r in all_results:
        if r["url"] not in seen:
            seen.add(r["url"])
            unique.append(r)

    if not unique:
        return (
            "🔍 *Mortgage Note Scan*\n\n"
            "No Tavily API key set — can't scan live listings.\n\n"
            "Add `TAVILY_API_KEY` to your `.env` (free at app.tavily.com)\n\n"
            "In the meantime:\n"
            "• Underwrite a deal: `underwrite UPB $85k, asking $62k, TX, performing`\n"
            "• Draft seller outreach: `draft email to note seller on Paperstac`\n"
            "• Browse directly: paperstac.com · notesdirect.com · notexchange.com"
        )

    context = format_results(unique[:20])
    state_list = ", ".join(NON_JUDICIAL_STATES)

    prompt = (
        f"Scan these search results for ACTUAL mortgage note listings with real price data.\n\n"
        f"Justin's criteria (strict):\n"
        f"- Performing first lien notes ONLY\n"
        f"- UPB under $100,000\n"
        f"- Purchase price at least 20% below UPB\n"
        f"- Non-judicial states only: {state_list}\n\n"
        f"Search results:\n{context}\n\n"
        f"STRICT RULES:\n"
        f"1. Only include results that show an ACTUAL note for sale with a real dollar UPB or asking price\n"
        f"2. Do NOT mention blogs, forums, articles, educational content, or general websites as 'leads'\n"
        f"3. Do NOT mention BiggerPockets threads, WealthFormula, Facebook groups, or YouTube channels\n"
        f"4. If you see a real listing — format it using your deal template with state, UPB, ask, yield, rating\n"
        f"5. If there are NO real listings with dollar figures in the results, respond ONLY with:\n"
        f"   '🔍 No live listings found today matching your criteria. Marketplaces may require login to view deals. "
        f"   Try going directly to paperstac.com, notesdirect.com, or notexchange.com.'\n"
        f"   Do NOT pad this with generic advice or sources."
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
