"""
Conversation memory — rolling buffer of recent user↔assistant turns.

This is a single-user personal assistant, so history is global (not per-user-id).
Stored in data/conversation.json. Max 10 turns kept.

Usage:
    from core.conversation import add_turn, format_context, get_history_for_llm

    # In bot.py — record each exchange
    add_turn(user_msg, response, agent="calendar")

    # In command_router — help with pronoun resolution ("cancel that", "send it")
    context = format_context(n=3)
    classify(message, context=context)

    # In agents — inject into LLM calls for contextual answers
    history = get_history_for_llm(n=4)
    chat(SYSTEM, user_message, history=history)
"""

import json
import logging
import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

_CONV_FILE = Path(__file__).parent.parent / "data" / "conversation.json"
_MAX_TURNS = 10


def add_turn(user_msg: str, response: str, agent: str = "") -> None:
    """Record one user→assistant exchange. Keeps last _MAX_TURNS turns."""
    history = _load()
    history.append({
        "user": user_msg[:1000],           # cap storage size
        "assistant": response[:800],
        "agent": agent,
        "ts": datetime.datetime.now().isoformat(),
    })
    _save(history[-_MAX_TURNS:])


def get_recent(n: int = 4) -> list[dict]:
    """Return last n turns as raw dicts."""
    return _load()[-n:]


def format_context(n: int = 3) -> str:
    """
    Format last n turns as plain text for router/classifier context.
    Keeps it tight — just enough for pronoun resolution.
    """
    turns = get_recent(n)
    if not turns:
        return ""
    lines = []
    for t in turns:
        lines.append(f"User: {t['user']}")
        lines.append(f"Assistant: {t['assistant'][:300]}")
    return "\n".join(lines)


def get_history_for_llm(n: int = 4) -> list[dict]:
    """
    Return last n turns as OpenAI-style message objects for multi-turn chat.
    Suitable for passing as `history` to core.llm.chat().

    Returns:
        [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...]
    """
    turns = get_recent(n)
    messages = []
    for t in turns:
        messages.append({"role": "user", "content": t["user"]})
        messages.append({"role": "assistant", "content": t["assistant"]})
    return messages


def clear() -> None:
    """Wipe conversation history (useful for tests or explicit /reset)."""
    _save([])


def _load() -> list:
    try:
        return json.loads(_CONV_FILE.read_text())
    except Exception:
        return []


def _save(history: list) -> None:
    try:
        _CONV_FILE.parent.mkdir(exist_ok=True)
        _CONV_FILE.write_text(json.dumps(history, indent=2))
    except Exception as e:
        logger.warning("conversation save error: %s", e)
