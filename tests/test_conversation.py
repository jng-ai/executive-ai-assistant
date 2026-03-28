"""
Tests for core/conversation.py — rolling buffer, LLM history formatting,
and integration with command_router classify().
"""

import json
import pytest
from pathlib import Path
from unittest.mock import patch, MagicMock


# ── Helpers ───────────────────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def isolated_conv(tmp_path, monkeypatch):
    """Redirect conversation file to tmp_path for every test."""
    import core.conversation as c
    monkeypatch.setattr(c, "_CONV_FILE", tmp_path / "conversation.json")
    c.clear()          # start clean
    yield
    c.clear()


# ── add_turn / get_recent ─────────────────────────────────────────────────────

class TestAddAndRetrieve:
    def test_add_single_turn(self):
        from core.conversation import add_turn, get_recent
        add_turn("hello", "hi there", agent="general")
        turns = get_recent(10)
        assert len(turns) == 1
        assert turns[0]["user"] == "hello"
        assert turns[0]["assistant"] == "hi there"
        assert turns[0]["agent"] == "general"

    def test_get_recent_respects_n(self):
        from core.conversation import add_turn, get_recent
        for i in range(5):
            add_turn(f"msg {i}", f"reply {i}")
        assert len(get_recent(3)) == 3
        assert len(get_recent(1)) == 1

    def test_rolling_buffer_caps_at_max_turns(self):
        """Adding more than _MAX_TURNS entries should drop the oldest."""
        import core.conversation as c
        from core.conversation import add_turn, get_recent
        c._MAX_TURNS = 3
        for i in range(5):
            add_turn(f"msg {i}", f"reply {i}")
        turns = get_recent(10)
        assert len(turns) == 3
        # Most recent should be the last 3 messages
        assert turns[-1]["user"] == "msg 4"
        assert turns[0]["user"] == "msg 2"

    def test_empty_history_returns_empty_list(self):
        from core.conversation import get_recent
        assert get_recent(5) == []

    def test_long_messages_are_truncated(self):
        """Very long messages should be stored truncated to avoid bloat."""
        from core.conversation import add_turn, get_recent
        long_user = "a" * 2000
        long_reply = "b" * 2000
        add_turn(long_user, long_reply)
        turn = get_recent(1)[0]
        assert len(turn["user"]) <= 1000
        assert len(turn["assistant"]) <= 800


# ── format_context ────────────────────────────────────────────────────────────

class TestFormatContext:
    def test_empty_returns_empty_string(self):
        from core.conversation import format_context
        assert format_context() == ""

    def test_single_turn_formatted(self):
        from core.conversation import add_turn, format_context
        add_turn("what's on my calendar today?", "You have 3 meetings.")
        ctx = format_context(n=1)
        assert "User:" in ctx
        assert "what's on my calendar today?" in ctx
        assert "Assistant:" in ctx
        assert "3 meetings" in ctx

    def test_respects_n_param(self):
        from core.conversation import add_turn, format_context
        add_turn("first", "first reply")
        add_turn("second", "second reply")
        add_turn("third", "third reply")
        ctx = format_context(n=2)
        assert "second" in ctx
        assert "third" in ctx
        assert "first" not in ctx

    def test_assistant_content_is_truncated_in_context(self):
        """Long assistant replies should be clipped in the context string."""
        from core.conversation import add_turn, format_context
        add_turn("question", "x" * 1000)
        ctx = format_context(n=1)
        # The context text for assistant should be capped
        assert len(ctx) < 1200  # not the full 1000-char response


# ── get_history_for_llm ───────────────────────────────────────────────────────

class TestGetHistoryForLlm:
    def test_empty_returns_empty_list(self):
        from core.conversation import get_history_for_llm
        assert get_history_for_llm() == []

    def test_single_turn_produces_two_messages(self):
        from core.conversation import add_turn, get_history_for_llm
        add_turn("user msg", "assistant msg")
        history = get_history_for_llm(n=1)
        assert len(history) == 2
        assert history[0] == {"role": "user", "content": "user msg"}
        assert history[1] == {"role": "assistant", "content": "assistant msg"}

    def test_two_turns_produce_four_messages(self):
        from core.conversation import add_turn, get_history_for_llm
        add_turn("turn 1 user", "turn 1 assistant")
        add_turn("turn 2 user", "turn 2 assistant")
        history = get_history_for_llm(n=2)
        assert len(history) == 4
        assert history[0]["role"] == "user"
        assert history[1]["role"] == "assistant"
        assert history[2]["role"] == "user"
        assert history[3]["role"] == "assistant"

    def test_alternating_roles(self):
        """Roles must strictly alternate user→assistant→user→assistant."""
        from core.conversation import add_turn, get_history_for_llm
        for i in range(3):
            add_turn(f"user {i}", f"asst {i}")
        history = get_history_for_llm(n=3)
        roles = [m["role"] for m in history]
        assert roles == ["user", "assistant"] * 3


# ── clear ──────────────────────────────────────────────────────────────────────

class TestClear:
    def test_clear_empties_history(self):
        from core.conversation import add_turn, clear, get_recent
        add_turn("hello", "hi")
        clear()
        assert get_recent(10) == []


# ── llm.chat history integration ─────────────────────────────────────────────

class TestLlmChatHistory:
    def test_history_injected_into_messages(self):
        """chat() should include history turns between system and current user msg."""
        with patch("core.llm.get_client") as mock_client, \
             patch("core.llm.os.environ.get", return_value="groq"):
            mock_resp = MagicMock()
            mock_resp.choices[0].message.content = "answer"
            mock_client.return_value.chat.completions.create.return_value = mock_resp

            from core.llm import chat
            history = [
                {"role": "user", "content": "prior question"},
                {"role": "assistant", "content": "prior answer"},
            ]
            chat("system prompt", "current question", history=history)

            call_args = mock_client.return_value.chat.completions.create.call_args
            messages = call_args.kwargs["messages"]
            assert messages[0]["role"] == "system"
            assert messages[1]["role"] == "user"
            assert messages[1]["content"] == "prior question"
            assert messages[2]["role"] == "assistant"
            assert messages[3]["role"] == "user"
            assert messages[3]["content"] == "current question"

    def test_no_history_works_as_before(self):
        """chat() without history should behave exactly as before."""
        with patch("core.llm.get_client") as mock_client, \
             patch("core.llm.os.environ.get", return_value="groq"):
            mock_resp = MagicMock()
            mock_resp.choices[0].message.content = "answer"
            mock_client.return_value.chat.completions.create.return_value = mock_resp

            from core.llm import chat
            chat("system", "question")

            messages = mock_client.return_value.chat.completions.create.call_args.kwargs["messages"]
            assert len(messages) == 2
            assert messages[0]["role"] == "system"
            assert messages[1]["role"] == "user"


# ── command_router classify with context ─────────────────────────────────────

class TestClassifyWithContext:
    def test_classify_passes_context_to_llm(self):
        """When context is provided, it should be included in the LLM prompt."""
        with patch("core.command_router.chat") as mock_chat:
            mock_chat.return_value = '{"intent": "schedule_meeting", "details": "that", "params": {}}'
            from core.command_router import classify
            classify("reschedule that", context="User: add meeting\nAssistant: Created meeting")
            call_user_content = mock_chat.call_args[0][1]
            assert "Recent conversation" in call_user_content
            assert "reschedule that" in call_user_content

    def test_classify_without_context_sends_raw_message(self):
        """Without context, the raw message is sent directly."""
        with patch("core.command_router.chat") as mock_chat:
            mock_chat.return_value = '{"intent": "general_question", "details": "hello", "params": {}}'
            from core.command_router import classify
            classify("hello")
            call_user_content = mock_chat.call_args[0][1]
            assert call_user_content == "hello"

    def test_classify_still_returns_valid_intent(self):
        """Context injection should not break the JSON parsing logic."""
        with patch("core.command_router.chat") as mock_chat:
            mock_chat.return_value = '{"intent": "draft_email", "details": "reply to that", "params": {}}'
            from core.command_router import classify
            result = classify("reply to that", context="User: show emails\nAssistant: Here are 3 emails")
            assert result["intent"] == "draft_email"
