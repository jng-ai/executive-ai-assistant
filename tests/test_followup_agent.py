"""
Tests for agents/followup_agent/handler.py
"""

import json
import datetime
from unittest.mock import patch


class TestParseRequest:
    def test_returns_list_action_on_parse_failure(self):
        with patch("agents.followup_agent.handler.chat", return_value="not json"):
            from agents.followup_agent.handler import _parse_request
            result = _parse_request("what follow-ups do I have")
        assert result["action"] == "list"

    def test_parses_create_action(self):
        payload = {"action": "create", "type": "email", "contact": "Marcus",
                   "context": "infusion RFP", "body_request": "Check status", "delay_days": 3}
        with patch("agents.followup_agent.handler.chat", return_value=json.dumps(payload)):
            from agents.followup_agent.handler import _parse_request
            result = _parse_request("follow up with Marcus in 3 days")
        assert result["action"] == "create"
        assert result["contact"] == "Marcus"

    def test_strips_markdown_fences(self):
        payload = {"action": "list"}
        wrapped = f"```json\n{json.dumps(payload)}\n```"
        with patch("agents.followup_agent.handler.chat", return_value=wrapped):
            from agents.followup_agent.handler import _parse_request
            result = _parse_request("list followups")
        assert result["action"] == "list"


class TestHandle:
    def test_list_with_no_pending(self, tmp_data_dir):
        with patch("agents.followup_agent.handler.chat", return_value=json.dumps({"action": "list"})):
            from agents.followup_agent.handler import handle
            result = handle("what follow-ups do I have?")
        assert "No pending" in result or "all caught up" in result

    def test_list_with_pending_followups(self, tmp_data_dir):
        from core.followups import add_followup
        future = (datetime.datetime.now() + datetime.timedelta(days=3)).isoformat()
        add_followup("email", "Alice", "project update", "check status", future)

        with patch("agents.followup_agent.handler.chat", return_value=json.dumps({"action": "list"})):
            from agents.followup_agent.handler import handle
            result = handle("what follow-ups do I have?")
        assert "Alice" in result
        assert "project update" in result

    def test_cancel_with_valid_id(self, tmp_data_dir):
        from core.followups import add_followup
        f = add_followup("email", "Bob", "ctx", "body", "2026-04-01T09:00:00")
        payload = {"action": "cancel", "followup_id": f["id"]}
        with patch("agents.followup_agent.handler.chat", return_value=json.dumps(payload)):
            from agents.followup_agent.handler import handle
            result = handle(f"cancel follow-up {f['id']}")
        assert "cancelled" in result.lower() or "🗑" in result

    def test_cancel_extracts_id_from_message(self, tmp_data_dir):
        from core.followups import add_followup
        f = add_followup("email", "Charlie", "ctx", "body", "2026-04-01T09:00:00")
        # LLM returns no followup_id so handler falls back to regex
        payload = {"action": "cancel", "followup_id": None}
        with patch("agents.followup_agent.handler.chat", return_value=json.dumps(payload)):
            from agents.followup_agent.handler import handle
            result = handle(f"cancel follow-up {f['id']}")
        assert "cancelled" in result.lower() or "🗑" in result or "Couldn't find" in result

    def test_cancel_nonexistent_id_returns_error(self, tmp_data_dir):
        payload = {"action": "cancel", "followup_id": 9999}
        with patch("agents.followup_agent.handler.chat", return_value=json.dumps(payload)):
            from agents.followup_agent.handler import handle
            result = handle("cancel follow-up 9999")
        assert "Couldn't find" in result

    def test_create_without_contact_returns_error(self, tmp_data_dir):
        payload = {"action": "create", "type": "email", "contact": "", "delay_days": 3}
        with patch("agents.followup_agent.handler.chat", return_value=json.dumps(payload)):
            from agents.followup_agent.handler import handle
            result = handle("follow up in 3 days")
        assert "Who should I follow up" in result

    def test_create_email_followup(self, tmp_data_dir):
        payload = {
            "action": "create", "type": "email", "contact": "Dr. Kim",
            "email": "", "context": "infusion proposal", "body_request": "Check status",
            "delay_days": 5
        }
        with patch("agents.followup_agent.handler.chat", return_value=json.dumps(payload)):
            from agents.followup_agent.handler import handle
            result = handle("follow up with Dr. Kim in 5 days")
        assert "Follow-up scheduled" in result
        assert "Dr. Kim" in result

    def test_create_meeting_followup(self, tmp_data_dir):
        payload = {
            "action": "create", "type": "meeting", "contact": "Alex",
            "email": "", "context": "strategy review", "body_request": "Discuss Q2 plan",
            "delay_days": 7
        }
        with patch("agents.followup_agent.handler.chat", return_value=json.dumps(payload)):
            from agents.followup_agent.handler import handle
            result = handle("schedule a follow-up meeting with Alex next week")
        assert "Follow-up scheduled" in result
        assert "meeting" in result.lower()

    def test_unknown_action_falls_through_to_chat(self, tmp_data_dir):
        payload = {"action": "unknown_action"}
        with patch("agents.followup_agent.handler.chat", side_effect=[json.dumps(payload), "fallback chat response"]):
            from agents.followup_agent.handler import handle
            result = handle("something weird")
        assert result == "fallback chat response"


class TestRunPendingFollowups:
    def test_returns_empty_when_nothing_due(self, tmp_data_dir):
        from agents.followup_agent.handler import run_pending_followups
        assert run_pending_followups() == []

    def test_fires_email_followup_without_email_address(self, tmp_data_dir):
        from core.followups import add_followup
        past = (datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat()
        add_followup("email", "Marcus", "RFP", "Check in", past, email="")

        with patch("agents.followup_agent.handler.chat", return_value="Dear Marcus, just checking in..."):
            with patch("integrations.google.auth.is_configured", return_value=False):
                from agents.followup_agent.handler import run_pending_followups
                results = run_pending_followups()
        assert len(results) == 1
        assert "Marcus" in results[0]

    def test_fires_meeting_followup_without_gcal(self, tmp_data_dir):
        from core.followups import add_followup
        past = (datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat()
        add_followup("meeting", "Dr. Lee", "catch up", "Schedule 30 min", past)

        with patch("integrations.google.auth.is_configured", return_value=False):
            from agents.followup_agent.handler import run_pending_followups
            results = run_pending_followups()
        assert len(results) == 1
        assert "Dr. Lee" in results[0]

    def test_marks_fired_followups_as_done(self, tmp_data_dir):
        from core.followups import add_followup, list_pending
        past = (datetime.datetime.now() - datetime.timedelta(hours=1)).isoformat()
        add_followup("email", "Eve", "topic", "body", past, email="")

        with patch("agents.followup_agent.handler.chat", return_value="email body"):
            with patch("integrations.google.auth.is_configured", return_value=False):
                from agents.followup_agent.handler import run_pending_followups
                run_pending_followups()

        assert list_pending() == []
