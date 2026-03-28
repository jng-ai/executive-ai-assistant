"""
NYC Social & Events Agent — personalized free event scout for Justin Ngai.

Sources: Luma (lu.ma/nyc), Eventbrite, Meetup, Partiful, Yelp Events,
         nycgo.com, allevents.in, do.nyc, Time Out NYC, Thrillist, Reddit,
         X/Twitter ("RSVP NYC", "sign up NYC"), Instagram (#RSVPnyc),
         SplashThat (tech/healthcare invite-only events).
Features:
  - handle()          — on-demand query (responds to Telegram messages)
  - run_event_scan()  — proactive scheduled scan, sends Telegram alert if hot events found
                        (runs 2x/week via APScheduler in bot.py)
"""

import datetime
import json
import os
import re
from concurrent.futures import ThreadPoolExecutor, as_completed
from core.llm import chat
from core.search import search, fetch_page, format_results

_SOCIAL_CACHE_PATH = os.path.join(os.path.dirname(__file__), "..", "..", "data", "social_cache.json")

# ── Justin's identity context ─────────────────────────────────────────────────

SYSTEM = """You are an NYC event scout. Surface the best FREE or very low-cost upcoming NYC events.

CRITICAL DATE RULE: You MUST only surface events that have NOT yet occurred. If a date appears
in the search results that is before today's date, IGNORE that event entirely. Do not mention it.
If you are unsure whether an event is upcoming or past, exclude it. When in doubt, leave it out.

Priority event types (in order):
1. 🍻 Events with FREE FOOD or FREE DRINKS / open bar / complimentary drinks (always #1)
2. 🏃 New activities, hobbies, or experiences — things Justin hasn't tried (climbing, ceramics,
   salsa, archery, cooking class, comedy, improv, sports leagues, outdoor activities, etc.)
3. 🏥 Healthcare / health-tech / digital health networking
4. 💻 Tech / startup / AI demo nights
5. 🎌 Asian / AAPI / Japanese / Hong Kong cultural or professional events
6. 🎉 Pop-up events (food, art, retail, experiences — anything flash/one-time)
7. 🎊 General free NYC networking and community events

Sources to surface links from when found: Luma (lu.ma), Eventbrite, Meetup, Partiful,
Yelp Events, nycgo.com, allevents.in, do.nyc, X/Twitter RSVP posts,
Instagram (#RSVPnyc, #NYCevents, #NYCpopup), Time Out NYC, Thrillist, Reddit r/nyc.

When Instagram content appears in results, label it as 📸 Instagram and include the hashtag or
account handle if visible. Instagram posts often surface pop-up events and food/drink events
before they appear on formal listing sites.

Format each event as:
🗓 *[Event Name]*
📍 [Venue / Neighborhood]
🕐 [Date & Time]
💰 [Free / Cost]
📌 [Source: Luma / Eventbrite / Meetup / 𝕏 / 📸 Instagram / Partiful / etc.]
🔗 [Direct RSVP link — must be the specific event page URL, never a category/listing page]
✨ [One line: why this is worth going to]

Rules:
- Only include events that are UPCOMING (on or after today)
- Prioritize events with a direct RSVP link
- 🍻 FREE FOOD or OPEN BAR events get a 🍻 emoji and always appear first
- 🆕 New activity/hobby events get a 🆕 emoji
- If a pop-up or flash event is found, always include it regardless of category
- If X/Twitter posts with event links are in the results, surface them
- At the end: bold the single top pick and say why in one line"""

# Keywords that warrant an immediate proactive alert (don't wait for weekly roundup)
HOT_KEYWORDS = [
    # Free food/drinks (highest priority)
    "free food", "free drinks", "open bar", "complimentary drinks", "happy hour",
    "food and drink", "drinks included", "networking reception", "cocktail reception",
    "free beer", "free wine", "free snacks", "catered", "refreshments",
    # Food events
    "sake", "ramen", "izakaya", "dim sum", "japanese", "hong kong", "cantonese",
    "food festival", "tasting", "wine tasting", "beer tasting", "sake tasting",
    # Asian / AAPI
    "aapi", "asian american",
    # Pop-ups
    "pop-up", "popup", "pop up", "flash event", "drop-in",
    # New activities / hobbies
    "climbing", "ceramics", "pottery", "salsa", "dance class", "cooking class",
    "archery", "yoga class", "improv", "comedy", "sports league", "tennis",
    "volleyball", "pickleball", "kayaking", "hiking club", "book club",
    "photography walk", "sketching", "art class", "meditation", "breathwork",
    # Tech / health
    "tech networking", "healthcare networking", "startup", "demo night",
]


def _get_date_range() -> tuple[str, str, str, datetime.date]:
    """Returns (today_str, end_str, today_iso, today_date) for filtering and display."""
    today = datetime.date.today()
    end = today + datetime.timedelta(days=14)
    return today.strftime("%B %d"), end.strftime("%B %d, %Y"), today.isoformat(), today


# ── Query bank — organized by source/theme ────────────────────────────────────

def _build_queries(focus: str = "") -> list[str]:
    """Build diverse search queries across all sources targeting Justin's interest areas."""
    start, end, _, _ = _get_date_range()

    base_queries = [
        # ── X / Twitter: "RSVP NYC" and "sign up NYC" ────────────────────────
        f'"RSVP NYC" free event {start} 2026 lu.ma OR eventbrite OR partiful',
        f'"sign up NYC" free event {start} 2026 lu.ma OR eventbrite OR partiful',
        f'site:x.com "RSVP NYC" free event {start} 2026',
        f'site:x.com "sign up NYC" free event {start} 2026',
        f'site:twitter.com "RSVP NYC" OR "sign up NYC" free event {start} 2026',

        # ── Free food / drinks (highest priority) ────────────────────────────
        f'NYC "free food" OR "open bar" OR "free drinks" event {start} 2026',
        f'NYC "complimentary drinks" OR "catered" networking event {start} 2026',
        f'site:eventbrite.com NYC "free food" OR "open bar" event {start} 2026',
        f'site:lu.ma NYC "open bar" OR "free drinks" OR "free food" {start} 2026',

        # ── New activities & hobbies ──────────────────────────────────────────
        f'NYC free "try for the first time" activity class event {start} 2026',
        f'NYC free intro class workshop climbing ceramics cooking {start} 2026',
        f'NYC free sports league social club meetup {start} 2026',
        f'NYC free dance salsa yoga climbing pottery class beginner {start} 2026',
        f'site:eventbrite.com NYC free class workshop activity beginner {start} 2026',
        f'site:lu.ma NYC class workshop hobby activity free {start} 2026',

        # ── Luma ──────────────────────────────────────────────────────────────
        f'site:lu.ma NYC free events {start} 2026',
        f'site:lu.ma NYC healthcare tech AAPI Japanese free {start} 2026',

        # ── Eventbrite ────────────────────────────────────────────────────────
        f'site:eventbrite.com NYC free events {start} 2026 healthcare tech Asian',
        f'site:eventbrite.com NYC free networking {start} 2026',

        # ── Partiful ──────────────────────────────────────────────────────────
        f'site:partiful.com NYC free event {start} 2026',
        f'partiful NYC free party event {start} 2026',

        # ── Yelp Events ───────────────────────────────────────────────────────
        f'site:yelp.com/events NYC free event {start} 2026',
        f'yelp events NYC free "this week" {start} 2026',

        # ── NYC-specific event sites ──────────────────────────────────────────
        f'site:nycgo.com free events {start} 2026',
        f'site:allevents.in NYC free events {start} 2026',
        f'site:do.nyc free events {start} 2026',
        f'site:timeout.com NYC free events this week 2026',
        f'nycfreeevents.com {start} 2026',

        # ── Healthcare & tech ─────────────────────────────────────────────────
        f'NYC free health tech digital health networking events {start} 2026',
        f'NYC free startup tech AI demo networking event {start} 2026',

        # ── Asian / AAPI / Japanese / Hong Kong ───────────────────────────────
        f'NYC free Japanese cultural events {start} 2026',
        f'NYC free AAPI Asian American professional networking {start} 2026',
        f'NYC Japan Society free events {start} 2026',

        # ── Pop-up events ─────────────────────────────────────────────────────
        f'NYC pop-up free event this week {start} 2026 food drinks art',
        f'NYC free pop-up flash drop-in event {start} 2026',

        # ── General free NYC ──────────────────────────────────────────────────
        f'NYC free events this week {start} {end} food drinks 2026',
        f'NYC free events {start} 2026 site:reddit.com r/nyc OR r/nycevents',
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
    "splashthat.com": "SplashThat",
    "timeout.com": "Time Out",
    "thrillist.com": "Thrillist",
    "reddit.com": "Reddit",
    "meetup.com": "Meetup",
}


def _extract_event_urls(content: str) -> list[str]:
    """
    Parse individual event page URLs from a listing/category page's content.
    Returns specific event URLs — not the listing page itself.

    Platforms supported:
    - Eventbrite: /e/event-name-tickets-1234567890
    - Luma:       lu.ma/abc123  or  lu.ma/event/slug
    - Meetup:     meetup.com/group-name/events/1234567890/
    - Partiful:   partiful.com/e/abc123
    - SplashThat: splashthat.com/sites/view/slug  or  brand.splashthat.com
    - Instagram:  instagram.com/p/abc123  or  /reel/abc123
    """
    found = []

    patterns = [
        # Eventbrite individual event pages
        (r'https?://(?:www\.)?eventbrite\.com/e/[\w\-]+-\d{6,}', "eventbrite"),
        # Luma individual event pages (short slug, not /discover or /nyc)
        (r'https?://lu\.ma/(?!nyc|discover|home|calendar|about|pricing|blog|event$)[a-z0-9]{4,16}(?!\w)', "luma"),
        # Luma /event/slug format
        (r'https?://lu\.ma/event/[\w\-]+', "luma"),
        # Meetup individual event pages
        (r'https?://(?:www\.)?meetup\.com/[\w\-]+/events/\d{6,}/?', "meetup"),
        # Partiful individual event pages
        (r'https?://(?:www\.)?partiful\.com/e/[\w\-]+', "partiful"),
        # SplashThat — branded subdomain AND /sites/view/ paths
        (r'https?://[\w\-]+\.splashthat\.com(?:/[\w\-/]*)?', "splashthat"),
        (r'https?://(?:www\.)?splashthat\.com/sites/view/[\w\-]+', "splashthat"),
        # Instagram posts
        (r'https?://(?:www\.)?instagram\.com/(?:p|reel)/[\w\-]+/?', "instagram"),
        # Picuki/Imginn individual post pages
        (r'https?://(?:www\.)?picuki\.com/media/\d+', "instagram"),
    ]

    for pattern, _ in patterns:
        for match in re.finditer(pattern, content):
            url = match.group(0).rstrip(".,;)'\"")
            if url not in found:
                found.append(url)

    return found[:20]  # cap to avoid noise


def _is_listing_url(url: str) -> bool:
    """Return True if a URL looks like a category/listing page rather than a specific event."""
    listing_patterns = [
        r'eventbrite\.com/d/',
        r'eventbrite\.com/discover',
        r'lu\.ma/(nyc|discover|home|calendar|about|events)$',
        r'lu\.ma/(nyc|discover|home|calendar)/?$',
        r'meetup\.com/find',
        r'meetup\.com/cities/',
        r'yelp\.com/events/[^/]+/?$',   # top-level city page
        r'allevents\.in/[^/]+/?$',
        r'timeout\.com/newyork/things-to-do',
        r'nycgo\.com/articles',
        r'nycfreeevents\.com/?$',
        r'partiful\.com/?$',
        r'splashthat\.com/?$',
    ]
    for pat in listing_patterns:
        if re.search(pat, url):
            return True
    return False


def _listing_page_to_events(content: str, listing_url: str, source_label: str) -> list[dict]:
    """
    Convert a fetched listing page into individual event result dicts
    by extracting specific event URLs from the page content.
    Falls back to returning the listing page itself if no event URLs found.
    """
    event_urls = _extract_event_urls(content)

    if not event_urls:
        # No individual links found — return the listing page as-is
        return [{"title": source_label, "url": listing_url, "content": content}]

    # Return each individual event URL as its own result, with the listing content as context
    results = []
    for url in event_urls:
        results.append({
            "title": f"{source_label} event",
            "url": url,
            "content": content[:600],  # listing page content as context
        })
    return results


def _is_hot_event(text: str) -> bool:
    """Return True if event description contains high-priority trigger keywords."""
    text_lower = text.lower()
    return any(kw in text_lower for kw in HOT_KEYWORDS)


def _filter_stale(results: list[dict]) -> list[dict]:
    """
    Drop results that clearly reference past events.
    Checks: past years, past months this year, and specific past dates in current month.
    This is a fast pre-filter before the LLM sees the data.
    """
    today = datetime.date.today()
    current_year = today.year
    past_years = [str(y) for y in range(2020, current_year)]

    month_names = ["january","february","march","april","may","june",
                   "july","august","september","october","november","december"]
    # Months that have fully passed this year
    past_months_this_year = [month_names[i] for i in range(today.month - 1)]
    current_month_name = month_names[today.month - 1]

    # Past dates in the current month (e.g. "march 1" through "march 22" when today is march 23)
    past_day_patterns = []
    for day in range(1, today.day):
        past_day_patterns.append(f"{current_month_name} {day}")
        past_day_patterns.append(f"{current_month_name} {day},")
        past_day_patterns.append(f"{current_month_name} {day:02d}")

    kept = []
    for r in results:
        text = (r.get("title","") + " " + r.get("content","") + " " + r.get("url","")).lower()

        # Drop if it references a clearly past year
        if any(py in text for py in past_years):
            continue

        # Drop if it references a past month + this year
        stale = False
        for pm in past_months_this_year:
            if pm in text and str(current_year) in text:
                stale = True
                break
        if stale:
            continue

        # Drop if it references a specific past date in the current month
        for pat in past_day_patterns:
            if pat in text:
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
    start, _, _, _ = _get_date_range()
    results = []

    # Direct Luma NYC discover pages
    luma_urls = [
        "https://lu.ma/nyc",
        "https://lu.ma/discover?query=NYC+free&start=today",
        "https://lu.ma/discover?query=NYC+health+tech&start=today",
        "https://lu.ma/discover?query=NYC+Asian+AAPI&start=today",
    ]
    for url in luma_urls:
        content = fetch_page(url, max_chars=6000)
        if content and len(content) > 200:
            results.extend(_listing_page_to_events(content, url, "Luma NYC"))

    # Also run targeted Tavily searches to surface specific Luma event pages
    luma_queries = [
        f'site:lu.ma NYC free events {start} 2026',
        f'site:lu.ma NYC healthcare tech startup networking {start} 2026',
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
    start, _, _, _ = _get_date_range()
    results = []

    # Direct Eventbrite NYC listing pages
    eb_urls = [
        "https://www.eventbrite.com/d/ny--new-york/free--events/",
        "https://www.eventbrite.com/d/ny--new-york/networking--events/",
        "https://www.eventbrite.com/d/ny--new-york/free--networking--events/",
        "https://www.eventbrite.com/d/ny--new-york/health--events/",
    ]
    for url in eb_urls:
        content = fetch_page(url, max_chars=6000)
        if content and len(content) > 200:
            results.extend(_listing_page_to_events(content, url, "Eventbrite NYC"))

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
    start, _, _, _ = _get_date_range()
    results = []

    meetup_urls = [
        "https://www.meetup.com/find/?location=New+York%2C+NY&source=EVENTS&eventType=inPerson&distance=tenMiles",
        "https://www.meetup.com/find/?keywords=health+tech&location=New+York%2C+NY&source=EVENTS&eventType=inPerson",
        "https://www.meetup.com/find/?keywords=startup+networking&location=New+York%2C+NY&source=EVENTS&eventType=inPerson",
    ]
    for url in meetup_urls:
        content = fetch_page(url, max_chars=6000)
        if content and len(content) > 200:
            results.extend(_listing_page_to_events(content, url, "Meetup NYC"))

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
    Scan X/Twitter for RSVP NYC / sign up NYC / join us NYC / link in bio posts.
    X blocks most crawlers, so we try Nitter (X proxy) instances first,
    then fall back to Tavily searches that may surface indexed tweet content.
    """
    start, _, _, _ = _get_date_range()
    results = []

    # Nitter search queries — expanded keyword set
    nitter_queries = [
        "RSVP+NYC+free",
        "sign+up+NYC+free+event",
        "join+us+NYC+free",
        "RSVP+NYC+lu.ma",
        "NYC+free+event+link",
        "register+NYC+free+event",
        "tickets+NYC+free+event",
    ]
    nitter_bases = [
        "https://nitter.privacydev.net",
        "https://nitter.poast.org",
        "https://nitter.1d4.us",
        "https://nitter.net",
    ]
    found_working_nitter = False
    for base in nitter_bases:
        for q in nitter_queries[:3]:
            url = f"{base}/search?q={q}&f=tweets"
            content = fetch_page(url, max_chars=4000)
            if content and len(content) > 300 and ("tweet" in content.lower() or "nitter" in content.lower()):
                # Extract any event links from the tweet content
                event_urls = _extract_event_urls(content)
                if event_urls:
                    for eu in event_urls:
                        results.append({"title": f"𝕏 post: {q.replace('+', ' ')}", "url": eu, "content": content[:400]})
                else:
                    results.append({"title": f"𝕏: {q.replace('+', ' ')}", "url": url, "content": content})
                found_working_nitter = True
        if found_working_nitter:
            break

    # Tavily searches for indexed X/tweet content — expanded keywords
    x_queries = [
        f'"RSVP NYC" free event {start} 2026 lu.ma OR eventbrite OR partiful OR splashthat',
        f'"sign up NYC" free event {start} 2026',
        f'"join us NYC" free event {start} 2026',
        f'"RSVP NYC" OR "sign up NYC" free food drinks event {start} 2026',
        f'"NYC free event" RSVP link 2026 healthcare OR tech OR food OR popup',
        f'x.com "RSVP NYC" event free {start} 2026',
        f'"link in bio" NYC free event RSVP {start} 2026',
        f'"register now" NYC free event {start} 2026 lu.ma OR eventbrite OR splashthat',
    ]
    for q in x_queries:
        for r in search(q, max_results=4):
            results.append(r)

    return results


def _fetch_splashthat() -> list[dict]:
    """
    Scrape SplashThat for NYC events.
    SplashThat is used heavily by tech companies, healthcare orgs, and startups
    for invite-only and semi-public events — many never appear on Eventbrite or Luma.

    Approach:
    1. Search Tavily for site:splashthat.com NYC events
    2. Search for branded SplashThat subdomains with NYC keywords
    3. Direct fetch of SplashThat discovery pages if available
    """
    start, _, _, _ = _get_date_range()
    results = []

    # Tavily searches for SplashThat NYC events
    splash_queries = [
        f'site:splashthat.com NYC event free {start} 2026',
        f'site:splashthat.com NYC networking {start} 2026',
        f'site:splashthat.com NYC tech startup healthcare {start} 2026',
        f'site:splashthat.com NYC AAPI Asian professional {start} 2026',
        f'site:splashthat.com NYC free food drinks reception {start} 2026',
        f'splashthat.com NYC event RSVP free {start} 2026',
        f'splashthat NYC "free" OR "RSVP" event {start} 2026',
        # Branded subdomains commonly used in NYC tech/health space
        f'splashthat NYC health OR healthcare OR hospital OR medical event {start} 2026',
        f'splashthat NYC startup founder investor networking {start} 2026',
    ]
    for q in splash_queries:
        for r in search(q, max_results=4):
            # Prioritize actual splashthat.com links
            url = r.get("url", "")
            if "splashthat.com" in url:
                results.insert(0, r)  # bump specific splashthat links to top
            else:
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
    start, _, _, _ = _get_date_range()
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
        content = fetch_page(url, max_chars=6000)
        if content and len(content) > 300:
            results.extend(_listing_page_to_events(content, url, "Instagram"))

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
    Fetch from Partiful, Time Out NYC, Reddit, Thrillist, Yelp Events,
    nycgo.com, allevents.in, do.nyc, and other sources.
    """
    start, _, _, _ = _get_date_range()
    results = []

    # Direct page fetches — curated listing pages
    other_urls = [
        "https://www.timeout.com/newyork/things-to-do/free-things-to-do-in-nyc-this-weekend",
        "https://www.timeout.com/newyork/things-to-do/best-free-events-in-new-york",
        "https://www.nycgo.com/articles/free-things-to-do-in-nyc",
        "https://allevents.in/new%20york/free",
        "https://www.nycfreeevents.com",
        "https://www.yelp.com/events/nyc-new-york",
    ]
    for url in other_urls:
        content = fetch_page(url, max_chars=6000)
        if content and len(content) > 200:
            results.extend(_listing_page_to_events(content, url, "NYC Events"))

    # Partiful + Reddit + Thrillist + new sites via search
    other_queries = [
        f'site:partiful.com NYC free event {start} 2026',
        f'site:yelp.com/events NYC free {start} 2026',
        f'site:allevents.in NYC free events {start} 2026',
        f'site:nycgo.com free events {start} 2026',
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


def _fetch_new_activities() -> list[dict]:
    """
    Search for free intro classes, hobby workshops, and new activity events in NYC.
    Targets things Justin likely hasn't tried: ceramics, climbing, salsa, cooking, etc.
    """
    start, _, _, _ = _get_date_range()
    results = []

    activity_queries = [
        f'NYC free intro class beginner workshop "first time" {start} 2026',
        f'NYC free cooking class workshop event {start} 2026',
        f'NYC free pottery ceramics class event {start} 2026',
        f'NYC free rock climbing intro session {start} 2026',
        f'NYC free salsa dance class beginner {start} 2026',
        f'NYC free comedy improv open mic {start} 2026',
        f'NYC free sports social league volleyball pickleball {start} 2026',
        f'NYC free outdoor activity hiking kayaking {start} 2026',
        f'site:eventbrite.com NYC free beginner class workshop {start} 2026',
        f'site:lu.ma NYC class workshop activity {start} 2026',
        f'site:meetup.com NYC hobby club beginner free {start} 2026',
    ]
    for q in activity_queries:
        for r in search(q, max_results=3):
            results.append(r)

    return results


def _enrich_listing_results(results: list[dict]) -> list[dict]:
    """
    Post-process search results: for any result whose URL is a listing/category page,
    attempt to fetch the page and extract specific event URLs.
    Results with specific event URLs replace the listing result.
    """
    enriched = []
    seen_urls: set[str] = set()

    for r in results:
        url = r.get("url", "")
        if url in seen_urls:
            continue

        if url and _is_listing_url(url):
            # Try to fetch the listing page and extract specific event links
            try:
                content = fetch_page(url, max_chars=6000)
                if content and len(content) > 200:
                    specific_urls = _extract_event_urls(content)
                    if specific_urls:
                        for ev_url in specific_urls:
                            if ev_url not in seen_urls:
                                seen_urls.add(ev_url)
                                enriched.append({
                                    "title": r.get("title", "Event"),
                                    "url": ev_url,
                                    "content": r.get("content", "") + " " + content[:400],
                                })
                        seen_urls.add(url)
                        continue
            except Exception:
                pass

        seen_urls.add(url)
        enriched.append(r)

    return enriched


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
        "splashthat": _fetch_splashthat,
        "instagram": _fetch_instagram,
        "new_activities": _fetch_new_activities,
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
        start, _, _, _ = _get_date_range()
        for q in [
            f'NYC free events {focus} {start} 2026',
            f'site:lu.ma NYC {focus} free {start} 2026',
            f'site:eventbrite.com NYC {focus} free {start} 2026',
        ]:
            for r in search(q, max_results=4):
                if r["url"] not in seen_urls:
                    seen_urls.add(r["url"])
                    all_results.append(r)

    # Upgrade listing-page URLs to specific event page URLs where possible
    all_results = _enrich_listing_results(all_results)

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
        f"Any event before today is IRRELEVANT — exclude it completely. "
        f"Do not mention events from any past date or past month of {today.year}, "
        f"or from any prior year. If you cannot confirm an event is in the future, exclude it.\n\n"
        f"Date window to surface: {start}–{end}\n\n"
        f"{cal_context}\n\n"
        f"Search results:\n{context_block}\n\n"
        f"PRIORITY ORDER (strictly follow this ranking):\n"
        f"1. 🍻 Events with FREE FOOD, FREE DRINKS, open bar, or complimentary refreshments — always first\n"
        f"2. 🆕 New activities or hobbies Justin likely hasn't tried "
        f"(climbing, ceramics, salsa, cooking class, improv, sports league, kayaking, etc.)\n"
        f"3. 🏥 Healthcare / health-tech / digital health networking\n"
        f"4. 💻 Tech / startup / AI demo nights\n"
        f"5. 🎌 Asian / AAPI / Japanese / Hong Kong cultural or professional\n"
        f"6. 🎉 Pop-ups and flash events (always include any found)\n"
        f"7. 🎊 General free NYC networking\n\n"
        f"Mark 🍻 on any event with free food/drinks. Mark 🆕 on new activity/hobby events.\n"
        f"If any X/Twitter posts with event RSVP links appear (from 'RSVP NYC' or 'sign up NYC' searches), "
        f"label source as 𝕏 and prioritize them.\n"
        f"If Instagram posts appear (#RSVPnyc, #NYCevents, #NYCpopup), label source as 📸 Instagram.\n"
        f"Include Yelp Events, nycgo.com, allevents.in, Partiful, and Meetup links if found.\n"
        f"If recurring clubs or communities worth joining long-term appear, call them out separately.\n"
        f"LINK RULE: Each event's 🔗 link MUST be the direct event RSVP page "
        f"(eventbrite.com/e/..., lu.ma/abc123, meetup.com/group/events/123, partiful.com/e/...). "
        f"NEVER use a category/listing page as the link. Omit the link if no specific event URL found.\n"
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
        f"Priority order:\n"
        f"1. 🍻 FREE FOOD / FREE DRINKS / open bar — always rank these #1\n"
        f"2. 🆕 New activities/hobbies (climbing, ceramics, salsa, cooking class, improv, etc.)\n"
        f"3. 🏥 Healthcare / health-tech\n"
        f"4. 💻 Tech / startup / AI\n"
        f"5. 🎌 Asian/AAPI/Japanese/HK cultural or professional\n"
        f"6. 🎉 Pop-ups and flash events [ALWAYS include any pop-ups found]\n"
        f"7. 🎊 General free NYC events\n\n"
        f"If X/Twitter posts with RSVP links appear, include them labelled as 𝕏. "
        f"Include Partiful links if found. "
        f"If recurring clubs or communities worth joining long-term appear, add a separate "
        f"'🏛 Communities to Join' section at the end.\n"
        f"If fewer than 3 future events are found in the results, say so honestly — do not invent events.\n"
        f"Format clearly for Telegram. Bold the top pick."
    )

    body = chat(SYSTEM, prompt, max_tokens=900)

    # ── Save structured event data to social_cache.json for dashboard ─────────
    try:
        _save_social_cache(results[:30], body, today_iso, hot)
    except Exception:
        pass

    return f"{mode_label}{hot_note}\n\n{body}"


def _save_social_cache(raw_results: list[dict], llm_summary: str, scan_date: str, hot: bool) -> None:
    """
    Persist event data to data/social_cache.json for the dashboard API.
    Extracts structured event objects from raw results and the LLM summary.
    """
    events = []
    seen_urls: set[str] = set()

    # Build structured events from raw search results that have specific event URLs
    for r in raw_results:
        url = r.get("url", "")
        if not url or _is_listing_url(url) or url in seen_urls:
            continue
        seen_urls.add(url)

        # Determine source label
        source = "Web"
        for domain, label in SOURCE_LABELS.items():
            if domain in url:
                source = label
                break

        title = r.get("title", "").strip()
        content = r.get("content", "")

        # Attempt to extract a date from content/title
        date_match = re.search(
            r'\b(January|February|March|April|May|June|July|August|September|October|November|December)'
            r'\s+\d{1,2}(?:,\s*\d{4})?',
            content + " " + title, re.IGNORECASE
        )
        event_date = date_match.group(0) if date_match else ""

        events.append({
            "title": title,
            "url": url,
            "source": source,
            "date": event_date,
            "content_snippet": content[:200],
        })

    cache = {
        "last_scan": scan_date,
        "hot": hot,
        "event_count": len(events),
        "events": events[:25],
        "summary": llm_summary,
    }

    cache_path = os.path.normpath(_SOCIAL_CACHE_PATH)
    os.makedirs(os.path.dirname(cache_path), exist_ok=True)
    with open(cache_path, "w") as f:
        json.dump(cache, f, indent=2)
