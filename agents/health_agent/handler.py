"""
Health Agent — logs and tracks Justin's health metrics.

Justin's targets:
- Weight: 165 lbs (currently ~175+, working down)
- Sleep: 7.5 hours/night
- Workouts: 3-4x per week (gym + apartment pool)
- Meals: track what he eats, rough calories
- Goal: build consistent habits, not perfection
"""

import datetime
from core.llm import chat
from core.memory import log_health, get_health_summary

TARGETS = {
    "weight":   {"goal": 165,  "current_est": 175, "unit": "lbs",    "direction": "down"},
    "sleep":    {"goal": 7.5,  "unit": "hours",  "direction": "up"},
    "workouts": {"goal": 3,    "unit": "per week", "direction": "up"},
}

SYSTEM = """You are Justin Ngai's personal health coach and habit tracker.

Justin's goals:
- Weight: get from ~175 lbs down to 165 lbs (focus on consistency, not crash dieting)
- Sleep: 7.5 hours per night minimum
- Workouts: 3-4x per week — he has access to an apartment pool (swimming) and wants to lift weights at the gym
- Meals: track what he eats without being obsessive
- Overall philosophy: build consistent habits, not perfection

When reviewing his data:
- Celebrate consistency streaks
- Flag if he's missing workouts or sleep
- Give ONE concrete tip for today — not a lecture
- Be like a supportive coach, not a drill sergeant

Keep responses short and phone-friendly. Use emojis for quick scanning."""


def parse_log(message: str) -> dict | None:
    """Parse natural language health log into structured data."""
    msg = message.lower()

    # Weight
    for word in ["weight", "weighed", "lbs", "pounds", "scale"]:
        if word in msg:
            for token in msg.split():
                try:
                    val = float(token.replace("lbs", "").replace("lb", ""))
                    if 100 < val < 400:
                        return {"metric": "weight", "value": str(val), "unit": "lbs"}
                except ValueError:
                    continue

    # Sleep
    for word in ["sleep", "slept", "hours sleep", "hr sleep", "hrs"]:
        if word in msg:
            for token in msg.split():
                try:
                    val = float(token.replace("h", "").replace("hr", "").replace("hrs", ""))
                    if 0 < val < 24:
                        return {"metric": "sleep", "value": str(val), "unit": "hours"}
                except ValueError:
                    continue

    # Meals / food
    food_words = ["ate", "had", "breakfast", "lunch", "dinner", "meal", "calories",
                  "cal", "protein", "carbs", "food", "ate ", "drank"]
    for word in food_words:
        if word in msg:
            return {"metric": "meal", "value": message.strip(), "unit": "food log"}

    # Workout
    workout_words = ["workout", "gym", "lifted", "ran", "run", "swim", "swam",
                     "pool", "biked", "shoulders", "chest", "legs", "back",
                     "arms", "cardio", "hiit", "weights", "press", "squat"]
    for word in workout_words:
        if word in msg:
            return {"metric": "workout", "value": message.strip(), "unit": "session"}

    return None


def handle(message: str) -> str:
    msg_lower = message.lower()

    # Summary / trend request
    if any(w in msg_lower for w in ["summary", "trend", "progress", "stats",
                                     "how am i", "report", "week", "overview", "check in"]):
        return _build_summary()

    # Try to parse as a log entry
    parsed = parse_log(message)
    if parsed:
        entry = log_health(parsed["metric"], parsed["value"], note=message)
        metric = parsed["metric"]
        value = parsed["value"]
        unit = parsed.get("unit", "")

        feedback = ""

        if metric == "weight":
            try:
                current = float(value)
                goal = TARGETS["weight"]["goal"]
                lbs_to_go = current - goal
                if lbs_to_go > 0:
                    feedback = f"\n🎯 {lbs_to_go:.1f} lbs to goal ({goal} lbs)"
                else:
                    feedback = f"\n🎉 Goal reached! You're {abs(lbs_to_go):.1f} lbs below target!"
            except ValueError:
                pass

        elif metric == "sleep":
            try:
                hrs = float(value)
                goal = TARGETS["sleep"]["goal"]
                if hrs >= goal:
                    feedback = f"\n✅ Hit your {goal}h target"
                else:
                    feedback = f"\n⚠️ {goal - hrs:.1f}h short of your {goal}h target"
            except ValueError:
                pass

        elif metric == "workout":
            recent = get_health_summary(7)
            workouts_this_week = [l for l in recent if l["metric"] == "workout"]
            count = len(workouts_this_week)
            goal = TARGETS["workouts"]["goal"]
            remaining = max(0, goal - count)
            if remaining == 0:
                feedback = f"\n🔥 Hit your {goal}/week target!"
            else:
                feedback = f"\n💪 {count}/{goal} workouts this week — {remaining} to go"

        elif metric == "meal":
            feedback = "\n🥗 Meal logged"

        return f"✅ Logged: *{metric}*\n_{value}_{feedback}"

    # Not a log — ask the AI
    summary_data = get_health_summary(7)
    context = f"Justin's recent health logs (7 days):\n{summary_data}\n\nQuestion: {message}"
    return chat(SYSTEM, context, max_tokens=400)


def _build_summary() -> str:
    logs = get_health_summary(7)

    if not logs:
        return (
            "📊 *Health Summary*\n\n"
            "Nothing logged yet this week.\n\n"
            "Try:\n"
            "• `weight 175`\n"
            "• `slept 7.5 hours`\n"
            "• `swam 30 mins`\n"
            "• `had chicken and rice for lunch`"
        )

    by_metric: dict = {}
    for entry in logs:
        m = entry["metric"]
        if m not in by_metric:
            by_metric[m] = []
        by_metric[m].append(entry)

    lines = ["📊 *7-Day Health Check-In*\n"]

    if "weight" in by_metric:
        weights = [float(e["value"]) for e in by_metric["weight"] if _is_num(e["value"])]
        if weights:
            latest = weights[-1]
            to_go = latest - TARGETS["weight"]["goal"]
            trend = "↓" if len(weights) > 1 and weights[-1] < weights[0] else "↑" if len(weights) > 1 else "—"
            lines.append(f"⚖️ Weight: *{latest} lbs* {trend}  (goal: 165 lbs, {to_go:.0f} to go)")

    if "sleep" in by_metric:
        sleeps = [float(e["value"]) for e in by_metric["sleep"] if _is_num(e["value"])]
        if sleeps:
            avg = sum(sleeps) / len(sleeps)
            emoji = "✅" if avg >= TARGETS["sleep"]["goal"] else "⚠️"
            lines.append(f"😴 Avg sleep: *{avg:.1f}h* {emoji}  (goal: 7.5h)")

    if "workout" in by_metric:
        count = len(by_metric["workout"])
        goal = TARGETS["workouts"]["goal"]
        emoji = "🔥" if count >= goal else "💪"
        types = set()
        for w in by_metric["workout"]:
            v = w["value"].lower()
            if any(x in v for x in ["swim", "pool"]):
                types.add("🏊 swim")
            elif any(x in v for x in ["gym", "lift", "weight", "press"]):
                types.add("🏋️ lift")
            elif any(x in v for x in ["run", "cardio"]):
                types.add("🏃 cardio")
        type_str = " · ".join(types) if types else ""
        lines.append(f"🏋️ Workouts: *{count}/{goal}* this week {emoji}  {type_str}")

    if "meal" in by_metric:
        count = len(by_metric["meal"])
        lines.append(f"🥗 Meals logged: *{count}* this week")

    # AI tip
    context = f"Health data this week: {by_metric}"
    tip = chat(SYSTEM,
               f"Based on this week's data, give Justin ONE specific actionable tip for today. Max 1 sentence:\n{context}",
               max_tokens=80)
    lines.append(f"\n💡 *Today:* {tip.strip()}")

    return "\n".join(lines)


def _is_num(val: str) -> bool:
    try:
        float(val)
        return True
    except (ValueError, TypeError):
        return False
