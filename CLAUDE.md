# Executive AI Assistant

Personal executive AI system for Justin Ngai, running as a Telegram bot with multiple specialized agents.

## Stack
- Python 3.12, python-telegram-bot 20+, APScheduler (job_queue)
- LLM: Groq (llama-3.3-70b) via `core/llm.py`; vision via Groq llama-3.2-11b-vision
- TTS: edge-tts (en-US-AndrewNeural) with gTTS fallback
- STT: Groq Whisper (whisper-large-v3)
- Search: Tavily API
- Storage: local JSON (`data/`) + Notion sync (background, non-blocking)
- Google: Calendar API + Gmail API (OAuth2 refresh token in .env)
- Paperstac: Playwright headless scraper (authenticated)

## Entry Point
```bash
python main.py
```
Running via LaunchAgent: `~/Library/LaunchAgents/com.justinngai.executive-ai.plist`
Logs: `logs/bot.log` and `logs/bot_error.log`

## Key Files
| File | Purpose |
|------|---------|
| `integrations/telegram/bot.py` | Main bot — all handlers, photo triage, voice, scheduler |
| `core/command_router.py` | Intent classification (12 intents) |
| `core/memory.py` | Local JSON store (health, tasks, notes) + Notion sync |
| `core/llm.py` | Groq LLM wrapper |
| `core/search.py` | Tavily search wrapper |
| `integrations/google/calendar_client.py` | Multi-calendar read/write |
| `integrations/google/gmail_client.py` | Gmail read/draft/send |
| `integrations/paperstac/scraper.py` | Playwright Paperstac login + listings scrape |
| `data/health.json` | Health logs (gitignored — local only) |
| `data/bonus_alerts_sent.json` | Tracks last bonus alert scan date |

## Agents
| Agent | Trigger | Notes |
|-------|---------|-------|
| `health_agent` | food/workout logs, photos, "what should I eat/do" | PRD v2 — nutrition balance, workout rotation, goal progression |
| `social_agent` | NYC events, "what's happening" | Luma, Eventbrite, Meetup, X, Instagram; individual event URL extraction |
| `market_agent` | tickers, market briefing, sector rotation | Time-context aware (pre-market/open/after-hours) |
| `finance_agent` | CC/bank bonuses, budget | Reads CC Tracker + Bank Tracker Google Sheets |
| `bonus_alert` | Scheduled 8 AM ET daily | Scrapes DoC, Frequent Miner, Reddit for elevated bonuses |
| `mortgage_notes` | "notes scan" | Playwright login to Paperstac, filter performing/first-lien notes |
| `travel_hack` | award flights, miles, points | Asia-focused |
| `calendar_agent` | calendar queries, event creation | All calendars via _get_calendar_ids() |
| `email_agent` | email read/draft/send | Gmail API |
| `infusion_consulting` | hospital infusion ops intel | Quiet from employer |
| `general_handler` | fallback | Zero personal info in system prompt (privacy) |

## Scheduled Jobs (APScheduler / ET timezone)
| Time | Job |
|------|-----|
| 7:30 AM | Health nudge (silent if on track) |
| 8:00 AM | Bonus alert scan (DoC, Frequent Miner, Reddit) |
| Tue/Fri 9 AM | Event scan (alert-only Tue, full roundup Fri) |

## Photo Triage Pipeline
1. Vision model classifies: food / event / receipt / document / screenshot / general
2. Routes to: `_analyze_food_image` / `_handle_event_image` / `_handle_receipt_image` / etc.
3. Event images → extract `CALENDAR_DATA:` JSON → auto-create Google Calendar event

## .env Required Keys
```
TELEGRAM_BOT_TOKEN=
GROQ_API_KEY=
TAVILY_API_KEY=
NOTION_TOKEN=
GOOGLE_CLIENT_ID=
GOOGLE_CLIENT_SECRET=
GOOGLE_REFRESH_TOKEN=
GOOGLE_SHEETS_CC_WEBHOOK=
GOOGLE_SHEETS_BANK_WEBHOOK=
PAPERSTAC_EMAIL=
PAPERSTAC_PASSWORD=
```

## Restart Bot
```bash
launchctl bootout gui/501 ~/Library/LaunchAgents/com.justinngai.executive-ai.plist
launchctl bootstrap gui/501 ~/Library/LaunchAgents/com.justinngai.executive-ai.plist
```

## Known Issues / Notes
- Notion health_log schema mismatch (non-blocking, logged but doesn't affect bot)
- `data/` is gitignored — health.json lives only on local machine; copy manually when changing computers
- Paperstac scraper uses Playwright + Chromium headless (~90MB, installed separately via `playwright install chromium`)
- Google OAuth refresh token is long-lived; re-run `scripts/google_auth.py` only if it expires
