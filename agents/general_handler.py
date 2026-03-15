"""
General handler — answers questions that don't fit a specific agent.
"""

import os
from anthropic import Anthropic

SYSTEM = """You are Justin Ngai's personal executive AI assistant.
Justin is a hospital infusion operations consultant, real estate investor focused
on mortgage notes, traveler who optimizes award flights, and NYC resident.

Answer concisely. When something is outside your real-time data, say so.
Keep responses short enough for a phone screen."""


def handle_general(message: str) -> str:
    client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
    resp = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=500,
        system=SYSTEM,
        messages=[{"role": "user", "content": message}],
    )
    return resp.content[0].text
