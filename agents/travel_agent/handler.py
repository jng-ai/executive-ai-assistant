"""
Travel Hacker Agent — award flight alerts and miles optimization.

Live data source: jng-ai/flight-tracker (GitHub Actions, Mon/Wed/Fri 8AM EST)
Results published to: https://raw.githubusercontent.com/jng-ai/flight-tracker/main/docs/results.json

Justin's profile:
- Base: NYC (JFK/EWR/LGA)
- Goals: Business class to Asia (Tokyo, Bangkok, Singapore, Hong Kong)
- Programs: Alaska Mileage Plan, AAdvantage, Amex MR, Chase UR, Cathay Asia Miles
- Airlines: ANA, Singapore Airlines, Cathay Pacific, Qatar Airways
- Budget: points/miles for flights; cash open for hotels
- Thresholds: Asia RT <$700, Europe RT <$550, etc.
"""

import json
import datetime
from core.llm import chat
from core.search import search, format_results

# ─── Live results URL ─────────────────────────────────────────────────────────
RESULTS_JSON_URL = (
    "https://raw.githubusercontent.com/jng-ai/flight-tracker/main/docs/results.json"
)

SYSTEM = """You are Justin Ngai's personal travel hacker and award flight advisor.

Justin's profile:
- Base: New York City (JFK/EWR/LGA)
- Goals: Business class to Asia (Japan, Thailand, Singapore, Hong Kong)
- Programs: Alaska Mileage Plan, AAdvantage, Amex Membership Rewards, Chase Ultimate Rewards,
            Cathay Pacific Asia Miles, United MileagePlus, Delta SkyMiles, Capital One Miles
- Airlines: ANA, Singapore Airlines, Cathay Pacific, Qatar Airways
- Budget: points/miles for flights; cash open for hotels
- Thresholds: Asia RT <$700, Europe RT <$550, Central America RT <$350

When advising, include:
- Which program to use and miles/points required
- Transfer partners and any active transfer bonuses
- Tips for finding award space (seats.aero, point.me, AwardHacker)
- Cents-per-point value vs just buying cash
- Any time-sensitive deal context

Keep it actionable and phone-friendly. Lead with the best move RIGHT NOW."""


def fetch_live_deals() -> dict | None:
    """Fetch current deal data from the flight-tracker GitHub repo.
    Uses GITHUB_TOKEN env var if set (needed for private repo access).
    """
    import os
    import urllib.request
    try:
        req = urllib.request.Request(RESULTS_JSON_URL)
        token = os.environ.get("GITHUB_TOKEN", "")
        if token:
            req.add_header("Authorization", f"token {token}")
        req.add_header("Accept", "application/vnd.github.v3.raw")
        with urllib.request.urlopen(req, timeout=8) as resp:
            return json.loads(resp.read().decode())
    except Exception:
        return None


def _format_deals_for_context(data: dict) -> str:
    """Format results.json into a compact LLM context block."""
    if not data:
        return ""

    last_updated = data.get("lastUpdated", "")
    if last_updated:
        try:
            dt = datetime.datetime.fromisoformat(last_updated.replace("Z", "+00:00"))
            age = (datetime.datetime.now(datetime.timezone.utc) - dt).days
            age_str = "today" if age == 0 else f"{age}d ago"
        except Exception:
            age_str = "recently"
    else:
        age_str = "recently"

    deals = data.get("deals", [])
    alert_deals = [d for d in deals if d.get("priority") in ("steal", "alert", "info")]

    if not alert_deals:
        return f"Last scan: {age_str}. No deals currently meeting thresholds."

    lines = [f"Live flight deal data (scanned {age_str}, Mon/Wed/Fri 8AM EST):"]
    lines.append(f"Routes searched: {', '.join(data.get('searchedRoutes', [])[:8])}")
    lines.append("")

    steals = [d for d in alert_deals if d.get("priority") == "steal"]
    alerts = [d for d in alert_deals if d.get("priority") == "alert"]
    awards = [d for d in alert_deals if d.get("priority") == "info"]

    if steals:
        lines.append(f"🔥 STEALS ({len(steals)}):")
        for d in steals[:4]:
            pct = f" ({d.get('pctUnder', 0)}% under threshold)" if d.get("pctUnder") else ""
            lines.append(f"  {d.get('route')} — {d.get('price')}{pct} | {d.get('meta', '')}")
            if d.get("details"):
                lines.append(f"    Context: {d['details'][:120]}")

    if alerts:
        lines.append(f"\n🔔 DEALS ({len(alerts)}):")
        for d in alerts[:4]:
            lines.append(f"  {d.get('route')} — {d.get('price')} | {d.get('meta', '')}")

    if awards:
        lines.append(f"\n✨ AWARD SPACE ({len(awards)}):")
        for d in awards[:4]:
            lines.append(f"  {d.get('route')} — {d.get('price')} via {d.get('source', '?')} | {d.get('meta', '')}")

    return "\n".join(lines)


def get_status() -> dict:
    """Return structured status for the dashboard."""
    data = fetch_live_deals()
    if not data:
        return {"live": False, "last_updated": None, "steals": 0, "alerts": 0, "awards": 0, "deals": []}

    deals = data.get("deals", [])
    return {
        "live": True,
        "last_updated": data.get("lastUpdated"),
        "searched_routes": data.get("searchedRoutes", []),
        "steals": sum(1 for d in deals if d.get("priority") == "steal"),
        "alerts": sum(1 for d in deals if d.get("priority") == "alert"),
        "awards": sum(1 for d in deals if d.get("priority") == "info"),
        "below": sum(1 for d in deals if d.get("priority") == "low"),
        "deals": [d for d in deals if d.get("priority") in ("steal", "alert", "info")][:6],
    }


def handle(message: str) -> str:
    msg_lower = message.lower()

    # Try to fetch live deal data first
    live_data = fetch_live_deals()
    live_context = _format_deals_for_context(live_data) if live_data else ""

    # Force scan / status check — just return live data summary
    if any(k in msg_lower for k in ["scan", "deals", "status", "what's available", "what deals"]):
        if live_context:
            prompt = f"Summarize the current flight deals for Justin and give your top recommendation:\n\n{live_context}"
            return chat(SYSTEM, prompt, max_tokens=700)
        else:
            # Fall back to web search
            results = []
            for q in [
                "best award flight NYC Tokyo business class 2026",
                "Alaska Mileage Plan ANA business class award space 2026",
            ]:
                results.extend(search(q, max_results=4))
            context = format_results(results[:10])
            prompt = f"What are the best award travel opportunities right now?\n\n{context}"
            return chat(SYSTEM, prompt, max_tokens=700)

    # Award / miles / points question — blend live data + search
    if any(k in msg_lower for k in ["award", "miles", "points", "transfer", "redemption", "sweet spot"]):
        search_q = message if len(message) > 10 else "award flight NYC Asia business class miles 2026"
        results = search(search_q, max_results=5)
        context_parts = []
        if live_context:
            context_parts.append(live_context)
        if results:
            context_parts.append(format_results(results))
        prompt = f"{message}\n\n{'--- ' + chr(10).join(context_parts) if context_parts else ''}"
        return chat(SYSTEM, prompt, max_tokens=800)

    # General question — use live data as context if available
    if live_context:
        prompt = f"{message}\n\nContext — current live deals:\n{live_context}"
    else:
        prompt = message

    return chat(SYSTEM, prompt, max_tokens=800)
