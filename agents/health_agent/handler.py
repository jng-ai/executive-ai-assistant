"""
Health Agent — PRD v2

Purpose: Track Justin's health, keep him aligned on goals, and provide
         actionable insights to continuously improve.

Triggers:
  - Food photos (via bot.py triage → _analyze_food_image)
  - Text meal logs ("had chicken and rice")
  - Weight/sleep/workout logs
  - "What should I eat next / for lunch / tonight"
  - "What workout should I do" / "give me a routine"
  - "How am I doing" / summary requests
  - Proactive nudge (scheduled daily check-in via APScheduler)

Core capabilities:
  - Log weight, sleep, workouts, meals from text
  - After each meal log → show today's running macro total + what's still needed
  - "What should I eat" → analyzes today's intake, recommends specific meal
  - Workout suggestions that rotate muscle groups (avoids repeating yesterday)
  - 7-day summary with trends and one actionable tip
  - Proactive nudge: morning check-in if behind on workouts/sleep/protein
  - Incremental goal progression when targets consistently hit

Justin's targets:
  - Weight: 165 lbs (from ~175 — moderate deficit, not crash diet)
  - Protein: 150g/day
  - Calories: ~1,800–2,000/day (deficit)
  - Sleep: 7.5h/night
  - Workouts: 3–4x/week (gym lifts + apartment pool swimming)
  - Meal philosophy: whole foods, high protein, don't be obsessive
"""

import json
import logging
import datetime
from core.llm import chat
from core.memory import log_health, get_health_summary, update_last_food_log
from core.learning import add_learning, format_for_prompt

logger = logging.getLogger(__name__)

# ── Targets ───────────────────────────────────────────────────────────────────

TARGETS = {
    "weight":   {"goal": 165,   "unit": "lbs",     "direction": "down"},
    "sleep":    {"goal": 7.5,   "unit": "hours",   "direction": "up"},
    "workouts": {"goal": 3,     "unit": "per week","direction": "up"},
    "protein":  {"goal": 150,   "unit": "g/day"},
    "calories": {"goal": 1900,  "unit": "kcal/day"},
}

# ── System prompt ─────────────────────────────────────────────────────────────

SYSTEM = """You are Justin Ngai's personal fitness coach, trainer, and nutrition advisor.

Justin's profile:
- Goal: get from ~175 lbs down to 165 lbs through sustainable habits
- Daily nutrition targets: ~1,800–2,000 kcal, 150g protein, moderate carbs, healthy fats
- Sleep target: 7.5 hours/night
- Workout target: 3–4x/week — gym (weights) + apartment pool (swimming)
- Philosophy: consistency over perfection, whole foods, no crash dieting

Your identity as his coach:
- You actively track his muscle group history and ALWAYS suggest the next muscle group in rotation
- You are opinionated — you tell him exactly what to train and why, not just options
- You celebrate wins, flag recovery needs, and push him when he's coasting
- You program with progressive overload in mind across sessions
- If he's already trained a muscle group, you call it out and either redirect or adjust the session

Coaching style:
- Lead with what's actionable RIGHT NOW, not a recap of goals
- Be like a supportive coach who checks in — not a drill sergeant
- Celebrate streaks and progress, even small ones
- If he's falling short, give ONE concrete fix, not a list of failures
- Keep responses short and phone-friendly

Nutrition guidance:
- When reviewing today's meals, always calculate remaining protein/calorie needs
- Suggest specific real foods to fill gaps (e.g. "grab a Greek yogurt + hard boiled egg")
- Highlight if a meal is high-sodium, high-sugar, or low-protein for his goals
- Prioritize: protein first, then fiber, then overall calories

Workout guidance:
- ALWAYS check what muscle groups were recently trained — never repeat the same group two sessions in a row
- The standard rotation is: Chest & Triceps (Push) → Back & Biceps (Pull) → Legs → Cardio/Swim
- Suggest swim/cardio days for active recovery between heavy lifts
- Format workouts: Exercise | Sets × Reps | Rest | Coaching tip
- For abs/core: program into end of every lifting session
- When user asks for a specific muscle group, design the full session around that group"""


# ── Meal parsing prompt ────────────────────────────────────────────────────────

PARSE_PROMPT = """Extract a health log entry from this message. Return JSON only, no commentary.

CRITICAL RULE: Only return is_log:true if the person is REPORTING something they ALREADY DID or their current stats.
Return is_log:false for ANY question, request, or correction — even if it mentions health topics.

If the message IS a completed log, return:
{"is_log": true, "metric": "<weight|sleep|workout|meal|snack|drink>", "value": "<extracted value>", "unit": "<lbs|hours|session|food log|beverage log>"}

Metric rules:
- weight: extract number in lbs. Must be a plain weight statement.
- sleep: calculate total hours from times given. "Slept 12:10am to 7:40am" = 7.5 hours
- workout: ONLY if they clearly completed it TODAY or very recently (just now / this morning / earlier today).
  Value = description of what they did.
  Be permissive: "swimming today", "went to the pool", "hit the gym", "did some cardio",
  "was at the gym", "just finished working out" all count as workout logs.
  CRITICAL: If the message uses vague past timing like "recently", "the other day", "last week", "a few days ago",
  or "I did X recently" WITHOUT a clear "today/this morning/just now" indicator → return is_log:false.
  These are context statements for workout planning, NOT fresh logs.
- meal: A full meal they ate (breakfast, lunch, dinner). NOT questions or future plans.
- snack: A small bite between meals — protein bar, handful of nuts, fruit, chips, crackers, small food item.
- drink: Any beverage — coffee, tea, juice, water, soda, alcohol, protein shake, smoothie, energy drink.
  Note: a protein shake counts as drink if it's liquid, but log calories/protein in value.

Disambiguation:
- "had coffee" → drink
- "grabbed a protein bar" → snack
- "had a handful of almonds" → snack
- "drank an orange juice" → drink
- "had a beer" → drink
- "had a protein shake" → drink
- "ate a small apple" → snack
- "had chips" → snack
- "had chicken rice and cauliflower" → meal (full plate = meal)
- "had a big salad with salmon" → meal

Return is_log:false if the message:
- Asks a question ("what should I...", "can I...", "how do I...")
- Makes a request ("give me", "suggest", "help me", "recommend")
- Is a correction ("it's not a meal", "I meant")
- Is ambiguous about whether it was completed

Examples:
"Slept from 12:10am to 7:40am" → {"is_log":true,"metric":"sleep","value":"7.5","unit":"hours"}
"weight 174" → {"is_log":true,"metric":"weight","value":"174","unit":"lbs"}
"swam 30 mins" → {"is_log":true,"metric":"workout","value":"swam 30 mins","unit":"session"}
"had chicken and rice" → {"is_log":true,"metric":"meal","value":"chicken and rice","unit":"food log"}
"had a coffee with oat milk" → {"is_log":true,"metric":"drink","value":"coffee with oat milk","unit":"beverage log"}
"grabbed a Kind bar" → {"is_log":true,"metric":"snack","value":"Kind bar","unit":"food log"}
"drank a protein shake 40g protein" → {"is_log":true,"metric":"drink","value":"protein shake 40g protein","unit":"beverage log"}
"had a handful of mixed nuts" → {"is_log":true,"metric":"snack","value":"handful of mixed nuts","unit":"food log"}
"had a beer at happy hour" → {"is_log":true,"metric":"drink","value":"beer at happy hour","unit":"beverage log"}
"swimming today" → {"is_log":true,"metric":"workout","value":"swimming","unit":"session"}
"went to the pool" → {"is_log":true,"metric":"workout","value":"swimming at pool","unit":"session"}
"hit the gym" → {"is_log":true,"metric":"workout","value":"gym session","unit":"session"}
"was at the gym this morning" → {"is_log":true,"metric":"workout","value":"gym session","unit":"session"}
"did some cardio" → {"is_log":true,"metric":"workout","value":"cardio","unit":"session"}
"what should I eat" → {"is_log":false}
"give me a workout" → {"is_log":false}
"can I have pizza" → {"is_log":false}
"give me some insight on that workout" → {"is_log":false}
"I did back recently" → {"is_log":false}
"I trained chest last week" → {"is_log":false}
"I did legs the other day" → {"is_log":false}"""


# ── Keyword sets ──────────────────────────────────────────────────────────────

WORKOUT_SUGGEST_KEYWORDS = [
    "suggest", "routine", "plan", "program", "what should i", "what exercise",
    "give me a", "help me", "ideas", "recommend", "how to", "what do i",
    "what can i", "tomorrow", "next workout", "after this", "what workout",
]
WORKOUT_TOPIC_KEYWORDS = [
    "workout", "exercise", "bicep", "tricep", "chest", "back", "shoulder",
    "leg", "squat", "deadlift", "pull", "push", "abs", "core", "cardio",
    "swim", "hiit", "gym", "lift", "arms", "glute", "full body", "upper body",
    "lower body", "forearm", "calf", "hamstring", "quad", "lats", "traps",
]
WORKOUT_DONE_KEYWORDS = [
    "logged", "did", "completed", "finished", "swam", "ran", "lifted",
    "started", "just", "already", "done",
]
INSIGHT_KEYWORDS = [
    "insight", "insights", "analyze", "analysis", "tell me about", "how was",
    "what was", "breakdown", "break down", "review", "evaluate", "feedback",
    "thoughts on", "assess",
]

FOOD_SUGGEST_KEYWORDS = [
    "what should i eat", "what to eat", "what can i eat", "suggest a meal",
    "food suggestion", "meal idea", "what for lunch", "what for dinner",
    "what for breakfast", "what for snack", "help me eat", "recommend food",
    "what should i have", "balance my", "balance out",
]


# ── Helpers ───────────────────────────────────────────────────────────────────

def _is_num(val: str) -> bool:
    try:
        float(val)
        return True
    except (ValueError, TypeError):
        return False


def _et_hour() -> int:
    try:
        from zoneinfo import ZoneInfo
        return datetime.datetime.now(tz=ZoneInfo("America/New_York")).hour
    except Exception:
        # Fallback: rough UTC-4 (EDT). Better than always using EST.
        return (datetime.datetime.utcnow().hour - 4) % 24


def _meal_label() -> str:
    h = _et_hour()
    if 5 <= h < 11:   return "Breakfast"
    if 11 <= h < 15:  return "Lunch"
    if 15 <= h < 18:  return "Snack"
    return "Dinner"


def _get_todays_logs() -> list:
    """Return all health logs from today."""
    today = datetime.date.today().isoformat()
    return [l for l in get_health_summary(1) if l.get("date") == today]


def _get_recent_workouts(days: int = 7) -> list:
    """Return workout logs from the past N days."""
    logs = get_health_summary(days)
    return [l for l in logs if l.get("metric") == "workout"]


def _get_todays_food_logs() -> list:
    """Return today's meal, snack, and drink logs."""
    return [l for l in _get_todays_logs() if l.get("metric") in ("meal", "snack", "drink")]


def _get_todays_meals() -> list:
    """Return today's meal logs (text + photo). Includes snacks and drinks for nutrition balance."""
    return _get_todays_food_logs()


def parse_log(message: str) -> dict | None:
    """Use LLM to intelligently parse natural language health logs."""
    raw = chat(PARSE_PROMPT, message, max_tokens=100).strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()
    try:
        result = json.loads(raw)
        if result.get("is_log") and result.get("metric"):
            return result
        return None
    except (json.JSONDecodeError, AttributeError):
        return None


# ── Nutrition balance ─────────────────────────────────────────────────────────

def _nutrition_balance_response(new_meal: str = "") -> str:
    """
    Look at today's meals and return a running macro total + what's still needed.
    Called after every meal log.
    """
    meals = _get_todays_meals()
    if not meals:
        return ""

    meal_descriptions = "\n".join(
        f"- [{m.get('metric','meal').upper()}] {m.get('note') or m.get('value', '')}" for m in meals
    )
    if new_meal:
        meal_descriptions += f"\n- {new_meal} (just logged)"

    h = _et_hour()
    if h < 12:
        remaining_meals = "lunch and dinner"
    elif h < 16:
        remaining_meals = "an afternoon snack and dinner"
    elif h < 20:
        remaining_meals = "dinner"
    else:
        remaining_meals = "an evening snack if needed"

    prompt = (
        f"Justin's meals today:\n{meal_descriptions}\n\n"
        f"Daily targets: ~1,900 kcal, 150g protein, ~150g carbs, ~60g fat.\n"
        f"Current time: {'morning' if h < 12 else 'afternoon' if h < 17 else 'evening'}.\n\n"
        "Estimate total macros consumed so far. Then:\n"
        "1. Show running total (cal / protein / carbs / fat)\n"
        "2. Show what's still needed to hit targets\n"
        f"3. Suggest specific meals for {remaining_meals} to close the gap — each with cal + protein estimate\n\n"
        "Format:\n"
        "📊 *Today so far:* ~[X] kcal · [X]g protein · [X]g carbs · [X]g fat\n"
        "🎯 *Still need:* ~[X] kcal · [X]g protein\n"
        f"🍽 *Next meals ({remaining_meals}):*\n"
        "• [Meal option 1] — ~[X] kcal · [X]g protein\n"
        "• [Meal option 2] — ~[X] kcal · [X]g protein"
    )
    return chat(SYSTEM, prompt, max_tokens=300)


def _what_to_eat(message: str) -> str:
    """Suggest a meal based on today's intake so far."""
    meals = _get_todays_meals()
    meal_label = _meal_label()

    if meals:
        meal_descriptions = "\n".join(
            f"- {m.get('note') or m.get('value', '')}" for m in meals
        )
        context = f"Today's meals so far:\n{meal_descriptions}\n\n"
    else:
        context = "No meals logged yet today.\n\n"

    prompt = (
        f"{context}"
        f"Daily targets: ~1,900 kcal, 150g protein.\n"
        f"Justin is asking what to eat for {meal_label.lower()} / next meal.\n"
        f"His question: {message}\n\n"
        "Suggest 2–3 specific, realistic meal options that:\n"
        "- Fill his remaining protein/calorie gap for today\n"
        "- Are easy to get in NYC (restaurants, delivery, or simple home prep)\n"
        "- Align with fat loss + muscle building goals\n\n"
        "Format each as:\n"
        "🥗 *[Meal name]* — ~[X] kcal · [X]g protein\n"
        "   [Why it fits his day in one line]\n\n"
        "End with one bold top pick."
    )
    return chat(SYSTEM, prompt, max_tokens=400)


# ── Workout rotation helpers ──────────────────────────────────────────────────

_ROTATION = ["push", "pull", "legs", "swim"]

# "press" removed from push — "leg press" contains it and should resolve to legs (via "leg")
# "rdl" removed from legs — "romanian deadlift RDL" should resolve to pull (via "deadlift")
# "ran" added to swim — "ran 5 miles" is cardio, not strength
_PUSH_KW  = ["push", "chest", "shoulder", "tricep", "bench", "delt", "overhead"]
_PULL_KW  = ["pull", "back", "row", "deadlift", "bicep", "lat", "chin", "pullup", "pull-up", "rhomboid"]
_LEGS_KW  = ["leg", "squat", "lunge", "hamstring", "quad", "glute", "calf", "hip thrust"]
_SWIM_KW  = ["swim", "pool", "cardio", "run", "ran", "bike", "cycle", "endurance", "hiit", "sprint"]


def _classify_workout_type(value: str) -> str | None:
    """Return 'push' | 'pull' | 'legs' | 'swim' from a workout log entry, or None."""
    v = value.lower()
    # Check legs before push — "leg press" and "quad extensions leg press" resolve to legs
    if any(k in v for k in _LEGS_KW):  return "legs"
    if any(k in v for k in _PUSH_KW):  return "push"
    if any(k in v for k in _PULL_KW):  return "pull"
    if any(k in v for k in _SWIM_KW):  return "swim"
    return None


# Descriptive labels for each rotation slot — shown in reminder and suggestions
_ROTATION_LABELS = {
    "push": "Chest & Triceps",
    "pull": "Back & Biceps",
    "legs": "Legs (Quads / Hamstrings / Glutes)",
    "swim": "Cardio / Swim",
}


def _next_rotation_type(recent_workouts: list[dict]) -> str:
    """
    Walk backwards through recent workout logs, find the last classifiable type,
    and return the NEXT type in the push→pull→legs→swim rotation.
    Returns None if no classifiable history (caller should handle gracefully).
    """
    for log in reversed(recent_workouts):
        wtype = _classify_workout_type(log.get("value", ""))
        if wtype:
            idx = _ROTATION.index(wtype)
            return _ROTATION[(idx + 1) % len(_ROTATION)]
    return None  # No history — don't assume push


# ── Muscle group detection ─────────────────────────────────────────────────────

# Map of keyword → specific muscle group focus (overrides rotation when detected)
_MUSCLE_FOCUS_MAP = {
    "chest":      ("push",  "chest — bench press, flyes, cable crossovers"),
    "pec":        ("push",  "chest — bench press, pec deck, dips"),
    "tricep":     ("push",  "triceps — pushdowns, overhead extension, skull crushers"),
    "shoulder":   ("push",  "shoulders — overhead press, lateral raises, front raises, face pulls"),
    "delt":       ("push",  "shoulders — lateral raises, overhead press, rear delt flyes"),
    "back":       ("pull",  "back — rows, pull-ups, lat pulldowns, deadlifts"),
    "lat":        ("pull",  "lats — lat pulldowns, pull-ups, straight arm pushdowns"),
    "trap":       ("pull",  "traps — shrugs, face pulls, rack pulls"),
    "rhomboid":   ("pull",  "upper back — rows, face pulls, reverse flyes"),
    "bicep":      ("pull",  "biceps — curls, hammer curls, chin-ups"),
    "biceps":     ("pull",  "biceps — curls, hammer curls, chin-ups"),
    "leg":        ("legs",  "legs — squats, leg press, Romanian deadlifts, lunges"),
    "quad":       ("legs",  "quads — squats, leg press, leg extensions, lunges"),
    "hamstring":  ("legs",  "hamstrings — Romanian deadlifts, lying leg curls, good mornings"),
    "glute":      ("legs",  "glutes — hip thrusts, Bulgarian split squats, cable kickbacks"),
    "calf":       ("legs",  "calves — standing calf raises, seated calf raises, jump rope"),
    "squat":      ("legs",  "legs — squat-focused: back squat, front squat, goblet squat, lunges"),
    "deadlift":   ("pull",  "posterior chain — deadlifts, RDLs, good mornings, rows"),
    "upper body": ("push",  "upper body — push + pull supersets: bench, rows, shoulder press, curls"),
    "lower body": ("legs",  "lower body — full leg day: squats, RDLs, lunges, hip thrusts, calves"),
    "full body":  (None,    "full body — compound movements: squat, deadlift, bench, row, overhead press"),
    "abs":        (None,    "core/abs — planks, cable crunches, hanging leg raises, Russian twists"),
    "core":       (None,    "core — planks, ab wheel, cable crunches, dead bugs, L-sits"),
    "forearm":    ("pull",  "forearms — wrist curls, reverse curls, farmer's walks, grip training"),
    "swim":       ("swim",  "cardio swim — laps, kick drills, interval sets"),
    "cardio":     ("swim",  "cardio — swimming laps, HIIT, cycling, rowing machine"),
}


# ── Exercise demo links ───────────────────────────────────────────────────────

# Curated YouTube short IDs for common exercises (reliable form demos)
_EXERCISE_DEMO_URLS = {
    # Push — Chest
    "bench press":            "https://youtu.be/rT7DgCr-3pg",
    "incline bench":          "https://youtu.be/DbFgADa2PL8",
    "incline dumbbell press": "https://youtu.be/DbFgADa2PL8",
    "dumbbell flye":          "https://youtu.be/eozdVDA78K0",
    "cable crossover":        "https://youtu.be/taI4XduLpTk",
    "chest fly":              "https://youtu.be/taI4XduLpTk",
    "pec deck":               "https://youtu.be/e8NG5T5YTRE",
    "push up":                "https://youtu.be/_l3ySVKYVJ8",
    "dip":                    "https://youtu.be/2z8JmcrW-As",
    # Push — Shoulders
    "overhead press":         "https://youtu.be/2yjwXTZQDDI",
    "shoulder press":         "https://youtu.be/qEwKCR5JCog",
    "lateral raise":          "https://youtu.be/FeJT_FgBXt0",
    "front raise":            "https://youtu.be/sOt_qqCsRkc",
    "face pull":              "https://youtu.be/HSoHeSjvIdU",
    "rear delt fly":          "https://youtu.be/EA7u4Q_8HQ0",
    "upright row":            "https://youtu.be/um3SX3fZHs4",
    # Push — Triceps
    "tricep pushdown":        "https://youtu.be/2-LAMcpzODU",
    "overhead extension":     "https://youtu.be/YbX7Wd8jQ-Q",
    "skull crusher":          "https://youtu.be/d_KZxkY_0cM",
    "close grip bench":       "https://youtu.be/nEF0bv2FW94",
    # Pull — Back
    "pull up":                "https://youtu.be/eGo4IYlbE5g",
    "chin up":                "https://youtu.be/7dphcZ4-TJk",
    "lat pulldown":           "https://youtu.be/CAwf7n6Luuc",
    "seated cable row":       "https://youtu.be/GZbfZ033f74",
    "barbell row":            "https://youtu.be/kBWAon7ItDw",
    "dumbbell row":           "https://youtu.be/pYcpY20QaE8",
    "t-bar row":              "https://youtu.be/j3y8mR00JoM",
    "straight arm pulldown":  "https://youtu.be/4tpIH50BSOY",
    "deadlift":               "https://youtu.be/op9kVnSso6Q",
    "romanian deadlift":      "https://youtu.be/hCDzSR6bW10",
    "rdl":                    "https://youtu.be/hCDzSR6bW10",
    # Pull — Biceps
    "barbell curl":           "https://youtu.be/kwG2ipFRgfo",
    "dumbbell curl":          "https://youtu.be/sAq_ocpRh_I",
    "hammer curl":            "https://youtu.be/zC3nLlEvin4",
    "preacher curl":          "https://youtu.be/fIWP-FRFNU0",
    "incline curl":           "https://youtu.be/soxrZlIl35U",
    "cable curl":             "https://youtu.be/NFzTWp2qpiE",
    # Legs
    "squat":                  "https://youtu.be/ultWZbUMPL8",
    "front squat":            "https://youtu.be/uYumuL_G_V0",
    "goblet squat":           "https://youtu.be/MeIiIdhvXT4",
    "leg press":              "https://youtu.be/IZxyjW7MPJQ",
    "lunge":                  "https://youtu.be/D7KaRcUTQeE",
    "bulgarian split squat":  "https://youtu.be/2C-uNgKwPLE",
    "leg extension":          "https://youtu.be/YyvSfVjQeL0",
    "leg curl":               "https://youtu.be/1Tq3QdYUuHs",
    "hip thrust":             "https://youtu.be/SEdqd1n0cvg",
    "calf raise":             "https://youtu.be/-M4-G8p1fCI",
    "good morning":           "https://youtu.be/YA-h3n9L4YU",
    # Core
    "plank":                  "https://youtu.be/pSHjTRCQxIw",
    "ab wheel":               "https://youtu.be/DHFBUFPKhtM",
    "cable crunch":           "https://youtu.be/ULlP9avvRfk",
    "hanging leg raise":      "https://youtu.be/Pr1ieGZ5atk",
    "russian twist":          "https://youtu.be/wkD8rjkodUI",
    "dead bug":               "https://youtu.be/g_BYB0R-4Ws",
    "crunch":                 "https://youtu.be/Xyd_fa5zoEU",
}


def _demo_link(exercise: str) -> str:
    """Return a YouTube demo URL for the given exercise name."""
    ex_lower = exercise.lower().strip()
    # Exact match first
    if ex_lower in _EXERCISE_DEMO_URLS:
        return _EXERCISE_DEMO_URLS[ex_lower]
    # Partial match
    for key, url in _EXERCISE_DEMO_URLS.items():
        if key in ex_lower or ex_lower in key:
            return url
    # Fallback: YouTube search
    query = exercise.strip().replace(" ", "+") + "+form+tutorial"
    return f"https://www.youtube.com/results?search_query={query}"


def _inject_demo_links(workout_text: str) -> str:
    """
    Post-process a workout table response to add YouTube demo links to exercise names.
    Turns "| Bench Press | 4 × 8 |..." into "| [Bench Press](url) | 4 × 8 |..."
    """
    import re
    lines = workout_text.split("\n")
    result = []
    header_passed = False

    for line in lines:
        if not line.startswith("|"):
            header_passed = False
            result.append(line)
            continue

        cells = line.split("|")
        # Skip header row (contains "Exercise") and separator row (contains "---")
        if len(cells) < 3:
            result.append(line)
            continue
        exercise_cell = cells[1].strip()
        if not exercise_cell or "Exercise" in exercise_cell or "---" in exercise_cell:
            result.append(line)
            continue

        # Strip any existing markdown link so we don't double-wrap
        plain = re.sub(r"\[(.+?)\]\(.+?\)", r"\1", exercise_cell)
        if plain:
            url = _demo_link(plain)
            cells[1] = f" [{plain}]({url}) "
            line = "|".join(cells)
        result.append(line)

    return "\n".join(result)


def extract_exercise_images(workout_text: str) -> list[tuple[str, str]]:
    """
    Parse exercise names from a workout table and return (name, thumbnail_url) pairs.
    Only returns exercises that map to a real YouTube video (not search fallback).
    Used by bot.py to send exercise demo photo album after a workout suggestion.
    """
    import re
    results = []
    seen: set[str] = set()

    for line in workout_text.split("\n"):
        if not line.startswith("|"):
            continue
        cells = line.split("|")
        if len(cells) < 3:
            continue
        cell = cells[1].strip()
        if not cell or "Exercise" in cell or "---" in cell:
            continue

        # Extract plain name from markdown link [Name](url) or raw text
        m = re.match(r"\[(.+?)\]\(.+?\)", cell)
        name = m.group(1).strip() if m else cell.strip()

        if not name or name.lower() in seen:
            continue
        seen.add(name.lower())

        url = _demo_link(name)
        # Only include real YouTube video links (not search fallback)
        yt = re.search(r"youtu\.be/([A-Za-z0-9_-]+)", url)
        if yt:
            thumb = f"https://img.youtube.com/vi/{yt.group(1)}/hqdefault.jpg"
            results.append((name, thumb))

    return results


def _detect_muscle_focus(message: str) -> tuple[str | None, str | None]:
    """
    Detect if the user is asking for a specific muscle group workout.
    Returns (rotation_type_or_None, focus_description_or_None).
    None means use rotation.
    """
    msg_lower = message.lower()
    for keyword, (rtype, focus_desc) in _MUSCLE_FOCUS_MAP.items():
        if keyword in msg_lower:
            return rtype, focus_desc
    return None, None


# ── Workout suggestions ───────────────────────────────────────────────────────

def _suggest_workout(message: str) -> str:
    """
    Suggest a workout. Two modes:
    1. Muscle group specified → design workout around that muscle group
    2. No specific group → use push/pull/legs/swim rotation based on recent history
    """
    recent = _get_recent_workouts(days=7)
    week_logs = get_health_summary(7)
    workouts_this_week = [l for l in week_logs if l.get("metric") == "workout"]
    count_this_week = len(workouts_this_week)
    remaining = max(0, TARGETS["workouts"]["goal"] - count_this_week)

    if recent:
        recent_desc = "\n".join(
            f"- {r.get('date','')}: {r.get('value','')}" for r in recent[-7:]
        )
        history_context = f"Recent workouts (last 7 days):\n{recent_desc}\n"
    else:
        history_context = "No workouts logged this week yet.\n"

    week_context = (
        f"This week: {count_this_week}/{TARGETS['workouts']['goal']} workouts done. "
        f"{remaining} more needed to hit goal.\n\n"
    )

    # ── Check if user specified a muscle group ────────────────────────────────
    req_type, focus_desc = _detect_muscle_focus(message)

    if focus_desc:
        # User asked for a specific muscle group
        # Check if this group was already trained recently (warn but still deliver)
        recently_trained = []
        for log in recent[-3:]:
            wt = _classify_workout_type(log.get("value", ""))
            if req_type and wt == req_type:
                recently_trained.append(log.get("date", "recently"))

        recent_warning = ""
        if recently_trained:
            recent_warning = (
                f"⚠️ Note: you trained {req_type} on {', '.join(recently_trained[-1:])} — "
                f"consider adequate recovery. Designing the session as requested.\n\n"
            )

        prompt = (
            f"{history_context}"
            f"{week_context}"
            f"Justin's request: {message}\n\n"
            f"Design a focused *{focus_desc}* workout.\n\n"
            f"{recent_warning}"
            "Rules:\n"
            "- Build the session around the requested muscle group(s)\n"
            "- Use different exercises than what was done in recent sessions (vary stimulus)\n"
            "- Include abs/core at the end of any lifting session\n"
            "- Suggest 4–6 exercises with progressive overload in mind\n\n"
            "Format (use exact exercise names so I can look up demo videos):\n"
            "💪 *[Workout Name]* — [~X min]\n\n"
            "| Exercise | Sets × Reps | Rest | Coaching tip |\n"
            "| --- | --- | --- | --- |\n"
            "| [exercise name] | [X × X] | [Xs] | [cue] |\n\n"
            "📝 *Focus:* [One coaching point for this session]\n"
            "⚠️ *Avoid:* [One thing to watch given recent training]"
        )
    else:
        # No specific group — use rotation
        next_type = _next_rotation_type(recent)

        # Force swim if 3+ heavy lifts this week and no swim yet
        heavy_lifts = sum(
            1 for l in workouts_this_week
            if _classify_workout_type(l.get("value", "")) in ("push", "pull", "legs")
        )
        swims_this_week = sum(
            1 for l in workouts_this_week
            if _classify_workout_type(l.get("value", "")) == "swim"
        )
        if heavy_lifts >= 3 and swims_this_week == 0:
            next_type = "swim"

        if next_type:
            type_label = _ROTATION_LABELS.get(next_type, next_type.capitalize())
            type_instruction = (
                f"REQUIRED WORKOUT TYPE: **{type_label}** ({next_type} day) — determined by rotation.\n\n"
                "Rules:\n"
                "- Rotation is Chest & Triceps → Back & Biceps → Legs → Cardio/Swim.\n"
                "- Use different exercises than what was done in recent sessions of the same type\n"
                "- Include abs/core at the end of every lifting session\n"
            )
        else:
            type_label = "Full Body or your choice"
            type_instruction = (
                "No workout history found — no rotation to follow.\n"
                "Design a balanced full body session OR ask Justin what he wants to train.\n"
                "Suggest: 'What do you feel like training — upper body, legs, or full body?'\n"
            )

        prompt = (
            f"{history_context}"
            f"{week_context}"
            f"Justin's request: {message}\n\n"
            f"{type_instruction}\n"
            "Format (use exact exercise names so I can look up demo videos):\n"
            "💪 *[Workout Name]* — [~X min]\n\n"
            "| Exercise | Sets × Reps | Rest | Coaching tip |\n"
            "| --- | --- | --- | --- |\n"
            "| [exercise name] | [X × X] | [Xs] | [cue] |\n\n"
            "📝 *Coaching tip:* [One focus point for today's session]\n"
            "🎯 *Why this:* [Why this is the right next session based on your history]"
        )
    response = chat(SYSTEM, prompt, max_tokens=700)
    return _inject_demo_links(response)


# ── Goal progression ──────────────────────────────────────────────────────────

def _check_goal_progression() -> str:
    """
    Check if Justin has been consistently hitting targets.
    If so, suggest raising the bar slightly.
    Returns empty string if no progression to suggest.
    """
    logs = get_health_summary(14)  # 2 weeks
    if not logs:
        return ""

    sleeps = [float(l["value"]) for l in logs if l["metric"] == "sleep" and _is_num(l["value"])]
    weights = [float(l["value"]) for l in logs if l["metric"] == "weight" and _is_num(l["value"])]
    workouts_2w = [l for l in logs if l["metric"] == "workout"]

    suggestions = []

    # Sleep: consistently above 7.5h → suggest 8h
    if len(sleeps) >= 5 and all(s >= 7.5 for s in sleeps[-5:]):
        avg = sum(sleeps[-5:]) / 5
        if avg >= 7.8:
            suggestions.append(f"😴 Sleep is averaging {avg:.1f}h — consider pushing to 8h as your new baseline")

    # Weight: steadily dropping → celebrate + recalibrate
    if len(weights) >= 3:
        if weights[-1] < weights[0]:
            total_lost = weights[0] - weights[-1]
            to_go = weights[-1] - TARGETS["weight"]["goal"]
            if to_go <= 5 and to_go > 0:
                suggestions.append(f"⚖️ Only {to_go:.1f} lbs to goal — consider updating target to {int(weights[-1]-2)} lbs next")

    # Workouts: hitting 4+/week consistently → suggest adding a 5th or upping intensity
    if len(workouts_2w) >= 8:  # 4/week × 2 weeks
        suggestions.append("🏋️ Consistently hitting 4+ workouts/week — ready to add progressive overload or a 5th session")

    if suggestions:
        return "\n\n🔼 *Goal progression check:*\n" + "\n".join(f"• {s}" for s in suggestions)
    return ""


# ── Food correction handler ───────────────────────────────────────────────────

def handle_food_correction(correction_text: str, last_metric: str, last_value: str) -> str:
    """
    Handle a quantity/detail correction to the most recently logged food entry.
    Updates the last food log entry in health.json and returns updated nutrition balance.
    """
    updated = update_last_food_log(correction_text)
    if not updated:
        return (
            f"I don't see a recent {last_metric} log to update today.\n"
            f"Try logging it again: e.g. _'{last_value}, {correction_text}'_"
        )

    new_value = updated.get("value", "")
    metric = updated.get("metric", "meal")

    # Record correction as a learning so future logs are more accurate
    add_learning(
        "health", "correction",
        f"User corrected a {metric} log from '{last_value}' to '{new_value}'. "
        "When logging food, wait for quantity confirmation before finalizing.",
        source=correction_text,
    )

    type_emoji = {"meal": "🥗", "snack": "🍎", "drink": "☕"}.get(metric, "🥗")
    balance = _nutrition_balance_response()
    update_msg = f"✏️ *Updated {metric} log:*\n{type_emoji} _{new_value}_"
    if balance:
        update_msg += f"\n\n{balance}"
    return update_msg


# ── Main handler ──────────────────────────────────────────────────────────────

def handle(message: str) -> str:
    msg_lower = message.lower()

    # ── Summary / progress request ────────────────────────────────────────────
    if any(w in msg_lower for w in ["summary", "trend", "progress", "stats",
                                     "how am i", "report", "overview", "check in",
                                     "how's my", "how is my"]):
        return _build_summary()

    # ── "What should I eat" ───────────────────────────────────────────────────
    if any(phrase in msg_lower for phrase in FOOD_SUGGEST_KEYWORDS):
        return _what_to_eat(message)

    has_suggest = any(w in msg_lower for w in WORKOUT_SUGGEST_KEYWORDS)
    has_topic   = any(w in msg_lower for w in WORKOUT_TOPIC_KEYWORDS)
    has_done    = any(w in msg_lower for w in WORKOUT_DONE_KEYWORDS)
    has_insight = any(w in msg_lower for w in INSIGHT_KEYWORDS)

    # ── Insight/analysis request about a past workout or meal ─────────────────
    # e.g. "give me some insight on that workout" — analyze recent logs, don't plan next session
    if has_insight and has_topic:
        recent = get_health_summary(3)
        context = f"Justin's recent health logs (last 3 days):\n{json.dumps(recent, indent=2)}\n\nRequest: {message}"
        return chat(SYSTEM, context, max_tokens=400)

    # ── Pure workout suggestion ───────────────────────────────────────────────
    # Route to suggest when:
    #   a) User explicitly asks for a recommendation (has_suggest=True) — even if they
    #      mention a past workout for context ("I did back recently, give me a workout")
    #   b) User mentions a workout topic keyword with no past-tense completion marker
    if has_suggest and has_topic:
        return _suggest_workout(message)
    if has_topic and not has_done and not has_insight:
        return _suggest_workout(message)

    # ── Try to parse as a log entry ───────────────────────────────────────────
    parsed = parse_log(message)
    if parsed:
        entry = log_health(parsed["metric"], parsed["value"], note=message)
        metric = parsed["metric"]
        value  = parsed["value"]
        feedback = ""

        if metric == "weight":
            try:
                current = float(value)
                lbs_to_go = current - TARGETS["weight"]["goal"]
                if lbs_to_go > 0:
                    feedback = f"\n🎯 {lbs_to_go:.1f} lbs to goal (165 lbs)"
                else:
                    feedback = f"\n🎉 Goal reached! {abs(lbs_to_go):.1f} lbs below target!"
                # Check goal progression
                feedback += _check_goal_progression()
            except ValueError:
                pass

        elif metric == "sleep":
            try:
                hrs = float(value)
                goal = TARGETS["sleep"]["goal"]
                if hrs >= goal:
                    feedback = f"\n✅ Hit your {goal}h target"
                else:
                    deficit = goal - hrs
                    feedback = f"\n⚠️ {deficit:.1f}h short of {goal}h goal — try moving bedtime {int(deficit * 60)} min earlier tonight"
            except ValueError:
                pass

        elif metric == "workout":
            week_logs = get_health_summary(7)
            workouts_this_week = [l for l in week_logs if l.get("metric") == "workout"]
            count = len(workouts_this_week)
            goal  = TARGETS["workouts"]["goal"]
            remaining = max(0, goal - count)
            streak = f"{count}/{goal} workouts this week"
            # Generate rich workout insight
            insight_prompt = (
                f"Justin just logged this workout: {value}\n\n"
                f"Provide a brief but useful post-workout analysis:\n"
                f"1. 🔥 Estimated calories burned (give a range based on his ~175 lb bodyweight)\n"
                f"2. 💪 Muscle groups / type worked (cardio, strength, recovery, etc.)\n"
                f"3. ⏱ Recovery: what he should do in the next 24h (eat, stretch, rest, next session type)\n"
                f"4. One specific coaching observation about this workout\n\n"
                f"Be concise — 4 bullet points max. Phone-friendly."
            )
            insight = chat(SYSTEM, insight_prompt, max_tokens=250)
            if remaining == 0:
                feedback = f"\n🔥 {streak} — weekly goal hit!\n\n{insight}"
            else:
                feedback = f"\n💪 {streak} — {remaining} more to go\n\n{insight}"

        elif metric in ("meal", "snack", "drink"):
            label = _meal_label() if metric == "meal" else metric.capitalize()
            type_emoji = {"meal": "🥗", "snack": "🍎", "drink": "☕"}.get(metric, "🥗")

            if metric == "drink":
                insight_prompt = (
                    f"Justin just logged this drink: {value}\n\n"
                    f"Estimate the nutrition. Note any calories, sugar, caffeine, or alcohol.\n\n"
                    f"Format:\n"
                    f"📊 *Nutrition Estimate*\n"
                    f"• Calories: ~[X] kcal\n"
                    f"• Protein: ~[X]g (if any)\n"
                    f"• Sugar: ~[X]g (if applicable)\n"
                    f"• Caffeine / Alcohol: [note if relevant]\n\n"
                    f"💡 *Note* — [One coaching note relevant to his fat-loss / protein goals]"
                )
            elif metric == "snack":
                insight_prompt = (
                    f"Justin just logged this snack: {value}\n\n"
                    f"Estimate nutrition. Snacks should ideally be high-protein or high-fiber for his goals.\n\n"
                    f"Format:\n"
                    f"📊 *Nutrition Estimate*\n"
                    f"• Calories: ~[X] kcal\n"
                    f"• Protein: ~[X]g\n"
                    f"• Carbs: ~[X]g · Fat: ~[X]g\n\n"
                    f"✅ *Good* — [1 bullet]\n"
                    f"💡 *Better option* — [one higher-protein snack swap if applicable]"
                )
            else:
                insight_prompt = (
                    f"Justin just logged this {label.lower()}: {value}\n\n"
                    f"Estimate the nutrition for this meal. Be specific about portions if not stated.\n\n"
                    f"Format:\n"
                    f"📊 *Nutrition Estimate*\n"
                    f"• Calories: ~[X] kcal\n"
                    f"• Protein: ~[X]g\n"
                    f"• Carbs: ~[X]g\n"
                    f"• Fat: ~[X]g\n\n"
                    f"✅ *Strengths* — [1 bullet for his goals]\n"
                    f"⚠️ *Watch out* — [1 bullet if anything is off]\n"
                    f"💡 *Tip* — [One coaching note]"
                )
            food_insight = chat(SYSTEM, insight_prompt, max_tokens=250)
            feedback = f"\n{type_emoji} *{label} logged*\n\n{food_insight}"
            # Running nutrition balance (meals + snacks + drinks)
            nutrition = _nutrition_balance_response(new_meal=value)
            if nutrition:
                feedback += f"\n\n{nutrition}"

        metric_label = {"meal": "Meal", "snack": "Snack", "drink": "Drink",
                        "workout": "Workout", "weight": "Weight", "sleep": "Sleep"}.get(metric, metric.capitalize())
        log_response = f"✅ Logged: *{metric_label}*\n_{value}_{feedback}"

        # If they also asked for next steps, answer that too
        if has_suggest and metric == "workout":
            coaching = _suggest_workout(f"what should I do next after {value}?")
            return f"{log_response}\n\n{coaching}"

        return log_response

    # ── Fallback: general health question ─────────────────────────────────────
    from core.conversation import get_history_for_llm
    from core.learning import detect_and_save_preference

    # Detect and persist any preferences stated in the message
    detect_and_save_preference(message, "health")

    summary_data = get_health_summary(7)
    learnings_ctx = format_for_prompt("health")
    context = (
        f"Justin's recent health logs (7 days):\n{summary_data}\n\n"
        f"{learnings_ctx + chr(10) if learnings_ctx else ''}"
        f"Question: {message}"
    )
    history = get_history_for_llm(n=3)
    return chat(SYSTEM, context, max_tokens=400, history=history)


# ── Summary builder ───────────────────────────────────────────────────────────

def _build_summary() -> str:
    logs = get_health_summary(7)

    if not logs:
        return (
            "📊 *Health Check-In*\n\n"
            "Nothing logged yet this week. Start with:\n"
            "• `weight 175`\n"
            "• `slept 7.5 hours`\n"
            "• `swam 30 mins`\n"
            "• `had chicken and rice for lunch`\n"
            "• Send a food photo 📸"
        )

    by_metric: dict = {}
    for entry in logs:
        m = entry["metric"]
        if m not in by_metric:
            by_metric[m] = []
        by_metric[m].append(entry)

    lines = ["📊 *7-Day Health Check-In*\n"]

    # Weight
    if "weight" in by_metric:
        weights = [float(e["value"]) for e in by_metric["weight"] if _is_num(e["value"])]
        if weights:
            latest = weights[-1]
            to_go  = latest - TARGETS["weight"]["goal"]
            if len(weights) > 1:
                delta = weights[-1] - weights[0]
                trend = f"↓ {abs(delta):.1f} lbs this week" if delta < 0 else f"↑ {delta:.1f} lbs" if delta > 0 else "→ stable"
            else:
                trend = "—"
            lines.append(f"⚖️ Weight: *{latest} lbs* — {trend} · {to_go:.0f} lbs to goal (165)")

    # Sleep
    if "sleep" in by_metric:
        sleeps = [float(e["value"]) for e in by_metric["sleep"] if _is_num(e["value"])]
        if sleeps:
            avg  = sum(sleeps) / len(sleeps)
            low  = min(sleeps)
            emoji = "✅" if avg >= TARGETS["sleep"]["goal"] else "⚠️"
            lines.append(f"😴 Sleep: *{avg:.1f}h avg* {emoji} · worst night {low:.1f}h (goal 7.5h)")

    # Workouts
    if "workout" in by_metric:
        count = len(by_metric["workout"])
        goal  = TARGETS["workouts"]["goal"]
        emoji = "🔥" if count >= goal else "💪"
        types = []
        for w in by_metric["workout"]:
            v = w["value"].lower()
            if any(x in v for x in ["swim", "pool"]):       types.append("🏊 swim")
            elif any(x in v for x in ["push", "chest", "shoulder", "tricep"]): types.append("🏋️ push")
            elif any(x in v for x in ["pull", "back", "bicep", "row"]):       types.append("🏋️ pull")
            elif any(x in v for x in ["leg", "squat", "dead"]):               types.append("🏋️ legs")
            elif any(x in v for x in ["gym", "lift", "weight"]):              types.append("🏋️ lift")
            elif any(x in v for x in ["run", "cardio"]):                      types.append("🏃 cardio")
        type_str = " · ".join(dict.fromkeys(types))  # dedup, preserve order
        lines.append(f"🏋️ Workouts: *{count}/{goal}* this week {emoji} · {type_str}")

    # Meals + nutrition
    if "meal" in by_metric:
        count = len(by_metric["meal"])
        lines.append(f"🥗 Meals logged: *{count}* this week")

        # Estimate today's nutrition from today's meals
        todays_meals = _get_todays_meals()
        if todays_meals:
            meal_descs = "\n".join(f"- {m.get('note') or m.get('value','')}" for m in todays_meals)
            nutrition_est = chat(
                SYSTEM,
                f"Today's meals:\n{meal_descs}\n\nEstimate total protein consumed today in one line: 'Protein today: ~Xg / 150g target'",
                max_tokens=50
            )
            lines.append(f"   {nutrition_est.strip()}")

    # Goal progression check
    progression = _check_goal_progression()

    # AI coaching tip
    context = f"Week summary data: {by_metric}"
    tip = chat(
        SYSTEM,
        f"Based on this week's health data, give Justin ONE specific, actionable tip for today in 1 sentence max:\n{context}",
        max_tokens=80
    )
    lines.append(f"\n💡 *Today's focus:* {tip.strip()}")

    if progression:
        lines.append(progression)

    return "\n".join(lines)


# ── Proactive daily nudge (called by APScheduler) ─────────────────────────────

def run_daily_nudge() -> str:
    """
    Morning check-in — called at 8 AM daily.
    Returns a short nudge message if Justin is behind on any goal.
    Returns empty string if everything looks on track (no spam).
    """
    logs = get_health_summary(7)
    if not logs:
        return (
            "☀️ *Morning check-in*\n\n"
            "Nothing logged this week yet — start strong today!\n"
            "Log your weight, last night's sleep, or a meal to get tracking."
        )

    by_metric: dict = {}
    for l in logs:
        by_metric.setdefault(l["metric"], []).append(l)

    nudges = []
    today = datetime.date.today()
    weekday = today.weekday()  # 0=Mon, 6=Sun

    # Behind on workouts mid-week
    workout_count = len(by_metric.get("workout", []))
    days_into_week = weekday + 1  # 1=Mon, 7=Sun
    if days_into_week >= 3 and workout_count == 0:
        nudges.append("💪 No workouts logged yet this week — today's a great day to go")
    elif days_into_week >= 5 and workout_count < 2:
        nudges.append(f"💪 Only {workout_count} workout this week — need {TARGETS['workouts']['goal'] - workout_count} more by Sunday")

    # Sleep check
    sleeps = [float(l["value"]) for l in by_metric.get("sleep", []) if _is_num(l["value"])]
    if sleeps:
        avg_sleep = sum(sleeps) / len(sleeps)
        if avg_sleep < 7.0:
            nudges.append(f"😴 Avg sleep this week: {avg_sleep:.1f}h — aim for 7.5h tonight")

    # Weight check-in reminder if not logged in 3+ days
    weight_logs = by_metric.get("weight", [])
    if not weight_logs:
        nudges.append("⚖️ No weight logged this week — quick check-in: how much do you weigh today?")

    if not nudges:
        # Everything looks good — send a motivational note
        return ""  # Don't spam if on track

    # Get today's meal recommendation
    meal_label = _meal_label()
    meal_tip = chat(
        SYSTEM,
        f"Give Justin one high-protein breakfast or {meal_label.lower()} idea in one line (under 15 words) "
        f"aligned with his 150g protein / 1,900 kcal goal.",
        max_tokens=40
    )

    header = f"☀️ *Morning check-in — {today.strftime('%A, %b %d')}*\n"
    body   = "\n".join(f"• {n}" for n in nudges)
    footer = f"\n🍳 *Today's meal idea:* {meal_tip.strip()}"

    return f"{header}\n{body}{footer}"


# ── Proactive meal nudges (called by APScheduler) ─────────────────────────────

def run_meal_nudge(meal: str) -> str:
    """
    Check if a meal has been logged in the relevant time window today.
    Returns a nudge string if nothing logged, empty string if already logged (stay silent).

    meal: "breakfast" (called ~9:30 AM ET), "lunch" (called ~12:30 PM ET), or "dinner" (called ~7:30 PM ET)
    """
    try:
        import datetime
        try:
            from zoneinfo import ZoneInfo
            now = datetime.datetime.now(tz=ZoneInfo("America/New_York"))
        except Exception:
            now = datetime.datetime.now(tz=datetime.timezone(datetime.timedelta(hours=-4)))

        today = now.date().isoformat()
        today_logs = get_health_summary(1)

        # Find meals logged today with a timestamp in the relevant window
        if meal == "breakfast":
            window_start_hour = 5    # 5am ET
        elif meal == "lunch":
            window_start_hour = 10   # 10am ET
        else:  # dinner
            window_start_hour = 16   # 4pm ET

        meal_in_window = False
        for log in today_logs:
            if log.get("metric") != "meal":
                continue
            if log.get("date") != today:
                continue
            # Check timestamp if available
            ts_str = log.get("timestamp", "")
            if ts_str:
                try:
                    ts = datetime.datetime.fromisoformat(ts_str)
                    # Make timezone-naive comparison if needed
                    ts_hour = ts.hour
                    if ts_hour >= window_start_hour:
                        meal_in_window = True
                        break
                except Exception:
                    # If timestamp is unparseable, count it as logged
                    meal_in_window = True
                    break
            else:
                # No timestamp — just count it
                meal_in_window = True
                break

        if meal_in_window:
            return ""  # Already logged — stay silent

        emoji = "🍳" if meal == "breakfast" else "🥗" if meal == "lunch" else "🍽"
        return (
            f"{emoji} *{meal.capitalize()} check-in*\n\n"
            f"Haven't seen {meal} logged yet — did you eat?\n\n"
            f"📸 Snap a photo or type what you had.\n"
            f"_e.g. 'had a chicken sandwich for lunch'_"
        )
    except Exception as e:
        logger.warning("Meal nudge error: %s", e)
        return ""


def run_lunch_nudge() -> str:
    """Proactive 12:30 PM lunch check-in. Silent if already logged."""
    return run_meal_nudge("lunch")


def run_dinner_nudge() -> str:
    """Proactive 7:30 PM dinner check-in. Silent if already logged."""
    return run_meal_nudge("dinner")


def run_breakfast_nudge() -> str:
    """Proactive 9:30 AM breakfast check-in. Silent if already logged."""
    return run_meal_nudge("breakfast")


def _score_week(logs: list[dict]) -> dict:
    """
    Compute weekly metrics from health logs.
    Returns dict with workout_count, workout_goal_pct, avg_sleep, avg_protein_est,
    weight_start, weight_end, weight_delta, food_logs, snack_count, drink_count.
    """
    workouts = [l for l in logs if l.get("metric") == "workout"]
    sleeps   = [float(l["value"]) for l in logs if l.get("metric") == "sleep" and _is_num(l["value"])]
    weights  = [float(l["value"]) for l in logs if l.get("metric") == "weight" and _is_num(l["value"])]
    meals    = [l for l in logs if l.get("metric") == "meal"]
    snacks   = [l for l in logs if l.get("metric") == "snack"]
    drinks   = [l for l in logs if l.get("metric") == "drink"]

    workout_count = len(workouts)
    workout_goal  = TARGETS["workouts"]["goal"]
    workout_pct   = round(workout_count / workout_goal * 100)

    avg_sleep = round(sum(sleeps) / len(sleeps), 1) if sleeps else None
    weight_start = weights[0]  if weights else None
    weight_end   = weights[-1] if weights else None
    weight_delta = round(weight_end - weight_start, 1) if (weight_start and weight_end and len(weights) > 1) else None

    return {
        "workout_count": workout_count,
        "workout_goal": workout_goal,
        "workout_goal_pct": workout_pct,
        "workouts": workouts,
        "avg_sleep": avg_sleep,
        "weight_start": weight_start,
        "weight_end": weight_end,
        "weight_delta": weight_delta,
        "meal_count": len(meals),
        "snack_count": len(snacks),
        "drink_count": len(drinks),
        "all_food": meals + snacks + drinks,
    }


def run_weekly_health_report() -> str:
    """
    Comprehensive weekly health report — sent Sunday evening.
    Covers: workout goal met/missed, nutrition consistency, weight trend,
    sleep average, and one key action for next week.
    """
    try:
        today = datetime.date.today()
        logs = get_health_summary(7)
        if not logs:
            return ""

        s = _score_week(logs)
        workout_emoji = "✅" if s["workout_count"] >= s["workout_goal"] else "⚠️"
        sleep_emoji   = "✅" if (s["avg_sleep"] or 0) >= TARGETS["sleep"]["goal"] else "⚠️"

        # Build workout type breakdown
        workout_types = []
        for w in s["workouts"]:
            wt = _classify_workout_type(w.get("value", ""))
            if wt:
                workout_types.append(wt)
        type_str = " · ".join(workout_types) if workout_types else "unclassified"

        # Build food log summary for LLM
        food_lines = "\n".join(
            f"- [{l.get('metric','meal').upper()}] {l.get('note') or l.get('value','')}"
            for l in s["all_food"]
        ) or "No food logged this week."

        weight_str = ""
        if s["weight_end"]:
            to_go = s["weight_end"] - TARGETS["weight"]["goal"]
            weight_str = f"{s['weight_end']} lbs ({to_go:+.1f} lbs to 165 goal)"
            if s["weight_delta"] is not None:
                direction = "↓" if s["weight_delta"] < 0 else "↑"
                weight_str += f" — {direction}{abs(s['weight_delta'])} lbs this week"

        header = (
            f"📊 *Weekly Health Report — Week of {today.strftime('%b %d, %Y')}*\n\n"
            f"{workout_emoji} *Workouts:* {s['workout_count']}/{s['workout_goal']} "
            f"({'goal met! 🔥' if s['workout_count'] >= s['workout_goal'] else str(s['workout_goal_pct']) + '% of goal'}) "
            f"— {type_str}\n"
        )
        if s["avg_sleep"]:
            header += f"{sleep_emoji} *Sleep:* avg {s['avg_sleep']}h/night (goal 7.5h)\n"
        if weight_str:
            header += f"⚖️ *Weight:* {weight_str}\n"
        header += f"🥗 *Food logged:* {s['meal_count']} meals · {s['snack_count']} snacks · {s['drink_count']} drinks\n"

        # LLM generates nutrition analysis + action item
        llm_prompt = (
            f"Weekly health data for Justin Ngai (goal: 165 lbs, 150g protein/day, 3-4 workouts/week, 7.5h sleep):\n\n"
            f"Workouts this week: {s['workout_count']}/{s['workout_goal']} — types: {type_str}\n"
            f"Avg sleep: {s['avg_sleep'] or 'not logged'}h\n"
            f"Weight: {weight_str or 'not logged'}\n\n"
            f"Food logged this week:\n{food_lines}\n\n"
            f"Write a brief weekly health analysis with these sections:\n"
            f"*🥗 Nutrition*\nWas protein likely adequate? Any patterns (too many snacks, low protein days, "
            f"calorie-dense drinks)? Be specific about what he ate.\n\n"
            f"*💪 Fitness*\nDid he hit his workout goal? Quality of sessions? Recovery balance?\n\n"
            f"*⚖️ Progress*\nWeight/body composition trend. On track for 165 goal?\n\n"
            f"*🎯 #1 Focus for Next Week*\nOne specific, actionable priority — not a list.\n\n"
            f"Keep each section to 2-3 sentences. Phone-friendly. No fluff."
        )
        analysis = chat(SYSTEM, llm_prompt, max_tokens=500)

        return f"{header}\n{analysis}"

    except Exception as e:
        logger.error("Weekly health report error: %s", e)
        return ""


def run_monthly_health_report() -> str:
    """
    Monthly health report — sent on the 1st of each month.
    Covers 30-day trends: workout consistency %, weight trajectory,
    nutrition patterns, sleep trend, and monthly grade.
    """
    try:
        today = datetime.date.today()
        last_month = today - datetime.timedelta(days=1)  # yesterday = last month end
        logs = get_health_summary(30)
        if not logs:
            return ""

        workouts = [l for l in logs if l.get("metric") == "workout"]
        sleeps   = [float(l["value"]) for l in logs if l.get("metric") == "sleep" and _is_num(l["value"])]
        weights  = [float(l["value"]) for l in logs if l.get("metric") == "weight" and _is_num(l["value"])]
        meals    = [l for l in logs if l.get("metric") == "meal"]
        snacks   = [l for l in logs if l.get("metric") == "snack"]
        drinks   = [l for l in logs if l.get("metric") == "drink"]

        # Workouts: goal is ~13-17 per month (3-4/week × 4.3 weeks)
        monthly_workout_goal = round(TARGETS["workouts"]["goal"] * 4.3)
        workout_pct = round(len(workouts) / monthly_workout_goal * 100)

        avg_sleep = round(sum(sleeps) / len(sleeps), 1) if sleeps else None
        weight_start = weights[0]  if weights else None
        weight_end   = weights[-1] if weights else None
        weight_delta = round(weight_end - weight_start, 1) if (weight_start and weight_end) else None

        # Grade: A=90%+, B=75%, C=60%, D=50%, F=below
        score = 0
        score += 40 if workout_pct >= 90 else 30 if workout_pct >= 75 else 20 if workout_pct >= 60 else 10
        score += 30 if (avg_sleep or 0) >= 7.5 else 20 if (avg_sleep or 0) >= 7.0 else 10
        score += 30 if (weight_delta or 0) <= -0.5 else 20 if (weight_delta or 0) <= 0 else 10
        grade = "A" if score >= 85 else "B" if score >= 70 else "C" if score >= 55 else "D"

        workout_types = []
        for w in workouts:
            wt = _classify_workout_type(w.get("value", ""))
            if wt:
                workout_types.append(wt)
        type_counts = {t: workout_types.count(t) for t in set(workout_types)}
        type_str = " · ".join(f"{v}× {k}" for k, v in sorted(type_counts.items(), key=lambda x: -x[1]))

        food_lines = "\n".join(
            f"- [{l.get('metric','meal').upper()}] {l.get('note') or l.get('value','')}"
            for l in (meals + snacks + drinks)[-30:]  # last 30 food entries
        ) or "No food logged."

        header = (
            f"📅 *Monthly Health Report — {last_month.strftime('%B %Y')}*\n\n"
            f"🏆 *Overall Grade: {grade}*\n\n"
            f"💪 *Workouts:* {len(workouts)}/{monthly_workout_goal} target ({workout_pct}%) — {type_str or 'no type data'}\n"
        )
        if avg_sleep:
            header += f"😴 *Sleep:* avg {avg_sleep}h (goal 7.5h)\n"
        if weight_end:
            to_go = weight_end - TARGETS["weight"]["goal"]
            delta_str = f" ({weight_delta:+.1f} lbs this month)" if weight_delta is not None else ""
            header += f"⚖️ *Weight:* {weight_end} lbs{delta_str} — {to_go:.1f} lbs to goal\n"
        header += f"🥗 *Food logged:* {len(meals)} meals · {len(snacks)} snacks · {len(drinks)} drinks\n"

        llm_prompt = (
            f"Monthly health data for Justin Ngai (goal: 165 lbs, 150g protein/day, 3-4x/week workouts):\n\n"
            f"Month: {last_month.strftime('%B %Y')}\n"
            f"Workouts: {len(workouts)}/{monthly_workout_goal} ({workout_pct}%) — {type_str}\n"
            f"Avg sleep: {avg_sleep or 'not logged'}h\n"
            f"Weight start→end: {weight_start or '?'} → {weight_end or '?'} lbs\n"
            f"Food log sample (last 30 entries):\n{food_lines}\n\n"
            f"Write a monthly health debrief with:\n"
            f"*📈 Month in Review* — 2-3 sentences on overall consistency and biggest win\n"
            f"*🥗 Nutrition Patterns* — What eating patterns stand out? Enough protein? Too many drinks/snacks?\n"
            f"*💪 Fitness Consistency* — Workout frequency, muscle group balance, any gaps in rotation?\n"
            f"*⚖️ Body Composition* — Progress toward 165 goal, rate of change\n"
            f"*🎯 Next Month Priority* — One specific focus area with a concrete target\n\n"
            f"Be direct and specific. Phone-friendly. No generic advice."
        )
        analysis = chat(SYSTEM, llm_prompt, max_tokens=600)

        return f"{header}\n{analysis}"

    except Exception as e:
        logger.error("Monthly health report error: %s", e)
        return ""


def run_workout_reminder() -> str:
    """
    7 PM ET daily check — did Justin log a workout today?
    Silent if yes. Nudge with next recommended workout type if no.
    """
    try:
        today = datetime.date.today().isoformat()
        # Use 2 days to avoid off-by-one in get_health_summary cutoff
        today_logs = get_health_summary(2)
        worked_out_today = any(
            l.get("metric") == "workout" and l.get("date") == today
            for l in today_logs
        )
        if worked_out_today:
            return ""  # Already logged — stay silent

        # Check how many workouts this week
        week_logs = get_health_summary(7)
        workouts_this_week = [l for l in week_logs if l.get("metric") == "workout"]
        count = len(workouts_this_week)
        goal = TARGETS["workouts"]["goal"]
        remaining = max(0, goal - count)

        # What's next in the rotation?
        recent = _get_recent_workouts(days=14)
        next_type = _next_rotation_type(recent)

        # Force swim if 3+ heavy lifts this week and no swim yet
        heavy_lifts = sum(
            1 for l in workouts_this_week
            if _classify_workout_type(l.get("value", "")) in ("push", "pull", "legs")
        )
        swims_this_week = sum(
            1 for l in workouts_this_week
            if _classify_workout_type(l.get("value", "")) == "swim"
        )
        if heavy_lifts >= 3 and swims_this_week == 0:
            next_type = "swim"

        if remaining == 0:
            return (
                f"🏋️ *Evening check-in*\n\n"
                f"You've hit your workout goal this week ({count}/{goal}) — "
                f"but no session logged today. If you went, just say what you did!\n\n"
                f"_e.g. 'did 30 min swim' or 'hit chest and triceps'_"
            )

        if next_type:
            type_label = _ROTATION_LABELS.get(next_type, next_type.capitalize())
            type_emoji = {"push": "🏋️", "pull": "💪", "legs": "🦵", "swim": "🏊"}.get(next_type, "💪")
            # Map rotation type to overall session alternative
            overall_alt = {
                "push": "Upper Body",
                "pull": "Upper Body",
                "legs": "Lower Body",
                "swim": "Full Body / Cardio",
            }.get(next_type, "Full Body")
            suggestion = (
                f"{type_emoji} Based on your rotation, you could do:\n"
                f"• *{type_label}* (muscle-focused)\n"
                f"• *{overall_alt}* (overall session)\n"
                f"• *Cardio / Swim* (active recovery)\n\n"
                f"_Say what you want and I'll build the routine, or just log what you did._"
            )
        else:
            suggestion = (
                f"💪 No recent workout history — any session counts to start!\n\n"
                f"Options:\n"
                f"• *Upper Body* (chest, back, arms, shoulders)\n"
                f"• *Lower Body* (quads, hamstrings, glutes, calves)\n"
                f"• *Full Body* (compound movements)\n"
                f"• *Cardio / Swim*\n\n"
                f"_Say 'give me an upper body workout' or log what you did today._"
            )

        return (
            f"🏋️ *Evening workout check-in*\n\n"
            f"No workout logged today. You're at {count}/{goal} this week — "
            f"{remaining} more to hit your goal.\n\n"
            f"{suggestion}"
        )
    except Exception as e:
        logger.warning("Workout reminder error: %s", e)
        return ""
