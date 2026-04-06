"""
Bonus Alert Agent — scrapes Doctor of Credit, Frequent Miler, and Reddit
for elevated CC/bank bonuses and sends Telegram alerts above historical baseline.

Sources (no API key required):
- Doctor of Credit RSS feed
- Frequent Miler RSS feed
- Reddit JSON API: r/churning, r/personalfinance, r/deals
- Comparison vs "Historical Normal SUB" in CC Tracker Google Sheet
"""

import logging
import os
import re
import json
import datetime
import xml.etree.ElementTree as ET
from pathlib import Path
from core.llm import chat

logger = logging.getLogger(__name__)

try:
    import requests as _requests
except ImportError:
    _requests = None

TELEGRAM_TOKEN = os.environ.get("TELEGRAM_BOT_TOKEN", "")
TELEGRAM_CHAT_ID = os.environ.get("TELEGRAM_CHAT_ID", "")

LAST_ALERT_FILE = Path(__file__).parent.parent.parent / "data" / "bonus_alerts_sent.json"

SOURCES = [
    # ── RSS feeds ───────────────────────────────────────────────────────────────
    {"name": "Doctor of Credit",  "url": "https://www.doctorofcredit.com/feed/",   "type": "rss"},
    {"name": "Frequent Miler",    "url": "https://frequentmiler.com/feed/",         "type": "rss"},
    {"name": "NerdWallet",        "url": "https://www.nerdwallet.com/blog/feed/",   "type": "rss"},

    # ── r/churning — broad searches, not just "elevated" ───────────────────────
    {"name": "r/churning",        "url": "https://www.reddit.com/r/churning/search.json?q=bonus+offer+card&sort=new&restrict_sr=1&t=week&limit=20",    "type": "reddit"},
    {"name": "r/churning news",   "url": "https://www.reddit.com/r/churning/search.json?q=news+update&sort=new&restrict_sr=1&t=week&limit=10",          "type": "reddit"},
    {"name": "r/churning bank",   "url": "https://www.reddit.com/r/churning/search.json?q=bank+bonus&sort=new&restrict_sr=1&t=week&limit=10",           "type": "reddit"},

    # ── r/CreditCards — where mainstream card launches get discussed ────────────
    {"name": "r/CreditCards new", "url": "https://www.reddit.com/r/CreditCards/search.json?q=100k+bonus+OR+75k+bonus+OR+new+card+launch&sort=new&restrict_sr=1&t=week&limit=15", "type": "reddit"},
    {"name": "r/CreditCards hot", "url": "https://www.reddit.com/r/CreditCards/hot.json?limit=15",  "type": "reddit_hot"},
    {"name": "r/churning hot",    "url": "https://www.reddit.com/r/churning/hot.json?limit=10",     "type": "reddit_hot"},

    # ── r/personalfinance for bank account bonuses ──────────────────────────────
    {"name": "r/personalfinance", "url": "https://www.reddit.com/r/personalfinance/search.json?q=bank+bonus+$300+OR+$500+checking&sort=new&restrict_sr=1&t=week&limit=10", "type": "reddit"},
]

# Known card name aliases → normalized name
CARD_ALIASES = {
    "sapphire preferred": "Chase Sapphire Preferred",
    "sapphire reserve": "Chase Sapphire Reserve",
    "csp": "Chase Sapphire Preferred",
    "csr": "Chase Sapphire Reserve",
    "amex platinum": "Amex Platinum",
    "platinum card": "Amex Platinum",
    "gold card": "Amex Gold",
    "amex gold": "Amex Gold",
    "amex bce": "Amex Blue Cash Everyday",
    "amex bcp": "Amex Blue Cash Preferred",
    "blue cash preferred": "Amex Blue Cash Preferred",
    "venture x": "Capital One Venture X",
    "venture card": "Capital One Venture",
    "citi premier": "Citi Premier",
    "strata premier": "Citi Strata Premier",
    "ink preferred": "Chase Ink Business Preferred",
    "ink cash": "Chase Ink Business Cash",
    "ink unlimited": "Chase Ink Business Unlimited",
    "cip": "Chase Ink Business Preferred",
    "biz plat": "Amex Business Platinum",
    "business platinum": "Amex Business Platinum",
    "hyatt": "Chase World of Hyatt",
    "marriott bonvoy": "Marriott Bonvoy Boundless",
    "united explorer": "United Explorer",
    "delta gold": "Delta SkyMiles Gold",
    "delta platinum": "Delta SkyMiles Platinum",
}


def _load_last_alerts() -> dict:
    LAST_ALERT_FILE.parent.mkdir(exist_ok=True)
    if not LAST_ALERT_FILE.exists():
        return {}
    try:
        return json.loads(LAST_ALERT_FILE.read_text())
    except Exception:
        return {}


def _save_last_alerts(data: dict):
    LAST_ALERT_FILE.parent.mkdir(exist_ok=True)
    LAST_ALERT_FILE.write_text(json.dumps(data, indent=2))


def _fetch_rss(url: str, source_name: str) -> list[dict]:
    """Fetch and parse an RSS feed. Returns list of {title, summary, link}."""
    if not _requests:
        return []
    try:
        headers = {"User-Agent": "Mozilla/5.0 (personal finance bot; private use)"}
        resp = _requests.get(url, timeout=10, headers=headers)
        if resp.status_code != 200:
            return []
        root = ET.fromstring(resp.content)
        items = []
        for item in root.iter("item"):
            title = item.findtext("title", "")
            desc = item.findtext("description", "")
            link = item.findtext("link", "")
            # Strip HTML tags from description
            desc = re.sub(r"<[^>]+>", " ", desc)[:400]
            items.append({"title": title, "summary": desc, "link": link, "source": source_name})
        return items[:20]
    except Exception as e:
        logger.error("RSS fetch error (%s): %s", source_name, e)
        return []


def _fetch_reddit(url: str, source_name: str, min_score: int = 0) -> list[dict]:
    """
    Fetch Reddit JSON API. Returns list of {title, summary, link}.
    Includes post body (selftext) so the LLM can see card names mentioned in thread text.
    """
    if not _requests:
        return []
    try:
        headers = {"User-Agent": "personal-finance-bot/1.0 (private use)"}
        resp = _requests.get(url, timeout=10, headers=headers)
        if resp.status_code != 200:
            return []
        data = resp.json()
        items = []
        for post in data.get("data", {}).get("children", []):
            d = post.get("data", {})
            title = d.get("title", "")
            # Include selftext so we capture card names mentioned in thread bodies
            selftext = (d.get("selftext", "") or "")[:600]
            link = "https://reddit.com" + d.get("permalink", "")
            score = d.get("score", 0)

            # Always include if title mentions cards/bonuses; otherwise use score filter
            bonus_keywords = ["bonus", "offer", "card", "points", "miles", "bank", "elevated",
                              "100k", "75k", "80k", "chase", "amex", "citi", "capital one",
                              "atmos", "bank of america", "bofA", "boa", "venture", "sapphire",
                              "ink", "platinum", "gold", "new card", "launch"]
            has_bonus_signal = any(kw in title.lower() for kw in bonus_keywords)

            if score >= min_score or has_bonus_signal:
                summary = selftext if selftext and selftext != "[removed]" else ""
                items.append({"title": title, "summary": summary, "link": link, "source": source_name})
        return items
    except Exception as e:
        logger.error("Reddit fetch error (%s): %s", source_name, e)
        return []


def _fetch_tavily_bonuses() -> list[dict]:
    """Use Tavily to search for recent elevated credit card and bank bonuses."""
    try:
        from core.search import search
        queries = [
            "elevated credit card signup bonus offer 2026",
            "best credit card welcome bonus March April 2026",
            "bank account bonus promotion 2026",
        ]
        posts = []
        for q in queries:
            results = search(q, max_results=5)
            for r in results:
                posts.append({
                    "title": r.get("title", ""),
                    "summary": r.get("content", r.get("snippet", ""))[:400],
                    "link": r.get("url", ""),
                    "source": "Tavily Web Search",
                })
        return posts
    except Exception as e:
        logger.warning("Tavily bonus search failed: %s", e)
        return []


def _fetch_all_posts() -> list[dict]:
    """Fetch posts from all sources including Tavily web search."""
    posts = []
    for source in SOURCES:
        stype = source["type"]
        if stype == "rss":
            posts += _fetch_rss(source["url"], source["name"])
        elif stype == "reddit":
            # Search results — include anything with bonus signal regardless of score
            posts += _fetch_reddit(source["url"], source["name"], min_score=0)
        elif stype == "reddit_hot":
            # Hot feed — include posts with score > 10 or bonus keywords
            posts += _fetch_reddit(source["url"], source["name"], min_score=10)
    # Supplement with Tavily search to catch announcements not yet in RSS
    posts += _fetch_tavily_bonuses()
    # Deduplicate by title
    seen = set()
    deduped = []
    for p in posts:
        key = p["title"][:60].lower().strip()
        if key and key not in seen:
            seen.add(key)
            deduped.append(p)
    return deduped


def _get_historical_baselines() -> dict:
    """Read Historical Normal SUB from CC Tracker sheet."""
    if not _requests:
        return {}
    try:
        from integrations.google_sheets.client import read_bonus_tracker
        data = read_bonus_tracker()
        baselines = {}
        for row in data.get("CC Tracker", []):
            card_name = str(row.get("Card Name", "")).strip()
            hist = str(row.get("Historical Normal SUB", "")).strip()
            if card_name and hist:
                # Extract numeric value
                nums = re.findall(r"[\d,]+", hist.replace(",", ""))
                if nums:
                    baselines[card_name.lower()] = int(nums[0])
        return baselines
    except Exception as e:
        logger.error("Error reading baselines: %s", e)
        return {}


def _extract_bonus_amount(text: str) -> int | None:
    """Extract a bonus amount (points or dollars) from text."""
    # Look for patterns like "100,000 points", "$500 bonus", "100k miles"
    patterns = [
        r"(\d{2,3})[,.]?000\s*(?:points?|miles?|bonus|offer)",
        r"(\d{2,3})k\s*(?:points?|miles?|bonus)",
        r"\$(\d{3,4})\s*(?:bonus|cash|offer|back)",
        r"(\d{2,3})[,.]?000",
    ]
    for pat in patterns:
        m = re.search(pat, text, re.IGNORECASE)
        if m:
            val = int(m.group(1))
            if "k" in text[m.start():m.end()].lower() or "000" in m.group(0):
                return val * 1000 if val < 1000 else val
            return val
    return None


def _normalize_card_name(text: str) -> str | None:
    """Try to identify which card is being discussed."""
    text_lower = text.lower()
    for alias, canonical in CARD_ALIASES.items():
        if alias in text_lower:
            return canonical
    return None


ANALYSIS_PROMPT = """You are a credit card and bank bonus expert for a churner/points optimizer. Analyze these recent posts for NOTABLE signup bonuses worth flagging.

Flag an offer as is_elevated=true if ANY of these are true:
1. Current bonus is HIGHER than the card's usual/historical offer (even slightly elevated)
2. New card launch with an unusually high intro bonus (≥75,000 points OR ≥$500 cash)
3. Bank account bonus ≥$300
4. Limited-time elevated offer with an expiration date
5. A well-known card (Chase, Amex, Citi, Capital One, BofA) with any bonus above its known baseline

Known baselines for comparison:
- Chase Sapphire Preferred: 60k normal, 75k+ = elevated
- Chase Sapphire Reserve: 60k normal, 75k+ = elevated
- Amex Platinum: 80k normal, 100k+ = elevated
- Amex Gold: 60k normal, 75k+ = elevated
- Capital One Venture X: 75k normal, 90k+ = elevated
- Capital One Venture: 75k normal (standalone $250 travel credit counts as elevated)
- Citi Strata Premier / Citi Premier: 60k normal, 75k+ = elevated
- Citi AAdvantage Platinum Select: 50k normal, 70k+ = elevated
- Chase Ink Preferred: 90k normal, 100k+ = elevated
- Chase Ink Cash / Unlimited: 75k normal, 90k+ = elevated
- Marriott Bonvoy Boundless: 100k normal, 125k+ = elevated
- Hilton Surpass / Aspire: 130k normal, 175k+ = elevated
- Delta SkyMiles Gold / Platinum: 50k normal, 70k+ = elevated
- United Explorer: 60k normal, 80k+ = elevated

NEW cards launched in 2025-2026 (no historical baseline — flag all with any bonus):
- Bank of America Atmos Rewards (any tier) — flag all offers
- UBS Visa Infinite — flag all offers
- Any card explicitly described as "new" or "just launched" with bonus ≥50k points or ≥$300

For any other new card with no known history, flag if bonus ≥50k points or ≥$300 cash.

For each offer found, extract:
- Card/Bank name
- Current bonus amount (number only)
- Standard/historical bonus if known (0 if unknown)
- Min spend requirement
- Expiration date (if known, else "?")
- Source
- 1-sentence summary

Return JSON array. If nothing noteworthy, return [].

Example output:
[
  {
    "card": "Chase Sapphire Preferred",
    "current_bonus": 100000,
    "standard_bonus": 60000,
    "is_elevated": true,
    "min_spend": "$4,000 in 3 months",
    "expires": "March 31, 2026",
    "source": "Doctor of Credit",
    "summary": "Elevated to 100k from usual 60k via branch offer"
  }
]

Posts to analyze:
"""


def _analyze_posts_for_elevated(posts: list[dict]) -> list[dict]:
    """Use LLM to identify elevated bonus offers from raw posts."""
    if not posts:
        return []

    # Prepare digest of posts for LLM
    digest = ""
    for p in posts[:25]:  # limit to 25 posts
        digest += f"\n---\nSOURCE: {p['source']}\nTITLE: {p['title']}\nSUMMARY: {p['summary'][:300]}\n"

    raw = chat(ANALYSIS_PROMPT, digest, max_tokens=1000)
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        offers = json.loads(raw)
        return [o for o in offers if isinstance(o, dict) and o.get("is_elevated")]
    except Exception:
        return []


def _send_telegram_alert(message: str):
    """Send a Telegram message directly via Bot API."""
    if not _requests or not TELEGRAM_TOKEN or not TELEGRAM_CHAT_ID:
        logger.debug("[Bonus Alert] Would send: %s", message[:100])
        return
    try:
        _requests.post(
            f"https://api.telegram.org/bot{TELEGRAM_TOKEN}/sendMessage",
            json={
                "chat_id": TELEGRAM_CHAT_ID,
                "text": message,
                "parse_mode": "Markdown",
            },
            timeout=10,
        )
    except Exception as e:
        logger.error("Telegram send error: %s", e)


def _format_alert(offers: list[dict], baselines: dict) -> str | None:
    """Format elevated offers into a Telegram message."""
    if not offers:
        return None

    lines = ["🚨 *ELEVATED BONUS ALERT*\n"]
    alerted_count = 0

    for offer in offers:
        card = offer.get("card", "Unknown")
        current = offer.get("current_bonus", 0)
        standard = offer.get("standard_bonus", 0)
        min_spend = offer.get("min_spend", "?")
        expires = offer.get("expires", "?")
        source = offer.get("source", "")
        summary = offer.get("summary", "")

        # Check against our sheet's historical baseline
        card_lower = card.lower()
        sheet_baseline = None
        for k, v in baselines.items():
            if k in card_lower or card_lower in k:
                sheet_baseline = v
                break

        baseline_str = ""
        if sheet_baseline and current > sheet_baseline:
            baseline_str = f" _(your baseline: {sheet_baseline:,})_"
        elif standard:
            baseline_str = f" _(vs usual {standard:,})_"

        lines.append(
            f"💳 *{card}*\n"
            f"   Bonus: *{current:,}*{baseline_str}\n"
            f"   Spend: {min_spend}\n"
            f"   Expires: {expires}\n"
            f"   Source: {source}\n"
            f"   _{summary[:120]}_\n"
        )
        alerted_count += 1

    if alerted_count == 0:
        return None

    lines.append(f"_Checked {datetime.datetime.now().strftime('%b %d, %Y %H:%M')}_")
    return "\n".join(lines)


def run_bonus_scan(force: bool = False) -> str:
    """
    Main job: scan sources, find elevated offers, alert if new.
    Returns a summary string (for Telegram command response).
    Call with force=True to always report, even if already alerted today.
    """
    logger.info("[Bonus Alert] Starting scan at %s", datetime.datetime.now())

    last_alerts = _load_last_alerts()
    today = datetime.date.today().isoformat()

    # Skip if already scanned today (unless forced)
    if not force and last_alerts.get("last_scan") == today:
        return "✅ Already scanned today. Use 'force scan' to re-check."

    # Fetch posts from all sources
    posts = _fetch_all_posts()
    logger.info("[Bonus Alert] Fetched %d posts", len(posts))

    if not posts:
        return "⚠️ Couldn't fetch bonus sources. Check internet connection."

    # Get historical baselines from sheet
    baselines = _get_historical_baselines()
    logger.info("[Bonus Alert] Got %d baseline values from sheet", len(baselines))

    # LLM analysis
    elevated_offers = _analyze_posts_for_elevated(posts)
    logger.info("[Bonus Alert] Found %d elevated offers", len(elevated_offers))

    # Update scan timestamp
    last_alerts["last_scan"] = today
    last_alerts["last_count"] = len(elevated_offers)

    if not elevated_offers:
        _save_last_alerts(last_alerts)
        return None  # nothing to report

    # Format alert message
    alert_msg = _format_alert(elevated_offers, baselines)
    if alert_msg:
        last_alerts["last_alert"] = today
        last_alerts["last_offers"] = [o.get("card", "") for o in elevated_offers]
        _save_last_alerts(last_alerts)
        return alert_msg  # caller (scheduler or handle()) is responsible for sending

    _save_last_alerts(last_alerts)
    return None  # no noteworthy offers


def handle(message: str) -> str:
    """Handle Telegram command for bonus alerts."""
    msg_lower = message.lower()

    if any(w in msg_lower for w in ["force", "check now", "scan now", "rescan"]):
        result = run_bonus_scan(force=True)
        return result or "✅ Scan complete — no elevated offers found right now."

    if any(w in msg_lower for w in ["status", "last", "when"]):
        alerts = _load_last_alerts()
        last_scan = alerts.get("last_scan", "never")
        last_count = alerts.get("last_count", 0)
        last_alert = alerts.get("last_alert", "never")
        last_offers = alerts.get("last_offers", [])
        offers_str = ", ".join(last_offers) if last_offers else "none"
        return (
            f"📡 *Bonus Alert Status*\n\n"
            f"Last scan: {last_scan}\n"
            f"Elevated found: {last_count}\n"
            f"Last alert sent: {last_alert}\n"
            f"Cards alerted: {offers_str}\n\n"
            f"_Say 'scan now' to force a fresh scan_"
        )

    result = run_bonus_scan(force=False)
    return result or "✅ Already up to date — no new elevated offers."
