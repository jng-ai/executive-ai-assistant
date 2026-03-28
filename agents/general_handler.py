"""
General handler — answers knowledge questions that don't fit a specific agent.

Privacy design:
- NO personal details are included in the system prompt here.
- The LLM receives only the raw question + a generic assistant instruction.
- Personal context (health goals, finances, name, etc.) stays in the
  specialized agent prompts and is never sent for general queries.
- For maximum privacy on sensitive questions, set LLM_PROVIDER=ollama
  in .env to route all inference through your local machine.
"""

from core.llm import chat
from core.conversation import get_history_for_llm

# Generic — zero identifying information passed to the LLM
SYSTEM = (
    "You are a concise, accurate assistant. "
    "Answer the question directly and factually. "
    "If the answer requires real-time data you don't have, say so briefly. "
    "Keep responses short enough for a phone screen — no padding or disclaimers."
)


def handle_general(message: str) -> str:
    history = get_history_for_llm(n=4)
    return chat(SYSTEM, message, max_tokens=500, history=history)
