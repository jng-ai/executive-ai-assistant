"""
Telegram Bot — the phone/computer interface for your executive AI assistant.
Handles text messages, voice messages, and photos.
"""

import os
import asyncio
import logging
import base64
import tempfile
from telegram import Update
from telegram.ext import Application, MessageHandler, CommandHandler, filters, ContextTypes
from core.command_router import classify
from core.memory import add_task, log_health, list_tasks
from agents.infusion_agent.handler import handle as infusion_handle
from agents.mortgage_note_agent.handler import handle as mortgage_handle
from agents.investment_agent.handler import handle as investment_handle
from agents.travel_agent.handler import handle as travel_handle
from agents.health_agent.handler import handle as health_handle
from agents.social_agent.handler import handle as social_handle
from agents.general_handler import handle_general

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ── Photo handler (food logging via image) ────────────────────────────────────

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Receive a photo, analyze it with vision AI, log as a meal."""
    await update.message.reply_text("📸 Analyzing your food...")

    # Get the highest-resolution photo
    photo = update.message.photo[-1]
    caption = update.message.caption or ""

    # Download the photo
    file = await context.bot.get_file(photo.file_id)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        await file.download_to_drive(tmp.name)
        with open(tmp.name, "rb") as f:
            image_bytes = f.read()

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    # Analyze with Groq vision model
    response = await asyncio.to_thread(_analyze_food_image, image_b64, caption)
    await update.message.reply_text(response, parse_mode="Markdown")


def _analyze_food_image(image_b64: str, caption: str = "") -> str:
    """Send image to Groq vision model and log the meal."""
    from openai import OpenAI
    client = OpenAI(
        api_key=os.environ.get("GROQ_API_KEY", ""),
        base_url="https://api.groq.com/openai/v1",
    )

    prompt = (
        "Analyze this food photo. Identify what's in it, estimate:\n"
        "- Calories (rough estimate)\n"
        "- Protein (g)\n"
        "- Main macros\n"
        "- Is this a healthy choice?\n\n"
        f"Additional context from user: {caption}\n\n"
        "Reply in this format:\n"
        "🍽 **[Meal name]**\n"
        "~[X] cal · [X]g protein · [X]g carbs · [X]g fat\n"
        "✅/⚠️ [One sentence health note]"
    )

    try:
        resp = client.chat.completions.create(
            model="llama-3.2-11b-vision-preview",
            max_tokens=200,
            messages=[{
                "role": "user",
                "content": [
                    {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                    {"type": "text", "text": prompt},
                ]
            }]
        )
        result = resp.choices[0].message.content

        # Log to memory
        log_health("meal", result[:200], note="photo log")
        return f"{result}\n\n_✅ Meal logged_"

    except Exception as e:
        return f"⚠️ Couldn't analyze photo: {e}\n\nTip: describe your meal in text instead."


# ── Voice message handler ────────────────────────────────────────────────────

async def handle_voice(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Transcribe a voice message with Groq Whisper, then process as text."""
    await update.message.reply_text("🎙 Transcribing...")

    # Download the OGG voice file
    voice = update.message.voice
    file = await context.bot.get_file(voice.file_id)

    with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
        await file.download_to_drive(tmp.name)
        transcript = await asyncio.to_thread(_transcribe_audio, tmp.name)

    if not transcript:
        await update.message.reply_text("⚠️ Couldn't transcribe. Try typing it instead.")
        return

    # Show what was heard, then process like a text message
    await update.message.reply_text(f'🎙 _Heard: "{transcript}"_', parse_mode="Markdown")

    classified = classify(transcript)
    intent = classified.get("intent", "general_question")
    details = classified.get("details", transcript)
    params = classified.get("params", {})

    response = await dispatch(intent, details, params, transcript)
    if len(response) > 4000:
        for i in range(0, len(response), 4000):
            await update.message.reply_text(response[i:i+4000], parse_mode="Markdown")
    else:
        await update.message.reply_text(response, parse_mode="Markdown")


def _transcribe_audio(file_path: str) -> str:
    """Transcribe audio using Groq's free Whisper API."""
    from openai import OpenAI
    client = OpenAI(
        api_key=os.environ.get("GROQ_API_KEY", ""),
        base_url="https://api.groq.com/openai/v1",
    )
    try:
        with open(file_path, "rb") as f:
            resp = client.audio.transcriptions.create(
                model="whisper-large-v3",
                file=f,
                response_format="text",
            )
        return str(resp).strip()
    except Exception as e:
        logger.error(f"Transcription error: {e}")
        return ""


# ── Text message handler ──────────────────────────────────────────────────────

async def handle_message(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Main handler — classify message and dispatch to the right agent."""
    text = update.message.text or ""
    await update.message.reply_text("Thinking...")

    classified = classify(text)
    intent = classified.get("intent", "general_question")
    details = classified.get("details", text)
    params = classified.get("params", {})

    response = await dispatch(intent, details, params, text)

    # Telegram has 4096 char limit — split if needed
    if len(response) > 4000:
        for i in range(0, len(response), 4000):
            await update.message.reply_text(response[i:i+4000], parse_mode="Markdown")
    else:
        await update.message.reply_text(response, parse_mode="Markdown")


async def dispatch(intent: str, details: str, params: dict, raw: str) -> str:
    """Route to the correct handler based on intent."""

    if intent == "create_task":
        entry = add_task(details, due=params.get("due", ""))
        return f"✅ Task saved: *{details}*\nID: #{entry['id']}"

    elif intent == "log_health":
        return await asyncio.to_thread(health_handle, raw)

    elif intent == "infusion_consulting":
        return await asyncio.to_thread(infusion_handle, details)

    elif intent == "mortgage_notes":
        return await asyncio.to_thread(mortgage_handle, details)

    elif intent == "investment_research":
        return await asyncio.to_thread(investment_handle, details)

    elif intent == "travel_hack":
        return await asyncio.to_thread(travel_handle, details)

    elif intent == "nyc_events":
        return await asyncio.to_thread(social_handle, details)

    elif intent == "daily_briefing":
        return await build_briefing()

    elif intent == "general_question":
        return await asyncio.to_thread(handle_general, raw)

    else:
        return await asyncio.to_thread(handle_general, raw)


async def build_briefing() -> str:
    """Morning executive briefing."""
    from agents.health_agent.handler import _build_summary
    tasks = list_tasks("open")
    task_lines = "\n".join(f"  • {t['task']}" for t in tasks[:5]) or "  None"
    health = await asyncio.to_thread(_build_summary)

    return (
        "*Good morning, Justin* ☀️\n\n"
        f"*Open Tasks ({len(tasks)}):*\n{task_lines}\n\n"
        f"{health}\n\n"
        "_Type `events` for NYC events · `notes scan` for mortgage deals · `briefing` anytime_"
    )


# ── Start command ─────────────────────────────────────────────────────────────

async def start_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    chat_id = update.effective_chat.id
    await update.message.reply_text(
        f"*Executive AI Assistant online* 🤖\nChat ID: `{chat_id}`\n\n"
        "*What I can do:*\n"
        "• Type or 🎙 voice anything — I'll figure it out\n"
        "• 📸 Send a food photo → auto calorie estimate\n"
        "• `weight 174` / `slept 7h` → health log\n"
        "• `Morning briefing` → daily summary\n"
        "• `NYC events` → free events this week\n"
        "• `Infusion center question` → consulting intel\n"
        "• `AAPL analysis` → investment research\n"
        "• `Award flights Tokyo` → travel hacking\n"
        "• `Remind me to...` → task creation",
        parse_mode="Markdown",
    )


# ── Run ───────────────────────────────────────────────────────────────────────

def run_bot():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in .env")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    logger.info("Bot running. Send /start to your bot in Telegram.")
    app.run_polling(drop_pending_updates=True)
