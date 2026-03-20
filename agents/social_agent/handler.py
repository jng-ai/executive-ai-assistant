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
from concurrent.futures import ThreadPoolExecutor, as_completed
from core.llm import chat
from core.search import search, fetch_page, format_results

# ── Justin's identity context ─────────────────────────────────────────────────

SYSTEM = """You are an NYC event scout. Surface the best FREE or very low-cost upcoming NYC events.

CRITICAL DATE RULE: You MUST only surface events that have NOT yet occurred. If a date appears
in the search results that is before today's date, IGNORE that event entirely. Do not mention it.
If you are unsure whether an event is upcoming or past, exclude it. When in doubt, leave it out.

Priority event types (in order):
1. Healthcare / health-tech / digital health networking
2. Tech / startup / AI demo nights
3. Asian / AAPI / Japanese / Hong Kong cultural or professional events
4. Pop-up events (food, art, retail, experiences — anything flash/one-time)
5. Food & drink events (tastings, happy hours, open bars, ramen, sake, dim sum)
6. General free NYC networking and community events

Sources to surface links from when found: Luma (lu.ma), Eventbrite, Meetup, Partiful,
X/Twitter RSVP posts, Instagram (#RSVPnyc, #NYCevents, #NYCpopup),
Time Out NYC, Thrillist, Reddit r/nyc, nycfreeevents.com.

When Instagram content appears in results, label it as 📸 Instagram and include the hashtag or
account handle if visible. Instagram posts often surface pop-up events and food/drink events
before they appear on formal listing sites.

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


def _get_date_range() -> tuple[str, str, str, datetime.date]:
    """Returns (today_str, end_str, today_iso, today_date) for filtering and display."""
    today = datetime.date.today()
    end = today + datetime.timedelta(days=10)
    return today.strftime("%B %d"), end.strftime("%B %d, %Y"), today.isoformat(), today


# ── Query bank — organized by source/theme ────────────────────────────────────

def _build_queries(focus: str = "") -> list[str]:
    """Build diverse search queries across all sources targeting Justin's interest areas."""
    start, end, today_iso, today = _get_date_range()

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


def _filter_stale(results: list[dict]) -> list[dict]:
    """
    Drop results that clearly reference past years/months.
    We check for year mentions older than current year and month strings before today.
    This is a fast pre-filter before the LLM sees the data.
    """
    import re
    today = datetime.date.today()
    current_year = today.year
    past_years = [str(y) for y in range(2020, current_year)]

    # Month names that have fully passed this year
    month_names = ["january","february","march","april","may","june",
                   "july","august","september","october","november","december"]
    past_months_this_year = [month_names[i] for i in range(today.month - 1)]  # months before current

    kept = []
    for r in results:
        text = (r.get("title","") + " " + r.get("content","") + " " + r.get("url","")).lower()

        # Drop if it references a clearly past year
        if any(py in text for py in past_years):
            continue

        # Drop if it references a past month + this year (e.g. "january 2026" when it's March)
        stale = False
        for pm in past_months_this_year:
            if pm in text and str(current_year) in text:
                stale = True
                break
        if stale:
            continue

        kept.append(r)

    # If filtering removed everything, return original (better than empty)
    return kept if kept else results


def _fetch_luma() -> list[dict]:
    """
    Directly crawl Luma NYC event listing pages.
    This gets actual upcoming events, not just indexed search snippets.
    """
    start, end, today_iso, today = _get_date_range()
    results = []

    # Direct Luma NYC discover pages
    luma_urls = [
        "https://lu.ma/nyc",
        "https://lu.ma/discover?query=NYC+free&start=today",
        "https://lu.ma/discover?query=NYC+health+tech&start=today",
        "https://lu.ma/discover?query=NYC+Asian+AAPI&start=today",
    ]
    for url in luma_urls:
        content = fetch_page(url, max_chars=4000)
        if content and len(content) > 200:
            results.append({"title": f"Luma Events: {url}", "url": url, "content": content})

    # Also run targeted Tavily searches to surface specific Luma event pages
    luma_queries = [
        f'site:lu.ma NYC free events {start} 2026',
        f'site:lu.ma NYC healthcare tech startup networking {start} OR {end} 2026',
        f'site:lu.ma NYC AAPI Japanese Asian free {start} 2026',
        f'site:lu.ma NYC pop-up food drink free {start} 2026',
    ]
    for q in luma_queries:
        for r in search(q, max_results=5):
            results.append(r)

    return results


def _fetch_eventbrite() -> list[dict]:
    """
    Directly crawl Eventbrite NYC free event pages + targeted searches.
    """
    start, end, today_iso, today = _get_date_range()
    results = []

    # Direct Eventbrite NYC listing pages
    eb_urls = [
        "https://www.eventbrite.com/d/ny--new-york/free--events/",
        "https://www.eventbrite.com/d/ny--new-york/networking--events/",
        "https://www.eventbrite.com/d/ny--new-york/free--networking--events/",
        "https://www.eventbrite.com/d/ny--new-york/health--events/",
    ]
    for url in eb_urls:
        content = fetch_page(url, max_chars=4000)
        if content and len(content) > 200:
            results.append({"title": f"Eventbrite NYC: {url}", "url": url, "content": content})

    # Tavily searches for specific Eventbrite event pages
    eb_queries = [
        f'site:eventbrite.com NYC free networking {start} 2026',
        f'site:eventbrite.com NYC healthcare tech digital health free {start} 2026',
        f'site:eventbrite.com NYC AAPI Asian professional free {start} 2026',
        f'site:eventbrite.com NYC pop-up food drink free {start} 2026',
    ]
    for q in eb_queries:
        for r in search(q, max_results=5):
            results.append(r)

    return results


def _fetch_meetup() -> list[dict]:
    """
    Fetch Meetup.com NYC events for healthcare, tech, and AAPI groups.
    """
    start, _, today_iso, today = _get_date_range()
    results = []

    meetup_urls = [
        "https://www.meetup.com/find/?location=New+York%2C+NY&source=EVENTS&eventType=inPerson&distance=tenMiles",
        "https://www.meetup.com/find/?keywords=health+tech&location=New+York%2C+NY&source=EVENTS&eventType=inPerson",
        "https://www.meetup.com/find/?keywords=startup+networking&location=New+York%2C+NY&source=EVENTS&eventType=inPerson",
    ]
    for url in meetup_urls:
        content = fetch_page(url, max_chars=3000)
        if content and len(content) > 200:
            results.append({"title": "Meetup NYC Events", "url": url, "content": content})

    meetup_queries = [
        f'site:meetup.com NYC free health tech digital health networking {start} 2026',
        f'site:meetup.com NYC AAPI Asian startup tech networking free {start} 2026',
    ]
    for q in meetup_queries:
        for r in search(q, max_results=3):
            results.append(r)

    return results


def _fetch_x_rsvp() -> list[dict]:
    """
    Scan X/Twitter for RSVP NYC posts.
    X blocks most crawlers, so we try Nitter (X proxy) instances first,
    then fall back to Tavily searches that may surface indexed tweets.
    """
    results = []

    # Try Nitter instances — X-compatible frontend that allows search
    nitter_instances = [
        "https://nitter.privacydev.net/search?q=RSVP+NYC+free&f=tweets",
        "https://nitter.poast.org/search?q=RSVP+NYC+free&f=tweets",
        "https://nitter.1d4.us/search?q=RSVP+NYC+free&f=tweets",
        "https://nitter.net/search?q=RSVP+NYC+free&f=tweets",
    ]
    for url in nitter_instances:
        content = fetch_page(url, max_chars=4000)
        if content and len(content) > 300 and "tweet" in content.lower():
            results.append({"title": "X/Twitter: RSVP NYC", "url": url, "content": content})
            break  # One working Nitter instance is enough

    # Also try fetching @rsvpnyc style aggregator accounts on Nitter
    aggregator_urls = [
        "https://nitter.privacydev.net/search?q=%22RSVP+NYC%22+lu.ma&f=tweets",
        "https://nitter.privacydev.net/search?q=%22NYC+free+event%22+lu.ma+OR+eventbrite&f=tweets",
    ]
    for url in aggregator_urls:
        content = fetch_page(url, max_chars=3000)
        if content and len(content) > 300:
            results.append({"title": "X/Twitter: NYC Free Events", "url": url, "content": content})

    # Fallback: Tavily queries that may surface indexed tweet content
    x_queries = [
        '"RSVP NYC" free event lu.ma OR eventbrite OR partiful 2026',
        '"NYC free event" RSVP link 2026 healthcare OR tech OR popup OR food',
    ]
    for q in x_queries:
        for r in search(q, max_results=4):
            results.append(r)

    return results


def _fetch_instagram() -> list[dict]:
    """
    Scan Instagram for NYC event posts.
    Instagram blocks direct API access, so we use three layers:
    1. Public Instagram viewer proxies (Picuki, Imginn) for hashtag feeds
    2. Tavily site:instagram.com — Google indexes some public posts
    3. Broad searches that surface pages embedding Instagram event posts
    All results are forward-date filtered before reaching the LLM.
    """
    start, end, today_iso, today = _get_date_range()
    results = []

    # ── Layer 1: Public Instagram viewer proxies ──────────────────────────────
    # These allow hashtag browsing without login
    ig_proxy_urls = [
        # Hashtag feeds on Picuki
        "https://www.picuki.com/tag/RSVPnyc",
        "https://www.picuki.com/tag/NYCevents",
        "https://www.picuki.com/tag/NYCfreeevents",
        "https://www.picuki.com/tag/NYCpopup",
        "https://www.picuki.com/tag/NYChealthtech",
        # Imginn as backup proxy
        "https://imginn.com/tags/rsvpnyc/",
        "https://imginn.com/tags/nycevents/",
        "https://imginn.com/tags/nycfreeevents/",
    ]
    for url in ig_proxy_urls:
        content = fetch_page(url, max_chars=3000)
        if content and len(content) > 300:
            results.append({"title": f"Instagram: {url}", "url": url, "content": content})

    # ── Layer 2: Tavily site:instagram.com — indexes some public posts ────────
    ig_search_queries = [
        f'site:instagram.com "RSVP NYC" free event 2026',
        f'site:instagram.com NYC free event {start} 2026',
        f'site:instagram.com NYC popup free {start} 2026',
        f'site:instagram.com NYC health tech networking event {start} 2026',
        f'site:instagram.com NYC AAPI Asian Japanese free event {start} 2026',
        f'site:instagram.com NYC food drink tasting popup {start} 2026',
    ]
    for q in ig_search_queries:
        for r in search(q, max_results=4):
            results.append(r)

    # ── Layer 3: Pages that aggregate or embed Instagram NYC event posts ──────
    agg_queries = [
        f'"instagram" "RSVP NYC" free event {start} 2026',
        f'"instagram.com" NYC free event pop-up RSVP {start} 2026',
    ]
    for q in agg_queries:
        for r in search(q, max_results=3):
            results.append(r)

    return results


def _fetch_other_sources() -> list[dict]:
    """
    Fetch from Partiful, Time Out NYC, Reddit, Thrillist, and other sources.
    """
    start, end, today_iso, today = _get_date_range()
    results = []

    # Direct page fetches
    other_urls = [
        "https://www.timeout.com/newyork/things-to-do/free-things-to-do-in-nyc-this-weekend",
        "https://www.timeout.com/newyork/things-to-do/best-free-events-in-new-york",
        "https://www.nycfreeevents.com",
    ]
    for url in other_urls:
        content = fetch_page(url, max_chars=3000)
        if content and len(content) > 200:
            results.append({"title": f"Events: {url}", "url": url, "content": content})

    # Partiful + Reddit + Thrillist via search
    other_queries = [
        f'site:partiful.com NYC free event {start} 2026',
        f'site:reddit.com r/nyc OR r/nycevents free event RSVP {start} 2026',
        f'site:thrillist.com NYC free events {start} 2026',
        f'NYC Japan Society free events {start} 2026',
        f'NYC free AAPI Asian professional networking event {start} 2026',
        f'NYC free investor real estate finance networking {start} 2026',
    ]
    for q in other_queries:
        for r in search(q, max_results=3):
            results.append(r)

    return results


def _gather_all_events(focus: str = "") -> list[dict]:
    """
    Run all source fetchers in parallel and combine results.
    Returns deduplicated, stale-filtered list.
    """
    fetchers = {
        "luma": _fetch_luma,
        "eventbrite": _fetch_eventbrite,
        "meetup": _fetch_meetup,
        "x_rsvp": _fetch_x_rsvp,
        "instagram": _fetch_instagram,
        "other": _fetch_other_sources,
    }

    all_results = []
    seen_urls = set()

    with ThreadPoolExecutor(max_workers=6) as executor:
        futures = {executor.submit(fn): name for name, fn in fetchers.items()}
        for future in as_completed(futures):
            try:
                for r in future.result():
                    if r.get("url") and r["url"] not in seen_urls:
                        seen_urls.add(r["url"])
                        all_results.append(r)
            except Exception:
                pass

    # Add focus-specific queries on top if user has a specific interest
    if focus:
        start, end, today_iso, today = _get_date_range()
        for q in [
            f'NYC free events {focus} {start} 2026',
            f'site:lu.ma NYC {focus} free {start} 2026',
            f'site:eventbrite.com NYC {focus} free {start} 2026',
        ]:
            for r in search(q, max_results=4):
                if r["url"] not in seen_urls:
                    seen_urls.add(r["url"])
                    all_results.append(r)

    return _filter_stale(all_results)


def _search_events(queries: list[str], max_per_query: int = 5) -> list[dict]:
    """Legacy: run searches and return deduplicated, stale-filtered results."""
    all_results = []
    seen_urls = set()

    for q in queries:
        for r in search(q, max_results=max_per_query):
            if r["url"] not in seen_urls:
                seen_urls.add(r["url"])
                all_results.append(r)
        time.sleep(0.2)

    return _filter_stale(all_results)


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

    results = _gather_all_events(focus=focus)

    if not results:
        return (
            "🗓 *NYC Events*\n\n"
            "Search returned no results right now. Try asking about a specific type "
            "of event (Japanese, AAPI, healthcare, food & drinks, investor meetup, etc.)\n\n"
            "I also browse: Luma (lu.ma/nyc), Eventbrite, and RSVP NYC."
        )

    start, end, today_iso, today = _get_date_range()
    cal_context = _pull_calendar_context()
    context_block = format_results(results[:30])

    prompt = (
        f"TODAY IS {today_iso}. You are finding UPCOMING NYC events.\n\n"
        f"STRICT RULE: Only include events occurring on or after {today_iso}. "
        f"Any event that occurred before today is IRRELEVANT — exclude it completely. "
        f"Do not mention events from January, February, or any past month of {today.year}, "
        f"and do not mention any events from prior years. "
        f"If you are not sure an event is in the future, exclude it.\n\n"
        f"Date window to surface: {start}–{end}\n\n"
        f"{cal_context}\n\n"
        f"Search results:\n{context_block}\n\n"
        f"Priority order: (1) healthcare/health-tech, (2) tech/startup/AI, "
        f"(3) Asian/AAPI/Japanese/HK cultural or professional, (4) pop-ups and flash events, "
        f"(5) food & drink, (6) general free NYC.\n"
        f"If any X/Twitter posts with event RSVP links appear in results, label source as 𝕏. "
        f"If Instagram posts appear (#RSVPnyc, #NYCevents, #NYCpopup), label source as 📸 Instagram. "
        f"Include Partiful, Meetup, and Meetup group links if found.\n"
        f"If recurring clubs or communities appear that are worth joining long-term, call them out.\n"
        f"If fewer than 3 future events are found, say so honestly — do not invent events.\n"
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
    results = _gather_all_events()

    if not results:
        if send_all:
            return "🗓 *Weekly Events Roundup*\n\nNo new events found this scan. Check lu.ma/nyc manually!"
        return ""

    start, end, today_iso, today = _get_date_range()
    cal_context = _pull_calendar_context()
    context_block = format_results(results[:30])

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
        f"TODAY IS {today_iso}. You are finding UPCOMING NYC events for a proactive alert.\n\n"
        f"STRICT RULE: Only include events occurring on or after {today_iso}. "
        f"Any event before today is IRRELEVANT — exclude it entirely. "
        f"Do not mention events from January, February, or any past month of {today.year}, "
        f"and do not mention any events from prior years. "
        f"If you cannot confirm an event is in the future, exclude it.\n\n"
        f"Date window to surface: {start}–{end}\n\n"
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
        f"If fewer than 3 future events are found in the results, say so honestly — do not invent events.\n"
        f"Format clearly for Telegram. Bold the top pick."
    )

    body = chat(SYSTEM, prompt, max_tokens=900)

    return f"{mode_label}{hot_note}\n\n{body}"
