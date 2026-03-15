# Executive AI Assistant

Personal AI executive assistant for Justin Ngai. Works via Telegram on phone and desktop.

## What it does

- Receives commands via Telegram (text or voice)
- Routes them to the right specialized agent
- Responds with concise, actionable output
- Logs tasks, health data, and notes

## Agents

| Agent | Status | Purpose |
|-------|--------|---------|
| Infusion Consulting | ✅ Live | Hospital ops consulting, leads, speaking opps |
| General Assistant | ✅ Live | Q&A, anything else |
| Investment Analyst | 🔜 Coming | Stock ideas, portfolio rebalancing |
| Mortgage Notes | 🔜 Coming | Discounted note alerts, underwriting |
| Travel Hacker | 🔜 Coming | Award flight alerts, miles optimization |
| Health Tracker | 🔜 Coming | Health logging, trends |
| NYC Events | 🔜 Coming | Networking, local events |

## Stack

- **AI**: Claude (Anthropic)
- **Interface**: Telegram Bot (phone + desktop)
- **Orchestration**: n8n (for scheduled scans)
- **Storage**: Local JSON → Supabase (when ready)
- **Automation**: Python

## Quick Start

```bash
git clone https://github.com/YOUR_USERNAME/executive-ai-assistant.git
cd executive-ai-assistant
chmod +x setup.sh && ./setup.sh
# Edit .env with your API keys
source venv/bin/activate
python main.py
```

## Setup

### 1. Get API Keys

| Key | Where |
|-----|-------|
| `ANTHROPIC_API_KEY` | [console.anthropic.com](https://console.anthropic.com) |
| `TELEGRAM_BOT_TOKEN` | Message `@BotFather` on Telegram → `/newbot` |
| `BRAVE_API_KEY` | [brave.com/search/api](https://brave.com/search/api/) — free tier available |

### 2. Get your Telegram Chat ID

1. Start the bot and send `/start`
2. The bot replies with your Chat ID
3. Add it to `.env` as `TELEGRAM_CHAT_ID`

### 3. Run

```bash
source venv/bin/activate
python main.py test   # test command routing
python main.py        # start the bot
```

## Example Commands (send via Telegram)

```
Schedule lunch with Alex Thursday
Log weight 175
Remind me to research mortgage notes tomorrow
What's a good chair utilization benchmark for a 20-chair infusion center?
Find business class award seats NYC to Tokyo
Morning briefing
```

## On a New Computer

```bash
git clone https://github.com/YOUR_USERNAME/executive-ai-assistant.git
cd executive-ai-assistant
./setup.sh
# Copy your .env values over
python main.py
```

## Architecture

```
You (Telegram)
     ↓
Telegram Bot (integrations/telegram/bot.py)
     ↓
Command Router (core/command_router.py)
     ↓
Specialized Agent
     ↓
Memory / External APIs
     ↓
Response → You
```
