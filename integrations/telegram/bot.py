"""
Telegram Bot — the phone/computer interface for your executive AI assistant.
Receives messages, routes them to the command router, sends responses back.

Run: python main.py
"""

import os
import asyncio
import logging
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
from core.command_router import classify
from core.memory import add_task, log_health, list_tasks, add_note
from agents.infusion_agent.handler import handle as infusion_handle
from agents.mortgage_note_agent.handler import handle as mortgage_handle
from agents.investment_agent.handler import handle as investment_handle
from agents.travel_agent.handler import handle as travel_handle
from agents.general_handler import handle_general

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main handler — classify message and dispatch to the right agent."""
    text = update.message.text or ""
    await update.message.reply_text("Thinking...")

    classified = classify(text)
    intent = classified.get("intent", "general_question")
    details = classified.get("details", text)
    params = classified.get("params", {})

    response = await dispatch(intent, details, params, text)
    await update.message.reply_text(response, parse_mode="Markdown")


async def dispatch(intent: str, details: str, params: dict, raw: str) -> str:
    """Route to the correct handler based on intent."""

    if intent == "create_task":
        entry = add_task(details, due=params.get("due", ""))
        return f"Task saved: *{details}*\nID: #{entry['id']}"

    elif intent == "log_health":
        metric = params.get("metric", "note")
        value = params.get("value", details)
        entry = log_health(metric, value)
        return f"Logged: *{metric}* = {value} ({entry['date']})"

    elif intent == "infusion_consulting":
        return await asyncio.to_thread(infusion_handle, details)

    elif intent == "mortgage_notes":
        return await asyncio.to_thread(mortgage_handle, details)

    elif intent == "investment_research":
        return await asyncio.to_thread(investment_handle, details)

    elif intent == "travel_hack":
        return await asyncio.to_thread(travel_handle, details)

    elif intent == "daily_briefing":
        return await build_briefing()

    elif intent == "general_question":
        return await asyncio.to_thread(handle_general, raw)

    else:
        return await asyncio.to_thread(handle_general, raw)


async def build_briefing() -> str:
    """Morning executive briefing."""
    tasks = list_tasks("open")
    task_lines = "\n".join(f"  • {t['task']}" for t in tasks[:5]) or "  None"

    return (
        "*Good morning, Justin.*\n\n"
        f"*Open Tasks ({len(tasks)}):*\n{task_lines}\n\n"
        "_Agents online: Infusion · Mortgage Notes · Investment · Travel_\n"
        "_Coming soon: Health tracker · NYC Events · Email · Calendar_"
    )


async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"Executive AI Assistant online.\nYour chat ID: `{chat_id}`\n\n"
        "Try:\n"
        "• `Schedule lunch with Alex Thursday`\n"
        "• `Log weight 175`\n"
        "• `Remind me to call the infusion director`\n"
        "• `Briefing`",
        parse_mode="Markdown",
    )


def run_bot():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in .env")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot running. Send /start to your bot in Telegram.")
    app.run_polling(drop_pending_updates=True)
