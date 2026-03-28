"""
Personal Finance Agent — pocket CFA/CFP for Justin Ngai.

Income mix:
  • W2:     Director of Infusion Services, NewYork-Presbyterian Hospital
  • 1099:   Freelance management consultant, infusion services (other institutions)
  • Rental: Townhouse, Virginia Beach VA (partial ownership)
            Condo, Cliffside Park NJ (full ownership)

Capabilities:
  - CC/bank signup bonuses (DoC, FM, Reddit, NerdWallet, Bankrate, r/churning)
  - Re-eligibility engine (reads Google Sheets CC/Bank Trackers)
  - Application logging → Google Sheets with full field capture
  - Tax strategy: W2 + SE + rental optimization (QBI, Solo 401k, depreciation, S-Corp)
  - Side hustle scanner + idea development (subagent spawner)
  - Holistic financial review
  - Budget tracking
  - Self-improving financial profile
  - Cross-agent collaboration (market intel, travel)
"""

import json
import logging
import datetime
import re
from pathlib import Path
from core.llm import chat
from core.search import search, format_results

logger = logging.getLogger(__name__)

# ── Data files ───────────────────────────────────────────────────────────────
DATA_DIR = Path(__file__).parent.parent.parent / "data"
BONUS_DATA_FILE      = DATA_DIR / "finance_bonuses.json"
BUDGET_FILE          = DATA_DIR / "budget_log.json"
PROFILE_FILE         = DATA_DIR / "financial_profile.json"
SIDE_HUSTLE_FILE     = DATA_DIR / "side_hustle_ideas.json"
INVESTMENT_FLAGS_FILE = DATA_DIR / "finance_investment_flags.json"

# ── Justin's financial context (baseline for every prompt) ──────────────────
JUSTIN_CONTEXT = """
Justin Ngai's Financial Profile:
• W2: Director of Infusion Services — NewYork-Presbyterian Hospital (NYC, high W2 earner)
• 1099: Freelance management consultant — infusion services at other hospitals (SE income)
• Real Estate:
  - Townhouse, Virginia Beach VA — partial ownership (rental income, co-owner)
  - Condo, Cliffside Park NJ — full ownership (rental income)
• Active churner: tracks CC + bank bonuses in Google Sheets
• Evaluating side hustles and passive income streams
• Based in NYC/NJ area; HCOL, high marginal tax rate (federal + NY/NJ state)

Tax situation: W2 + SE income + rental income = complex multi-source filing
Key tax levers: QBI deduction (SE), Solo 401(k)/SEP-IRA, home office, rental depreciation
                (27.5yr), SALT cap ($10k), potential S-Corp election, passive activity rules
"""

SYSTEM = f"""You are Justin Ngai's personal financial board of directors — a coalition of:

• JP Morgan Private Bank Managing Director — macro-aware wealth management, credit strategy, real estate financing, tax-efficient structuring for high-net-worth multi-income professionals
• Jane Street Principal — quantitative risk assessment, systematic allocation, factor-aware portfolio construction, precise expected-value calculations

{JUSTIN_CONTEXT}

Your mandate:
1. ANALYZE — Review financial data with precision. Flag anomalies, trends, drift from targets.
2. SURFACE — Proactively raise what Justin should know, even if he didn't ask.
3. TRANSLATE — Connect macro movements (Fed, rates, sector rotation, credit spreads) to Justin's balance sheet.
4. RECOMMEND — Give concrete, quantified, actionable guidance. State conviction: HIGH / MEDIUM / LOW.
5. PIPELINE — When analysis reveals investment opportunities, flag them explicitly for the investment agent.

Expertise domains:
• CC/bank signup bonuses — Doctor of Credit, Frequent Miler, r/churning depth
• Tax: W2 + SE + rental optimization — QBI, Solo 401k, depreciation, S-Corp, SALT
• Side hustle and passive income for a high-income NYC professional
• Portfolio construction, allocation drift, real estate leverage

Style:
• Board-room directness — lead with the headline insight, no preamble
• Quantify everything: "$X at risk", "X% over budget", "~$X opportunity value"
• Urgency flags: 🔴 ACT NOW  🟡 WATCH  🟢 NOTED
• Use real Origin numbers when available — never estimate what you can measure
• Phone-friendly: bullets, emojis, scannable sections
• For bonuses: min spend, time window, annual fee, re-eligibility rule
• For tax: cite strategy, flag CLEAR WIN / GREY AREA / AGGRESSIVE

When you learn new financial facts about Justin, note them for profile update."""


# ── Trusted sources ─────────────────────────────────────────────────────────
BONUS_SEARCH_SITES = [
    "doctorofcredit.com", "frequentmiler.com", "dannythedealsguru.com",
    "thepointsguy.com", "nerdwallet.com", "bankrate.com", "wallethub.com",
    "creditcards.com", "reddit.com/r/churning", "reddit.com/r/personalfinance",
    "reddit.com/r/creditcards",
]

REDDIT_FINANCE_URLS = [
    ("r/churning",             "https://www.reddit.com/r/churning/search.json?q=elevated+bonus&sort=new&restrict_sr=1&t=week&limit=10"),
    ("r/personalfinance",      "https://www.reddit.com/r/personalfinance/search.json?q=bank+bonus+signup&sort=new&restrict_sr=1&t=week&limit=8"),
    ("r/creditcards",          "https://www.reddit.com/r/CreditCards/search.json?q=elevated+offer+bonus&sort=new&restrict_sr=1&t=week&limit=8"),
    ("r/financialindependence","https://www.reddit.com/r/financialindependence/hot.json?limit=10"),
    ("r/sidehustle",           "https://www.reddit.com/r/sidehustle/hot.json?limit=10"),
    ("r/passive_income",       "https://www.reddit.com/r/passive_income/hot.json?limit=10"),
    ("r/realestateinvesting",  "https://www.reddit.com/r/realestateinvesting/hot.json?limit=8"),
]


# ── Profile helpers ──────────────────────────────────────────────────────────

def _load_profile() -> dict:
    DATA_DIR.mkdir(exist_ok=True)
    if not PROFILE_FILE.exists():
        return {}
    try:
        return json.loads(PROFILE_FILE.read_text())
    except Exception:
        return {}


def _save_profile(data: dict):
    DATA_DIR.mkdir(exist_ok=True)
    PROFILE_FILE.write_text(json.dumps(data, indent=2))


def _profile_context() -> str:
    """Return any stored profile additions as context string."""
    p = _load_profile()
    if not p:
        return ""
    lines = ["\nAdditional saved context:"]
    for k, v in p.items():
        lines.append(f"  • {k}: {v}")
    return "\n".join(lines)


# ── Bonus/budget data helpers ────────────────────────────────────────────────

def _load_bonuses() -> list:
    DATA_DIR.mkdir(exist_ok=True)
    if not BONUS_DATA_FILE.exists():
        return []
    try:
        return json.loads(BONUS_DATA_FILE.read_text())
    except Exception:
        return []


def _save_bonuses(data: list):
    DATA_DIR.mkdir(exist_ok=True)
    BONUS_DATA_FILE.write_text(json.dumps(data, indent=2))


def _load_budget() -> list:
    DATA_DIR.mkdir(exist_ok=True)
    if not BUDGET_FILE.exists():
        return []
    try:
        return json.loads(BUDGET_FILE.read_text())
    except Exception:
        return []


def _save_budget(data: list):
    DATA_DIR.mkdir(exist_ok=True)
    BUDGET_FILE.write_text(json.dumps(data, indent=2))


def _load_side_hustles() -> list:
    DATA_DIR.mkdir(exist_ok=True)
    if not SIDE_HUSTLE_FILE.exists():
        return []
    try:
        return json.loads(SIDE_HUSTLE_FILE.read_text())
    except Exception:
        return []


def _save_side_hustles(data: list):
    DATA_DIR.mkdir(exist_ok=True)
    SIDE_HUSTLE_FILE.write_text(json.dumps(data, indent=2))


# ── Reddit fetch ─────────────────────────────────────────────────────────────

def _fetch_reddit_posts(subreddits: list[str] = None) -> list[dict]:
    """Fetch posts from specified subreddits (defaults to bonus-focused ones)."""
    try:
        import requests as _req
    except ImportError:
        return []

    target = subreddits or [
        "r/churning", "r/personalfinance", "r/creditcards"
    ]
    url_map = dict(REDDIT_FINANCE_URLS)
    posts = []
    headers = {"User-Agent": "personal-finance-bot/1.0 (private use)"}

    for sub in target:
        url = url_map.get(sub)
        if not url:
            continue
        try:
            resp = _req.get(url, timeout=8, headers=headers)
            if resp.status_code != 200:
                continue
            for post in resp.json().get("data", {}).get("children", []):
                d = post.get("data", {})
                title = d.get("title", "")
                text  = d.get("selftext", "")[:500]
                score = d.get("score", 0)
                link  = "https://reddit.com" + d.get("permalink", "")
                if score > 3 or any(w in title.lower() for w in
                        ["bonus", "elevated", "offer", "hustle", "income", "passive"]):
                    posts.append({"title": title, "summary": text,
                                  "link": link, "source": sub, "score": score})
        except Exception:
            continue
    return posts


# ── Intent detection ─────────────────────────────────────────────────────────

PARSE_PROMPT = """Classify this personal finance message. Return JSON only.

Types:
- "bank_bonuses"         : find best bank account signup bonuses
- "cc_bonuses"           : find best credit card signup bonuses/SUBs
- "eligibility"          : check eligibility/re-eligibility for a specific card or bank
- "re_eligibility_check" : show what cards/banks I can apply for now or soon (no specific card)
- "log_application"      : user just opened/applied for a new card or bank account
- "log_bonus"            : user received a bonus or wants to record a bonus earned
- "track_bonus"          : show bonus tracker / what they've logged
- "budget_log"           : logging an expense or income
- "budget_summary"       : spending summary or budget overview
- "tax_strategy"         : tax optimization, deductions, W2+1099+rental strategies
- "side_hustle_scan"     : find side hustle, passive income, or new income ideas
- "side_hustle_develop"  : deep dive or develop a specific side hustle idea
- "finance_review"       : holistic review of financial situation, habits, opportunities
- "update_profile"       : update financial context (new income, property, goal, etc.)
- "finance_general"      : general personal finance question

Return:
{"type": "<type>", "query": "<extracted key info>", "card_or_bank": "<name if mentioned or null>", "idea": "<side hustle idea if mentioned or null>"}

Examples:
"best bank bonuses right now" → {"type":"bank_bonuses","query":"best bank account signup bonuses 2026","card_or_bank":null,"idea":null}
"elevated Chase Sapphire offers?" → {"type":"cc_bonuses","query":"Chase Sapphire Preferred elevated signup bonus 2026","card_or_bank":"Chase Sapphire Preferred","idea":null}
"when am I eligible for Amex Platinum again?" → {"type":"eligibility","query":"Amex Platinum re-eligibility","card_or_bank":"Amex Platinum","idea":null}
"what cards can I apply for soon?" → {"type":"re_eligibility_check","query":"","card_or_bank":null,"idea":null}
"I just opened the Chase Ink Preferred" → {"type":"log_application","query":"Chase Ink Business Preferred","card_or_bank":"Chase Ink Business Preferred","idea":null}
"I got the Amex Gold bonus" → {"type":"log_bonus","query":"Amex Gold","card_or_bank":"Amex Gold","idea":null}
"show my tracker" → {"type":"track_bonus","query":"","card_or_bank":null,"idea":null}
"spent $200 on groceries" → {"type":"budget_log","query":"groceries $200","card_or_bank":null,"idea":null}
"what did I spend this month" → {"type":"budget_summary","query":"","card_or_bank":null,"idea":null}
"how do I reduce my tax bill with 1099 income?" → {"type":"tax_strategy","query":"1099 self-employment tax reduction strategies","card_or_bank":null,"idea":null}
"any good side hustle ideas for a healthcare consultant?" → {"type":"side_hustle_scan","query":"side hustle ideas healthcare consultant director","card_or_bank":null,"idea":null}
"let's develop the consulting course idea" → {"type":"side_hustle_develop","query":"","card_or_bank":null,"idea":"consulting course"}
"review my finances" → {"type":"finance_review","query":"","card_or_bank":null,"idea":null}
"I got a $20k raise" → {"type":"update_profile","query":"salary increase $20k","card_or_bank":null,"idea":null}"""


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
        return {"type": "finance_general", "query": message,
                "card_or_bank": None, "idea": None}


# ── Bonus search helpers ─────────────────────────────────────────────────────

def _find_bank_bonuses(query: str) -> str:
    search_query = query or "best bank account signup bonuses promotions 2026"
    results = search(search_query, max_results=5)
    doc_results = search("site:doctorofcredit.com bank account bonus 2026", max_results=3)
    reddit_posts = _fetch_reddit_posts(["r/churning", "r/personalfinance"])

    all_results = results + doc_results
    context = format_results(all_results[:6]) if all_results else ""

    reddit_digest = ""
    for p in reddit_posts[:5]:
        if any(w in (p["title"] + p["summary"]).lower() for w in ["bank", "checking", "savings", "bonus"]):
            reddit_digest += f"\n[{p['source']}] {p['title']}: {p['summary'][:200]}"

    prompt = f"""Based on these search results and Reddit intel, list the TOP 3-5 best bank signup bonuses right now.

For each:
🏦 **[Bank Name]** — $[Bonus]
• Requirement: [deposit/activity needed]
• Time window: [X months]
• Monthly fee / waiver: [details]
• Early closure penalty: [if any]
• Re-eligible: [how long / ChexSystems notes]
• Source: [site]
⚡ ELEVATED if above historical standard

Search results:
{context}

Reddit intel:
{reddit_digest or "none"}

Today: {datetime.date.today()}"""

    return chat(SYSTEM + _profile_context(), prompt, max_tokens=700)


def _find_cc_bonuses(query: str, card_name: str = None) -> str:
    if card_name:
        search_query = f"{card_name} signup bonus elevated offer 2026"
    else:
        search_query = query or "best credit card signup bonuses elevated offers 2026"

    results     = search(search_query, max_results=5)
    fm_results  = search("site:frequentmiler.com credit card bonus 2026", max_results=2)
    doc_results = search("site:doctorofcredit.com credit card bonus 2026", max_results=2)
    reddit_posts = _fetch_reddit_posts(["r/churning", "r/creditcards"])
    all_results = results + fm_results + doc_results

    context = format_results(all_results[:7]) if all_results else ""

    reddit_digest = ""
    for p in reddit_posts[:6]:
        reddit_digest += f"\n[{p['source']}] {p['title']}: {p['summary'][:200]}"

    focus = f"Focus specifically on: {card_name}" if card_name else "List top 3-5 cards across categories."

    prompt = f"""Based on search results and Reddit, list the best credit card signup bonuses.
{focus}

For each:
💳 **[Card Name]** — [Bonus]
• Est. value: ~$[X] (at [X]cpp)
• Min spend: $[X] in [X] months
• Annual fee: $[X] (yr 1 waived / not waived)
• Re-eligibility: [rule — e.g. "Amex once per lifetime", "Chase 5/24"]
• Source: [site or subreddit]
⚡ ELEVATED — expires [date if known]

Note Chase 5/24 impact if relevant. Flag any Amex NLL (no-lifetime-language) links found on Reddit.

Search results:
{context}

Reddit:
{reddit_digest or "none"}

Today: {datetime.date.today()}"""

    return chat(SYSTEM + _profile_context(), prompt, max_tokens=800)


# ── Re-eligibility engine ────────────────────────────────────────────────────

def _parse_re_eligibility_months(raw: str) -> int | None:
    """Parse re-eligibility string → months. Returns None if lifetime/unparseable."""
    if not raw:
        return None
    raw_l = raw.lower()
    if "lifetime" in raw_l or "once per" in raw_l:
        return None  # None = never again
    # "24 months", "48 months from close", "2 years"
    m = re.search(r"(\d+)\s*(month|mo)", raw_l)
    if m:
        return int(m.group(1))
    m = re.search(r"(\d+)\s*year", raw_l)
    if m:
        return int(m.group(1)) * 12
    return None


def _check_re_eligibility(message: str = "", card_name: str = None) -> str:
    """
    Show all cards/banks from Google Sheets with re-eligibility dates.
    Flags: ELIGIBLE NOW / ELIGIBLE IN <N> DAYS / NOT ELIGIBLE / LIFETIME.
    """
    try:
        from integrations.google_sheets.client import read_bonus_tracker
        data = read_bonus_tracker()
    except Exception:
        data = {}

    today = datetime.date.today()
    window_days = 180  # flag anything eligible within 6 months

    lines_eligible   = []
    lines_soon       = []
    lines_not_yet    = []
    lines_lifetime   = []
    lines_no_rule    = []

    for sheet_name, rows in data.items():
        if not isinstance(rows, list):
            continue
        is_cc = "CC" in sheet_name or "Credit" in sheet_name

        for row in rows:
            if is_cc:
                name         = str(row.get("Card Name", row.get("card_name", ""))).strip()
                date_opened  = str(row.get("Date Opened", row.get("date_opened", ""))).strip()
                re_elig_raw  = str(row.get("Re-Eligibility", row.get("re_eligibility", ""))).strip()
                status       = str(row.get("Card Status", row.get("card_status", ""))).strip()
            else:
                name         = str(row.get("Bank", row.get("bank", ""))).strip()
                date_opened  = str(row.get("Date Opened", row.get("date_opened", ""))).strip()
                re_elig_raw  = str(row.get("Re-Eligibility", row.get("re_eligibility", ""))).strip()
                status       = str(row.get("Status", row.get("status", ""))).strip()

            if not name:
                continue

            # Filter by specific card if requested
            if card_name and card_name.lower() not in name.lower():
                continue

            months = _parse_re_eligibility_months(re_elig_raw)

            # Parse date_opened
            open_date = None
            for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%m/%d/%y", "%B %d, %Y"):
                try:
                    open_date = datetime.datetime.strptime(date_opened, fmt).date()
                    break
                except Exception:
                    continue

            tag = "💳" if is_cc else "🏦"

            if re_elig_raw.lower() in ("", "n/a", "none"):
                lines_no_rule.append(f"{tag} {name} — _no rule saved_")
                continue

            if months is None:
                lines_lifetime.append(f"{tag} {name} — 🚫 Once per lifetime")
                continue

            if open_date:
                eligible_date = open_date + datetime.timedelta(days=months * 30)
                days_until    = (eligible_date - today).days

                if days_until <= 0:
                    lines_eligible.append(f"{tag} **{name}** — ✅ ELIGIBLE NOW _(since {eligible_date})_")
                elif days_until <= window_days:
                    lines_soon.append(f"{tag} **{name}** — ⏰ {days_until}d ({eligible_date})")
                else:
                    lines_not_yet.append(f"{tag} {name} — {eligible_date} ({days_until}d)")
            else:
                lines_no_rule.append(f"{tag} {name} — {re_elig_raw} _(no open date)_")

    if not any([lines_eligible, lines_soon, lines_not_yet, lines_lifetime, lines_no_rule]):
        return (
            "📋 *Re-Eligibility Check*\n\n"
            "No tracker data found. Make sure your Google Sheets webhooks are configured.\n\n"
            "_Tip: ask me 'best bank bonuses' or 'best CC bonuses' to find new offers._"
        )

    out = ["📋 *Re-Eligibility Tracker*\n"]

    if lines_eligible:
        out.append("✅ *ELIGIBLE NOW*")
        out.extend(lines_eligible)
        out.append("")

    if lines_soon:
        out.append(f"⏰ *ELIGIBLE WITHIN {window_days//30} MONTHS*")
        out.extend(lines_soon)
        out.append("")

    if lines_not_yet:
        out.append("🔒 *NOT YET ELIGIBLE*")
        out.extend(lines_not_yet)
        out.append("")

    if lines_lifetime:
        out.append("🚫 *LIFETIME RULE*")
        out.extend(lines_lifetime)
        out.append("")

    if lines_no_rule:
        out.append("❓ *UNKNOWN / NO RULE SAVED*")
        out.extend(lines_no_rule)

    out.append(f"\n_Checked {today}_")
    return "\n".join(out)


def _check_eligibility_specific(message: str, card_name: str = None) -> str:
    """Deep eligibility check for a specific card — searches DoC + Reddit."""
    query = f"{card_name or ''} credit card eligibility re-eligibility churning rule"
    results     = search(query, max_results=4)
    doc_results = search(f"site:doctorofcredit.com {card_name} eligibility", max_results=3)
    all_results = results + doc_results

    context = format_results(all_results[:5]) if all_results else ""
    search_section = ("Search results:\n" + context) if context else ""

    prompt = f"""User question: {message}
Card/bank: {card_name or 'not specified'}

{search_section}

Answer:
- New cardmember / bonus eligibility rules
- Re-eligibility timeline (24 months, 48 months, once per lifetime, etc.)
- Family card restrictions (Amex card family rule, Chase product families)
- Chase 5/24 applicability
- Any NLL (no-lifetime-language) loopholes currently circulating on r/churning
- Current elevated offers and expiry

Concise, phone-friendly."""

    return chat(SYSTEM + _profile_context(), prompt, max_tokens=450)


# ── Application logging ──────────────────────────────────────────────────────

LOG_APP_PROMPT = """Extract details from this application/opening message. Return JSON only.

User is logging a new credit card or bank account they just opened.

Return:
{
  "account_type": "credit_card" | "bank",
  "issuer_or_bank": "<bank/issuer name>",
  "card_or_account_name": "<full card or account name>",
  "date_opened": "<YYYY-MM-DD or null>",
  "sign_up_bonus": "<bonus description or null>",
  "bonus_amount": "<number or null>",
  "min_spend": "<spend requirement or null>",
  "spend_deadline_months": <number or null>,
  "annual_fee": "<fee or null>",
  "re_eligibility": "<rule if mentioned or null>",
  "notes": "<anything else>",
  "apy": "<APY if bank account>",
  "min_deposit": "<min deposit if bank>",
  "days_to_qualify": "<days to qualify if bank>"
}"""


def _log_application(message: str, card_name: str = None) -> str:
    """Log a new CC/bank application with full details to Google Sheets."""
    today = datetime.date.today().isoformat()

    raw = chat(LOG_APP_PROMPT, message, max_tokens=300)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        parsed = json.loads(raw)
    except Exception:
        parsed = {
            "account_type": "credit_card",
            "card_or_account_name": card_name or message[:60],
            "issuer_or_bank": "",
        }

    parsed.setdefault("date_opened", today)
    parsed.setdefault("card_status", "Active")

    acct_type = parsed.get("account_type", "credit_card")
    name      = parsed.get("card_or_account_name") or card_name or message[:60]
    issuer    = parsed.get("issuer_or_bank", "")

    # Calculate spend deadline date
    spend_dl = ""
    months = parsed.get("spend_deadline_months")
    if months:
        try:
            open_dt = datetime.date.fromisoformat(parsed["date_opened"])
            spend_dl = (open_dt + datetime.timedelta(days=int(months) * 30)).isoformat()
        except Exception:
            pass

    # Build sheet entry
    if acct_type == "credit_card":
        entry = {
            "bank_issuer":          issuer,
            "card_name":            name,
            "date_opened":          parsed.get("date_opened", today),
            "annual_fee":           parsed.get("annual_fee", ""),
            "annual_fee_date":      "",
            "sign_up_bonus":        parsed.get("sign_up_bonus", ""),
            "min_spend":            parsed.get("min_spend", ""),
            "spend_deadline":       spend_dl,
            "sub_status":           "In Progress",
            "sub_earned_date":      "",
            "card_status":          "Active",
            "action_by_date":       spend_dl,
            "downgrade_to":         "",
            "re_eligibility":       parsed.get("re_eligibility", ""),
            "historical_normal_sub": parsed.get("sign_up_bonus", ""),
            "notes":                parsed.get("notes", message[:200]),
        }
        try:
            from integrations.google_sheets.client import append_cc_row
            sheet_ok = append_cc_row(entry)
        except Exception:
            sheet_ok = False

        confirm = (
            f"✅ *CC Application Logged*\n\n"
            f"💳 **{name}**\n"
            f"🏦 Issuer: {issuer or 'unknown'}\n"
            f"📅 Opened: {entry['date_opened']}\n"
            f"🎁 Bonus: {entry['sign_up_bonus'] or 'not captured'}\n"
            f"💰 Min spend: {entry['min_spend'] or '?'}"
            + (f" by {spend_dl}" if spend_dl else "") + "\n"
            f"💵 Annual fee: {entry['annual_fee'] or 'none/unknown'}\n"
            f"🔄 Re-eligible: {entry['re_eligibility'] or 'not captured'}\n"
            f"{'📊 Synced to CC Tracker' if sheet_ok else '⚠️ Sheet sync failed — check webhook'}\n\n"
            f"_Tip: tell me the re-eligibility rule if you know it so I can track it._"
        )
    else:
        entry = {
            "bank":                 issuer or name,
            "account_type":         "Checking/Savings",
            "date_opened":          parsed.get("date_opened", today),
            "bonus_amount":         parsed.get("bonus_amount", parsed.get("sign_up_bonus", "")),
            "min_deposit":          parsed.get("min_deposit", parsed.get("min_spend", "")),
            "days_to_qualify":      parsed.get("days_to_qualify", ""),
            "bonus_deadline":       spend_dl,
            "apy":                  parsed.get("apy", ""),
            "monthly_fee":          "",
            "fee_waiver":           "",
            "early_closure_penalty": "",
            "status":               "Active",
            "bonus_received_date":  "",
            "date_closed":          "",
            "re_eligibility":       parsed.get("re_eligibility", ""),
            "notes":                parsed.get("notes", message[:200]),
            "source":               "logged via bot",
        }
        try:
            from integrations.google_sheets.client import append_bank_row
            sheet_ok = append_bank_row(entry)
        except Exception:
            sheet_ok = False

        confirm = (
            f"✅ *Bank Account Logged*\n\n"
            f"🏦 **{name}**\n"
            f"📅 Opened: {entry['date_opened']}\n"
            f"🎁 Bonus: {entry['bonus_amount'] or 'not captured'}\n"
            f"💰 Min deposit: {entry['min_deposit'] or '?'}\n"
            f"📈 APY: {entry['apy'] or 'not captured'}\n"
            f"🔄 Re-eligible: {entry['re_eligibility'] or 'not captured'}\n"
            f"{'📊 Synced to Bank Tracker' if sheet_ok else '⚠️ Sheet sync failed — check webhook'}"
        )

    return confirm


# ── Bonus received logging ───────────────────────────────────────────────────

def _log_bonus(message: str, card_name: str = None) -> str:
    bonuses = _load_bonuses()
    today   = datetime.date.today().isoformat()

    entry = {
        "id":           len(bonuses) + 1,
        "card_or_bank": card_name or message[:60],
        "date_logged":  today,
        "status":       "received",
        "note":         message,
    }
    bonuses.append(entry)
    _save_bonuses(bonuses)

    # Update Google Sheets
    try:
        from integrations.google_sheets.client import append_bonus_row
        append_bonus_row(entry)
    except Exception:
        pass

    return (
        f"✅ *Bonus Received — Logged!*\n"
        f"_{entry['card_or_bank']}_\n"
        f"📅 {today}\n\n"
        f"_Next: ask 'when am I eligible for [card] again?' to track re-eligibility._"
    )


def _show_tracker() -> str:
    bonuses = _load_bonuses()
    if not bonuses:
        return (
            "📋 *Bonus Tracker* — Empty\n\n"
            "Log a new card: 'I just opened the Chase Ink Preferred'\n"
            "Log a bonus received: 'I got the Amex Gold bonus'\n"
            "See full re-eligibility: 'what can I apply for soon?'"
        )

    lines = ["📋 *Your Bonus Log* (last 10)\n"]
    for b in bonuses[-10:]:
        emoji = {"received": "✅", "applied": "📝", "closed": "🔒"}.get(b.get("status", ""), "•")
        lines.append(f"{emoji} *{b['card_or_bank']}* — {b['date_logged']}")

    lines.append(f"\n_{len(bonuses)} total • Use 'what can I apply for?' for re-eligibility_")
    return "\n".join(lines)


# ── Tax strategy ─────────────────────────────────────────────────────────────

TAX_CONTEXT = """
Justin's tax situation:
• High W2 income: Director of Infusion Services, NYP (NYC, likely top federal bracket)
• 1099 SE income: Freelance infusion management consulting
• Rental income: VA Beach townhouse (partial) + Cliffside Park NJ condo (full)
• State: NY/NJ — high state taxes, SALT cap ($10k) applies
• No known retirement accounts mentioned yet

Key optimization levers:
- Solo 401(k) or SEP-IRA → shelter up to $69k/yr of 1099 income (2024)
- QBI deduction → 20% pass-through deduction on 1099 income (if below phaseout ~$383k MFJ)
- S-Corp election → if SE income >$80k-100k, save SE tax on reasonable salary vs distributions
- Home office deduction → dedicated workspace for consulting business (actual method vs simplified)
- Business expenses: phone, software, travel, professional dues, education (consulting-related)
- Rental depreciation → 27.5yr on residential buildings (non-cash deduction against rental income)
- Rental repairs vs improvements → expensing repairs, capitalizing improvements
- Passive activity loss rules → rental losses passive unless Real Estate Professional status
- 1031 exchange → defer capital gains on property sale by rolling into new property
- SALT → already capped at $10k; explore entity-level SALT workarounds (NY PTET, NJ BAIT)
- HSA → if on HDHP, triple-tax-advantaged; $4,150/yr (self) 2024
- Backdoor Roth → if income too high for direct Roth contribution
"""


def _get_tax_strategy(message: str) -> str:
    results = search(f"tax strategy {message} W2 1099 self-employed rental income 2024 2025", max_results=4)
    context = format_results(results) if results else ""

    prompt = f"""Tax question: {message}

{TAX_CONTEXT}

Search results:
{context}

Answer with:
1. **Most impactful strategies** for Justin's situation (quantify savings where possible)
2. **Clear wins** vs **Grey areas** vs **Aggressive/risky** — label each
3. **Specific next steps** (e.g., "open Solo 401(k) by Dec 31", "document home office sqft")
4. **Relevant tax code sections** or IRS guidance where applicable
5. Flag any NY/NJ-specific considerations

Be direct. If a strategy could trigger audit risk, say so clearly.
Today: {datetime.date.today()}"""

    return chat(SYSTEM + _profile_context(), prompt, max_tokens=800)


# ── Side hustle scanner ──────────────────────────────────────────────────────

HUSTLE_VET_PROMPT = """You are vetting side hustle and passive income ideas for Justin Ngai.

Justin's profile:
- Director of Infusion Services at NYP (W2, healthcare ops expert)
- Freelance infusion management consultant (1099)
- Landlord: VA Beach townhouse + Cliffside Park NJ condo
- High earner, NYC-based, limited time, values leverage and passive income
- Investment interests: stocks, real estate, notes, travel hacking
- Must keep infusion consulting quiet from employer

For each idea found, score and present:
💡 **[Idea Name]** — [Income Range/yr]
• Time to launch: [weeks/months]
• Startup cost: $[X]
• Weekly time: [X hrs]
• Income type: active | semi-passive | fully passive
• Tax treatment: [Schedule C / rental / capital gains / etc.]
• Justin fit score: [1-10] — [1-sentence reason]
• Key risk / caveat: [one line]

Rank by Justin fit score. Flag conflicts of interest with NYP employment."""


def _scan_side_hustles(query: str) -> str:
    search_queries = [
        query or "best side hustles passive income high earner professional 2025",
        "passive income ideas healthcare consultant director",
        "real estate side hustle landlord additional income",
        "online consulting course income healthcare professional",
        "side income ideas W2 employee freelancer 2025",
    ]

    all_results = []
    for q in search_queries[:3]:
        all_results.extend(search(q, max_results=3))

    reddit_posts = _fetch_reddit_posts(
        ["r/sidehustle", "r/passive_income", "r/financialindependence", "r/realestateinvesting"]
    )

    context = format_results(all_results[:8]) if all_results else ""

    reddit_digest = ""
    for p in reddit_posts[:8]:
        reddit_digest += f"\n[{p['source']}] {p['title']}: {p['summary'][:200]}"

    prompt = f"""Scan these sources and identify the TOP 5 side hustle / passive income opportunities most relevant to Justin.

{HUSTLE_VET_PROMPT}

Search results:
{context}

Reddit intel:
{reddit_digest or "none"}

Today: {datetime.date.today()}

After listing the ideas, add:
---
💬 *Want to develop any of these?* Say "develop [idea name]" to get a full plan,
financial model, and the option to create a dedicated subagent for it."""

    return chat(SYSTEM + _profile_context(), prompt, max_tokens=1000)


def _develop_side_hustle(message: str, idea: str = None) -> str:
    """Deep dive on a specific side hustle idea — saves to file, offers subagent."""
    idea_name = idea or message

    # Search for specifics
    results = search(f"{idea_name} side hustle income how to start 2025", max_results=4)
    tax_results = search(f"{idea_name} tax treatment self-employed income", max_results=2)
    all_results = results + tax_results
    context = format_results(all_results[:5]) if all_results else ""

    prompt = f"""Deep dive on this side hustle idea for Justin: **{idea_name}**

Justin's profile context:
- Healthcare ops director + infusion consultant + landlord
- High earner, limited time, NYC-based
- Wants leverage and passive income
- Tax position: W2 + 1099 + rental — any new income goes on top

Build a full analysis:

## 1. Overview
[What is it, how does it work]

## 2. Financial Model
• Startup cost: $X
• Monthly expenses: $X
• Revenue potential: $X/mo at [X] scale (conservative / realistic / optimistic)
• Break-even: [timeline]
• Annual income potential: $X

## 3. Time Investment
• Launch phase: [X hrs/wk for X months]
• Steady state: [X hrs/wk]
• Delegation potential: [can you hire/automate this?]

## 4. Tax Treatment
• Income type: [Schedule C / passive / capital gains]
• Key deductions available
• Estimated tax rate on this income

## 5. Justin Fit Analysis
• Leverages his expertise? [yes/no + how]
• Conflicts with NYP employment? [yes/no + notes]
• Realistic given his schedule?

## 6. Next 3 Steps to Launch
1. [Specific, actionable]
2. [...]
3. [...]

## 7. Risks & Mitigation
[Top 2-3 risks]

Search context:
{context}"""

    response = chat(SYSTEM + _profile_context(), prompt, max_tokens=1200)

    # Save to side_hustle_ideas.json
    ideas = _load_side_hustles()
    today = datetime.date.today().isoformat()
    existing = next((i for i in ideas if i["idea"].lower() == idea_name.lower()), None)

    if existing:
        existing["last_updated"] = today
        existing["analysis"] = response
    else:
        ideas.append({
            "id":          len(ideas) + 1,
            "idea":        idea_name,
            "date_added":  today,
            "last_updated": today,
            "status":      "exploring",
            "analysis":    response,
        })
    _save_side_hustles(ideas)

    response += (
        f"\n\n---\n"
        f"💾 *Saved to your side hustle tracker.*\n"
        f"_Say 'my side hustles' to see all ideas, or continue the conversation to refine this plan._\n"
        f"_Say 'create a follow-up for [idea]' to set a reminder to revisit._"
    )
    return response


def _list_side_hustles() -> str:
    ideas = _load_side_hustles()
    if not ideas:
        return (
            "📋 *Side Hustle Tracker* — Empty\n\n"
            "Say 'scan for side hustle ideas' to find opportunities, or\n"
            "'develop [idea name]' to deep-dive one."
        )
    lines = ["📋 *Your Side Hustle Ideas*\n"]
    status_emoji = {"exploring": "🔍", "active": "🚀", "paused": "⏸", "dropped": "❌"}
    for i in ideas:
        emoji = status_emoji.get(i.get("status", ""), "•")
        lines.append(f"{emoji} **#{i['id']} {i['idea']}** — {i.get('status','?')} ({i.get('last_updated','')})")
    lines.append(f"\n_Say 'develop [idea]' to continue refining any of these._")
    return "\n".join(lines)


# ── Financial review ─────────────────────────────────────────────────────────

def _finance_review(message: str) -> str:
    """Holistic financial review using all available context."""
    # Pull bonus tracker data
    try:
        from integrations.google_sheets.client import read_bonus_tracker
        sheet_data = read_bonus_tracker()
        cc_count   = len(sheet_data.get("CC Tracker", []))
        bank_count = len(sheet_data.get("Bank Tracker", []))
        tracker_summary = f"Active CC tracker entries: {cc_count}, Bank entries: {bank_count}"
    except Exception:
        tracker_summary = "Tracker data unavailable"

    # Pull budget summary
    budget    = _load_budget()
    today     = datetime.date.today()
    month_entries = [e for e in budget if e.get("date", "") >= today.replace(day=1).isoformat()]
    total_out = sum(e.get("amount", 0) for e in month_entries if e.get("type") == "expense")
    total_in  = sum(e.get("amount", 0) for e in month_entries if e.get("type") == "income")

    # Pull side hustle ideas
    ideas = _load_side_hustles()
    idea_names = [i["idea"] for i in ideas if i.get("status") != "dropped"]

    # Search for any relevant news
    results = search("personal finance strategy high income W2 1099 rental 2025 tax optimization", max_results=3)
    context = format_results(results) if results else ""

    origin_ctx = _origin_finance_context()

    prompt = f"""Conduct a holistic financial review for Justin. Be his pocket CFP.

Current data:
- Bonus tracker: {tracker_summary}
- This month's logged spending: ${total_out:,.0f} out / ${total_in:,.0f} in
- Side hustle ideas in pipeline: {', '.join(idea_names) if idea_names else 'none'}
- User question/context: {message}
{origin_ctx}

{TAX_CONTEXT}

Profile additions: {_profile_context()}

Review across these dimensions:
1. 🏆 **Top 3 financial moves** Justin should make in the next 30 days
2. 💳 **Bonus/churning** — anything to act on now vs let expire?
3. 🏠 **Real estate** — is he optimizing his rental income and tax treatment?
4. 📊 **Tax** — biggest untapped deductions or strategies given his income mix
5. 💡 **Side income** — most promising next move given his profile
6. ⚠️ **Risks** — anything he should be watching out for

Be specific. Quantify where possible. Flag time-sensitive items.

Search context:
{context}

Today: {today}"""

    return chat(SYSTEM + _profile_context(), prompt, max_tokens=1000)


# ── Profile update ───────────────────────────────────────────────────────────

def _update_profile(message: str) -> str:
    """Extract and save new financial facts about Justin."""
    parse_prompt = """Extract new financial fact from this message. Return JSON only.
{"key": "<short descriptive key>", "value": "<the fact>"}
Examples:
"I got a $20k raise" → {"key": "w2_salary_update", "value": "$20k raise, noted Mar 2026"}
"I sold the VA Beach property" → {"key": "real_estate_VA_beach", "value": "Sold, no longer owned"}
"I opened a Solo 401k with Fidelity" → {"key": "solo_401k", "value": "Opened at Fidelity"}"""

    raw = chat(parse_prompt, message, max_tokens=100)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        fact = json.loads(raw)
    except Exception:
        return "⚠️ Couldn't parse that update. Try: 'update my profile: I opened a Solo 401k'"

    profile = _load_profile()
    profile[fact["key"]] = fact["value"]
    _save_profile(profile)

    return (
        f"✅ *Profile updated*\n"
        f"`{fact['key']}` → {fact['value']}\n\n"
        f"_Your financial profile now has {len(profile)} saved facts. "
        f"These inform every finance recommendation I make._"
    )


# ── Budget ───────────────────────────────────────────────────────────────────

def _log_budget(message: str) -> str:
    budget = _load_budget()
    today  = datetime.date.today().isoformat()

    parse_prompt = """Extract expense/income from this message. Return JSON only.
{"type": "expense" or "income", "amount": <number>, "category": "<groceries|dining|transport|shopping|bills|health|entertainment|income|consulting|rental|other>", "description": "<short desc>"}
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
        return "⚠️ Couldn't parse that. Try: 'spent $50 on groceries'"

    entry = {
        "id":          len(budget) + 1,
        "type":        parsed["type"],
        "amount":      parsed.get("amount", 0),
        "category":    parsed.get("category", "other"),
        "description": parsed.get("description", message),
        "date":        today,
    }
    budget.append(entry)
    _save_budget(budget)

    try:
        from integrations.google_sheets.client import append_budget_row
        append_budget_row(entry)
    except Exception:
        pass

    emoji = "💸" if parsed["type"] == "expense" else "💰"
    return (
        f"{emoji} *{parsed['type'].title()} logged*\n"
        f"${parsed.get('amount', '?'):,} — {parsed.get('category', '').title()}\n"
        f"_{parsed.get('description', '')}_"
    )


def _parse_origin_structured() -> dict:
    """
    Parse raw Origin page text into clean structured metrics.
    Origin outputs label on one line, value on the next — handle accordingly.
    """
    try:
        from integrations.origin.scraper import load_snapshot
        snap = load_snapshot()
        if not snap:
            return {}
    except Exception:
        return {}

    result = {}
    dash = snap.get("dashboard_text", "")
    lines = [l.strip() for l in dash.split("\n")]

    # ── Net worth — find $XK values in the forecast block near "NET WORTH" ────
    # Origin shows forecast Y-axis as $945K/$952K/$959K/$966K/$973K — take the max (current/end value)
    for i, line in enumerate(lines):
        if "NET WORTH" in line.upper():
            nw_candidates = []
            for j in range(i, min(i + 20, len(lines))):
                if re.match(r"^\$\d[\d,\.]*[KMB]$", lines[j]):  # must end with K/M/B
                    nw_candidates.append(lines[j])
            if nw_candidates:
                result["net_worth"] = nw_candidates[-1]  # last in forecast range = highest/current
            break

    # Net worth change
    for line in lines:
        if re.match(r"^[+\-]\$[\d,\.]+ \([\d\.]+%\)$", line):
            result["net_worth_change"] = line
            break

    # ── Budget ────────────────────────────────────────────────────────────────
    for i, line in enumerate(lines):
        if "BUDGET IN" in line.upper():
            block = lines[i:i+10]
            result["budget_spent"] = next((l for l in block if re.match(r"^\$[\d,]+$", l)), None)
            result["budget_target"] = next((l for l in block if l.startswith("of $")), None)
            result["budget_pct"] = next((l for l in block if re.match(r"^\d+\.?\d*%$", l)), None)
            break

    # Spent in month
    for i, line in enumerate(lines):
        if "SPENT IN" in line.upper():
            for j in range(i+1, min(i+3, len(lines))):
                if re.match(r"^\$[\d,]+$", lines[j]):
                    result["spent_month"] = lines[j]
                    break
            break

    # ── Credit score ──────────────────────────────────────────────────────────
    for i, line in enumerate(lines):
        if "CREDIT SCORE" in line.upper():
            for j in range(i+1, min(i+4, len(lines))):
                if re.match(r"^\d{3}$", lines[j]):
                    result["credit_score"] = lines[j]
                    break
            break

    # ── Investments (from dashboard) ──────────────────────────────────────────
    for i, line in enumerate(lines):
        if line.upper() == "INVESTMENTS":
            for j in range(i+1, min(i+3, len(lines))):
                if re.match(r"^\$[\d,]+$", lines[j]):
                    result["investments_value"] = lines[j]
                    break
            break

    # ── Market watch ──────────────────────────────────────────────────────────
    market_lines = []
    in_market = False
    for line in lines:
        if "MARKET WATCH" in line.upper():
            in_market = True
            continue
        if in_market:
            if line and len(line) > 2:
                market_lines.append(line)
            if len(market_lines) >= 8:
                break
    result["market_lines"] = market_lines

    # ── Spending categories ────────────────────────────────────────────────────
    spending = snap.get("spending_text", "") + "\n" + snap.get("spending_breakdown_text", "")
    spending_lines = [l.strip() for l in spending.split("\n")
                      if l.strip() and ("$" in l or "%" in l) and len(l.strip()) > 2]
    result["spending_lines"] = spending_lines[:30]

    # ── Investments detail ────────────────────────────────────────────────────
    invest = snap.get("investments_text", "")
    invest_lines = [l.strip() for l in invest.split("\n")
                    if l.strip() and ("$" in l or "%" in l or any(
                        kw in l.lower() for kw in ["401", "ira", "brokerage", "etf", "fund", "allocation"]))]
    result["investment_lines"] = invest_lines[:30]

    # ── Equity / RSU ──────────────────────────────────────────────────────────
    equity = snap.get("equity_text", "")
    equity_lines = [l.strip() for l in equity.split("\n")
                    if l.strip() and ("$" in l or "%" in l or "rsu" in l.lower() or "vest" in l.lower())]
    result["equity_lines"] = equity_lines[:20]

    # ── Forecast ──────────────────────────────────────────────────────────────
    forecast = snap.get("forecast_text", "")
    forecast_lines = [l.strip() for l in forecast.split("\n") if l.strip() and len(l.strip()) > 5]
    result["forecast_lines"] = forecast_lines[:15]

    result["_scraped_at"] = snap.get("_scraped_at", "unknown")
    return result


def _get_macro_context() -> str:
    """
    Pull real-time macro signals relevant to Justin's financial situation:
    Fed/rates, real estate, healthcare sector, NYC/NJ market.
    Returns compressed briefing string.
    """
    queries = [
        "Federal Reserve interest rate outlook 2026 mortgage real estate impact",
        "NYC NJ real estate market trends rental income 2026",
        "healthcare sector stocks performance outlook Q2 2026",
        "high income earner tax strategy changes 2026 IRS Solo 401k limits",
    ]
    all_results = []
    for q in queries:
        try:
            results = search(q, max_results=2)
            all_results.extend(results)
        except Exception:
            continue

    if not all_results:
        return ""

    raw = format_results(all_results[:8])
    compressed = chat(
        "You are a macro analyst. Extract only the most actionable signals from these search results "
        "for a high-income NYC professional with W2+1099 income, two rental properties (VA + NJ), "
        "and a moderate-aggressive investment portfolio. Be extremely concise — 5-8 bullet points max. "
        "Focus on: rates/mortgage impact, real estate trends, healthcare sector, tax law changes.",
        raw,
        max_tokens=400,
    )
    return compressed


def _flag_investment_ideas(ideas: list[dict]) -> str:
    """
    Save investment ideas flagged by financial analysis to data file.
    Each idea: {"ticker_or_theme": str, "rationale": str, "conviction": str, "source": "finance_board"}
    Returns summary of what was flagged.
    """
    DATA_DIR.mkdir(exist_ok=True)
    existing = []
    if INVESTMENT_FLAGS_FILE.exists():
        try:
            existing = json.loads(INVESTMENT_FLAGS_FILE.read_text())
        except Exception:
            existing = []

    today = datetime.date.today().isoformat()
    added = []
    for idea in ideas:
        idea["flagged_date"] = today
        idea["source"] = "finance_board"
        idea["status"] = "pending_review"
        existing.append(idea)
        added.append(idea.get("ticker_or_theme", "?"))

    INVESTMENT_FLAGS_FILE.write_text(json.dumps(existing, indent=2))
    logger.info("Finance board flagged %d investment ideas: %s", len(added), added)
    return added


def _financial_intelligence_report(trigger: str = "on_demand") -> str:
    """
    Core board-level financial intelligence report.
    Combines Origin structured data + macro context + LLM analysis.
    Proactively surfaces insights, alerts, and investment signals.
    """
    today = datetime.date.today()

    # ── Gather all data ────────────────────────────────────────────────────────
    origin = _parse_origin_structured()
    macro_ctx = _get_macro_context()
    budget = _load_budget()
    month_start = today.replace(day=1).isoformat()
    month_entries = [e for e in budget if e.get("date", "") >= month_start]
    total_out = sum(e.get("amount", 0) for e in month_entries if e.get("type") == "expense")
    total_in  = sum(e.get("amount", 0) for e in month_entries if e.get("type") == "income")
    profile_ctx = _profile_context()

    # ── Build prompt ───────────────────────────────────────────────────────────
    origin_section = ""
    if origin:
        origin_section = f"""
Origin Financial data (scraped {origin.get('_scraped_at', '?')[:10]}):
Net worth: {origin.get('net_worth', 'not found')} (change: {origin.get('net_worth_change', '?')})
Credit score: {origin.get('credit_score', '?')}
Investments portfolio: {origin.get('investments_value', '?')}
Spent this month: {origin.get('spent_month', '?')} vs budget target {origin.get('budget_target', '?')} ({origin.get('budget_pct', '?')} of budget)
Market: {'; '.join(origin.get('market_lines', [])[:6])}
Spending detail: {'; '.join(origin.get('spending_lines', [])[:15])}
Investment detail: {'; '.join(origin.get('investment_lines', [])[:10])}
Equity/RSU: {'; '.join(origin.get('equity_lines', [])[:8])}
Forecast: {'; '.join(origin.get('forecast_lines', [])[:6])}
"""
    else:
        origin_section = "Origin Financial data: not available (run /origin refresh)"

    macro_section = f"\nMacro context:\n{macro_ctx}" if macro_ctx else ""

    budget_section = f"""
Manually logged this month: ${total_out:,.0f} expenses / ${total_in:,.0f} income
"""

    prompt = f"""Conduct a comprehensive financial intelligence briefing for Justin. Today: {today}

{origin_section}
{budget_section}
{macro_section}
{profile_ctx}

Deliver a board-level briefing in this exact format:

📊 **SNAPSHOT**
[2-3 lines: net worth trend, portfolio value, budget status with % used if available]

🔴🟡🟢 **ALERTS & WATCH LIST**
[3-5 bullets. Flag overspending categories, portfolio drift, upcoming deadlines, rate/tax risks.
Use 🔴 ACT NOW / 🟡 WATCH / 🟢 NOTED]

💡 **OPPORTUNITIES**
[2-4 bullets. Tax moves, refi timing, bonus plays, income optimization, real estate strategy.
State conviction: HIGH/MEDIUM/LOW and estimated dollar value where possible]

📈 **INVESTMENT SIGNALS** [for investment agent]
[2-3 bullets max. Specific tickers or themes that emerge from macro + personal situation.
Format: TICKER/THEME — one-line rationale — conviction HIGH/MEDIUM/LOW]

🎯 **RECOMMENDED ACTIONS THIS WEEK**
[Top 2-3 concrete next steps with clear owner: "You should..." or "Ask investment agent about..."]"""

    response = chat(SYSTEM + profile_ctx, prompt, max_tokens=1200)

    # ── Extract and save investment signals ───────────────────────────────────
    if "INVESTMENT SIGNALS" in response:
        try:
            signal_section = response.split("INVESTMENT SIGNALS")[1].split("RECOMMENDED ACTIONS")[0]
            lines = [l.strip("•- ").strip() for l in signal_section.split("\n") if l.strip() and "—" in l]
            flags = []
            for line in lines[:4]:
                parts = line.split("—")
                if len(parts) >= 2:
                    conviction = "MEDIUM"
                    for c in ["HIGH", "MEDIUM", "LOW"]:
                        if c in line.upper():
                            conviction = c
                            break
                    flags.append({
                        "ticker_or_theme": parts[0].strip(),
                        "rationale": parts[1].strip() if len(parts) > 1 else "",
                        "conviction": conviction,
                    })
            if flags:
                flagged = _flag_investment_ideas(flags)
                if flagged:
                    response += f"\n\n_📌 Flagged for investment agent: {', '.join(flagged)}_"
        except Exception as e:
            logger.warning("Could not parse investment signals: %s", e)

    return response


def run_weekly_board_briefing() -> str:
    """
    Weekly financial board meeting — full intelligence report.
    Scheduled Sunday 6 PM ET. Returns report string (empty = silent).
    """
    try:
        return _financial_intelligence_report(trigger="weekly_scheduled")
    except Exception as e:
        logger.error("Weekly board briefing error: %s", e)
        return ""


def _origin_refresh() -> str:
    """
    Refresh Origin data. Tries saved cookies first (autonomous), then Chrome CDP.
    After a successful CDP scrape, cookies are saved for future autonomous runs.
    """
    try:
        from integrations.origin.scraper import (
            scrape_with_cookies, refresh_from_chrome,
            cookies_exist, snapshot_age_hours, get_finance_context
        )

        # Try cookie-based headless scrape first (no Chrome needed)
        if cookies_exist():
            snap = scrape_with_cookies()
            if snap and "error" not in snap:
                age = snapshot_age_hours()
                age_str = "just now" if not age or age < 0.1 else f"{age*60:.0f}m ago"
                ctx = get_finance_context()
                preview = ctx[:500] if ctx else "_No structured data extracted._"
                return f"✅ *Origin refreshed* ({age_str})\n\n{preview}"
            if snap.get("error") == "session_expired":
                # Fall through to CDP below
                pass

        # Fall back to CDP (requires Chrome with --remote-debugging-port=9222)
        snap = refresh_from_chrome()
        if not snap or "error" in snap:
            err = snap.get("error", "no data") if snap else "no data"
            return (
                "❌ *Origin refresh failed*\n"
                f"`{err}`\n\n"
                "_Run `scripts/start_chrome_cdp.sh`, log into Origin, then try again.\n"
                "After that first login, daily refreshes will run automatically._"
            )

        age = snapshot_age_hours()
        age_str = "just now" if not age or age < 0.1 else f"{age*60:.0f}m ago"
        ctx = get_finance_context()
        preview = ctx[:500] if ctx else "_No structured data extracted._"
        return (
            f"✅ *Origin refreshed via Chrome* ({age_str})\n"
            "_Session saved — future refreshes will run automatically._\n\n"
            f"{preview}"
        )
    except Exception as e:
        return f"❌ Origin refresh error: {e}"


def _origin_status() -> str:
    """Return snapshot age + key metrics without triggering a new scrape."""
    try:
        from integrations.origin.scraper import load_snapshot, snapshot_age_hours, get_finance_context
        snap = load_snapshot()
        if not snap:
            return (
                "📊 *Origin Financial*\n\nNo snapshot on file.\n\n"
                "_Say 'origin refresh' to pull data from Chrome._"
            )
        age = snapshot_age_hours()
        age_str = f"{age:.0f}h ago" if age is not None else "unknown"
        scraped_at = snap.get("_scraped_at", "?")[:19]
        ctx = get_finance_context()
        preview = ctx[:600] if ctx else "_No structured data extracted._"
        return (
            f"📊 *Origin Financial* (synced {age_str}, `{scraped_at}`)\n\n"
            f"{preview}\n\n"
            "_Say 'origin refresh' to pull fresh data._"
        )
    except Exception as e:
        return f"❌ Origin status error: {e}"


def _origin_finance_context() -> str:
    """Pull live Origin Financial budget/spending data as context string."""
    try:
        from integrations.origin.scraper import get_finance_context
        return get_finance_context()
    except Exception:
        return ""


def _budget_summary() -> str:
    budget = _load_budget()
    today  = datetime.date.today()
    month_start = today.replace(day=1).isoformat()
    month_entries = [e for e in budget if e.get("date", "") >= month_start]

    # Prepend Origin data if available
    origin_ctx = _origin_finance_context()

    if not month_entries:
        if origin_ctx:
            return chat(
                SYSTEM + _profile_context(),
                f"Give a budget summary for Justin based on this Origin Financial data:\n{origin_ctx}\n\nToday: {today}",
                max_tokens=500,
            )
        return (
            f"📊 *Budget — {today.strftime('%B %Y')}*\n\n"
            "Nothing manually logged yet.\n"
            "_Start with: 'spent $50 on groceries'_"
        )

    by_category: dict = {}
    total_out = 0
    total_in  = 0
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

    if origin_ctx:
        lines.append(f"\n_Origin Financial data also available — ask for a full review._")

    return "\n".join(lines)


# ── Main handle ──────────────────────────────────────────────────────────────

def handle(message: str) -> str:
    parsed   = _parse_intent(message)
    msg_type = parsed.get("type", "finance_general")
    query    = parsed.get("query", message)
    card     = parsed.get("card_or_bank")
    idea     = parsed.get("idea")

    msg_lower = message.lower()

    # Board briefing / financial intelligence
    if any(w in msg_lower for w in ["board briefing", "financial intel", "finance intel",
                                     "board meeting", "financial briefing", "full review",
                                     "financial report", "intelligence report"]):
        return _financial_intelligence_report()

    # Origin Financial shortcuts
    if any(w in msg_lower for w in ["origin refresh", "refresh origin", "sync origin", "origin sync"]):
        return _origin_refresh()
    if any(w in msg_lower for w in ["origin status", "origin data", "origin snapshot", "origin balance",
                                     "origin budget", "show origin", "what does origin say"]):
        return _origin_status()

    # Side hustle list shortcut
    if any(w in message.lower() for w in ["my side hustles", "side hustle list", "show my ideas"]):
        return _list_side_hustles()

    if msg_type == "bank_bonuses":
        return _find_bank_bonuses(query)

    elif msg_type == "cc_bonuses":
        return _find_cc_bonuses(query, card)

    elif msg_type == "eligibility":
        return _check_eligibility_specific(message, card)

    elif msg_type == "re_eligibility_check":
        return _check_re_eligibility(message, card)

    elif msg_type == "log_application":
        return _log_application(message, card)

    elif msg_type == "log_bonus":
        return _log_bonus(message, card)

    elif msg_type == "track_bonus":
        return _show_tracker()

    elif msg_type == "budget_log":
        return _log_budget(message)

    elif msg_type == "budget_summary":
        return _budget_summary()

    elif msg_type == "tax_strategy":
        return _get_tax_strategy(query or message)

    elif msg_type == "side_hustle_scan":
        return _scan_side_hustles(query or message)

    elif msg_type == "side_hustle_develop":
        return _develop_side_hustle(message, idea)

    elif msg_type == "finance_review":
        return _financial_intelligence_report()

    elif msg_type == "update_profile":
        return _update_profile(message)

    else:
        results = search(query or message, max_results=4)
        context = format_results(results) if results else ""
        full_prompt = f"Question: {message}\n\n{('Search results:\n' + context) if context else ''}"
        return chat(SYSTEM + _profile_context(), full_prompt, max_tokens=600)
