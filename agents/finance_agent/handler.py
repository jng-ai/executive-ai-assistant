"""
Personal Finance Agent — tracks budget, finds bank/CC signup bonuses,
monitors eligibility, and syncs to Google Sheets tracker.

Sources searched: Doctor of Credit, Frequent Miler, Danny the Deal Guru,
TPG, direct bank sites.
"""

import json
import datetime
from pathlib import Path
from core.llm import chat
from core.search import search, format_results

# ── Trusted sources ────────────────────────────────────────────────────────────
BONUS_SOURCES = [
    "doctorofcredit.com",
    "frequentmiler.com",
    "dannythedealsguru.com",
    "thepointsguy.com",
    "creditcards.com",
    "nerdwallet.com",
    "chase.com",
    "americanexpress.com",
    "bankofamerica.com",
    "wellsfargo.com",
    "citi.com",
    "discover.com",
    "capitalone.com",
]

SYSTEM = """You are Justin Ngai's personal finance advisor specializing in bank and credit card signup bonuses.

Your job:
1. Find the best current signup bonuses from trusted sources (Doctor of Credit, Frequent Miler, Danny the Deal Guru, TPG)
2. Explain eligibility rules clearly (e.g., Amex once per lifetime, Chase 5/24, Citi 24/48 month rule)
3. Highlight limited-time elevated offers vs standard offers
4. Calculate the real value: bonus value minus annual fee for year 1
5. Flag re-eligibility timelines (when can you apply again?)

Format responses for quick phone scanning:
- Use emojis for quick scanning
- Lead with the headline bonus number
- Always mention: min spend, time window, annual fee (if any), re-eligibility rule
- Flag if it's a limited-time elevated offer vs standard

Be concise — Justin doesn't need lectures, just the key intel."""

BONUS_DATA_FILE = Path(__file__).parent.parent.parent / "data" / "finance_bonuses.json"
BUDGET_FILE = Path(__file__).parent.parent.parent / "data" / "budget_log.json"


def _load_bonuses() -> list:
    BONUS_DATA_FILE.parent.mkdir(exist_ok=True)
    if not BONUS_DATA_FILE.exists():
        return []
    try:
        return json.loads(BONUS_DATA_FILE.read_text())
    except Exception:
        return []


def _save_bonuses(data: list):
    BONUS_DATA_FILE.parent.mkdir(exist_ok=True)
    BONUS_DATA_FILE.write_text(json.dumps(data, indent=2))


def _load_budget() -> list:
    BUDGET_FILE.parent.mkdir(exist_ok=True)
    if not BUDGET_FILE.exists():
        return []
    try:
        return json.loads(BUDGET_FILE.read_text())
    except Exception:
        return []


def _save_budget(data: list):
    BUDGET_FILE.parent.mkdir(exist_ok=True)
    BUDGET_FILE.write_text(json.dumps(data, indent=2))


# ── Intent detection ───────────────────────────────────────────────────────────

PARSE_PROMPT = """Classify this personal finance message. Return JSON only.

Types:
- "bank_bonuses"      : find best bank account signup bonuses/promotions
- "cc_bonuses"        : find best credit card signup bonuses/SUBs
- "eligibility"       : check eligibility or re-eligibility for a specific card/bank
- "log_bonus"         : user is recording a bonus they received or applied for
- "track_bonus"       : user wants to see their bonus tracker / what they're tracking
- "budget_log"        : logging an expense or income
- "budget_summary"    : asking for spending summary or budget overview
- "finance_general"   : general personal finance question

Return:
{"type": "<type>", "query": "<extracted key info>", "card_or_bank": "<name if mentioned or null>"}

Examples:
"best bank bonuses right now" → {"type":"bank_bonuses","query":"best bank account signup bonuses 2026","card_or_bank":null}
"any elevated Chase Sapphire offers?" → {"type":"cc_bonuses","query":"Chase Sapphire Preferred elevated signup bonus 2026","card_or_bank":"Chase Sapphire Preferred"}
"when am I eligible for Amex Platinum again?" → {"type":"eligibility","query":"Amex Platinum re-eligibility rule","card_or_bank":"Amex Platinum"}
"I got the Chase Ink bonus" → {"type":"log_bonus","query":"Chase Ink Business","card_or_bank":"Chase Ink"}
"show me my bonus tracker" → {"type":"track_bonus","query":"","card_or_bank":null}
"spent $200 on groceries" → {"type":"budget_log","query":"groceries $200","card_or_bank":null}
"what did I spend this month" → {"type":"budget_summary","query":"monthly spending summary","card_or_bank":null}"""


def _parse_intent(message: str) -> dict:
    raw = chat(PARSE_PROMPT, message, max_tokens=150)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    try:
        return json.loads(raw)
    except Exception:
        return {"type": "finance_general", "query": message, "card_or_bank": None}


# ── Handlers ───────────────────────────────────────────────────────────────────

def _find_bank_bonuses(query: str) -> str:
    """Search for best bank account signup bonuses."""
    search_query = query or "best bank account signup bonuses high yield promotions 2026"
    results = search(search_query, max_results=5)

    # Also search Doctor of Credit specifically
    doc_results = search(f"site:doctorofcredit.com bank account bonus 2026", max_results=3)
    all_results = results + doc_results

    if not all_results:
        return "⚠️ Search unavailable. Check doctorofcredit.com for latest bank bonuses."

    context = format_results(all_results[:6])
    prompt = f"""Based on these search results, list the TOP 3-5 best bank signup bonuses right now.

For each:
🏦 **[Bank Name]** — $[Bonus Amount]
• Requirement: [min deposit/activity]
• Time window: [X months]
• Annual fee: [none or $X]
• Re-eligible: [rule]
• Source: [site name]
⚡ ELEVATED if it's above the standard offer

Search results:
{context}

Today's date: {datetime.date.today()}"""

    return chat(SYSTEM, prompt, max_tokens=600)


def _find_cc_bonuses(query: str, card_name: str = None) -> str:
    """Search for best credit card signup bonuses."""
    if card_name:
        search_query = f"{card_name} signup bonus welcome offer 2026 elevated offer"
    else:
        search_query = query or "best credit card signup bonuses elevated offers 2026"

    results = search(search_query, max_results=5)
    fm_results = search(f"site:frequentmiler.com credit card bonus 2026", max_results=2)
    doc_results = search(f"site:doctorofcredit.com credit card bonus 2026", max_results=2)
    all_results = results + fm_results + doc_results

    if not all_results:
        return "⚠️ Search unavailable. Check frequentmiler.com and doctorofcredit.com for latest offers."

    context = format_results(all_results[:7])
    prompt = f"""Based on these search results, list the TOP credit card signup bonuses.
{"Focus specifically on: " + card_name if card_name else "List top 3-5 cards across categories."}

For each card:
💳 **[Card Name]** — [Bonus Points/Cash]
• Est. value: ~$[X] (at [X]cpp)
• Min spend: $[X] in [X] months
• Annual fee: $[X] (waived/not waived yr 1)
• Re-eligibility: [rule — e.g., "Amex once per lifetime", "Chase 5/24"]
• Source: [site]
⚡ ELEVATED if above standard offer — expires [date if known]

Include Chase 5/24 status note if relevant.

Search results:
{context}

Today: {datetime.date.today()}"""

    return chat(SYSTEM, prompt, max_tokens=700)


def _check_eligibility(message: str, card_name: str = None) -> str:
    """Check eligibility or re-eligibility for a specific card/bank."""
    query = f"{card_name or ''} credit card eligibility re-eligibility rule churning"
    results = search(query, max_results=4)
    doc_results = search(f"site:doctorofcredit.com {card_name} eligibility", max_results=3)
    all_results = results + doc_results

    context = format_results(all_results[:5]) if all_results else ""
    prompt = f"""User question: {message}
Card/bank in question: {card_name or 'not specified'}

{"Search results:\n" + context if context else ""}

Explain the eligibility rules clearly:
- Who qualifies for the bonus (new cardmember rules, etc.)
- Re-eligibility timeline (e.g., 24 months, 48 months, once per lifetime)
- Any family card restrictions (e.g., Amex card family rule)
- Chase 5/24 applicability if relevant
- Any current elevated offers and when they expire

Keep it concise and phone-friendly."""

    return chat(SYSTEM, prompt, max_tokens=400)


def _log_bonus(message: str, card_name: str = None) -> str:
    """Log a bonus the user received or applied for."""
    bonuses = _load_bonuses()
    today = datetime.date.today().isoformat()

    entry = {
        "id": len(bonuses) + 1,
        "card_or_bank": card_name or message[:60],
        "date_logged": today,
        "status": "received",
        "note": message,
    }
    bonuses.append(entry)
    _save_bonuses(bonuses)

    # Sync to Notion
    try:
        from core.memory import _notion_sync_direct
        _notion_sync_direct("finance_bonuses", entry["card_or_bank"], {
            "Type":          "credit_card" if any(w in message.lower() for w in ["card", "amex", "chase", "citi", "capital"]) else "bank",
            "Date Received": today,
            "Status":        "Received",
            "Notes":         message,
        })
    except Exception:
        pass

    # Sync to Google Sheets
    try:
        from integrations.google_sheets.client import append_bonus_row
        append_bonus_row(entry)
    except Exception:
        pass

    return (
        f"✅ *Bonus logged!*\n"
        f"_{entry['card_or_bank']}_\n"
        f"📅 {today}\n\n"
        f"Tip: track re-eligibility — ask me 'when can I apply for [card] again?'"
    )


def _show_tracker() -> str:
    """Show the user's bonus tracker."""
    bonuses = _load_bonuses()
    if not bonuses:
        return (
            "📋 *Bonus Tracker* — Empty\n\n"
            "Log a bonus with: 'I got the Chase Sapphire bonus'\n"
            "Find new bonuses with: 'best bank bonuses right now'"
        )

    lines = ["📋 *Your Bonus Tracker*\n"]
    for b in bonuses[-10:]:  # show last 10
        status_emoji = {"received": "✅", "applied": "📝", "closed": "🔒"}.get(b.get("status", ""), "•")
        lines.append(f"{status_emoji} *{b['card_or_bank']}* — {b['date_logged']}")

    lines.append(f"\n_{len(bonuses)} total logged_")
    return "\n".join(lines)


def _log_budget(message: str) -> str:
    """Log a budget entry."""
    budget = _load_budget()
    today = datetime.date.today().isoformat()

    # Parse with LLM
    parse_prompt = """Extract expense/income from this message. Return JSON only.
{"type": "expense" or "income", "amount": <number>, "category": "<groceries|dining|transport|shopping|bills|income|other>", "description": "<short desc>"}
If cannot parse: {"type": null}"""

    raw = chat(parse_prompt, message, max_tokens=80)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = {"type": None}

    if not parsed.get("type"):
        return "⚠️ Couldn't parse that expense. Try: 'spent $50 on groceries'"

    entry = {
        "id": len(budget) + 1,
        "type": parsed["type"],
        "amount": parsed.get("amount", 0),
        "category": parsed.get("category", "other"),
        "description": parsed.get("description", message),
        "date": today,
    }
    budget.append(entry)
    _save_budget(budget)

    emoji = "💸" if parsed["type"] == "expense" else "💰"
    return f"{emoji} *{parsed['type'].title()} logged*\n${parsed.get('amount', '?')} — {parsed.get('category', '').title()}\n_{parsed.get('description', '')}_"


def _budget_summary() -> str:
    """Summarize spending this month."""
    budget = _load_budget()
    today = datetime.date.today()
    month_start = today.replace(day=1).isoformat()

    month_entries = [e for e in budget if e.get("date", "") >= month_start]
    if not month_entries:
        return (
            f"📊 *Budget — {today.strftime('%B %Y')}*\n\n"
            "Nothing logged yet. Start with:\n"
            "'spent $50 on groceries'"
        )

    by_category: dict = {}
    total_out = 0
    total_in = 0
    for e in month_entries:
        if e["type"] == "expense":
            cat = e.get("category", "other")
            by_category[cat] = by_category.get(cat, 0) + e.get("amount", 0)
            total_out += e.get("amount", 0)
        else:
            total_in += e.get("amount", 0)

    lines = [f"📊 *Budget — {today.strftime('%B %Y')}*\n"]
    for cat, amt in sorted(by_category.items(), key=lambda x: -x[1]):
        lines.append(f"  • {cat.title()}: *${amt:,.0f}*")
    lines.append(f"\n💸 Total out: *${total_out:,.0f}*")
    if total_in:
        lines.append(f"💰 Total in: *${total_in:,.0f}*")
        lines.append(f"📈 Net: *${total_in - total_out:+,.0f}*")

    return "\n".join(lines)


# ── Main handle ────────────────────────────────────────────────────────────────

def handle(message: str) -> str:
    parsed = _parse_intent(message)
    msg_type = parsed.get("type", "finance_general")
    query = parsed.get("query", message)
    card = parsed.get("card_or_bank")

    if msg_type == "bank_bonuses":
        return _find_bank_bonuses(query)

    elif msg_type == "cc_bonuses":
        return _find_cc_bonuses(query, card)

    elif msg_type == "eligibility":
        return _check_eligibility(message, card)

    elif msg_type == "log_bonus":
        return _log_bonus(message, card)

    elif msg_type == "track_bonus":
        return _show_tracker()

    elif msg_type == "budget_log":
        return _log_budget(message)

    elif msg_type == "budget_summary":
        return _budget_summary()

    else:
        # General finance question
        results = search(query, max_results=4)
        context = format_results(results) if results else ""
        full_prompt = f"Question: {message}\n\n{'Search results:\n' + context if context else ''}"
        return chat(SYSTEM, full_prompt, max_tokens=500)
