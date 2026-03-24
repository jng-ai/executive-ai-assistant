"""
Shared fixtures for the executive-ai-assistant test suite.

Conventions:
- mock_chat: patches core.llm.chat → returns a configurable string
- tmp_data_dir: redirects DATA_DIR to a temp directory so tests never touch real data files
- env_groq / env_anthropic / env_ollama: set LLM_PROVIDER env var
"""

import json
import os
import pytest
from pathlib import Path
from unittest.mock import MagicMock, patch


# ── LLM mock ──────────────────────────────────────────────────────────────────

@pytest.fixture
def mock_chat():
    """Patch core.llm.chat to return a fixed string. Yields the mock so tests can
    customise return_value or side_effect per-test."""
    with patch("core.llm.chat", return_value="mocked response") as m:
        yield m


# ── Tmp data directory ────────────────────────────────────────────────────────

@pytest.fixture
def tmp_data_dir(tmp_path, monkeypatch):
    """
    Redirect every DATA_DIR reference to a fresh tmp_path so no test
    touches data/ on disk.  Patches core.memory and core.followups.
    """
    import core.memory as mem
    import core.followups as fu

    monkeypatch.setattr(mem, "DATA_DIR", tmp_path)
    monkeypatch.setattr(mem, "TASKS_FILE", tmp_path / "tasks.json")
    monkeypatch.setattr(mem, "HEALTH_FILE", tmp_path / "health.json")
    monkeypatch.setattr(mem, "NOTES_FILE", tmp_path / "notes.json")

    monkeypatch.setattr(fu, "DATA_DIR", tmp_path)
    monkeypatch.setattr(fu, "FOLLOWUPS_FILE", tmp_path / "followups.json")

    return tmp_path


# ── Env helpers ───────────────────────────────────────────────────────────────

@pytest.fixture
def env_groq(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "groq")
    monkeypatch.setenv("GROQ_API_KEY", "test-groq-key")


@pytest.fixture
def env_ollama(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "ollama")
    monkeypatch.delenv("GROQ_API_KEY", raising=False)


@pytest.fixture
def env_anthropic(monkeypatch):
    monkeypatch.setenv("LLM_PROVIDER", "anthropic")
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-anthropic-key")


# ── Google env helpers ────────────────────────────────────────────────────────

@pytest.fixture
def google_env(monkeypatch):
    monkeypatch.setenv("GOOGLE_CLIENT_ID", "test-client-id")
    monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "test-client-secret")
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "test-refresh-token")


@pytest.fixture
def google_env_secondary(monkeypatch, google_env):
    monkeypatch.setenv("GOOGLE_REFRESH_TOKEN_JNGAI53", "test-refresh-token-secondary")


# ── Notion helpers ────────────────────────────────────────────────────────────

@pytest.fixture
def notion_not_configured(monkeypatch):
    """Ensure Notion is disabled during the test."""
    monkeypatch.delenv("NOTION_API_KEY", raising=False)
