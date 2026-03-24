"""
Tests for agents/general_handler.py
"""

from unittest.mock import patch


class TestHandleGeneral:
    def test_returns_string(self):
        with patch("agents.general_handler.chat", return_value="The capital of France is Paris."):
            from agents.general_handler import handle_general
            result = handle_general("What is the capital of France?")
        assert result == "The capital of France is Paris."

    def test_passes_message_to_chat(self):
        with patch("agents.general_handler.chat", return_value="answer") as mock_chat:
            from agents.general_handler import handle_general
            handle_general("my question here")
        # user message is second arg
        assert mock_chat.call_args[0][1] == "my question here"

    def test_max_tokens_is_500(self):
        with patch("agents.general_handler.chat", return_value="ok") as mock_chat:
            from agents.general_handler import handle_general
            handle_general("test")
        assert mock_chat.call_args[1].get("max_tokens") == 500 or \
               mock_chat.call_args[0][2] == 500

    def test_system_prompt_has_no_personal_info(self):
        """Privacy design: no personal details in SYSTEM prompt."""
        from agents.general_handler import SYSTEM
        # These personal identifiers must NOT appear in the generic system prompt
        for personal_term in ["Justin", "Ngai", "infusion", "165 lbs", "jynpriority"]:
            assert personal_term not in SYSTEM
