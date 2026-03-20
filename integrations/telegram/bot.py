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
from agents.health_agent.handler import handle as health_handle, run_daily_nudge
from agents.social_agent.handler import handle as social_handle, run_event_scan
from agents.finance_agent.handler import handle as finance_handle
from agents.bonus_alert.handler import handle as bonus_alert_handle, run_bonus_scan
from agents.market_agent.handler import handle as market_handle
from agents.calendar_agent.handler import handle as calendar_handle, run_morning_briefing, run_eod_calendar
from agents.email_agent.handler import handle as email_handle, run_morning_digest, run_eod_email_summary
from agents.followup_agent.handler import handle as followup_handle, run_pending_followups
from agents.general_handler import handle_general

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger(__name__)


# ── Photo handler — triage then route ────────────────────────────────────────

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Download photo, triage its type, then route to the right handler."""
    await update.message.reply_text("📸 Reading image...")

    photo = update.message.photo[-1]
    caption = update.message.caption or ""

    file = await context.bot.get_file(photo.file_id)
    with tempfile.NamedTemporaryFile(suffix=".jpg", delete=False) as tmp:
        tmp_path = tmp.name
        await file.download_to_drive(tmp_path)
        with open(tmp_path, "rb") as f:
            image_bytes = f.read()
    os.unlink(tmp_path)

    image_b64 = base64.b64encode(image_bytes).decode("utf-8")

    # Step 1: triage
    image_type = await asyncio.to_thread(_triage_image, image_b64, caption)

    # Step 2: route
    if image_type == "food":
        await update.message.reply_text("🍽 Logging meal...", parse_mode="Markdown")
        response = await asyncio.to_thread(_analyze_food_image, image_b64, caption)

    elif image_type == "event":
        await update.message.reply_text("📅 Extracting event details...", parse_mode="Markdown")
        response = await asyncio.to_thread(_handle_event_image, image_b64, caption)

    elif image_type == "receipt":
        await update.message.reply_text("🧾 Reading receipt...", parse_mode="Markdown")
        response = await asyncio.to_thread(_handle_receipt_image, image_b64, caption)

    elif image_type == "document":
        await update.message.reply_text("📄 Reading document...", parse_mode="Markdown")
        response = await asyncio.to_thread(_handle_document_image, image_b64, caption)

    else:
        # general / unknown
        await update.message.reply_text("🔍 Analyzing image...", parse_mode="Markdown")
        response = await asyncio.to_thread(_handle_general_image, image_b64, caption)

    if len(response) > 4000:
        for i in range(0, len(response), 4000):
            await update.message.reply_text(response[i:i+4000], parse_mode="Markdown")
    else:
        await update.message.reply_text(response, parse_mode="Markdown")


def _vision_call(image_b64: str, prompt: str, max_tokens: int = 600) -> str:
    """Shared helper — sends image + prompt to Groq vision model."""
    from openai import OpenAI
    client = OpenAI(
        api_key=os.environ.get("GROQ_API_KEY", ""),
        base_url="https://api.groq.com/openai/v1",
    )
    resp = client.chat.completions.create(
        model="llama-3.2-11b-vision-preview",
        max_tokens=max_tokens,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                {"type": "text", "text": prompt},
            ]
        }]
    )
    return resp.choices[0].message.content.strip()


def _triage_image(image_b64: str, caption: str = "") -> str:
    """
    Quick vision call to classify the image type.
    Returns one of: food | event | receipt | document | general
    Screenshots are NOT a separate category — they route to whatever content they contain.
    """
    prompt = (
        "Look at this image carefully. Classify it into exactly ONE of these categories:\n\n"
        "- food       → a meal, drink, snack, or food item (photo or screenshot of food)\n"
        "- event      → ANYTHING that contains event information: a date, time, location, "
        "               or event name. This includes: save-the-dates, party invites, wedding invites, "
        "               event flyers, event confirmation emails, RSVP confirmations, ticket screenshots, "
        "               screenshots of Luma/Eventbrite/Partiful pages, email screenshots about events, "
        "               or any screenshot/photo where a specific event date+location is visible.\n"
        "- receipt    → a store receipt, bill, invoice, or expense document\n"
        "- document   → a contract, form, letter, article, handwritten note, or general text document\n"
        "- general    → anything else (person, place, art, object, meme, app screenshot without event info)\n\n"
        "IMPORTANT: If an image is a screenshot but contains event info (date, time, venue), "
        "classify it as 'event', not 'general'. The content matters more than the format.\n\n"
        f"User caption: '{caption}'\n\n"
        "Reply with ONLY the single category word. No explanation."
    )
    try:
        result = _vision_call(image_b64, prompt, max_tokens=10)
        category = result.strip().lower().split()[0]
        valid = {"food", "event", "receipt", "document", "general"}
        return category if category in valid else "general"
    except Exception as e:
        logger.error(f"Image triage error: {e}")
        return "general"


def _get_meal_label() -> str:
    """Return breakfast/lunch/dinner/snack based on current ET hour."""
    import datetime
    et_offset = datetime.timezone(datetime.timedelta(hours=-5))
    hour = datetime.datetime.now(tz=et_offset).hour
    if 5 <= hour < 11:
        return "breakfast"
    elif 11 <= hour < 15:
        return "lunch"
    elif 15 <= hour < 18:
        return "snack"
    else:
        return "dinner"


def _analyze_food_image(image_b64: str, caption: str = "") -> str:
    """Nutrition analysis for food photos."""
    meal_label = _get_meal_label()
    prompt = (
        "You are a nutrition coach for Justin Ngai, who is working to get from ~175 lbs to 165 lbs. "
        "His priorities: hit ~150g protein/day, stay in a moderate calorie deficit, build muscle.\n\n"
        f"This photo was sent at {meal_label} time — treat it as his {meal_label}.\n"
        "Analyze this food photo carefully. Identify every item visible and estimate portions.\n\n"
        f"User note: {caption}\n\n"
        "Reply using EXACTLY this format:\n\n"
        f"🍽 *{meal_label.capitalize()}: [Meal name — be specific]*\n\n"
        "📊 *Nutrition Estimate*\n"
        "• Calories: ~[X] kcal\n"
        "• Protein: ~[X]g\n"
        "• Carbs: ~[X]g\n"
        "• Fat: ~[X]g\n"
        "• Fiber: ~[X]g\n\n"
        "🔍 *What's in it*\n"
        "[Each ingredient with portion + cal/protein estimate]\n\n"
        "✅ *Strengths* — [1-2 bullets: what this does well for Justin's goals]\n\n"
        "⚠️ *Watch out* — [1-2 bullets: sodium, hidden calories, portions]\n\n"
        "💡 *Coaching tip* — [One actionable suggestion for today's remaining meals]"
    )
    try:
        result = _vision_call(image_b64, prompt, max_tokens=600)
        log_health("meal", result[:300], note=f"{meal_label} photo log")
        return f"{result}\n\n_📝 {meal_label.capitalize()} logged_"
    except Exception as e:
        return f"⚠️ Couldn't analyze photo: {e}\n\nTip: describe your meal in text instead."


def _handle_event_image(image_b64: str, caption: str = "") -> str:
    """Extract event details from invite/save-the-date and offer to add to Google Calendar."""
    prompt = (
        "This image is an event invitation, save-the-date, or event flyer. "
        "Extract ALL event details visible in the image.\n\n"
        f"User caption: '{caption}'\n\n"
        "Reply using EXACTLY this format:\n\n"
        "📅 *Event Detected*\n\n"
        "• *Name:* [Full event name]\n"
        "• *Date:* [Date — spell it out, e.g. Saturday, June 14, 2026]\n"
        "• *Time:* [Start time – End time, include timezone if shown]\n"
        "• *Location:* [Venue name and/or address]\n"
        "• *Hosted by:* [Host name(s) if visible]\n"
        "• *RSVP/Details:* [Any RSVP info, link, or dress code]\n"
        "• *Notes:* [Anything else relevant — attire, registry, gifts, etc.]\n\n"
        "Then on a new line, write exactly:\n"
        "CALENDAR_DATA: {\"title\": \"...\", \"date\": \"YYYY-MM-DD\", \"time\": \"HH:MM\", "
        "\"end_time\": \"HH:MM\", \"location\": \"...\", \"description\": \"...\"}\n\n"
        "If any field is unknown, use null for the JSON value. "
        "Use 24-hour format for times in the JSON."
    )
    try:
        result = _vision_call(image_b64, prompt, max_tokens=500)

        # Try to auto-create calendar event if calendar is configured
        cal_response = ""
        if "CALENDAR_DATA:" in result:
            import json, re
            json_match = re.search(r'CALENDAR_DATA:\s*(\{.*?\})', result, re.DOTALL)
            if json_match:
                try:
                    data = json.loads(json_match.group(1))
                    cal_response = _try_create_calendar_event(data)
                    # Strip raw JSON from user-facing text
                    result = result[:result.index("CALENDAR_DATA:")].strip()
                except Exception:
                    result = result[:result.index("CALENDAR_DATA:")].strip()

        response = result
        if cal_response:
            response += f"\n\n{cal_response}"
        else:
            response += "\n\n_Reply 'add to calendar' to save this event._"
        return response

    except Exception as e:
        return f"⚠️ Couldn't read event details: {e}"


def _try_create_calendar_event(data: dict) -> str:
    """Attempt to create a Google Calendar event from extracted image data."""
    try:
        from integrations.google.calendar_client import create_event
        from integrations.google.auth import is_configured
        if not is_configured():
            return "_Google Calendar not configured — event not saved._"

        import datetime as dt

        title = data.get("title") or "Event from photo"
        date_str = data.get("date")        # YYYY-MM-DD
        time_str = data.get("time")        # HH:MM (24h)
        end_time_str = data.get("end_time")
        location = data.get("location") or ""
        description = data.get("description") or "Added from photo via Executive AI Assistant"

        if not date_str:
            return "_Couldn't read the date clearly — reply 'add to calendar [date]' to save manually._"

        if time_str:
            start_iso = f"{date_str}T{time_str}:00"
            if end_time_str:
                end_iso = f"{date_str}T{end_time_str}:00"
            else:
                # default 2 hours
                start_dt_obj = dt.datetime.strptime(start_iso, "%Y-%m-%dT%H:%M:%S")
                end_iso = (start_dt_obj + dt.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
        else:
            # all-day event
            start_iso = date_str
            end_iso = date_str

        created = create_event(
            title=title,
            start=start_iso,
            end=end_iso,
            location=location,
            description=description,
        )
        if created:
            html_link = created.get("htmlLink", "")
            if html_link:
                return f"✅ *Added to Google Calendar!*\n🔗 [View event]({html_link})"
            return "✅ Event saved to Google Calendar."
        return "_Couldn't save to calendar — try again or add manually._"
    except Exception as e:
        return f"_Couldn't auto-add to calendar: {e}_"


def _handle_receipt_image(image_b64: str, caption: str = "") -> str:
    """Extract and summarize receipt/expense data."""
    prompt = (
        "This is a receipt or bill. Extract all relevant information.\n\n"
        f"User note: '{caption}'\n\n"
        "Reply using EXACTLY this format:\n\n"
        "🧾 *Receipt Summary*\n\n"
        "• *Merchant:* [Store/restaurant name]\n"
        "• *Date:* [Date of purchase]\n"
        "• *Items:* [List key line items with prices]\n"
        "• *Subtotal:* $[X]\n"
        "• *Tax:* $[X]\n"
        "• *Tip:* $[X] (if applicable)\n"
        "• *Total:* $[X]\n"
        "• *Payment:* [Cash / Card type if visible]\n\n"
        "💡 *Category:* [Dining / Groceries / Transport / Shopping / Healthcare / Other]\n\n"
        "Then ask: 'Want me to log this to your budget tracker?'"
    )
    try:
        return _vision_call(image_b64, prompt, max_tokens=400)
    except Exception as e:
        return f"⚠️ Couldn't read receipt: {e}"


def _handle_document_image(image_b64: str, caption: str = "") -> str:
    """Extract and summarize text from a document photo."""
    prompt = (
        "This is a photo of a document, note, letter, or form. "
        "Read all visible text carefully and provide:\n\n"
        f"User note: '{caption}'\n\n"
        "📄 *Document Summary*\n\n"
        "• *Type:* [What kind of document is this?]\n"
        "• *Key info:* [Most important details — names, dates, amounts, action items]\n"
        "• *Full text:* [Transcribe all readable text]\n\n"
        "💡 *Action needed:* [Is there anything that requires a response or action?]"
    )
    try:
        return _vision_call(image_b64, prompt, max_tokens=500)
    except Exception as e:
        return f"⚠️ Couldn't read document: {e}"


def _handle_general_image(image_b64: str, caption: str = "") -> str:
    """Describe and respond to a general image."""
    prompt = (
        "You are Justin Ngai's executive AI assistant. He sent you this image.\n\n"
        f"His caption/question: '{caption}'\n\n"
        "Describe what you see and respond helpfully based on his caption. "
        "If there's no caption, briefly describe the image and ask what he'd like to do with it. "
        "Keep it concise — 3-5 sentences max."
    )
    try:
        return _vision_call(image_b64, prompt, max_tokens=300)
    except Exception as e:
        return f"⚠️ Couldn't analyze image: {e}"


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

    # Reply with voice message too
    voice_file = await asyncio.to_thread(_text_to_voice, response)
    if voice_file:
        with open(voice_file, "rb") as f:
            await update.message.reply_voice(f)
        os.unlink(voice_file)


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


def _clean_for_speech(text: str) -> str:
    """Strip markdown and symbols so TTS reads cleanly."""
    import re
    clean = re.sub(r"\*+|_+|`+", "", text)                     # bold/italic/code
    clean = re.sub(r"\[([^\]]+)\]\([^\)]+\)", r"\1", clean)    # [link text](url)
    clean = re.sub(r"#{1,6}\s*", "", clean)                     # headers
    clean = re.sub(r"[•·→–—]", ",", clean)                     # bullets/dashes to pause
    clean = re.sub(r"📈|📉|📊|🔍|✅|⚠️|💡|🍽|📅|🗓|💰|📍|🕐|👥|🔗|✨|🌍|🏦|💱|🛢", "", clean)  # emojis
    clean = re.sub(r"\n{2,}", ". ", clean)                      # paragraph breaks → pause
    clean = re.sub(r"\n", " ", clean)
    clean = re.sub(r"\s{2,}", " ", clean)
    return clean.strip()


def _text_to_voice(text: str) -> str | None:
    """
    Convert text to an OGG voice file using edge-tts (Microsoft neural voices).
    Falls back to gTTS if edge-tts fails.
    Returns file path or None.
    """
    import re

    clean = _clean_for_speech(text)
    if not clean or len(clean) < 5:
        return None
    if len(clean) > 900:
        clean = clean[:900] + "."

    # Try edge-tts first — much better neural voice quality
    try:
        import edge_tts
        import asyncio as _asyncio

        VOICE = "en-US-AndrewNeural"  # natural conversational male voice

        async def _synth():
            communicate = edge_tts.Communicate(clean, VOICE)
            with tempfile.NamedTemporaryFile(suffix=".mp3", delete=False) as tmp:
                path = tmp.name
            await communicate.save(path)
            return path

        mp3_path = _asyncio.run(_synth())
        return mp3_path

    except Exception as e:
        logger.warning(f"edge-tts failed, falling back to gTTS: {e}")

    # Fallback: gTTS
    try:
        from gtts import gTTS
        tts = gTTS(text=clean, lang="en", slow=False)
        with tempfile.NamedTemporaryFile(suffix=".ogg", delete=False) as tmp:
            tts.save(tmp.name)
            return tmp.name
    except Exception as e:
        logger.error(f"TTS fallback error: {e}")
        return None


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

    elif intent == "personal_finance":
        return await asyncio.to_thread(finance_handle, raw)

    elif intent == "bonus_alert":
        return await asyncio.to_thread(bonus_alert_handle, raw)

    elif intent == "market_intel":
        return await asyncio.to_thread(market_handle, raw)

    elif intent == "schedule_meeting":
        return await asyncio.to_thread(calendar_handle, raw)

    elif intent == "draft_email":
        return await asyncio.to_thread(email_handle, raw)

    elif intent == "follow_up":
        return await asyncio.to_thread(followup_handle, raw)

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
        "• `Best bank bonuses` → bank signup offers\n"
        "• `Best credit card SUBs` → card signup bonuses\n"
        "• `Amex eligibility` → check re-eligibility rules\n"
        "• `Spent $50 groceries` → budget log\n"
        "• `Remind me to...` → task creation",
        parse_mode="Markdown",
    )


# ── Run ───────────────────────────────────────────────────────────────────────

async def _scheduled_bonus_scan(context: ContextTypes.DEFAULT_TYPE):
    """Daily bonus alert scan — runs automatically at 8 AM."""
    try:
        result = await asyncio.to_thread(run_bonus_scan, False)
        # Only message if there are elevated offers (message will contain "ALERT")
        if "ALERT" in result or "elevated" in result.lower():
            chat_id = os.environ.get("TELEGRAM_CHAT_ID")
            if chat_id:
                await context.bot.send_message(chat_id=chat_id, text=result, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Scheduled bonus scan error: {e}")


async def _scheduled_health_nudge(context: ContextTypes.DEFAULT_TYPE):
    """Daily 7:30 AM health check-in — only fires if Justin is behind on goals."""
    try:
        result = await asyncio.to_thread(run_daily_nudge)
        if result:
            chat_id = os.environ.get("TELEGRAM_CHAT_ID")
            if chat_id:
                await context.bot.send_message(chat_id=chat_id, text=result, parse_mode="Markdown")
    except Exception as e:
        logger.error(f"Health nudge error: {e}")


async def _scheduled_eod_wrapup(context: ContextTypes.DEFAULT_TYPE):
    """Daily 6 PM ET — combined calendar + email end-of-day wrap-up."""
    try:
        cal_summary = await asyncio.to_thread(run_eod_calendar)
        email_summary = await asyncio.to_thread(run_eod_email_summary)

        if not cal_summary and not email_summary:
            return   # Nothing to report — stay silent

        parts = ["🌆 *End of Day Wrap-up*\n"]
        if cal_summary:
            parts.append(cal_summary)
        if email_summary:
            parts.append(email_summary)

        message = "\n\n".join(parts)
        chat_id = os.environ.get("TELEGRAM_CHAT_ID")
        if chat_id:
            for i in range(0, len(message), 4000):
                await context.bot.send_message(
                    chat_id=chat_id, text=message[i:i+4000], parse_mode="Markdown"
                )
    except Exception as e:
        logger.error(f"EOD wrap-up error: {e}")


async def _scheduled_followup_check(context: ContextTypes.DEFAULT_TYPE):
    """Daily 8:05 AM check — fire any due follow-up emails or meeting invites."""
    try:
        results = await asyncio.to_thread(run_pending_followups)
        if results:
            chat_id = os.environ.get("TELEGRAM_CHAT_ID")
            if chat_id:
                for msg in results:
                    await context.bot.send_message(
                        chat_id=chat_id, text=msg, parse_mode="Markdown"
                    )
    except Exception as e:
        logger.error(f"Follow-up scheduler error: {e}")


async def _scheduled_calendar_briefing(context: ContextTypes.DEFAULT_TYPE):
    """Daily 7:45 AM calendar briefing — today + tomorrow events. Silent if nothing scheduled."""
    try:
        result = await asyncio.to_thread(run_morning_briefing)
        if result:
            chat_id = os.environ.get("TELEGRAM_CHAT_ID")
            if chat_id:
                await context.bot.send_message(
                    chat_id=chat_id, text=result, parse_mode="Markdown"
                )
    except Exception as e:
        logger.error(f"Calendar briefing error: {e}")


async def _scheduled_email_digest(context: ContextTypes.DEFAULT_TYPE):
    """Daily 7:50 AM email digest — urgency-triaged unread. Silent if inbox is zero."""
    try:
        result = await asyncio.to_thread(run_morning_digest)
        if result:
            chat_id = os.environ.get("TELEGRAM_CHAT_ID")
            if chat_id:
                await context.bot.send_message(
                    chat_id=chat_id, text=result, parse_mode="Markdown"
                )
    except Exception as e:
        logger.error(f"Email digest error: {e}")


async def _scheduled_event_scan(context: ContextTypes.DEFAULT_TYPE):
    """
    Twice-weekly NYC event scan — Tuesdays + Fridays at 9 AM ET.
    Sends full roundup on Fridays (send_all=True), immediate-alert-only on Tuesdays.
    """
    try:
        import datetime as dt
        today = dt.date.today()
        is_friday = today.weekday() == 4  # 0=Mon, 4=Fri
        result = await asyncio.to_thread(run_event_scan, is_friday)
        if result:
            chat_id = os.environ.get("TELEGRAM_CHAT_ID")
            if chat_id:
                # Split if long
                for i in range(0, len(result), 4000):
                    await context.bot.send_message(
                        chat_id=chat_id, text=result[i:i+4000], parse_mode="Markdown"
                    )
    except Exception as e:
        logger.error(f"Scheduled event scan error: {e}")


def run_bot():
    token = os.environ.get("TELEGRAM_BOT_TOKEN")
    if not token:
        raise ValueError("TELEGRAM_BOT_TOKEN not set in .env")

    app = Application.builder().token(token).build()
    app.add_handler(CommandHandler("start", start_command))
    app.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    app.add_handler(MessageHandler(filters.VOICE, handle_voice))
    app.add_handler(MessageHandler(filters.TEXT & ~filters.COMMAND, handle_message))

    # Schedule daily bonus alert scan at 8:00 AM
    job_queue = app.job_queue
    if job_queue:
        import datetime as dt
        ET = dt.timezone(dt.timedelta(hours=-5))

        job_queue.run_daily(
            _scheduled_bonus_scan,
            time=dt.time(hour=8, minute=0, tzinfo=ET),  # 8 AM ET daily
            name="daily_bonus_scan",
        )
        logger.info("Scheduled daily bonus scan at 8 AM ET")

        # NYC event scan — Tuesdays (alert-only) + Fridays (full roundup) at 9 AM ET
        job_queue.run_daily(
            _scheduled_event_scan,
            days=(1, 4),  # 1=Tuesday, 4=Friday
            time=dt.time(hour=9, minute=0, tzinfo=ET),
            name="biweekly_event_scan",
        )
        logger.info("Scheduled NYC event scan Tue + Fri at 9 AM ET")

        # Health nudge — every morning at 7:30 AM ET (only sends if behind on goals)
        job_queue.run_daily(
            _scheduled_health_nudge,
            time=dt.time(hour=7, minute=30, tzinfo=ET),
            name="daily_health_nudge",
        )
        logger.info("Scheduled daily health nudge at 7:30 AM ET")

        # EOD wrap-up — 6 PM ET daily (calendar + email combined, silent if clean)
        job_queue.run_daily(
            _scheduled_eod_wrapup,
            time=dt.time(hour=18, minute=0, tzinfo=ET),
            name="daily_eod_wrapup",
        )
        logger.info("Scheduled daily EOD wrap-up at 6 PM ET")

        # Follow-up check — 8:05 AM ET daily (fires due email/meeting follow-ups)
        job_queue.run_daily(
            _scheduled_followup_check,
            time=dt.time(hour=8, minute=5, tzinfo=ET),
            name="daily_followup_check",
        )
        logger.info("Scheduled daily follow-up check at 8:05 AM ET")

        # Calendar briefing — 7:45 AM ET daily (silent if no events)
        job_queue.run_daily(
            _scheduled_calendar_briefing,
            time=dt.time(hour=7, minute=45, tzinfo=ET),
            name="daily_calendar_briefing",
        )
        logger.info("Scheduled daily calendar briefing at 7:45 AM ET")

        # Email digest — 7:50 AM ET daily (silent if inbox zero)
        job_queue.run_daily(
            _scheduled_email_digest,
            time=dt.time(hour=7, minute=50, tzinfo=ET),
            name="daily_email_digest",
        )
        logger.info("Scheduled daily email digest at 7:50 AM ET")

    logger.info("Bot running. Send /start to your bot in Telegram.")
    app.run_polling(drop_pending_updates=True)
