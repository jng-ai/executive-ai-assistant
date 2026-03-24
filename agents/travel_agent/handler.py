"""
Travel Hacker Agent — award flight alerts, miles optimization, and cash deal hunting.

Data sources:
1. jng-ai/flight-tracker (GitHub Actions, Mon/Wed/Fri 8AM EST)
   → https://raw.githubusercontent.com/jng-ai/flight-tracker/main/docs/results.json
2. escape.flights NYC RSS feed (curated cash fare deals)
   → https://escape.flights/category/flights-from-new-york/feed/

Features:
- Live award/cash deal tracking from flight-tracker repo
- escape.flights deal ingestion with IATA code resolution
- Extended weekend option generator (Fri-Sun, Fri-Mon, Thu-Mon)
  including Sunday-return pricing context
- Kayak + Google Flights deep links for each trip option

Justin's profile:
- Base: NYC (JFK/EWR/LGA)
- Goals: Business class to Asia (Tokyo, Bangkok, Singapore, Hong Kong)
- Programs: Alaska Mileage Plan, AAdvantage, Amex MR, Chase UR, Cathay Asia Miles
- Thresholds: Asia RT <$700, Europe RT <$550, etc.
"""

import re
import json
import datetime
from core.llm import chat
from core.search import search, format_results

# ─── Live results URL ─────────────────────────────────────────────────────────
RESULTS_JSON_URL = (
    "https://raw.githubusercontent.com/jng-ai/flight-tracker/main/docs/results.json"
)

ESCAPE_FLIGHTS_RSS = (
    "https://escape.flights/category/flights-from-new-york/feed/"
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
- For cash deals: extended weekend options (Fri-Mon or Thu-Mon) and Sunday vs Monday return pricing

Keep it actionable and phone-friendly. Lead with the best move RIGHT NOW."""

# ─── IATA code lookup ─────────────────────────────────────────────────────────
# City name (lowercase) → primary IATA code
DESTINATION_IATA: dict[str, str] = {
    # Europe
    "madrid": "MAD", "barcelona": "BCN", "stockholm": "ARN", "reykjavik": "KEF",
    "london": "LHR", "paris": "CDG", "rome": "FCO", "milan": "MXP",
    "amsterdam": "AMS", "lisbon": "LIS", "dublin": "DUB", "zurich": "ZRH",
    "munich": "MUC", "frankfurt": "FRA", "vienna": "VIE", "brussels": "BRU",
    "copenhagen": "CPH", "oslo": "OSL", "helsinki": "HEL", "warsaw": "WAW",
    "prague": "PRG", "budapest": "BUD", "athens": "ATH", "istanbul": "IST",
    "dubrovnik": "DBV", "split": "SPU", "zagreb": "ZAG", "krakow": "KRK",
    "edinburgh": "EDI", "glasgow": "GLA", "nice": "NCE", "marseille": "MRS",
    "lyon": "LYS", "venice": "VCE", "florence": "FLR", "naples": "NAP",
    "palermo": "PMO", "tallinn": "TLL", "riga": "RIX", "vilnius": "VNO",
    "sofia": "SOF", "bucharest": "OTP", "belgrade": "BEG", "sarajevo": "SJJ",
    "tirana": "TIA",
    # Middle East / Africa
    "dubai": "DXB", "abu dhabi": "AUH", "doha": "DOH", "tel aviv": "TLV",
    "amman": "AMM", "beirut": "BEY", "muscat": "MCT", "cairo": "CAI",
    "nairobi": "NBO", "accra": "ACC", "cape town": "CPT", "johannesburg": "JNB",
    "marrakech": "RAK", "casablanca": "CMN",
    # Asia
    "tokyo": "NRT", "osaka": "KIX", "kyoto": "KIX", "seoul": "ICN",
    "beijing": "PEK", "shanghai": "PVG", "hong kong": "HKG", "taipei": "TPE",
    "bangkok": "BKK", "singapore": "SIN", "bali": "DPS", "jakarta": "CGK",
    "kuala lumpur": "KUL", "manila": "MNL", "hanoi": "HAN",
    "ho chi minh city": "SGN", "phnom penh": "PNH", "yangon": "RGN",
    "mumbai": "BOM", "delhi": "DEL", "bangalore": "BLR", "chennai": "MAA",
    "colombo": "CMB", "kathmandu": "KTM", "dhaka": "DAC",
    # Americas
    "cancun": "CUN", "mexico city": "MEX", "guadalajara": "GDL",
    "monterrey": "MTY", "san jose": "SJO", "panama city": "PTY",
    "bogota": "BOG", "medellin": "MDE", "cartagena": "CTG",
    "lima": "LIM", "quito": "UIO", "buenos aires": "EZE",
    "santiago": "SCL", "sao paulo": "GRU", "rio de janeiro": "GIG",
    "toronto": "YYZ", "montreal": "YUL", "vancouver": "YVR",
    "miami": "MIA", "los angeles": "LAX", "chicago": "ORD",
    "san francisco": "SFO", "seattle": "SEA", "denver": "DEN",
    "atlanta": "ATL", "dallas": "DFW", "portland": "PDX",
    "phoenix": "PHX", "las vegas": "LAS", "honolulu": "HNL",
    "kailua-kona": "KOA", "kailua kona": "KOA", "maui": "OGG",
    "nashville": "BNA", "new orleans": "MSY", "austin": "AUS",
    "boston": "BOS", "washington": "DCA", "philadelphia": "PHL",
    "detroit": "DTW", "minneapolis": "MSP", "salt lake city": "SLC",
    "san diego": "SAN", "houston": "IAH", "charlotte": "CLT",
    "raleigh": "RDU", "pittsburgh": "PIT", "cleveland": "CLE",
    "columbus": "CMH", "indianapolis": "IND", "kansas city": "MCI",
    "st. louis": "STL", "memphis": "MEM", "oklahoma city": "OKC",
    "tampa": "TPA", "orlando": "MCO", "fort lauderdale": "FLL",
    "west palm beach": "PBI", "jacksonville": "JAX", "savannah": "SAV",
}

MONTH_MAP = {
    "jan": 1, "feb": 2, "mar": 3, "apr": 4, "may": 5, "jun": 6,
    "jul": 7, "aug": 8, "sep": 9, "oct": 10, "nov": 11, "dec": 12,
    "january": 1, "february": 2, "march": 3, "april": 4,
    "june": 6, "july": 7, "august": 8, "september": 9,
    "october": 10, "november": 11, "december": 12,
}


# ─── Helper: month string parser ──────────────────────────────────────────────

def _parse_months(months_str: str) -> list[int]:
    """Parse travel window like 'Mar-Apr, Sep-Nov' → [3, 4, 9, 10, 11]."""
    result: set[int] = set()
    for part in months_str.lower().strip("[] ()").split(","):
        part = part.strip()
        if "-" in part:
            m1, m2 = part.split("-", 1)
            n1 = MONTH_MAP.get(m1.strip()[:3])
            n2 = MONTH_MAP.get(m2.strip()[:3])
            if n1 and n2:
                if n1 <= n2:
                    result.update(range(n1, n2 + 1))
                else:  # wraps year, e.g. Nov-Mar
                    result.update(range(n1, 13))
                    result.update(range(1, n2 + 1))
        else:
            n = MONTH_MAP.get(part.strip()[:3])
            if n:
                result.add(n)
    return sorted(result)


# ─── Helper: extended weekend finder ─────────────────────────────────────────

def _next_weekend_options(month_nums: list[int], n: int = 2) -> list[dict]:
    """
    Find the next N upcoming Fridays whose month is in month_nums.
    Returns options with Thu/Fri departure and Sun/Mon return dates.
    """
    today = datetime.date.today()
    options = []

    # Find the next Friday from today
    days_to_friday = (4 - today.weekday()) % 7  # Friday=4
    if days_to_friday == 0:
        days_to_friday = 7  # don't use today if already Friday

    next_fri = today + datetime.timedelta(days=days_to_friday)
    look_ahead = today + datetime.timedelta(days=150)  # ~5 months

    while next_fri <= look_ahead and len(options) < n:
        if next_fri.month in month_nums:
            options.append({
                "thu": (next_fri - datetime.timedelta(days=1)).isoformat(),
                "fri": next_fri.isoformat(),
                "sun": (next_fri + datetime.timedelta(days=2)).isoformat(),
                "mon": (next_fri + datetime.timedelta(days=3)).isoformat(),
            })
        next_fri += datetime.timedelta(days=7)

    return options


# ─── Helper: booking link builder ────────────────────────────────────────────

def _kayak_url(dest: str, depart: str, ret: str, origin: str = "NYC") -> str:
    """Generate a Kayak flights search URL."""
    return f"https://www.kayak.com/flights/{origin}-{dest}/{depart}/{ret}"


def _google_flights_url(dest: str, depart: str, ret: str, origin: str = "NYC") -> str:
    """Generate a Google Flights search URL."""
    return (
        f"https://www.google.com/travel/flights?q=flights+from+{origin}+to+"
        f"{dest}+on+{depart}+returning+{ret}"
    )


# ─── Helper: route extractor from deal title ─────────────────────────────────

def _extract_route(title: str) -> tuple[str, str, str, str]:
    """
    Parse escape.flights title like:
      'Nonstop Flights: New York to Madrid $339-$357 round-trip [Mar-Apr] – Iberia'
    Returns: (dest_city, price_str, months_str, airline)
    """
    # Destination: after "New York to/from " and before "$"
    dest_match = re.search(r"New York (?:to|from) (.+?)\s*\$", title, re.IGNORECASE)
    dest_city = dest_match.group(1).strip() if dest_match else ""
    # Strip trailing country: "Madrid, Spain" → "Madrid"
    if ", " in dest_city:
        dest_city = dest_city.split(", ")[0]

    # Price: "$339-$357" or "$430"
    price_match = re.search(r"\$[\d,]+(?:[–\-]\$[\d,]+)?", title)
    price_str = price_match.group(0) if price_match else ""

    # Months: content inside [...]
    months_match = re.search(r"\[([^\]]+)\]", title)
    months_str = months_match.group(1) if months_match else ""

    # Airline: after last "–" or "-"
    airline_match = re.search(r"[–\-]\s*([^–\-\[\]]+)\s*$", title)
    airline = airline_match.group(1).strip() if airline_match else ""

    return dest_city, price_str, months_str, airline


# ─── escape.flights RSS fetcher ───────────────────────────────────────────────

def _fetch_escape_rss() -> list[dict]:
    """
    Fetch and parse escape.flights NYC deal RSS feed.
    Enriches each deal with IATA codes and extended weekend booking links.
    """
    import urllib.request
    import xml.etree.ElementTree as ET

    try:
        req = urllib.request.Request(
            ESCAPE_FLIGHTS_RSS,
            headers={"User-Agent": "Mozilla/5.0 (compatible; ExecutiveAIBot/1.0)"},
        )
        with urllib.request.urlopen(req, timeout=10) as resp:
            content = resp.read()

        root = ET.fromstring(content)
        today = datetime.date.today()
        deals = []

        for item in root.findall(".//item")[:15]:
            title = item.findtext("title") or ""
            link = item.findtext("link") or ""
            pub_date = item.findtext("pubDate") or ""

            # Try content:encoded first, fall back to description
            desc_elem = item.find("{http://purl.org/rss/1.0/modules/content/}encoded")
            desc = (desc_elem.text or "") if desc_elem is not None else (item.findtext("description") or "")

            dest_city, price_str, months_str, airline = _extract_route(title)
            dest_iata = DESTINATION_IATA.get(dest_city.lower(), "")

            month_nums = _parse_months(months_str) if months_str else []
            # Only keep upcoming months
            upcoming = [m for m in month_nums if m >= today.month]
            weekend_opts = _next_weekend_options(upcoming) if upcoming else []

            deals.append({
                "title": title,
                "url": link,
                "published": pub_date,
                "dest_city": dest_city,
                "dest_iata": dest_iata,
                "price": price_str,
                "months": months_str,
                "airline": airline,
                "weekend_options": weekend_opts,
                "description": desc[:400] if desc else "",
                "source": "escape.flights",
            })

        return deals
    except Exception:
        return []


def _format_escape_deals(deals: list[dict]) -> str:
    """Format escape.flights deals with booking links for LLM context."""
    if not deals:
        return ""

    lines = ["📡 Current NYC Cash Deals (escape.flights — curated, manually verified):"]
    for d in deals[:10]:
        dest = d.get("dest_iata", "")
        months = d.get("months", "")
        price = d.get("price", "")
        airline = d.get("airline", "")
        title = d.get("title", "")

        # Compact one-liner
        label = f"  ✈ {d['dest_city']} {price}"
        if airline:
            label += f" via {airline}"
        if months:
            label += f" [{months}]"
        lines.append(label)

        # Weekend booking links
        opts = d.get("weekend_options", [])
        if dest and opts:
            o = opts[0]
            lines.append(f"    📅 Next extended weekend:")
            lines.append(
                f"      Fri-Sun  ({o['fri']} → {o['sun']}): "
                f"{_kayak_url(dest, o['fri'], o['sun'])}"
            )
            lines.append(
                f"      Fri-Mon  ({o['fri']} → {o['mon']}): "
                f"{_kayak_url(dest, o['fri'], o['mon'])}"
            )
            lines.append(
                f"      Thu-Mon  ({o['thu']} → {o['mon']}): "
                f"{_kayak_url(dest, o['thu'], o['mon'])}"
            )
            lines.append(f"      💡 Sunday returns are often $20–60 cheaper than Monday")
            # Second weekend if available
            if len(opts) > 1:
                o2 = opts[1]
                lines.append(
                    f"    📅 Weekend after: Fri-Mon ({o2['fri']} → {o2['mon']}): "
                    f"{_kayak_url(dest, o2['fri'], o2['mon'])}"
                )
        elif dest and months:
            lines.append(
                f"    🔍 Search: {_kayak_url(dest, 'flexible', 'flexible')}"
            )

        lines.append(f"    🔗 {d['url']}")

    return "\n".join(lines)


# ─── Flight-tracker repo fetcher ─────────────────────────────────────────────

def fetch_live_deals() -> dict | None:
    """Fetch current deal data from the flight-tracker GitHub repo."""
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


def _format_live_deals(data: dict) -> str:
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
        return f"flight-tracker last scan: {age_str}. No deals currently meeting thresholds."

    lines = [f"🛫 Award/Tracker Deals (scanned {age_str}):"]
    lines.append(f"Routes: {', '.join(data.get('searchedRoutes', [])[:8])}")

    steals = [d for d in alert_deals if d.get("priority") == "steal"]
    alerts = [d for d in alert_deals if d.get("priority") == "alert"]
    awards = [d for d in alert_deals if d.get("priority") == "info"]

    if steals:
        lines.append(f"\n🔥 STEALS ({len(steals)}):")
        for d in steals[:4]:
            pct = f" ({d.get('pctUnder', 0)}% under)" if d.get("pctUnder") else ""
            lines.append(f"  {d.get('route')} — {d.get('price')}{pct} | {d.get('meta', '')}")
            if d.get("details"):
                lines.append(f"    {d['details'][:120]}")

    if alerts:
        lines.append(f"\n🔔 DEALS ({len(alerts)}):")
        for d in alerts[:4]:
            lines.append(f"  {d.get('route')} — {d.get('price')} | {d.get('meta', '')}")

    if awards:
        lines.append(f"\n✨ AWARD SPACE ({len(awards)}):")
        for d in awards[:4]:
            lines.append(f"  {d.get('route')} — {d.get('price')} via {d.get('source', '?')} | {d.get('meta', '')}")

    return "\n".join(lines)


# ─── Dashboard status ─────────────────────────────────────────────────────────

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


# ─── Main handler ─────────────────────────────────────────────────────────────

def handle(message: str) -> str:
    msg_lower = message.lower()

    # Fetch both data sources (escape.flights is lightweight RSS; live deals from tracker)
    live_data = fetch_live_deals()
    escape_deals = _fetch_escape_rss()

    live_context = _format_live_deals(live_data) if live_data else ""
    escape_context = _format_escape_deals(escape_deals) if escape_deals else ""

    def _combined_context() -> str:
        parts = []
        if live_context:
            parts.append(live_context)
        if escape_context:
            parts.append(escape_context)
        return "\n\n".join(parts)

    # Weekend / getaway query — lead with escape.flights + booking links
    if any(k in msg_lower for k in ["weekend", "getaway", "quick trip", "extended weekend",
                                     "long weekend", "thursday", "friday", "monday return",
                                     "sunday return"]):
        ctx = _combined_context()
        prompt = (
            f"{message}\n\n"
            f"Focus on extended weekend options (Fri-Mon or Thu-Mon). "
            f"Sunday returns are often significantly cheaper than Monday. "
            f"Include the Kayak booking links provided for each option.\n\n"
            f"Current deal data:\n{ctx}"
        )
        return chat(SYSTEM, prompt, max_tokens=900)

    # Deal scan / status
    if any(k in msg_lower for k in ["scan", "deals", "status", "what's available", "what deals",
                                     "show me deals", "any deals"]):
        ctx = _combined_context()
        if ctx:
            prompt = (
                f"Summarize current flight deals for Justin. "
                f"For any cash deals with weekend options and Kayak links, highlight those. "
                f"Give your top recommendation.\n\n{ctx}"
            )
            return chat(SYSTEM, prompt, max_tokens=800)
        # Fall back to web search
        results = []
        for q in [
            "best award flight NYC Tokyo business class 2026",
            "Alaska Mileage Plan ANA business class award space 2026",
        ]:
            results.extend(search(q, max_results=4))
        ctx = format_results(results[:10])
        prompt = f"What are the best award travel opportunities right now?\n\n{ctx}"
        return chat(SYSTEM, prompt, max_tokens=700)

    # Award / miles / points question
    if any(k in msg_lower for k in ["award", "miles", "points", "transfer", "redemption", "sweet spot"]):
        search_q = message if len(message) > 10 else "award flight NYC Asia business class miles 2026"
        results = search(search_q, max_results=5)
        parts = []
        if live_context:
            parts.append(live_context)
        if results:
            parts.append(format_results(results))
        prompt = f"{message}\n\n{'--- ' + chr(10).join(parts) if parts else ''}"
        return chat(SYSTEM, prompt, max_tokens=800)

    # Specific destination query — pull escape.flights deals for that destination + booking links
    for city, iata in DESTINATION_IATA.items():
        if city in msg_lower or iata.lower() in msg_lower:
            # Find matching escape deals
            matching = [
                d for d in escape_deals
                if city in d.get("dest_city", "").lower() or d.get("dest_iata") == iata
            ]
            ctx_parts = []
            if matching:
                ctx_parts.append(_format_escape_deals(matching))
            if live_context:
                ctx_parts.append(live_context)
            ctx = "\n\n".join(ctx_parts) if ctx_parts else _combined_context()
            prompt = (
                f"{message}\n\n"
                f"If there are cash deals for this destination, include the extended weekend "
                f"Kayak booking links. Also advise on award options.\n\n{ctx}"
            )
            return chat(SYSTEM, prompt, max_tokens=900)

    # General question — blend all context
    ctx = _combined_context()
    if ctx:
        prompt = f"{message}\n\nCurrent deal context:\n{ctx}"
    else:
        prompt = message

    return chat(SYSTEM, prompt, max_tokens=800)
