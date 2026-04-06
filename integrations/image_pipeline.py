"""
Image pipeline — vision triage and per-type handlers.

Extracted from bot.py so all handlers are independently testable.

Flow:
  triage_image() classifies the image
      → food       → _analyze_food_image()     → health agent logging
      → event      → _handle_event_image()     → Google Calendar auto-create
      → receipt    → _handle_receipt_image()   → budget prompt
      → travel     → _handle_image_with_agent("travel")
      → market     → _handle_image_with_agent("market")
      → infusion   → _handle_image_with_agent("infusion")
      → mortgage   → _handle_image_with_agent("mortgage")
      → document   → _handle_document_image()
      → general    → _handle_general_image()

Public API:
    route_image(image_b64, caption, user_id) -> (response_str, image_type)
    last_event_cache: dict  — shared with bot.py for "add to calendar" follow-up
"""

import os
import json
import logging
import re

logger = logging.getLogger(__name__)

# Shared cache so handle_message in bot.py can find the last event extracted from a photo
last_event_cache: dict = {}


# ── Vision model ──────────────────────────────────────────────────────────────

def _vision_call(image_b64: str, prompt: str, max_tokens: int = 600) -> str:
    """Send image + prompt to Groq vision model."""
    from openai import OpenAI
    client = OpenAI(
        api_key=os.environ.get("GROQ_API_KEY", ""),
        base_url="https://api.groq.com/openai/v1",
    )
    resp = client.chat.completions.create(
        model="meta-llama/llama-4-scout-17b-16e-instruct",
        max_tokens=max_tokens,
        messages=[{
            "role": "user",
            "content": [
                {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{image_b64}"}},
                {"type": "text", "text": prompt},
            ],
        }],
    )
    return resp.choices[0].message.content.strip()


# ── Meal label ────────────────────────────────────────────────────────────────

def _get_meal_label() -> str:
    """Return breakfast/lunch/snack/dinner based on current ET hour (DST-aware)."""
    import datetime
    try:
        from zoneinfo import ZoneInfo
        now = datetime.datetime.now(tz=ZoneInfo("America/New_York"))
    except Exception:
        now = datetime.datetime.now(tz=datetime.timezone(datetime.timedelta(hours=-4)))
    hour = now.hour
    if 5 <= hour < 11:    return "breakfast"
    elif 11 <= hour < 15: return "lunch"
    elif 15 <= hour < 18: return "snack"
    else:                 return "dinner"


# ── Triage ────────────────────────────────────────────────────────────────────

def triage_image(image_b64: str, caption: str = "") -> str:
    """
    Classify image into one of:
      food | event | receipt | document |
      travel | market | infusion | mortgage | general

    Caption is the strongest override signal — user words come first.
    Falls back to a vision LLM call only when caption gives no clear signal.
    """
    cap = caption.lower()

    _travel_signals   = ["flight", "deal", "ticket", "miles", "points", "award",
                         "which is better", "better price", "fare", "itinerary",
                         "layover", "airline", "seat"]
    _market_signals   = ["chart", "stock", "ticker", "etf", "crypto", "candle",
                         "technical", "price action", "moving average", "support",
                         "resistance", "trade"]
    _infusion_signals = ["infusion", "clinic", "hospital", "patient", "report",
                         "clinical", "data table", "census", "volume", "drip",
                         "iv", "oncology", "pharmacy"]
    _mortgage_signals = ["mortgage", "note", "lien", "upb", "deed", "trust",
                         "real estate", "property", "foreclosure", "npl",
                         "performer", "paperstac"]
    _food_signals     = ["food", "meal", "ate", "eating", "lunch", "breakfast",
                         "dinner", "snack", "recipe", "calories", "protein"]
    _event_signals    = ["event", "rsvp", "invite", "save the date", "party",
                         "wedding", "conference", "meetup", "luma", "eventbrite"]

    if any(s in cap for s in _travel_signals):   return "travel"
    if any(s in cap for s in _market_signals):   return "market"
    if any(s in cap for s in _infusion_signals): return "infusion"
    if any(s in cap for s in _mortgage_signals): return "mortgage"
    if any(s in cap for s in _food_signals):     return "food"
    if any(s in cap for s in _event_signals):    return "event"

    # Vision call for anything caption doesn't resolve
    prompt = (
        "Look at this image carefully. The user's caption is: '{caption}'\n\n"
        "Classify the image into exactly ONE of these categories:\n\n"
        "- food       → meal, drink, snack, or food item\n"
        "- event      → event info: date, time, venue, invite, RSVP, ticket, flyer, "
        "               save-the-date, Luma/Eventbrite/Partiful screenshot\n"
        "- receipt    → store receipt, bill, invoice, expense\n"
        "- travel     → flight search results, boarding pass, seat map, hotel booking, "
        "               award flight comparison, price comparison\n"
        "- market     → stock chart, candlestick, ticker performance, financial chart, "
        "               portfolio screenshot, crypto chart, market data table\n"
        "- infusion   → hospital report, clinical data table, infusion center census, "
        "               patient volume, pharmacy/IV data, healthcare ops data\n"
        "- mortgage   → mortgage note, deed of trust, real estate document, note listing, "
        "               Paperstac screenshot, UPB table, property data\n"
        "- document   → contract, form, letter, article, handwritten note, general text\n"
        "- general    → anything else\n\n"
        "RULES:\n"
        "- Event images trump most other categories if a date+venue is clearly visible.\n"
        "- The content matters more than format (screenshot vs photo).\n\n"
        "Reply with ONLY the single category word. No explanation."
    ).format(caption=caption)

    try:
        result = _vision_call(image_b64, prompt, max_tokens=10)
        category = result.strip().lower().split()[0]
        valid = {"food", "event", "receipt", "document",
                 "travel", "market", "infusion", "mortgage", "general"}
        return category if category in valid else "general"
    except Exception as e:
        logger.error("Image triage error: %s", e)
        return "general"


# ── Per-type handlers ─────────────────────────────────────────────────────────

def _analyze_food_image(image_b64: str, caption: str = "") -> str:
    """Nutrition analysis for food photos — logs to health agent."""
    from core.memory import log_health
    meal_label = _get_meal_label()
    prompt = (
        "You are a nutrition coach for Justin Ngai, working to get from ~175 lbs to 165 lbs. "
        "Priorities: hit ~150g protein/day, stay in a moderate calorie deficit, build muscle.\n\n"
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


def _handle_event_image(image_b64: str, caption: str = "", user_id: int = 0) -> str:
    """Extract event details from invite/flyer and auto-add to Google Calendar."""
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
        "If any field is unknown, use null. Use 24-hour format for times."
    )
    try:
        result = _vision_call(image_b64, prompt, max_tokens=500)

        cal_response = ""
        if "CALENDAR_DATA:" in result:
            json_match = re.search(r"CALENDAR_DATA:\s*(\{.*?\})", result, re.DOTALL)
            if json_match:
                try:
                    data = json.loads(json_match.group(1))
                    if user_id:
                        last_event_cache[user_id] = data
                    cal_response = _try_create_calendar_event(data)
                except Exception:
                    pass
                result = result[:result.index("CALENDAR_DATA:")].strip()

        if cal_response:
            return f"{result}\n\n{cal_response}"
        return f"{result}\n\n_Tap 'add to calendar' to save this event._"

    except Exception as e:
        return f"⚠️ Couldn't read event details: {e}"


def _try_create_calendar_event(data: dict) -> str:
    """Create a Google Calendar event from extracted image data."""
    try:
        from integrations.google.calendar_client import create_event
        from integrations.google.auth import is_configured
        if not is_configured():
            return "_Google Calendar not configured — event not saved._"

        import datetime as dt

        title        = data.get("title") or "Event from photo"
        date_str     = data.get("date")
        time_str     = data.get("time")
        end_time_str = data.get("end_time")
        location     = data.get("location") or ""
        description  = data.get("description") or "Added from photo via Executive AI Assistant"

        if not date_str:
            return "_Couldn't read the date — reply 'add to calendar [date]' to save manually._"

        if time_str:
            start_iso = f"{date_str}T{time_str}:00"
            if end_time_str:
                end_iso = f"{date_str}T{end_time_str}:00"
            else:
                start_dt_obj = dt.datetime.strptime(start_iso, "%Y-%m-%dT%H:%M:%S")
                end_iso = (start_dt_obj + dt.timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%S")
        else:
            start_iso = date_str
            end_iso = date_str

        created = create_event(title=title, start=start_iso, end=end_iso,
                               location=location, description=description)
        if created:
            link = created.get("htmlLink", "")
            return (f"✅ *Added to Google Calendar!*\n🔗 [View event]({link})"
                    if link else "✅ Event saved to Google Calendar.")
        return "_Couldn't save to calendar — try again or add manually._"
    except Exception as e:
        return f"_Couldn't auto-add to calendar: {e}_"


def _handle_receipt_image(image_b64: str, caption: str = "") -> str:
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


_AGENT_IMAGE_PROMPTS = {
    "travel": (
        "You are Justin Ngai's travel hacking expert — miles, points, award flights, Asia-focused.\n\n"
        "He sent you this image (likely a flight search, fare comparison, or booking screenshot).\n"
        "His question/caption: '{caption}'\n\n"
        "Analyze what you see:\n"
        "• Identify the routes, prices, or options shown\n"
        "• Evaluate which is the better deal and WHY (price per mile, routing, cabin, layovers)\n"
        "• Flag any sweet spots or traps\n"
        "• Recommend the best option with 1-2 sentences of reasoning\n\n"
        "Be direct and actionable. No fluff."
    ),
    "market": (
        "You are a senior markets analyst (JP Morgan / Jane Street style).\n\n"
        "Justin Ngai sent you this chart or market data screenshot.\n"
        "His question/caption: '{caption}'\n\n"
        "Analyze what you see:\n"
        "• Identify the ticker/asset, timeframe, and key levels\n"
        "• Read the trend, momentum, and any pattern visible\n"
        "• Give a specific trade idea: direction, entry, target, stop\n"
        "• State the key risk\n\n"
        "Lead with the trade thesis. Be precise and actionable."
    ),
    "infusion": (
        "You are an infusion services operations expert advising Justin Ngai, "
        "Director of Infusion Services at NewYork-Presbyterian.\n\n"
        "He sent you this clinical/operational data image.\n"
        "His question/caption: '{caption}'\n\n"
        "Analyze what you see:\n"
        "• Summarize the key data points or metrics shown\n"
        "• Identify any operational issues, trends, or anomalies\n"
        "• Give 2-3 concrete recommendations for improving performance\n"
        "• Flag anything that needs immediate attention\n\n"
        "Be specific and operationally focused. Keep employer context confidential."
    ),
    "mortgage": (
        "You are a mortgage note investor advising Justin Ngai on distressed/performing notes.\n\n"
        "He sent you this mortgage note, document, or real estate listing image.\n"
        "His question/caption: '{caption}'\n\n"
        "Analyze what you see:\n"
        "• Extract key data: UPB, interest rate, lien position, property type, state\n"
        "• Assess the note quality: performing/non-performing, first/second lien\n"
        "• Flag red flags or deal-breakers\n"
        "• Give a quick buy/pass/investigate-further recommendation with reasoning\n\n"
        "Be direct. Focus on deal quality and risk."
    ),
}


def _handle_image_with_agent(image_b64: str, caption: str, agent: str) -> str:
    """Route an image to a domain-specific agent prompt."""
    prompt_template = _AGENT_IMAGE_PROMPTS.get(agent)
    if not prompt_template:
        return _handle_general_image(image_b64, caption)
    prompt = prompt_template.replace("{caption}", caption or "No caption provided")
    try:
        return _vision_call(image_b64, prompt, max_tokens=500)
    except Exception as e:
        return f"⚠️ {agent.capitalize()} agent couldn't analyze image: {e}"


# ── Public entry point ────────────────────────────────────────────────────────

def route_image(image_b64: str, caption: str, user_id: int) -> tuple[str, str]:
    """
    Triage and route an image to the correct handler.

    Returns:
        (response_text, image_type) — image_type is one of the valid category strings.
    """
    image_type = triage_image(image_b64, caption)

    if image_type == "food":
        return _analyze_food_image(image_b64, caption), image_type
    elif image_type == "event":
        return _handle_event_image(image_b64, caption, user_id), image_type
    elif image_type == "receipt":
        return _handle_receipt_image(image_b64, caption), image_type
    elif image_type in ("travel", "market", "infusion", "mortgage"):
        return _handle_image_with_agent(image_b64, caption, image_type), image_type
    elif image_type == "document":
        return _handle_document_image(image_b64, caption), image_type
    else:
        return _handle_general_image(image_b64, caption), image_type
