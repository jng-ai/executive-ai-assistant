"""
Learning store — persists corrections, preferences, and patterns from user interactions.
Agents inject these into prompts to improve over time without retraining.
"""

import json
import logging
import datetime
from pathlib import Path

logger = logging.getLogger(__name__)

DATA_DIR = Path(__file__).parent.parent / "data"
LEARNINGS_FILE = DATA_DIR / "agent_learnings.json"
MAX_LEARNINGS_TOTAL = 300


def _load() -> list:
    try:
        return json.loads(LEARNINGS_FILE.read_text()) if LEARNINGS_FILE.exists() else []
    except Exception:
        return []


def _save(data: list):
    DATA_DIR.mkdir(exist_ok=True)
    LEARNINGS_FILE.write_text(json.dumps(data, indent=2))


def add_learning(agent: str, category: str, content: str, source: str = "") -> dict:
    """
    Record a learning from an interaction.

    Args:
        agent: Agent key ('health', 'finance', 'general', 'all')
        category: Type ('correction', 'preference', 'pattern', 'habit', 'context')
        content: The learning to remember (concise, actionable)
        source: Original triggering message (truncated to 200 chars)
    """
    learnings = _load()
    entry = {
        "agent": agent,
        "category": category,
        "content": content,
        "source": (source or "")[:200],
        "timestamp": datetime.datetime.now().isoformat(),
    }
    learnings.append(entry)

    # Rolling window — keep most recent MAX_LEARNINGS_TOTAL
    if len(learnings) > MAX_LEARNINGS_TOTAL:
        learnings = learnings[-MAX_LEARNINGS_TOTAL:]

    _save(learnings)
    logger.debug("Learning saved [%s/%s]: %s", agent, category, content[:80])
    return entry


def get_learnings(agent: str = None, category: str = None, days: int = 60) -> list:
    """Retrieve recent learnings, optionally filtered by agent and/or category."""
    learnings = _load()
    cutoff = (datetime.datetime.now() - datetime.timedelta(days=days)).isoformat()
    result = [l for l in learnings if l.get("timestamp", "") >= cutoff]
    if agent:
        result = [l for l in result if l.get("agent") in (agent, "all")]
    if category:
        result = [l for l in result if l.get("category") == category]
    return result


def format_for_prompt(agent: str, max_items: int = 8) -> str:
    """
    Return a formatted context block to inject into agent system prompts.
    Returns empty string if no learnings exist.
    """
    learnings = get_learnings(agent=agent, days=60)
    if not learnings:
        return ""
    # Most recent first, deduplicate similar content
    seen_content = set()
    recent = []
    for l in sorted(learnings, key=lambda x: x.get("timestamp", ""), reverse=True):
        content = l.get("content", "").strip()
        # Simple dedup: skip if very similar to something already included
        key = content[:60].lower()
        if key not in seen_content:
            seen_content.add(key)
            recent.append(l)
        if len(recent) >= max_items:
            break

    lines = ["[Learned from past interactions with this user:]"]
    for l in recent:
        cat = l.get("category", "note")
        content = l.get("content", "")
        lines.append(f"- [{cat}] {content}")
    return "\n".join(lines)


def detect_and_save_preference(message: str, agent: str) -> str | None:
    """
    Detect if a message expresses a preference or correction, save it, and return
    the content string. Returns None if no preference detected.
    """
    msg_lower = message.lower().strip()

    # Explicit preference patterns
    preference_triggers = [
        ("i don't like", "dislikes: "),
        ("i dont like", "dislikes: "),
        ("i hate", "dislikes: "),
        ("i love", "preference: "),
        ("i prefer", "preference: "),
        ("i always", "habit: "),
        ("i usually", "habit: "),
        ("i never", "habit: "),
        ("my favorite", "preference: "),
        ("i'm allergic", "dietary restriction: "),
        ("i am allergic", "dietary restriction: "),
        ("i'm vegan", "dietary restriction: is vegan"),
        ("i'm vegetarian", "dietary restriction: is vegetarian"),
        ("i'm lactose", "dietary restriction: lactose intolerant"),
    ]

    for trigger, prefix in preference_triggers:
        if trigger in msg_lower:
            content = prefix + message.strip()
            add_learning(agent, "preference", content, source=message)
            return content

    return None
