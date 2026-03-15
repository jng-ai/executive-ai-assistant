"""
Command Router — classifies incoming user messages and routes to the right agent.
"""

import json
import os
from anthropic import Anthropic

ROUTER_PROMPT = """You are the command router for Justin Ngai's personal executive AI assistant.

Classify the user's message into one of these intent types:

- schedule_meeting     : scheduling, calendar, appointments, meetings
- draft_email          : compose or send an email
- create_task          : reminders, to-dos, follow-ups
- log_health           : weight, sleep, workouts, health data
- infusion_consulting  : hospital infusion ops, consulting leads, speaking opps
- mortgage_notes       : mortgage notes, real estate, distressed notes, underwriting
- investment_research  : stocks, portfolio, market ideas, investment analysis
- travel_hack          : award flights, miles, travel deals, points optimization
- nyc_events           : NYC events, meetups, networking, things to do
- daily_briefing       : morning briefing, summary, what's happening today
- general_question     : anything else

Return ONLY valid JSON. No commentary. No markdown. Example:
{"intent": "log_health", "details": "weight 176", "params": {"metric": "weight", "value": "176"}}

If multiple intents fit, pick the most specific one."""


def classify(message: str) -> dict:
    """Classify a user message into a structured intent."""
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])

    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=256,
        system=ROUTER_PROMPT,
        messages=[{"role": "user", "content": message}],
    )

    raw = resp.content[0].text.strip()

    try:
        return json.loads(raw)
    except json.JSONDecodeError:
        # Fallback if model returns something unexpected
        return {"intent": "general_question", "details": message, "params": {}}
