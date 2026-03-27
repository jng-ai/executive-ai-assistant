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
from core.memory import log_health, get_health_summary

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

SYSTEM = """You are Justin Ngai's personal health coach, trainer, and nutrition advisor.

Justin's profile:
- Goal: get from ~175 lbs down to 165 lbs through sustainable habits
- Daily nutrition targets: ~1,800–2,000 kcal, 150g protein, moderate carbs, healthy fats
- Sleep target: 7.5 hours/night
- Workout target: 3–4x/week — gym (weights) + apartment pool (swimming)
- Philosophy: consistency over perfection, whole foods, no crash dieting

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
- Always check what muscle groups were recently trained — don't repeat them
- Suggest swim days for active recovery between heavy lifts
- Format workouts: Exercise | Sets × Reps | Rest | Coaching tip
- Default split: Push / Pull / Legs / Swim — rotate accordingly
- For abs/core: program into end of every session"""


# ── Meal parsing prompt ────────────────────────────────────────────────────────

PARSE_PROMPT = """Extract a health log entry from this message. Return JSON only, no commentary.

CRITICAL RULE: Only return is_log:true if the person is REPORTING something they ALREADY DID or their current stats.
Return is_log:false for ANY question, request, or correction — even if it mentions health topics.

If the message IS a completed log, return:
{"is_log": true, "metric": "<weight|sleep|workout|meal>", "value": "<extracted value>", "unit": "<lbs|hours|session|food log>"}

Rules:
- weight: extract number in lbs. Must be a plain weight statement.
- sleep: calculate total hours from times given. "Slept 12:10am to 7:40am" = 7.5 hours
- workout: ONLY if they clearly completed it. Value = description of what they did.
- meal: ONLY food they actually ate. NOT corrections, questions, or future plans.

Return is_log:false if the message:
- Asks a question ("what should I...", "can I...", "how do I...")
- Makes a request ("give me", "suggest", "help me", "recommend")
- Is a correction ("it's not a meal", "I meant")
- Mentions doing something AND asks what to do next (log only the done part if clear, else false)
- Is ambiguous about whether it was completed

Examples:
"Slept from 12:10am to 7:40am" → {"is_log":true,"metric":"sleep","value":"7.5","unit":"hours"}
"weight 174" → {"is_log":true,"metric":"weight","value":"174","unit":"lbs"}
"swam 30 mins" → {"is_log":true,"metric":"workout","value":"swam 30 mins","unit":"session"}
"I did 30min swimming laps" → {"is_log":true,"metric":"workout","value":"30min swimming laps","unit":"session"}
"had chicken and rice" → {"is_log":true,"metric":"meal","value":"chicken and rice","unit":"food log"}
"what should I eat" → {"is_log":false}
"give me a workout" → {"is_log":false}
"give me a quick workout routine I started some biceps already" → {"is_log":false}
"It's sleep not meal" → {"is_log":false}
"I did biceps today what should I do tomorrow" → {"is_log":true,"metric":"workout","value":"biceps","unit":"session"}
"can I have pizza" → {"is_log":false}
"give me some insight on that workout" → {"is_log":false}"""


# ── Keyword sets ──────────────────────────────────────────────────────────────

WORKOUT_SUGGEST_KEYWORDS = [
    "suggest", "routine", "plan", "program", "what should i", "what exercise",
    "give me a", "help me", "ideas", "recommend", "how to", "what do i",
    "what can i", "tomorrow", "next workout", "after this", "what workout",
]
WORKOUT_TOPIC_KEYWORDS = [
    "workout", "exercise", "bicep", "tricep", "chest", "back", "shoulder",
    "leg", "squat", "deadlift", "pull", "push", "abs", "core", "cardio",
    "swim", "hiit", "gym", "lift", "arms", "glute",
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


def _get_todays_meals() -> list:
    """Return today's meal logs (text + photo)."""
    return [l for l in _get_todays_logs() if l.get("metric") == "meal"]


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
        f"- {m.get('note') or m.get('value', '')}" for m in meals
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


def _next_rotation_type(recent_workouts: list[dict]) -> str:
    """
    Walk backwards through recent workout logs, find the last classifiable type,
    and return the NEXT type in the push→pull→legs→swim rotation.
    Returns 'push' if no classifiable history.
    """
    for log in reversed(recent_workouts):
        wtype = _classify_workout_type(log.get("value", ""))
        if wtype:
            idx = _ROTATION.index(wtype)
            return _ROTATION[(idx + 1) % len(_ROTATION)]
    return _ROTATION[0]


# ── Workout suggestions ───────────────────────────────────────────────────────

def _suggest_workout(message: str) -> str:
    """
    Suggest next workout using push/pull/legs/swim rotation.
    Enforces rotation deterministically — LLM cannot override the type.
    """
    recent = _get_recent_workouts(days=7)
    week_logs = get_health_summary(7)
    workouts_this_week = [l for l in week_logs if l.get("metric") == "workout"]
    count_this_week = len(workouts_this_week)
    remaining = max(0, TARGETS["workouts"]["goal"] - count_this_week)

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

    if recent:
        recent_desc = "\n".join(f"- {r.get('value','')}" for r in recent[-5:])
        history_context = f"Recent workouts (last 7 days):\n{recent_desc}\n"
    else:
        history_context = "No workouts logged this week yet.\n"

    prompt = (
        f"{history_context}"
        f"This week: {count_this_week}/{TARGETS['workouts']['goal']} workouts done. "
        f"{remaining} more needed to hit goal.\n\n"
        f"Justin's request: {message}\n\n"
        f"REQUIRED WORKOUT TYPE: **{next_type.upper()}** — this is determined by the rotation schedule "
        f"and CANNOT be changed. Design a {next_type} workout.\n\n"
        "Rules:\n"
        "- Rotation is Push → Pull → Legs → Swim. You MUST follow this.\n"
        "- Include abs/core at the end of every lifting session\n"
        "- Vary specific exercises (different chest movements each push day, etc.)\n\n"
        "Format:\n"
        "💪 *[Workout Name]* — [~X min]\n\n"
        "| Exercise | Sets × Reps | Rest |\n"
        "| --- | --- | --- |\n"
        "| [exercise] | [X × X] | [Xs] |\n\n"
        "📝 *Coaching tip:* [One focus point for today's session]\n"
        "🎯 *Why this:* [One sentence on why this is the right next session]"
    )
    return chat(SYSTEM, prompt, max_tokens=600)


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
    if (has_suggest or has_topic) and not has_done and not has_insight:
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

        elif metric == "meal":
            label = _meal_label()
            # Generate nutrition insight for text-logged meals (same quality as photo handler)
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
            meal_insight = chat(SYSTEM, insight_prompt, max_tokens=250)
            feedback = f"\n🥗 *{label} logged*\n\n{meal_insight}"
            # Running nutrition balance
            nutrition = _nutrition_balance_response(new_meal=value)
            if nutrition:
                feedback += f"\n\n{nutrition}"

        log_response = f"✅ Logged: *{metric}*\n_{value}_{feedback}"

        # If they also asked for next steps, answer that too
        if has_suggest and metric == "workout":
            coaching = _suggest_workout(f"what should I do next after {value}?")
            return f"{log_response}\n\n{coaching}"

        return log_response

    # ── Fallback: general health question ─────────────────────────────────────
    summary_data = get_health_summary(7)
    context = f"Justin's recent health logs (7 days):\n{summary_data}\n\nQuestion: {message}"
    return chat(SYSTEM, context, max_tokens=400)


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
