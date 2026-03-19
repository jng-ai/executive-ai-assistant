"""
General handler — answers questions that don't fit a specific agent.
"""

from core.llm import chat

SYSTEM = """You are a knowledgeable assistant. Answer questions accurately and concisely.
When something is outside your training data or requires real-time information, say so.
Keep responses short enough for a phone screen."""


def handle_general(message: str) -> str:
    return chat(SYSTEM, message, max_tokens=500)
