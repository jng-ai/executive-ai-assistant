"""
Tests for core/llm.py
"""

import pytest
from unittest.mock import MagicMock, patch


class TestGetClient:
    def test_groq_returns_openai_client(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "groq")
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        from core.llm import get_client
        client = get_client()
        assert client is not None
        # Should have a base_url pointing at Groq
        assert "groq" in str(client.base_url).lower()

    def test_ollama_returns_openai_client(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "ollama")
        from core.llm import get_client
        client = get_client()
        assert client is not None
        assert "11434" in str(client.base_url)

    def test_ollama_custom_base_url(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "ollama")
        monkeypatch.setenv("OLLAMA_BASE_URL", "http://myserver:9999/v1")
        from core.llm import get_client
        client = get_client()
        assert "9999" in str(client.base_url)

    def test_anthropic_returns_none(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        from core.llm import get_client
        assert get_client() is None

    def test_unknown_provider_raises(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "unknown_provider")
        from core.llm import get_client
        with pytest.raises(ValueError, match="Unknown LLM_PROVIDER"):
            get_client()

    def test_defaults_to_groq_when_env_missing(self, monkeypatch):
        monkeypatch.delenv("LLM_PROVIDER", raising=False)
        monkeypatch.setenv("GROQ_API_KEY", "test-key")
        from core.llm import get_client
        client = get_client()
        assert "groq" in str(client.base_url).lower()


class TestGetModel:
    def test_groq_default_model(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "groq")
        monkeypatch.delenv("LLM_MODEL", raising=False)
        from core.llm import get_model
        assert get_model() == "llama-3.3-70b-versatile"

    def test_ollama_default_model(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "ollama")
        monkeypatch.delenv("LLM_MODEL", raising=False)
        from core.llm import get_model
        assert get_model() == "llama3.2"

    def test_anthropic_default_model(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        monkeypatch.delenv("LLM_MODEL", raising=False)
        from core.llm import get_model
        assert get_model() == "claude-sonnet-4-6"

    def test_override_via_env(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "groq")
        monkeypatch.setenv("LLM_MODEL", "llama-3.1-8b-instant")
        from core.llm import get_model
        assert get_model() == "llama-3.1-8b-instant"

    def test_unknown_provider_falls_back(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "future_provider")
        monkeypatch.delenv("LLM_MODEL", raising=False)
        from core.llm import get_model
        # Falls through dict.get → default string
        assert get_model() == "llama-3.3-70b-versatile"


class TestChat:
    def test_groq_chat_calls_completions(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "groq")
        monkeypatch.setenv("GROQ_API_KEY", "test-key")

        fake_resp = MagicMock()
        fake_resp.choices[0].message.content = "Hello from Groq"

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = fake_resp

        with patch("core.llm.get_client", return_value=mock_client):
            from core.llm import chat
            result = chat("system prompt", "user message")

        assert result == "Hello from Groq"
        mock_client.chat.completions.create.assert_called_once()

    def test_groq_passes_correct_messages(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "groq")
        monkeypatch.setenv("GROQ_API_KEY", "test-key")

        fake_resp = MagicMock()
        fake_resp.choices[0].message.content = "response"

        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = fake_resp

        with patch("core.llm.get_client", return_value=mock_client):
            from core.llm import chat
            chat("my system", "my user", max_tokens=123)

        call_kwargs = mock_client.chat.completions.create.call_args[1]
        messages = call_kwargs["messages"]
        assert messages[0] == {"role": "system", "content": "my system"}
        assert messages[1] == {"role": "user", "content": "my user"}
        assert call_kwargs["max_tokens"] == 123

    def test_anthropic_chat_uses_anthropic_sdk(self, monkeypatch):
        monkeypatch.setenv("LLM_PROVIDER", "anthropic")
        monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key")

        fake_resp = MagicMock()
        fake_resp.content[0].text = "Hello from Anthropic"

        mock_anthropic_module = MagicMock()
        mock_anthropic_module.Anthropic.return_value.messages.create.return_value = fake_resp

        with patch.dict("sys.modules", {"anthropic": mock_anthropic_module}):
            with patch("core.llm.get_model", return_value="claude-sonnet-4-6"):
                from core.llm import chat
                result = chat("sys", "user")

        assert result == "Hello from Anthropic"
