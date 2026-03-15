#!/usr/bin/env python3
"""
Executive AI Assistant — Justin Ngai
Entry point. Loads env, starts the Telegram bot.

Usage:
  python main.py          → start the Telegram bot
  python main.py test     → test the command router locally
"""

import sys
import os
from pathlib import Path
from dotenv import load_dotenv

# Load .env from project root
load_dotenv(Path(__file__).parent / ".env")

def check_env():
    required = ["ANTHROPIC_API_KEY", "TELEGRAM_BOT_TOKEN"]
    missing = [k for k in required if not os.environ.get(k)]
    if missing:
        print(f"Missing required env vars: {', '.join(missing)}")
        print("Copy .env.example to .env and fill in your keys.")
        sys.exit(1)

def run_bot():
    check_env()
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
