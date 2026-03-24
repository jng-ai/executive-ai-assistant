# Dashboard Implementation To-Do

> **Goal:** Turn the web dashboard from a static status board into a fully interactive command center — click into any agent and see live data, trends, and one-tap actions.

**Branch:** `main` | **PRs:** #3 (merged), #17 (merged)

---

## Completed ✅

- [x] FastAPI web server (`integrations/web/server.py`) with `/api/summary` + 8 detail endpoints
- [x] Dark mobile-first dashboard (`integrations/web/static/index.html`) with agent cards
- [x] Auto-refresh every 30s with progress bar countdown
- [x] Slide-in detail panel with shimmer loading states
- [x] Health detail: weight sparkline, sleep bar chart, workout dot grid, macro progress bars
- [x] Finance detail: budget by category, bonus offers list, side hustle ideas
- [x] Market detail: live yfinance watchlist with 52-week range bars, session badge
- [x] Calendar detail: day-grouped agenda, conflict detection, Google Calendar links
- [x] Email detail: dual-account inbox, urgency triage (🔴/🟡/⚪), expand-to-preview
- [x] Travel detail: deal browser with booking links, escape.flights cash deals section
- [x] Follow-up detail: overdue + upcoming list
- [x] Bonus detail: last scan results + elevated offer cards + action button
- [x] Social detail: cached NYC events + scan action button
- [x] Mortgage detail: Paperstac listings with STRONG/GOOD ratings + scan button
- [x] Investment agent: 12th card + full watchlist panel with 52w range
- [x] Action buttons: bonus_scan, social_scan, mortgage_scan, briefing (POST /api/action/*)
- [x] SVG sparklines: weight trend, sleep bar chart (zero-dependency)
- [x] PWA manifest (`integrations/web/static/manifest.json`)
- [x] Status helpers enriched for all 12 agents in `/api/summary`

---

---

## Remaining / Next Sprint

### P1 — Core Data (do these first, they unblock everything)

#### 1. Add missing API endpoints · [Issue #5](../../issues/5)
> **Why first:** Every P1 panel below needs one of these endpoints to exist.

- [ ] `GET /api/market` — session status + yfinance watchlist prices (5-min cache)
- [ ] `GET /api/bonus` — reads `data/bonus_alerts_sent.json`, returns `{ last_scan, last_count, last_offers[] }`
- [ ] `GET /api/investment` — yfinance batch fetch for `["UNH","AGIO","ACAD","VEEV","IIPR","HIMS"]`
- [ ] Wire all new endpoints into `/api/summary` agent status block
- [ ] Add `_market_status()`, `_bonus_status_full()`, `_investment_status()` to server.py
- **File:** `integrations/web/server.py`

---

#### 2. Health Agent detail panel · [Issue #6](../../issues/6)
> Weight trend sparkline, macro progress, workout ring

- [ ] Enrich `GET /api/health` response: add `weight_history[]` (14d), `sleep_history[]` (7d), `today_macros`
- [ ] `renderHealthDetail()` — macro progress bars (protein g / 150g, calories / 1900)
- [ ] Inline SVG weight sparkline (see issue #11 for helper function)
- [ ] Sleep history as 7-night mini bar chart
- [ ] Workout this week: `3/4` colored progress bar
- **Files:** `server.py` + `index.html`

---

#### 3. Finance Agent detail panel · [Issue #7](../../issues/7)
> Budget by category, bonus offer list, side hustle tracker

- [ ] Enrich `GET /api/finance`: add `budget_by_category{}`, `last_offers[]`, `side_hustles[]`
- [ ] `renderFinanceDetail()` — budget table grouped by category with monthly total
- [ ] Show `last_offers[]` from last bonus scan (card name, bonus amount, min spend)
- [ ] Show top 3 side hustle ideas from `data/side_hustle_ideas.json`
- **Files:** `server.py` + `index.html`

---

#### 4. Market Agent detail panel · [Issue #8](../../issues/8)
> Live watchlist with prices, session badge on card

- [ ] `GET /api/market` (from step 1) — fetch via yfinance, 5-min module-level cache
- [ ] `renderMarketDetail()` — price grid: ticker, price, change % (green/red), 52w range bar
- [ ] Market card: show session badge inline (Market Open 🟢 / Pre-market 🟡 / Closed ⚫)
- [ ] Handle market closed (show last close price, gray)
- **Files:** `server.py` + `index.html`

---

#### 5. Calendar Agent detail panel · [Issue #9](../../issues/9)
> Day-grouped agenda, event cards with time + location

- [ ] Enrich `GET /api/calendar`: include `end` time, `calendar_name`, `html_link` per event
- [ ] `renderCalendarDetail()` — group events by day (`Today`, `Tomorrow`, `Wed Mar 26…`)
- [ ] Event cards: name, time range, location with 📍, Google Calendar link
- [ ] Conflict detection: flag overlapping events in yellow
- [ ] Free time gaps ≥ 1h highlighted
- **Files:** `server.py` + `index.html`

---

#### 6. Email Agent detail panel · [Issue #10](../../issues/10)
> Dual-account inbox with urgency triage

- [ ] Rewrite `GET /api/email`: return per-account structure with urgency flag per message
  - Urgency: 🔴 urgent keywords / 🟡 question/reply needed / ⚪ FYI/newsletter
- [ ] `renderEmailDetail()` — two sections (jynpriority / jngai5.3), urgency dot per email
- [ ] Email row: sender name, subject (full, wrapping), time received
- [ ] Expand-on-click to show snippet inline
- **Files:** `server.py` + `gmail_client.py` (check dual-account) + `index.html`

---

### P2 — Enrichment (do after P1 is working)

#### 7. Investment Agent card + panel · [Issue #12](../../issues/12)
> Add investment as a 12th agent card on dashboard

- [ ] Add `GET /api/investment` (from step 1)
- [ ] Add `investment` to `AGENTS_ORDER` in `index.html`
- [ ] Add investment card to `/api/summary` agents block
- [ ] `renderInvestmentDetail()` — watchlist table with 52w range bar per ticker
- [ ] Conviction ratings from agent (if stored)
- **Files:** `server.py` + `index.html`

---

#### 8. Social + Mortgage + Bonus panels · [Issue #13](../../issues/13)

**Social:**
- [ ] `GET /api/social` — call `_gather_all_events()` if `data/social_cache.json` is stale (>6h), else return cache
- [ ] `renderSocialDetail()` — event cards with RSVP link, cost badge, source badge

**Mortgage:**
- [ ] `GET /api/mortgage` — read `data/mortgage_cache.json` if exists, else empty
- [ ] `renderMortgageDetail()` — listing cards with discount%, yield%, rating badge (STRONG/GOOD/PASS)

**Bonus:**
- [ ] `GET /api/bonus` (from step 1) already covers this
- [ ] `renderBonusDetail()` — offer cards from `last_offers[]`, source link to DoC

---

#### 9. Travel Agent deal browser · [Issue #11](../../issues/11)
> Booking deep links, escape.flights section, steal highlight

- [ ] Ensure `get_status()` in `travel_agent/handler.py` includes `cash_deals[]` from escape.flights RSS
- [ ] `renderTravelDetail()` — steals section with pulsing highlight, booking_url deep links
- [ ] Escape.flights section with Kayak URL per deal
- **Files:** `agents/travel_agent/handler.py` + `index.html`

---

#### 10. Inline SVG sparklines · [Issue #15](../../issues/15)
> Zero-dependency trend charts for health + investment

- [ ] Write `sparkline(values, opts)` helper in `index.html` (~40 lines, pure SVG)
- [ ] `barChart(values, opts)` for sleep nightly bars
- [ ] Use in health detail (weight trend, sleep bars)
- [ ] Use in investment detail (52w range mini-bars)
- [ ] Weight direction: going down = green, going up = red
- **File:** `index.html`

---

#### 11. Interactive action buttons · [Issue #14](../../issues/14)
> Trigger agent scans from the web UI

- [ ] `POST /api/action/bonus_scan` → calls `bonus_alert.run_bonus_scan(force=True)`
- [ ] `POST /api/action/social_scan` → calls `social_agent.run_event_scan()`
- [ ] `POST /api/action/mortgage_scan` → calls `mortgage_note_agent.handle("scan")`
- [ ] `POST /api/action/briefing` → calls `calendar_agent.run_morning_briefing()`
- [ ] Add simple `DASHBOARD_TOKEN` env var check to all action endpoints
- [ ] Action button component in `index.html` with spinner + result toast
- **Files:** `server.py` + `index.html` + `.env`

---

#### 13. Image OCR / Text Extraction for Better Agent Routing · (new)
> **Why:** When a user sends an image to the bot, routing currently relies on the vision model classifying the image type (food/event/receipt/etc). But images with embedded text — screenshots of data tables, flight prices, medical charts, lease agreements — can be misclassified because the vision model may not reliably read the text content. Extracting text from the image first and including it in the routing decision would dramatically improve accuracy.

- [ ] In `integrations/telegram/bot.py → _triage_image()`: after base64-encoding the image, also run an OCR pass to extract any embedded text
- [ ] Use Groq's vision model with a dedicated "extract all text from this image verbatim" prompt — store result as `image_text`
- [ ] Pass `image_text` alongside the image to the classification prompt so the router can see both visual content AND text content
- [ ] Update `_AGENT_IMAGE_PROMPTS` — when routing to an agent, include `image_text` in the context so the agent can see the extracted data
- [ ] Add caption keyword fast-path: if `image_text` mentions "flight", "award", "miles" → travel; if "infusion", "IV", "patient" → infusion; if table headers match known patterns, route to appropriate agent
- [ ] Test with: Amadeus flight result screenshots, health/lab result images, Paperstac listing screenshots, calendar invite screenshots
- **File:** `integrations/telegram/bot.py`

---

#### 12. Permanent Cloudflare Tunnel + PWA · [Issue #16](../../issues/16)
> Permanent URL + iPhone home screen app

- [ ] Run one-time: `cloudflared tunnel login && cloudflared tunnel create executive-ai`
- [ ] Create `~/.cloudflared/config.yml` pointing to `localhost:8080`
- [ ] Create `~/Library/LaunchAgents/com.justinngai.cloudflare-tunnel.plist`
- [ ] Add `integrations/web/static/manifest.json` for PWA
- [ ] Add `<link rel="manifest">` + apple meta tags to `index.html`
- [ ] Generate 192×192 app icon to `integrations/web/static/icon-192.png`
- **Files:** new config files + `index.html`

---

## Issue → File Map (quick reference)

| Issue | File(s) to Edit |
|-------|-----------------|
| #5 missing endpoints | `integrations/web/server.py` |
| #6 health panel | `server.py` + `index.html` |
| #7 finance panel | `server.py` + `index.html` |
| #8 market panel | `server.py` + `index.html` |
| #9 calendar panel | `server.py` + `index.html` |
| #10 email panel | `server.py` + `integrations/google/gmail_client.py` + `index.html` |
| #11 travel panel | `agents/travel_agent/handler.py` + `index.html` |
| #12 investment panel | `server.py` + `index.html` |
| #13 social/mortgage/bonus | `server.py` + `index.html` |
| #14 action buttons | `server.py` + `index.html` |
| #15 sparklines | `index.html` |
| #16 tunnel + PWA | config files + `index.html` |

---

## Architecture Notes

- **`integrations/web/server.py`** is the only backend file to touch. All new endpoints follow the `_load()` + `JSONResponse()` pattern already there.
- **`index.html`** is a single file (no build step). All JS is inline. Add renderers below the existing ones.
- **yfinance cache:** Use a module-level `_cache = {}` dict with `{"data": ..., "ts": datetime}`. Both `/api/market` and `/api/investment` share it. Cache TTL = 5 minutes.
- **Agent runner imports:** All scheduled runners are already importable. E.g., `from agents.bonus_alert.handler import run_bonus_scan`.
- **Dual-account Gmail:** `integrations/google/gmail_client.py` has `list_unread(account="primary"|"secondary")` — verify signature before calling.
