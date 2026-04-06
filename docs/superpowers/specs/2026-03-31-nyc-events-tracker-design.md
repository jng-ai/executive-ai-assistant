# NYC Events Tracker & Dashboard — Design Spec
**Date:** 2026-03-31
**Status:** Approved by user

---

## Overview

A Notion-backed NYC events discovery, tracking, and social coordination system. Extends the existing `social_agent` into a full lifecycle tool: daily multi-source scanning → Telegram/dashboard intake → calendar-aware auto-registration → progress tracking → post-event confirmation. A shared dashboard page lets friends see upcoming events and RSVP to join. A theme search panel lets Justin search on-demand by any freeform theme.

---

## Goals

- Discover and track NYC events across 10 hobby/interest categories
- Goal: attend **20 events in 2026**, with at least one per category
- Auto-register for events (Playwright autofill) after confirming calendar availability
- Share upcoming events with friends; friends can RSVP to join
- On-demand theme-based search from the dashboard
- 100% free stack — no new paid services

---

## User Profile

- **Name:** Justin Ngai | **Email:** jngai5.3@gmail.com
- 28, single, NYC
- Price cap: **≤$80/event**
- Calendar: Google Calendar (already integrated)
- Interface: Telegram (primary) + web dashboard (secondary)

---

## Categories (10)

| Emoji | Category | Priority |
|-------|----------|----------|
| 💪 | Fitness & Outdoors | Core |
| 💘 | Dating & Meetups | Core |
| 🍜 | Food & Drinks | Core |
| 🎨 | Painting & Visual Arts | Core |
| 🏺 | Ceramics & Crafts | Core |
| 🎲 | Games & Trivia | Core |
| 🎭 | Performing Arts | Core |
| 🤝 | Community & Clubs | Core |
| 💼 | Professional | Secondary |
| 🎉 | Nightlife | Low |

---

## Architecture

### Data Hub: Notion Database

One Notion database — **"NYC Events 2026"** — is the single source of truth. All agents read from and write to it.

**Database properties:**

| Property | Type | Notes |
|----------|------|-------|
| Name | Title | Event name |
| Date | Date | Start datetime |
| End Time | Date | For post-event confirmation scheduling |
| Venue | Text | Venue name |
| Address | Text | Full street address when available |
| Neighborhood | Select | e.g. Brooklyn, Midtown, LES |
| Category | Select | One of the 10 categories |
| Price | Number | 0 = free |
| Source | Select | Luma, Eventbrite, Partiful, Reddit, X, Manual |
| RSVP Link | URL | Direct event registration URL |
| Status | Select | New / Interested / Going / Attended / Skipped |
| Registered | Checkbox | Whether Playwright autofill was completed |
| Friends Going | Rich text | Comma-separated friend names added via dashboard form |
| Cal Event ID | Text | Google Calendar event ID (written post-registration; not used for dedup) |
| Notes | Text | Extra context |

**Notion Views (internal):**
- Upcoming by Date (default)
- By Category (grouped)
- Attended (status = Attended filter)

**Note on friend sharing:** The Notion database itself is kept private. Friends access a dedicated read-only page on the shared dashboard (see Component 6). This avoids Notion free plan column-visibility limitations and keeps internal fields (Cal Event ID, Registered, Notes) hidden from friends.

---

## Components

### 1. Event Scanner (`agents/social_agent/handler.py` — extended)

**Schedule:** Daily at 8:15 AM ET via APScheduler in `bot.py`. This **replaces** the existing Tue/Fri 9 AM `run_event_scan()` job — the old schedule is removed to avoid double-scanning.

**Sources & methods:**

| Source | Method |
|--------|--------|
| Luma | Tavily search `site:lu.ma NYC [category]` |
| Eventbrite | Tavily search + Eventbrite public browse URL scrape |
| Partiful | Tavily search `site:partiful.com NYC` |
| Reddit | Reddit JSON API — `r/nyc`, `r/nycmeetups`, `r/nycactivities`, `r/nycevents` |
| X/Twitter | Tavily search `NYC RSVP sign up [category] site:twitter.com` |
| Catch-all | Tavily `NYC events this week [category]` per category |

**Filters applied before pushing to Notion:**
- Price ≤ $80 (LLM extracts price from page)
- Date must be upcoming (≥ today)
- Exclude events without a direct RSVP link
- **Deduplication:** before writing each event, query Notion for existing records matching the same RSVP Link URL. Skip if found.

**Per event pushed to Notion:** name, date, end time, venue, address, category (LLM-classified into one of the 10), price, source, RSVP link, status = "New"

**Batched Telegram digest:** After the scan completes, all newly discovered events are sent as a single Telegram message (not one message per event). Format:

```
🗓 New events found today (8):

💪 Brooklyn 5K Run — Apr 5, Free · Prospect Park
  lu.ma/bk5k · Calendar: Free ✓ [Sign me up]

💘 Speed Dating NYC — Apr 6, $35 · Midtown
  eventbrite.com/... · Calendar: Free ✓ [Sign me up]
...

Reply with event numbers to register, or tap buttons above.
```

Each event gets a [Sign me up] inline button. This batching prevents spam when the scanner finds many events at once.

---

### 2. Manual Event Intake

Two entry points, same extraction pipeline:

**Via Telegram:** User pastes any event URL into chat → `command_router` classifies as `event_intake` intent → `social_agent.handle_intake(url)` → fetches page via `core.search.fetch_page()` → LLM extracts fields → dedup check against Notion → push to Notion with status "New" → Telegram confirms: "Added: [Event Name] on [Date] · [Category]"

**Via Dashboard:** URL input field on Events tab → POST `/api/events/intake` → same `handle_intake()` pipeline → dashboard refreshes event feed

**LLM extraction targets:** name, date (ISO), end time (ISO), venue name, full street address, price (number), category (one of 10), RSVP link (must match the input URL or be more specific)

**`event_intake` intent in command_router:** triggered when message matches URL pattern (`https?://`) AND is not a known non-event domain.

---

### 3. Calendar-Aware Registration Flow

Triggered only by **explicit user action** — either tapping [Sign me up] in the Telegram digest or clicking "Sign me up" on the dashboard event card. Never fires automatically on scan.

**Flow:**
1. Fetch event details from Notion by ID
2. Check Google Calendar for conflicts at event date/time using `calendar_client.list_events()`
3. Send Telegram confirmation:
   - If free: `"✅ Calendar is free. Registering you for Brooklyn 5K Run on Apr 5…"`
   - If conflict: `"⚠️ You have [Event X] at that time. Still register? [Yes] [No]"`
4. On user confirm → Playwright (headless=True, timeout=30s) opens RSVP link and autofills:
   - Name: Justin Ngai
   - Email: jngai5.3@gmail.com
   - Phone: from env `JUSTIN_PHONE` if field detected
   - Standard field detection: looks for `name`, `email`, `first_name`, `last_name`, `phone` input attributes
5. **On Playwright success:** Notion status → "Going", Registered → ✓, Google Calendar event created (title = event name, location = address), Cal Event ID stored
6. **On Playwright failure** (timeout, CAPTCHA detected, login wall, form structure unrecognized):
   - Take screenshot → save to `data/reg_failures/`
   - Telegram: `"⚠️ Couldn't auto-register (CAPTCHA/login). Here's the link: [RSVP Link]"` + status → "Interested"
7. **CAPTCHA detection:** if page contains `recaptcha`, `hcaptcha`, or iframe from known CAPTCHA domains after load, skip autofill immediately and go to failure path.

**Registration is never attempted without explicit user confirmation.**

---

### 4. Post-Event Confirmation

APScheduler job runs daily at **9:00 AM ET** (distinct from scanner at 8:15 AM):

1. Query Notion for events where Status = "Going" AND End Time is before current datetime (i.e., event ended yesterday or earlier, up to 3 days ago to catch missed checks)
2. For each matching event (max 3 per run to avoid spam): send Telegram inline keyboard:
   > "Did you make it to **Brooklyn 5K Run**? 👍 Yes  👎 No"
3. Callback handler in `bot.py`:
   - Yes → `update_event_status(id, "Attended")` in Notion
   - No → `update_event_status(id, "Skipped")` in Notion
4. Progress count (attended events) is derived live from Notion query — no separate counter needed.

---

### 5. Dashboard — Events Tab

New tab in existing FastAPI dashboard (`integrations/web/`). Pulls from Notion API via new helper functions in `integrations/notion/client.py`.

**Layout (approved Layout C):**

**Top — Progress Section:**
- Summary bar: `X / 20 events attended · Y categories tried · Z upcoming confirmed`
- Per-category progress bars: attended count, list of attended event names, color-coded
- "Branch out" nudge box: lists untried categories + matching upcoming events from Notion
- Monthly heatmap: one dot per attended event day, color = category

**Middle — Theme Search Panel (new):**
- Freeform text input: `"Find me NYC events about: ___________"`
- Examples shown: `salsa dancing`, `Japanese culture`, `pottery beginners`, `chess club`
- On submit → POST `/api/events/theme-search` → runs targeted Tavily + Reddit search for that theme → LLM extracts events → returns list of results with name, date, venue, address, price, RSVP link
- Results shown inline on dashboard with "Add to tracker" button per event
- "Add to tracker" → same intake pipeline → pushed to Notion → appears in feed
- Theme search results are **not** auto-pushed to Notion; user must explicitly add them

**Bottom — Event Feed:**
- Chronological list of upcoming events from Notion
- Each card: name, date, venue, address, neighborhood, price badge, source badge, status badge, RSVP link button, "Sign me up" button
- Filter pills: All / Going / New / [each category]
- URL drop box above feed: `Paste any event link to add it`

**API endpoints added to `server.py`:**
- `GET /api/events` — upcoming events from Notion, sorted by date, with optional `?category=` and `?status=` filters
- `GET /api/events/progress` — attended count by category, heatmap data, goal progress (X/20)
- `POST /api/events/intake` — body: `{"url": "..."}` → extract + dedup + push to Notion
- `POST /api/events/rsvp/{notion_id}` — trigger registration flow for a specific event
- `POST /api/events/theme-search` — body: `{"theme": "..."}` → search + return results (does not auto-push)
- `POST /api/events/add` — body: parsed event dict → push to Notion (used after theme search "Add" click)

---

### 6. Friend Collaboration

Friends access a **dedicated `/friends` route** on the dashboard (not Notion directly). This avoids Notion free plan column-visibility limitations.

**`/friends` page (`GET /friends`):**
- Served as a separate HTML page from the same FastAPI server
- Shows: upcoming events with Status = "Going" or "New", fields: Name, Date, Venue, Address, Price, RSVP Link, Friends Going
- Internal fields (Cal Event ID, Registered, Notes, Status internals) are never exposed
- Each event has a **"I'm in!" form**: text input for friend's name → POST `/api/events/friend-rsvp/{notion_id}`

**`POST /api/events/friend-rsvp/{notion_id}`:**
- Body: `{"name": "Mike"}` (name only, no auth required — low-stakes social use)
- Appends name to Notion `Friends Going` rich text field (comma-separated)
- Basic spam guard: name must be 2–40 chars, no URLs, max 10 friends per event
- Returns success message shown inline on the page

**Friend RSVP → Telegram notification:**
- APScheduler polls Notion `Friends Going` field every **15 minutes** for events with Status "Going"
- Compares against last-known state stored in `data/events_friends_cache.json` (dict of `{notion_id: [names]}`)
- On change detected: Telegram to Justin: `"🎉 Mike is joining you for Brooklyn 5K Run on Apr 5!"`
- Cache updated after notification sent

**Sharing the link:** Justin shares the Cloudflare Tunnel URL + `/friends` path (e.g. `https://xyz.trycloudflare.com/friends`) with friends via text/Telegram.

---

## Data Flow Summary

```
Sources (daily 8:15 AM)
    ↓ Tavily / Reddit JSON API / web scrape
social_agent.run_event_scan_daily()
    ↓ LLM: extract + categorize + filter + dedup by RSVP URL
Notion "NYC Events 2026" database
    ↓
    ├── Telegram digest → [Sign me up] → user confirms
    │       → Playwright headless autofill (30s timeout)
    │       → success: Going ✓ + Google Cal event created
    │       → failure: CAPTCHA/login → link sent to user, status = Interested
    │
    ├── Dashboard /api/events → Events tab
    │       → Progress section (20-event goal, category bars, heatmap)
    │       → Theme search panel (freeform → Tavily → results → opt-in add)
    │       → Event feed (filter by category/status)
    │       → URL drop box (manual intake → same pipeline)
    │
    ├── Post-event check (9:00 AM daily)
    │       → Status=Going + ended → "Did you go?" → Attended or Skipped
    │
    └── /friends page (shared URL)
            → Friends see Going/New events → "I'm in!" form
            → APScheduler polls every 15 min → Telegram ping on new RSVP
```

---

## Notion MCP Bootstrap (`scripts/notion_events_bootstrap.py`)

One-time setup script using Notion MCP tools:
1. Create "NYC Events 2026" database in user's Notion workspace
2. Create all properties with correct types, select options for Category/Status/Source/Neighborhood
3. Create 3 views: Upcoming by Date, By Category, Attended
4. Print database ID → user adds to `.env` as `NOTION_EVENTS_DB_ID`

---

## Free Stack Confirmation

| Component | Tool | Cost |
|-----------|------|------|
| LLM calls | Groq (llama-3.3-70b) | Free tier |
| Web search | Tavily | Free tier |
| Reddit | Public JSON API (`reddit.com/r/x.json`) | Free |
| Event data | Web scrape / Tavily | Free |
| Database | Notion | Free plan |
| Auto-registration | Playwright (already installed) | Free |
| Notifications | Telegram bot (already running) | Free |
| External access | Cloudflare Tunnel | Free |
| Calendar | Google Calendar API (already auth'd) | Free |

---

## Files Changed / Created

| File | Change |
|------|--------|
| `agents/social_agent/handler.py` | Replace Tue/Fri scan with daily `run_event_scan_daily()`; add Reddit source; push to Notion; add `handle_intake(url)`; add `run_theme_search(theme)` |
| `integrations/web/server.py` | Add 6 new `/api/events/*` endpoints; add `/friends` route |
| `integrations/web/static/index.html` | Add Events tab: progress section, theme search panel, event feed, URL drop box |
| `integrations/web/static/friends.html` | New — friends view: event list + "I'm in!" form per event |
| `integrations/notion/client.py` | Add `push_event()`, `update_event_status()`, `get_events()`, `get_progress()`, `add_friend_rsvp()`, `get_friends_going()` |
| `integrations/telegram/bot.py` | Add inline keyboard callbacks for registration confirm, post-event confirm, friend RSVP poll job |
| `core/command_router.py` | Add `event_intake` intent (URL pattern detection) |
| `.env` | Add `NOTION_EVENTS_DB_ID`, `JUSTIN_PHONE` |
| `data/events_friends_cache.json` | New — tracks last-known Friends Going state for change detection |
| `scripts/notion_events_bootstrap.py` | New — one-time Notion DB + views setup |

---

## Out of Scope (for now)

- Native mobile app (Telegram handles mobile)
- Email notifications (Telegram sufficient)
- Friend accounts / login (open `/friends` page is sufficient for low-stakes social use)
- Recurring event / club membership tracking
- Theme search history or saved searches
