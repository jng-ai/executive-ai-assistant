#!/usr/bin/env python3
"""
Executive AI Assistant — Justin Ngai
Entry point. Loads env, starts the Telegram bot.

Usage:
  python main.py          → start the Telegram bot
  python main.py test     → test the command router locally
"""

import logging
import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).parent / ".env")


def _setup_logging():
    os.makedirs("logs", exist_ok=True)
    fmt = "%(asctime)s %(levelname)-8s %(name)s — %(message)s"
    logging.basicConfig(
        level=logging.INFO,
        format=fmt,
        handlers=[
            logging.StreamHandler(),
            logging.FileHandler("logs/bot.log", encoding="utf-8"),
        ]
    )
    # Silence noisy third-party loggers
    logging.getLogger("httpx").setLevel(logging.WARNING)
    logging.getLogger("httpcore").setLevel(logging.WARNING)
    logging.getLogger("telegram").setLevel(logging.WARNING)
    logging.getLogger("googleapiclient").setLevel(logging.WARNING)


def check_env():
    provider = os.environ.get("LLM_PROVIDER", "groq").lower()
    llm_key = {"groq": "GROQ_API_KEY", "anthropic": "ANTHROPIC_API_KEY"}.get(provider)
    required = [
        "TELEGRAM_BOT_TOKEN",
        "GOOGLE_CLIENT_ID",
        "GOOGLE_CLIENT_SECRET",
        "GOOGLE_REFRESH_TOKEN",
        "TAVILY_API_KEY",
    ] + ([llm_key] if llm_key else [])
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"Missing required env vars: {', '.join(missing)}")
        print("Edit your .env file and fill in the missing keys.")
        sys.exit(1)

def run_bot():
    _setup_logging()
    check_env()

    # Ensure all Notion databases have correct columns (silent on failure)
    try:
        from integrations.notion.client import is_configured, repair_databases
        if is_configured():
            repair_databases()
    except Exception:
        pass

    # Start web dashboard server in background thread (port 8080)
    try:
        from integrations.web.server import start as start_web
        start_web(port=8080)
        print("Web dashboard started on http://localhost:8080")
    except Exception as e:
        print(f"Web dashboard failed to start: {e}")

    from integrations.telegram.bot import run_bot
    run_bot()

def run_test():
    check_env()
    from core.command_router import classify
    test_messages = [
        "Schedule lunch with Alex Thursday",
        "Log weight 175",
        "Remind me to research mortgage notes tomorrow",
        "What's a good chair utilization target for an infusion center?",
        "Find me business class award flights to Tokyo",
        "Morning briefing",
    ]
    print("\nCommand Router Test\n" + "="*40)
    for msg in test_messages:
        result = classify(msg)
        print(f"\nInput:  {msg}")
        print(f"Intent: {result['intent']}")
        print(f"Detail: {result['details']}")

if __name__ == "__main__":
    mode = sys.argv[1] if len(sys.argv) > 1 else "bot"
    if mode == "test":
        run_test()
    else:
        run_bot()
