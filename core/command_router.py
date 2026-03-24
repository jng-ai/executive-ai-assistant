"""
Command Router — classifies incoming user messages and routes to the right agent.
"""

import json
from core.llm import chat

ROUTER_PROMPT = """You are a message classifier. Classify the user's message into one of these intent types:

- schedule_meeting     : scheduling, calendar, appointments, meetings
- draft_email          : compose or send an email
- create_task          : reminders, to-dos, follow-ups
- log_health           : weight, sleep, workouts, health data, workout suggestions, exercise routines, fitness advice, muscle group questions (e.g. "suggest a biceps workout", "give me a chest routine", "what should I do at the gym")
- infusion_consulting  : hospital infusion ops, consulting leads, speaking opps
- mortgage_notes       : mortgage notes, real estate, distressed notes, underwriting
- investment_research  : stocks, portfolio, market ideas, investment analysis
- travel_hack          : award flights, miles, travel deals, points optimization
- nyc_events           : NYC events, meetups, networking, things to do
- personal_finance     : bank signup bonuses, credit card SUBs, budget tracking, spending, eligibility rules, Doctor of Credit, Frequent Miler, re-eligibility check, logging a new card/bank application, tax strategy, side hustle ideas, passive income, financial review, update financial profile
- bonus_alert          : check for elevated bonuses, scan for deals, bonus alert status, force scan, check bonuses now
- market_intel         : stock market analysis, sector rotation, macro view, earnings catalysts, specific stock/ETF ideas, market briefing, trade ideas, JP Morgan style analysis
- daily_briefing       : morning briefing, summary, what's happening today
- follow_up            : schedule a follow-up email or meeting in the future ("follow up with X in 3 days", "remind me to email Y next week about Z", "what follow-ups do I have", "cancel follow-up 2")
- general_question     : anything else

Return ONLY valid JSON. No commentary. No markdown. Example:
{"intent": "log_health", "details": "weight 176", "params": {"metric": "weight", "value": "176"}}

If multiple intents fit, pick the most specific one."""


def classify(message: str) -> dict:
    """Classify a user message into a structured intent."""
    raw = chat(ROUTER_PROMPT, message, max_tokens=256)

    # Strip markdown fences if model wraps in ```json
    raw = raw.strip()
    if raw.startswith("```"):
        raw = raw.split("```")[1]
        if raw.startswith("json"):
            raw = raw[4:]
    raw = raw.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        return {"intent": "general_question", "details": message, "params": {}}
