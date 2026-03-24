"""
Tests for core/command_router.py
"""

import json
from unittest.mock import patch


# ── classify() ────────────────────────────────────────────────────────────────

class TestClassify:
    def test_returns_dict_with_intent(self):
        result = {"intent": "log_health", "details": "weight 175", "params": {"metric": "weight", "value": "175"}}
        with patch("core.command_router.chat", return_value=json.dumps(result)):
            from core.command_router import classify
            out = classify("weight 175")
        assert out["intent"] == "log_health"
        assert out["details"] == "weight 175"

    def test_strips_markdown_code_fence(self):
        payload = {"intent": "schedule_meeting", "details": "lunch Thursday", "params": {}}
        wrapped = f"```json\n{json.dumps(payload)}\n```"
        with patch("core.command_router.chat", return_value=wrapped):
            from core.command_router import classify
            out = classify("schedule lunch Thursday")
        assert out["intent"] == "schedule_meeting"

    def test_strips_code_fence_without_json_label(self):
        payload = {"intent": "draft_email", "details": "email to boss", "params": {}}
        wrapped = f"```\n{json.dumps(payload)}\n```"
        with patch("core.command_router.chat", return_value=wrapped):
            from core.command_router import classify
            out = classify("draft email to boss")
        assert out["intent"] == "draft_email"

    def test_falls_back_on_invalid_json(self):
        with patch("core.command_router.chat", return_value="not valid json at all"):
            from core.command_router import classify
            out = classify("some message")
        assert out["intent"] == "general_question"
        assert out["details"] == "some message"
        assert out["params"] == {}

    def test_falls_back_on_empty_response(self):
        with patch("core.command_router.chat", return_value=""):
            from core.command_router import classify
            out = classify("hello")
        assert out["intent"] == "general_question"

    def test_all_expected_intents_are_valid(self):
        """Router prompt lists 15 intent types — verify they are accepted as-is."""
        intents = [
            "schedule_meeting", "draft_email", "create_task", "log_health",
            "infusion_consulting", "mortgage_notes", "investment_research",
            "travel_hack", "nyc_events", "personal_finance", "bonus_alert",
            "market_intel", "daily_briefing", "follow_up", "general_question",
        ]
        for intent in intents:
            payload = {"intent": intent, "details": "test", "params": {}}
            with patch("core.command_router.chat", return_value=json.dumps(payload)):
                from core.command_router import classify
                out = classify("test")
            assert out["intent"] == intent

    def test_passes_message_to_chat(self):
        payload = {"intent": "general_question", "details": "hi", "params": {}}
        with patch("core.command_router.chat", return_value=json.dumps(payload)) as mock_chat:
            from core.command_router import classify
            classify("hello world")
        # Second argument to chat() is the user message
        assert mock_chat.call_args[0][1] == "hello world"

    def test_whitespace_stripped_before_parse(self):
        payload = {"intent": "log_health", "details": "slept 8h", "params": {}}
        with patch("core.command_router.chat", return_value=f"  {json.dumps(payload)}  "):
            from core.command_router import classify
            out = classify("slept 8h")
        assert out["intent"] == "log_health"
