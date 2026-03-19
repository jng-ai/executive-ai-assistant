"""
NYC Social & Events Agent — personalized free event scout for Justin Ngai.

Sources: Luma (lu.ma/nyc), Eventbrite, "RSVP NYC" Twitter/X style searches,
         Instagram events, Japanese/AAPI/healthcare community events.
Features:
  - handle()          — on-demand query (responds to Telegram messages)
  - run_event_scan()  — proactive scheduled scan, sends Telegram alert if hot events found
                        (runs 2x/week via APScheduler in bot.py)
"""

import time
import datetime
from core.llm import chat
from core.search import search, format_results

# ── Justin's identity context ─────────────────────────────────────────────────

SYSTEM = """You are an NYC event scout. Surface the best FREE or very low-cost upcoming NYC events.

Priority event types (in order):
1. Healthcare / health-tech / digital health networking
2. Tech / startup / AI demo nights
3. Asian / AAPI / Japanese / Hong Kong cultural or professional events
4. Pop-up events (food, art, retail, experiences — anything flash/one-time)
5. Food & drink events (tastings, happy hours, open bars, ramen, sake, dim sum)
6. General free NYC networking and community events

Sources to surface links from when found: Luma (lu.ma), Eventbrite, Partiful, X/Twitter
RSVP posts, Time Out NYC, Thrillist, Reddit r/nyc, nycfreeevents.com.

Format each event as:
🗓 *[Event Name]*
📍 [Venue / Neighborhood]
🕐 [Date & Time]
💰 [Free / Cost]
📌 [Source: Luma / Eventbrite / 𝕏 / Partiful / etc.]
🔗 [RSVP or event link — include if found]
✨ [One line: why this is worth going to]

Rules:
- Only include events that are UPCOMING (on or after today)
- Prioritize events with a direct RSVP link
- If a pop-up or flash event is found, always include it regardless of category
- If X/Twitter posts with event links are in the results, surface them
- At the end: bold the single top pick and say why in one line"""

# Keywords that warrant an immediate proactive alert (don't wait for weekly roundup)
HOT_KEYWORDS = [
    "free food", "free drinks", "open bar", "complimentary drinks", "happy hour",
    "food and drink", "drinks included", "networking reception", "cocktail reception",
    "sake", "ramen", "izakaya", "dim sum", "japanese", "hong kong", "cantonese",
    "aapi", "asian american", "food festival", "tasting", "wine tasting",
    "pop-up", "popup", "pop up", "flash event", "drop-in",
    "tech networking", "healthcare networking", "startup", "demo night",
]


def _get_date_range() -> tuple[str, str, str]:
    """Returns (today_str, end_str, today_iso) for filtering and display."""
    today = datetime.date.today()
    end = today + datetime.timedelta(days=10)
    return today.strftime("%B %d"), end.strftime("%B %d, %Y"), today.isoformat()


# ── Query bank — organized by source/theme ────────────────────────────────────

def _build_queries(focus: str = "") -> list[str]:
    """Build diverse search queries across all sources targeting Justin's interest areas."""
    start, end, today_iso = _get_date_range()

    base_queries = [
        # ── X / Twitter RSVP NYC (actual X posts with links) ──────────────────
        f'site:x.com "RSVP NYC" {start} 2026 link free event',
        f'site:twitter.com "RSVP NYC" free event link {start} 2026',
        f'site:x.com NYC free event "link in bio" OR "RSVP" {start} 2026',
        f'"RSVP NYC" OR "NYC free event" site:x.com 2026',

        # ── Luma ──────────────────────────────────────────────────────────────
        f'site:lu.ma NYC free events {start} 2026',
        f'site:lu.ma NYC healthcare tech AAPI Japanese free {start} 2026',
        f'lu.ma/nyc pop-up free networking {start} 2026',

        # ── Eventbrite ────────────────────────────────────────────────────────
        f'site:eventbrite.com NYC free events {start} 2026 healthcare tech Asian',
        f'site:eventbrite.com NYC free networking {start} 2026',
        f'site:eventbrite.com NYC pop-up free {start} 2026',

        # ── Partiful (pop-up party app) ───────────────────────────────────────
        f'site:partiful.com NYC free event {start} 2026',
        f'partiful NYC pop-up party free {start} 2026',

        # ── Healthcare & tech ─────────────────────────────────────────────────
        f'NYC free healthcare leadership networking events {start} 2026',
        f'NYC free health tech digital health networking events {start} 2026',
        f'NYC free startup tech demo networking event {start} 2026',
        f'NYC free AI tech founder networking event {start} 2026',

        # ── Asian / AAPI / Japanese / Hong Kong ───────────────────────────────
        f'NYC free Japanese cultural events {start} 2026',
        f'NYC free AAPI Asian American professional networking {start} 2026',
        f'NYC free Hong Kong Cantonese community events {start} 2026',
        f'NYC Japan Society free events {start} 2026',
        f'NYC Asian Pacific American free events networking {start} 2026',

        # ── Pop-up events ─────────────────────────────────────────────────────
        f'NYC pop-up free event this week {start} 2026 food drinks art',
        f'NYC free pop-up market shop food drink {start} 2026',
        f'NYC flash event drop-in free {start} 2026',
        f'site:timeout.com NYC free events this week 2026',
        f'site:thrillist.com NYC free events {start} 2026',
        f'nycfreeevents.com {start} 2026',

        # ── General free NYC ──────────────────────────────────────────────────
        f'free NYC events this week {start} {end} food drinks networking 2026',
        f'NYC free events {start} 2026 site:reddit.com r/nyc OR r/nycevents',

        # ── Investor / finance ────────────────────────────────────────────────
        f'NYC free investor real estate finance networking {start} 2026',
    ]

    if focus:
        base_queries.insert(0, f'NYC free events {focus} {start} 2026')
        base_queries.insert(1, f'site:lu.ma NYC {focus} free {start} 2026')
        base_queries.insert(2, f'site:eventbrite.com NYC {focus} free {start} 2026')

    return base_queries


# ── Source labels for display ─────────────────────────────────────────────────

SOURCE_LABELS = {
    "x.com": "𝕏",
    "twitter.com": "𝕏",
    "lu.ma": "Luma",
    "eventbrite.com": "Eventbrite",
    "partiful.com": "Partiful",
    "timeout.com": "Time Out",
    "thrillist.com": "Thrillist",
    "reddit.com": "Reddit",
}


def _is_hot_event(text: str) -> bool:
    """Return True if event description contains high-priority trigger keywords."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in HOT_KEYWORDS)


def _search_events(queries: list[str], max_per_query: int = 5) -> list[dict]:
    """Run searches and return deduplicated results."""
    all_results = []
    seen_urls = set()

    for q in queries:
        results = search(q, max_results=max_per_query)
        for r in results:
            if r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                all_results.append(r)
        time.sleep(0.25)

    return all_results


def _pull_calendar_context() -> str:
    """Get Justin's recent/upcoming calendar events to infer past event themes."""
    try:
        from integrations.google.calendar_client import list_events
        from integrations.google.auth import is_configured
        if not is_configured():
            return ""
        events = list_events(days_ahead=30)
        if not events:
            return ""
        titles = [ev.get("summary", "") for ev in events[:10] if ev.get("summary")]
        return "Justin's recent calendar events (for context on his interests): " + ", ".join(titles)
    except Exception:
        return ""


# ── On-demand handler ─────────────────────────────────────────────────────────

def handle(message: str = "") -> str:
    """Respond to a user's on-demand request for NYC events."""
    msg_lower = message.lower()

    # Detect specific focus from message
    if any(w in msg_lower for w in ["pop-up", "popup", "pop up", "flash", "drop-in"]):
        focus = "pop-up flash event"
    elif any(w in msg_lower for w in ["tech", "startup", "ai", "founder", "demo"]):
        focus = "tech startup AI networking"
    elif any(w in msg_lower for w in ["health", "medical", "hospital", "healthcare", "digital health"]):
        focus = "healthcare health-tech networking"
    elif any(w in msg_lower for w in ["japanese", "japan", "sake", "ramen", "izakaya"]):
        focus = "Japanese cultural"
    elif any(w in msg_lower for w in ["hong kong", "cantonese", "dim sum"]):
        focus = "Hong Kong Cantonese"
    elif any(w in msg_lower for w in ["aapi", "asian american", "asian"]):
        focus = "AAPI Asian American professional"
    elif any(w in msg_lower for w in ["invest", "real estate", "mortgage", "stock", "finance"]):
        focus = "investor networking real estate finance"
    elif any(w in msg_lower for w in ["travel", "miles", "points", "award"]):
        focus = "travel points miles enthusiast meetup"
    elif any(w in msg_lower for w in ["food", "drink", "eat", "tasting", "happy hour"]):
        focus = "food drink tasting happy hour free"
    elif any(w in msg_lower for w in ["club", "community", "join", "meet people"]):
        focus = "community club social networking"
    else:
        focus = ""

    queries = _build_queries(focus)
    results = _search_events(queries[:9])  # 9 queries on-demand for broad coverage

    if not results:
        return (
            "🗓 *NYC Events*\n\n"
            "Search returned no results right now. Try asking about a specific type "
            "of event (Japanese, AAPI, healthcare, food & drinks, investor meetup, etc.)\n\n"
            "I also browse: Luma (lu.ma/nyc), Eventbrite, and RSVP NYC."
        )

    start, end, today_iso = _get_date_range()
    cal_context = _pull_calendar_context()
    context_block = format_results(results[:20])

    prompt = (
        f"Today's date is {today_iso}. Find the best 5–7 FREE or very low-cost NYC events "
        f"that are UPCOMING — strictly on or after today ({start}). "
        f"Do NOT include any events that have already passed.\n\n"
        f"Date window: {start}–{end}\n\n"
        f"{cal_context}\n\n"
        f"Search results:\n{context_block}\n\n"
        f"Priority order: (1) healthcare/health-tech, (2) tech/startup/AI, "
        f"(3) Asian/AAPI/Japanese/HK cultural or professional, (4) pop-ups and flash events, "
        f"(5) food & drink, (6) general free NYC.\n"
        f"If any X/Twitter posts with event RSVP links appear in results, include them — "
        f"label source as 𝕏. Include Partiful links if found.\n"
        f"If recurring clubs or communities appear that are worth joining long-term, call them out.\n"
        f"User query: {message}"
    )

    return chat(SYSTEM, prompt, max_tokens=900)


# ── Scheduled proactive scan ──────────────────────────────────────────────────

def run_event_scan(send_all: bool = False) -> str:
    """
    Proactive scheduled scan — meant to be called by APScheduler.
    Returns a formatted message to send to Telegram.

    If send_all=True: return full roundup even if no hot events found.
    If send_all=False: only return message if hot events exist (daily-alert mode).
    """
    queries = _build_queries()
    results = _search_events(queries[:14])  # broader scan for scheduled runs

    if not results:
        if send_all:
            return "🗓 *Weekly Events Roundup*\n\nNo new events found this scan. Check lu.ma/nyc manually!"
        return ""

    start, end, today_iso = _get_date_range()
    cal_context = _pull_calendar_context()
    context_block = format_results(results[:25])

    # Check if any results contain hot keywords — if so, flag as immediate alert
    hot = any(_is_hot_event(r.get("content", "") + r.get("title", "")) for r in results)

    if not hot and not send_all:
        return ""  # No hot events — skip sending until next scheduled roundup

    mode_label = "🚨 *Hot Event Alert*" if hot else "🗓 *Weekly NYC Events Roundup*"
    hot_note = (
        "\n_⚡ Flagged: events with free food/drinks or strong profile match detected!_\n"
        if hot else ""
    )

    prompt = (
        f"Today's date is {today_iso}. Find the best 6–8 FREE or very low-cost NYC events "
        f"that are UPCOMING — strictly on or after today ({start}). "
        f"Do NOT include any events that have already passed.\n\n"
        f"Date window: {start}–{end}\n\n"
        f"{cal_context}\n\n"
        f"Search results:\n{context_block}\n\n"
        f"Priority order: (1) healthcare/health-tech, (2) tech/startup/AI, "
        f"(3) Asian/AAPI/Japanese/HK cultural or professional, (4) pop-ups and flash events "
        f"[ALWAYS include any pop-ups found], (5) food & drinks with free food/open bar, "
        f"(6) general free NYC events.\n"
        f"If X/Twitter posts with RSVP links appear, include them labelled as 𝕏. "
        f"Include Partiful links if found. "
        f"If recurring clubs or communities worth joining long-term appear, add a separate "
        f"'🏛 Communities to Join' section at the end.\n"
        f"Format clearly for Telegram. Bold the top pick."
    )

    body = chat(SYSTEM, prompt, max_tokens=900)

    return f"{mode_label}{hot_note}\n\n{body}"
