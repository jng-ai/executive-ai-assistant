"""
LLM wrapper — swap providers via .env without touching agent code.

Supported providers:
  groq    → free tier, cloud, fast (recommended)
  ollama  → free, local (requires ollama running on your Mac)
  anthropic → paid, most capable

Set in .env:
  LLM_PROVIDER=groq
  LLM_MODEL=llama-3.1-70b-versatile
"""

import logging
import os
from openai import OpenAI

logger = logging.getLogger(__name__)


def get_client():
    provider = os.environ.get("LLM_PROVIDER", "groq").lower()

    if provider == "groq":
        return OpenAI(
            api_key=os.environ.get("GROQ_API_KEY", ""),
            base_url="https://api.groq.com/openai/v1",
        )
    elif provider == "ollama":
        return OpenAI(
            api_key="ollama",  # Ollama doesn't need a real key
            base_url=os.environ.get("OLLAMA_BASE_URL", "http://localhost:11434/v1"),
        )
    elif provider == "anthropic":
        # Falls back to anthropic SDK in each handler
        return None
    else:
        raise ValueError(f"Unknown LLM_PROVIDER: {provider}")


def get_model() -> str:
    provider = os.environ.get("LLM_PROVIDER", "groq").lower()
    default_models = {
        "groq": "llama-3.3-70b-versatile",
        "ollama": "llama3.2",
        "anthropic": "claude-sonnet-4-6",
    }
    return os.environ.get("LLM_MODEL", default_models.get(provider, "llama-3.3-70b-versatile"))


def chat(system: str, user: str, max_tokens: int = 800,
         history: list[dict] | None = None) -> str:
    """
    Chat with optional multi-turn history.

    Args:
        system:    System prompt.
        user:      Current user message.
        max_tokens: Response length cap.
        history:   Optional prior turns as OpenAI-style message dicts,
                   e.g. [{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...]
                   Obtained from core.conversation.get_history_for_llm().
    """
    provider = os.environ.get("LLM_PROVIDER", "groq").lower()

    # Build the messages list: system → prior turns → current user message
    prior = history or []
    current = {"role": "user", "content": user}

    if provider == "anthropic":
        from anthropic import Anthropic
        client = Anthropic(api_key=os.environ["ANTHROPIC_API_KEY"])
        resp = client.messages.create(
            model=get_model(),
            max_tokens=max_tokens,
            system=system,
            messages=[*prior, current],
        )
        return resp.content[0].text

    client = get_client()
    resp = client.chat.completions.create(
        model=get_model(),
        max_tokens=max_tokens,
        messages=[
            {"role": "system", "content": system},
            *prior,
            current,
        ],
    )
    return resp.choices[0].message.content
