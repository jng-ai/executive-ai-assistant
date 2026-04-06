# Executive AI Assistant

Personal executive AI system for Justin Ngai, running as a Telegram bot with multiple specialized agents.

---

## Architecture Overview

This system is a **personal executive AI assistant** that acts as an intelligent interface between Justin and his digital life. It is built around five key design principles:

### 1. Intent-Based Routing
Every incoming message flows through `core/command_router.py`, which uses an LLM to classify the message into one of 15 intent types (e.g., `log_health`, `personal_finance`, `schedule_meeting`). This classification drives dispatch to the correct specialized agent. The router never guesses — if ambiguous, it falls back to `general_question`. This keeps each agent's logic clean and domain-focused.

### 2. Agent Per Domain
Each domain has a self-contained agent in `agents/`. Agents own their system prompts, data logic, and LLM calls. They are not aware of each other's internal state. Cross-agent collaboration (e.g., finance → market intel) happens via function imports, not shared memory. This makes each agent independently testable and replaceable.

### 3. Offline-First Storage
`core/memory.py` uses local JSON files in `data/` as the primary datastore — always fast, always available, never blocked by network. Notion is synced asynchronously in the background and **fails silently** (fire-and-forget). The bot never waits on Notion; it just logs to local JSON and returns immediately.

### 4. Provider Abstraction
`core/llm.py` wraps Groq, Ollama, and Anthropic behind a single `chat(system, user, max_tokens)` interface. Swap providers with one `.env` line. Vision (image analysis) uses Groq `meta-llama/llama-4-scout-17b-16e-instruct` via a separate base64 image call pattern. All agents call `core.llm.chat` — none import provider SDKs directly (except the Anthropic fallback path in `llm.py`).

### 5. Scheduled Proactive Intelligence
APScheduler delivers 8 scheduled jobs at configured ET times without user prompting. This turns the bot from a reactive Q&A tool into an active executive assistant that briefs, nudges, and alerts autonomously. The scheduler runs inside the same process as the Telegram bot (via `job_queue`).

---

## End-to-End Data Flow

### Text Message
```
User sends message (Telegram)
  → bot.py: handle_message()
  → command_router.classify(message)         ← LLM call (Groq)
  → dispatch(intent, details, params)
  → agent.handle(message)                    ← domain-specific logic
    → core.llm.chat(system, user)            ← LLM call
    → core.memory / integrations/* (if needed)
  → reply_text (split at 4096 chars if long)
```

### Photo Message
```
User sends photo (Telegram)
  → bot.py: handle_photo()
  → download + base64 encode
  → _triage_image(image_b64, caption)       ← vision LLM: food/event/receipt/document/general
  → route based on type:
      food     → _analyze_food_image()       → core.memory.log_health()
      event    → _handle_event_image()       → calendar_client.create_event() (auto)
      receipt  → _handle_receipt_image()
      document → _handle_document_image()
      general  → _handle_general_image()
```

### Voice Message
```
User sends voice OGG (Telegram)
  → bot.py: handle_voice()
  → download OGG → Groq Whisper transcription
  → process transcript as text (→ classify → dispatch)
  → edge-tts neural TTS (en-US-AndrewNeural)
  → send voice reply + text reply
```

### Scheduled Jobs (APScheduler, ET timezone)
```
7:30 AM  → health_agent.run_daily_nudge()          → Telegram push (silent if on track)
7:45 AM  → calendar_agent.run_morning_briefing()   → Today + tomorrow events
7:50 AM  → email_agent.run_morning_digest()        → Unread email urgency triage
8:00 AM  → bonus_alert.run_bonus_scan()            → DoC, FM, Reddit scan
8:05 AM  → followup_agent.run_pending_followups()  → Fire due follow-up emails/meetings
8:10 AM  → email_agent.scan_and_triage_confirmations() → Booking emails → calendar events
8:15 AM  → _scheduled_origin_refresh()             → Financial snapshot update
6:00 PM  → calendar_agent.run_eod_calendar()       → EOD calendar recap
6:00 PM  → email_agent.run_eod_email_summary()     → EOD email recap
Tue/Fri 9 AM → social_agent.run_event_scan()       → NYC events roundup
```

---

## Layer Breakdown

### Entry Point (`main.py`)
- Loads `.env`, validates required keys, optionally runs in test mode
- Calls `integrations/notion/client.repair_databases()` at startup (silent on fail)
- Starts FastAPI web dashboard on port 8080 in a background thread
- Starts Telegram bot + APScheduler via `run_bot()`

### Core Layer (`core/`)
| Module | Role |
|--------|------|
| `command_router.py` | LLM-based intent classifier → 15 intent types |
| `llm.py` | Provider-agnostic `chat()` — Groq / Ollama / Anthropic |
| `memory.py` | Local JSON CRUD (tasks, health, notes) + async Notion sync |
| `search.py` | Tavily web search + page extraction; falls back to `requests` |
| `followups.py` | Follow-up store: add / list / mark_done / cancel |

### Agent Layer (`agents/`)
Each agent exposes a `handle(message: str) -> str` function (plus optional scheduled runner functions).

| Agent | Scheduled Runner | Domain |
|-------|-----------------|--------|
| `health_agent` | `run_daily_nudge()` | Weight, sleep, workouts, nutrition |
| `finance_agent` | — | CC/bank bonuses, tax, side hustles, budget |
| `bonus_alert` | `run_bonus_scan()` | Elevated CC/bank bonus detection |
| `market_agent` | — | Stock market analysis, sector rotation |
| `calendar_agent` | `run_morning_briefing()`, `run_eod_calendar()` | Google Calendar CRUD |
| `email_agent` | `run_morning_digest()`, `run_eod_email_summary()`, `scan_and_triage_confirmations()` | Gmail read/draft/send |
| `followup_agent` | `run_pending_followups()` | Scheduled email/meeting follow-ups |
| `social_agent` | `run_event_scan()` | NYC events (Luma, Eventbrite, Meetup) |
| `mortgage_note_agent` | — | Paperstac scraper → performing first-lien notes |
| `investment_agent` | — | Stock ideas, portfolio analysis |
| `travel_agent` | — | Award flights, miles optimization |
| `infusion_agent` | — | Hospital infusion ops consulting intel |
| `general_handler` | — | Zero-context fallback (privacy design) |

### Integration Layer (`integrations/`)
| Module | Role |
|--------|------|
| `telegram/bot.py` | All Telegram handlers, photo/voice pipeline, APScheduler setup |
| `telegram/dashboard.py` | `/dashboard` inline keyboard — agent status hub |
| `google/auth.py` | Dual-account OAuth2 (primary + secondary Gmail/Calendar) |
| `google/calendar_client.py` | Multi-calendar read/write, free slot finder |
| `google/gmail_client.py` | Read, search, draft, send across both Gmail accounts |
| `google_sheets/client.py` | Webhook-based CC/bank application logging |
| `notion/client.py` | Database CRUD + auto-schema enforcement |
| `paperstac/scraper.py` | Playwright headless login + mortgage note listing extraction |
| `web/server.py` | FastAPI dashboard (port 8080) — agent status views |

---

## Agents In Depth

### Health Agent (`agents/health_agent/handler.py`)
PRD v2 — full nutrition + workout coach. Entry point: `handle(message)`.

**Routing logic** (in order):
1. Summary/progress keywords → `_build_summary()` (7-day trend)
2. Food suggestion keywords → `_what_to_eat()` (based on today's intake)
3. Workout suggestion/topic keywords + no "done" keywords → `_suggest_workout()`
4. Insight keywords + workout topic → LLM analysis of recent logs
5. LLM parse attempt → `parse_log()` → if is a log entry → `log_health()` + feedback
6. Fallback → general health Q&A with recent log context

**Justin's targets:** 165 lbs goal, 150g protein/day, 1,900 kcal/day, 7.5h sleep, 3–4 workouts/week.

**Key helpers:** `_et_hour()` → `_meal_label()` (Breakfast/Lunch/Snack/Dinner by ET hour); `_check_goal_progression()` (triggers after weight logging if on streak); `_nutrition_balance_response()` (called after every meal log — shows running macro total).

### Finance Agent (`agents/finance_agent/handler.py`)
Pocket CFA/CFP. Sub-classifies incoming messages into 15 finance sub-intents using its own LLM classifier, then dispatches to specialized sub-handlers: bonus search, re-eligibility check, application logging, tax strategy, side hustle scanning, budget tracking, profile update.

**Key data files:** `data/finance_bonuses.json`, `data/financial_profile.json`, `data/budget_log.json`, `data/side_hustle_ideas.json`.

### Follow-up Agent (`agents/followup_agent/handler.py`)
LLM-parses requests into `create | list | cancel` actions. `create` computes due date (today + delay_days) and calls `core.followups.add_followup()`. `run_pending_followups()` fires due items: email type → drafts + sends via Gmail; meeting type → creates Google Calendar event.

### Calendar Agent (`agents/calendar_agent/handler.py`)
LLM-parses calendar intent into `today | list | create | free_slots | delete | question`. Checks conflicts before creating. `run_morning_briefing()` runs at 7:45 AM and is **silent** if no events (no spam).

### Bonus Alert (`agents/bonus_alert/handler.py`)
Daily 8 AM scan of Doctor of Credit RSS, Frequent Miner RSS, and Reddit JSON APIs. Deduplicates via `data/bonus_alerts_sent.json` (stores last scan date). Only alerts if finds elevated offers above historical normal.

### Dashboard (`integrations/telegram/dashboard.py`)
`/dashboard` command shows a 2-column inline keyboard of all 11 agents. Each agent exposes a one-liner status (from local data — no LLM calls) and a drill-down dashboard screen. Navigates via `callback_data="dash:agent_key"` and `"dash:__main__"` for back.

---

## Privacy Design

The `general_handler` passes **zero** personal context to the LLM — only the raw question. This ensures that casual Q&A (weather, general knowledge, etc.) doesn't leak personal details to cloud LLM providers. For maximum privacy on all queries, set `LLM_PROVIDER=ollama` to route everything through local Llama.

---

## Stack
- Python 3.12, python-telegram-bot 20+, APScheduler (job_queue)
- LLM: Groq (llama-3.3-70b) via `core/llm.py`; vision via Groq meta-llama/llama-4-scout-17b-16e-instruct
- TTS: edge-tts (en-US-AndrewNeural) with gTTS fallback
- STT: Groq Whisper (whisper-large-v3)
- Search: Tavily API
- Storage: local JSON (`data/`) + Notion sync (background, non-blocking)
- Google: Calendar API + Gmail API (OAuth2 refresh token in .env)
- Paperstac: Playwright headless scraper (authenticated)

---

## Entry Point
```bash
python main.py        # start bot
python main.py test   # test command router locally
```
Running via LaunchAgent: `~/Library/LaunchAgents/com.justinngai.executive-ai.plist`
Logs: `logs/bot.log` and `logs/bot_error.log`

## Key Files
| File | Purpose |
|------|---------|
| `integrations/telegram/bot.py` | Main bot — all handlers, photo triage, voice, scheduler |
| `core/command_router.py` | Intent classification (15 intents) |
| `core/memory.py` | Local JSON store (health, tasks, notes) + Notion sync |
| `core/llm.py` | Groq/Ollama/Anthropic LLM wrapper |
| `core/search.py` | Tavily search wrapper |
| `core/followups.py` | Follow-up scheduler store |
| `integrations/google/calendar_client.py` | Multi-calendar read/write |
| `integrations/google/gmail_client.py` | Gmail read/draft/send |
| `integrations/paperstac/scraper.py` | Playwright Paperstac login + listings scrape |
| `data/health.json` | Health logs (gitignored — local only) |
| `data/bonus_alerts_sent.json` | Tracks last bonus alert scan date |

## Agents
| Agent | Trigger | Notes |
|-------|---------|-------|
| `health_agent` | food/workout logs, photos, "what should I eat/do" | PRD v2 — nutrition balance, workout rotation, goal progression |
| `social_agent` | NYC events, "what's happening" | Luma, Eventbrite, Meetup, X, Instagram |
| `market_agent` | tickers, market briefing, sector rotation | Time-context aware (pre-market/open/after-hours) |
| `finance_agent` | CC/bank bonuses, budget, tax strategy, side hustles | Pocket CFA/CFP — 15 sub-intents; re-eligibility engine; self-improving profile |
| `bonus_alert` | Scheduled 8 AM ET daily | Scrapes DoC, Frequent Miner, Reddit for elevated bonuses |
| `mortgage_notes` | "notes scan" | Playwright login to Paperstac, filter performing/first-lien notes |
| `travel_hack` | award flights, miles, points | Asia-focused |
| `calendar_agent` | calendar queries, event creation | All calendars; conflict check; run_morning_briefing() |
| `email_agent` | email read/draft/send | Gmail API; dual-account; confirmation triage → auto-calendar |
| `followup_agent` | "follow up with X in 3 days" | Stores + fires via Gmail/Calendar |
| `infusion_consulting` | hospital infusion ops intel | Quiet from employer |
| `investment_agent` | stocks, portfolio, investing | yfinance + Tavily |
| `general_handler` | fallback | Zero personal info in system prompt (privacy) |

## Scheduled Jobs (APScheduler / ET timezone)
| Time | Job |
|------|-----|
| 7:30 AM | Health nudge (silent if on track) |
| 7:45 AM | Calendar morning briefing |
| 7:50 AM | Email digest (urgency triage) |
| 8:00 AM | Bonus alert scan (DoC, Frequent Miner, Reddit) |
| 8:05 AM | Follow-up check (fire due reminders) |
| 8:10 AM | Confirmation email scan → auto-calendar |
| 8:15 AM | Origin financial snapshot refresh |
| Tue/Fri 9 AM | NYC event scan |
| 6:00 PM | EOD wrap-up (calendar + email) |

## Photo Triage Pipeline
1. **Caption override** (fast path): regex checks caption for travel/market/infusion/mortgage keywords → routes directly
2. **Vision triage** (fallback): Groq meta-llama/llama-4-scout-17b-16e-instruct classifies into 9 categories: `food`, `event`, `receipt`, `document`, `travel`, `market`, `infusion`, `mortgage`, `general`
3. Routes to domain handler:
   - `food` → `_analyze_food_image()` → nutrition estimate + `log_health()`
   - `event` → `_handle_event_image()` → extract `CALENDAR_DATA:` JSON → auto-create Google Calendar event
   - `receipt` → `_handle_receipt_image()` → parse expense + category
   - `document` → `_handle_document_image()` → OCR + summarize
   - `travel/market/infusion/mortgage` → respective agent-specific image prompts
   - `general` → `_handle_general_image()`

## .env Required Keys
```
TELEGRAM_BOT_TOKEN=
GROQ_API_KEY=
TAVILY_API_KEY=
NOTION_TOKEN=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REFRESH_TOKEN=
GOOGLE_REFRESH_TOKEN_JNGAI53=
GOOGLE_SHEETS_CC_WEBHOOK=
GOOGLE_SHEETS_BANK_WEBHOOK=
PAPERSTAC_EMAIL=
PAPERSTAC_PASSWORD=
ORIGIN_EMAIL=
ORIGIN_PASSWORD=
```

## Restart Bot
```bash
launchctl bootout gui/501 ~/Library/LaunchAgents/com.justinngai.executive-ai.plist
launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.justinngai.executive-ai.plist
```

## Testing
```bash
pytest tests/ -v --cov=. --cov-report=term-missing
```
Target: >90% coverage on core/ and agents/. External APIs (Telegram, Google, Notion, Tavily, Groq) are mocked.

## Known Issues / Notes
- Notion health_log schema mismatch (non-blocking, logged but doesn't affect bot)
- `data/` is gitignored — health.json lives only on local machine; copy manually when changing computers
- Paperstac scraper uses Playwright + Chromium headless (~90MB, installed separately via `playwright install chromium`)
- Google OAuth refresh token is long-lived; re-run `scripts/google_auth.py` only if it expires
- `scripts/oracle_setup.sh` — Oracle Cloud VM deployment script (not referenced by bot code; kept as deployment reference)
