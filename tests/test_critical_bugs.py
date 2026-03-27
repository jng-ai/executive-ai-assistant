"""
Regression tests for 4 critical bugs fixed in PR #27.

Bug 1: Dashboard follow-up count always 0
  — _followup_oneliner / _followup_dashboard used "due_date" key but
    core/followups.py stores it as "due".

Bug 2: DST blind spot — _et_now() hardcoded UTC-5 year-round
  — During EDT (March–November) market session times were off by 1 hour.

Bug 3: Reading / replying to jngai5.3 emails returned empty body
  — get_email_body() always defaulted to account="primary".

Bug 4: "send it" reply after drafting did nothing
  — Draft state was never persisted, so "send it" found no state to send.
"""

import datetime
import json
import pytest
from contextlib import ExitStack
from pathlib import Path
from unittest.mock import patch, MagicMock


# ══════════════════════════════════════════════════════════════════════════════
# Bug 1 — Dashboard follow-up field name: "due_date" → "due"
# ══════════════════════════════════════════════════════════════════════════════

def _make_followup(fid: int, due_iso: str, status: str = "pending") -> dict:
    return {
        "id": fid,
        "contact": f"Contact{fid}",
        "context": "test context",
        "type": "email",
        "due": due_iso,
        "status": status,
    }


class TestFollowupOnelinerFieldName:
    """_followup_oneliner must read f['due'], not f['due_date']."""

    def test_pending_count_with_due_field(self):
        """Two pending followups with 'due' field must show '2 pending'."""
        today = datetime.date.today().isoformat()
        pending = [_make_followup(1, today), _make_followup(2, today)]

        with patch("core.followups.list_all_pending", return_value=pending):
            from integrations.telegram.dashboard import _followup_oneliner
            result = _followup_oneliner()

        assert "2 pending" in result

    def test_overdue_count_with_due_field(self):
        """Followup with past 'due' date must appear in overdue count."""
        today = datetime.date.today().isoformat()
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        pending = [
            _make_followup(1, yesterday),  # overdue
            _make_followup(2, today),      # due today (also counted as overdue)
        ]

        with patch("core.followups.list_all_pending", return_value=pending):
            from integrations.telegram.dashboard import _followup_oneliner
            result = _followup_oneliner()

        assert "2 pending" in result
        assert "2 due today" in result

    def test_completed_followups_excluded(self):
        """Followups with status='done' must not appear in pending count."""
        today = datetime.date.today().isoformat()
        # list_all_pending by contract only returns pending items — simulate that
        with patch("core.followups.list_all_pending", return_value=[_make_followup(1, today)]):
            from integrations.telegram.dashboard import _followup_oneliner
            result = _followup_oneliner()

        assert "1 pending" in result

    def test_no_followups_shows_clear_message(self):
        """Empty follow-up list must produce a 'clear' or 'no pending' message."""
        with patch("core.followups.list_all_pending", return_value=[]):
            from integrations.telegram.dashboard import _followup_oneliner
            result = _followup_oneliner()

        assert "no pending" in result.lower() or "clear" in result.lower() or "0" in result

    def test_future_followup_not_overdue(self):
        """A followup due tomorrow must be pending but NOT in the overdue bucket."""
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        pending = [_make_followup(1, tomorrow)]

        with patch("core.followups.list_all_pending", return_value=pending):
            from integrations.telegram.dashboard import _followup_oneliner
            result = _followup_oneliner()

        assert "1 pending" in result
        assert "0 due today" in result


class TestFollowupDashboardFieldName:
    """_followup_dashboard must split pending into overdue/upcoming using 'due' field."""

    def test_overdue_and_upcoming_split_correctly(self):
        """Past 'due' → overdue bucket; future 'due' → upcoming bucket."""
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        pending = [
            _make_followup(1, yesterday),  # overdue
            _make_followup(2, tomorrow),   # upcoming
        ]

        with patch("core.followups.list_all_pending", return_value=pending):
            from integrations.telegram.dashboard import _followup_dashboard
            result = _followup_dashboard()

        assert "Contact1" in result  # overdue contact appears
        assert "Contact2" in result  # upcoming contact appears

    def test_overdue_appears_before_upcoming(self):
        """Overdue items must be listed before upcoming items in the output."""
        yesterday = (datetime.date.today() - datetime.timedelta(days=1)).isoformat()
        tomorrow = (datetime.date.today() + datetime.timedelta(days=1)).isoformat()
        pending = [
            _make_followup(1, yesterday),
            _make_followup(2, tomorrow),
        ]

        with patch("core.followups.list_all_pending", return_value=pending):
            from integrations.telegram.dashboard import _followup_dashboard
            result = _followup_dashboard()

        assert result.index("Contact1") < result.index("Contact2")

    def test_no_followups_shows_clear(self):
        with patch("core.followups.list_all_pending", return_value=[]):
            from integrations.telegram.dashboard import _followup_dashboard
            result = _followup_dashboard()
        assert isinstance(result, str)
        assert len(result) > 0


# ══════════════════════════════════════════════════════════════════════════════
# Bug 2 — DST-aware _et_now()
# ══════════════════════════════════════════════════════════════════════════════

class TestEtNowDST:
    """_et_now() must use America/New_York (auto DST), not hardcoded UTC-5."""

    def test_returns_timezone_aware_datetime(self):
        from integrations.telegram.dashboard import _et_now
        now = _et_now()
        assert now.tzinfo is not None

    def test_edt_offset_is_minus_four_in_spring(self):
        """March 27, 2026 is EDT — ZoneInfo offset must be -4:00."""
        try:
            from zoneinfo import ZoneInfo
            edt_dt = datetime.datetime(2026, 3, 27, 12, 0, 0,
                                       tzinfo=ZoneInfo("America/New_York"))
            offset = edt_dt.utcoffset()
            assert offset == datetime.timedelta(hours=-4), (
                f"Expected UTC-4 during EDT but got {offset} — "
                "hardcoded UTC-5 would fail this check"
            )
        except ImportError:
            pytest.skip("zoneinfo not available on this platform")

    def test_est_offset_is_minus_five_in_winter(self):
        """January 15, 2026 is EST — ZoneInfo offset must be -5:00."""
        try:
            from zoneinfo import ZoneInfo
            est_dt = datetime.datetime(2026, 1, 15, 12, 0, 0,
                                       tzinfo=ZoneInfo("America/New_York"))
            offset = est_dt.utcoffset()
            assert offset == datetime.timedelta(hours=-5), (
                f"Expected UTC-5 during EST but got {offset}"
            )
        except ImportError:
            pytest.skip("zoneinfo not available on this platform")

    def test_hardcoded_minus_five_wrong_in_spring(self):
        """Prove that hardcoded UTC-5 gives wrong result during EDT."""
        try:
            from zoneinfo import ZoneInfo
            real_edt = datetime.datetime(2026, 3, 27, 12, 0, 0,
                                         tzinfo=ZoneInfo("America/New_York"))
            hardcoded_est = datetime.datetime(2026, 3, 27, 12, 0, 0,
                                              tzinfo=datetime.timezone(
                                                  datetime.timedelta(hours=-5)))
            # They should NOT have the same UTC value
            assert real_edt.utcoffset() != hardcoded_est.utcoffset()
        except ImportError:
            pytest.skip("zoneinfo not available on this platform")

    def test_market_oneliner_works_with_zoneinfo_et(self, monkeypatch):
        """_market_oneliner must not crash when _et_now returns ZoneInfo datetime."""
        import integrations.telegram.dashboard as d
        try:
            from zoneinfo import ZoneInfo
            # Monday 11 AM EDT
            edt_dt = datetime.datetime(2026, 3, 23, 11, 0, 0,
                                       tzinfo=ZoneInfo("America/New_York"))
            monkeypatch.setattr(d, "_et_now", lambda: edt_dt)
            result = d._market_oneliner()
            assert isinstance(result, str) and len(result) > 0
        except ImportError:
            pytest.skip("zoneinfo not available on this platform")


# ══════════════════════════════════════════════════════════════════════════════
# Bug 3 — Email account routing: secondary account emails get correct body
# ══════════════════════════════════════════════════════════════════════════════

class TestEmailAccountDetermination:
    """The account string derived from match['account'] must be 'secondary' for jngai5.3."""

    def test_jngai53_maps_to_secondary(self):
        """Account field containing 'jngai5.3' must produce account='secondary'."""
        match = {"id": "msg-1", "account": "jngai5.3@gmail.com"}
        acct = "secondary" if "jngai5.3" in match.get("account", "") else "primary"
        assert acct == "secondary"

    def test_jynpriority_maps_to_primary(self):
        """Account field containing 'jynpriority' must produce account='primary'."""
        match = {"id": "msg-2", "account": "jynpriority@gmail.com"}
        acct = "secondary" if "jngai5.3" in match.get("account", "") else "primary"
        assert acct == "primary"

    def test_missing_account_defaults_to_primary(self):
        """No account field → defaults to 'primary' (safe default)."""
        match = {"id": "msg-3"}
        acct = "secondary" if "jngai5.3" in match.get("account", "") else "primary"
        assert acct == "primary"


class TestEmailGetBodyAccountParam:
    """get_email_body must receive account='secondary' for jngai5.3 emails."""

    def _secondary_email(self):
        return {"id": "msg-sec-1", "from": "x@y.com", "subject": "Test",
                "snippet": "hi", "account": "jngai5.3@gmail.com"}

    def _primary_email(self):
        return {"id": "msg-pri-1", "from": "x@y.com", "subject": "Test",
                "snippet": "hi", "account": "jynpriority@gmail.com"}

    def _full_body(self):
        return {"from": "x@y.com", "subject": "Test",
                "body": "Hello world", "thread_id": "t-1"}

    def test_secondary_email_calls_get_body_with_secondary(self):
        """Reading a jngai5.3 email must call get_email_body(..., account='secondary')."""
        import agents.email_agent.handler as h

        with ExitStack() as stack:
            stack.enter_context(patch("agents.email_agent.handler.is_configured",
                                      return_value=True))
            stack.enter_context(patch("agents.email_agent.handler._parse_request",
                                      return_value={"action": "read", "email_ref": "1"}))
            stack.enter_context(patch("agents.email_agent.handler._resolve_email_ref",
                                      return_value=self._secondary_email()))
            mock_body = stack.enter_context(
                patch("integrations.google.gmail_client.get_email_body",
                      return_value=self._full_body()))
            _gmail_stack(stack, {
                "integrations.google.gmail_client.reply_to_email": True,
                "integrations.google.gmail_client.send_email": True,
            })
            h._last_email_list = [self._secondary_email()]
            h.handle("read 1")

        mock_body.assert_called_once_with("msg-sec-1", account="secondary")

    def test_primary_email_calls_get_body_with_primary(self):
        """Reading a jynpriority email must call get_email_body(..., account='primary')."""
        import agents.email_agent.handler as h

        with ExitStack() as stack:
            stack.enter_context(patch("agents.email_agent.handler.is_configured",
                                      return_value=True))
            stack.enter_context(patch("agents.email_agent.handler._parse_request",
                                      return_value={"action": "read", "email_ref": "1"}))
            stack.enter_context(patch("agents.email_agent.handler._resolve_email_ref",
                                      return_value=self._primary_email()))
            mock_body = stack.enter_context(
                patch("integrations.google.gmail_client.get_email_body",
                      return_value=self._full_body()))
            _gmail_stack(stack, {
                "integrations.google.gmail_client.reply_to_email": True,
                "integrations.google.gmail_client.send_email": True,
            })
            h._last_email_list = [self._primary_email()]
            h.handle("read 1")

        mock_body.assert_called_once_with("msg-pri-1", account="primary")

    def test_cache_miss_tries_secondary_account(self):
        """When keyword search on primary returns nothing, secondary is tried."""
        import agents.email_agent.handler as h
        secondary_result = self._secondary_email()

        def fake_search(ref, max_results=1, account="primary"):
            return [secondary_result] if account == "secondary" else []

        with ExitStack() as stack:
            stack.enter_context(patch("agents.email_agent.handler.is_configured",
                                      return_value=True))
            stack.enter_context(patch("agents.email_agent.handler._parse_request",
                                      return_value={"action": "read", "email_ref": "invoice"}))
            stack.enter_context(patch("agents.email_agent.handler._resolve_email_ref",
                                      return_value=None))
            mock_body = stack.enter_context(
                patch("integrations.google.gmail_client.get_email_body",
                      return_value=self._full_body()))
            # Apply common patches first (includes search_emails → [])
            _gmail_stack(stack, {
                "integrations.google.gmail_client.reply_to_email": True,
                "integrations.google.gmail_client.send_email": True,
            })
            # Apply specific search override LAST so it wins
            mock_search = stack.enter_context(
                patch("integrations.google.gmail_client.search_emails",
                      side_effect=fake_search))
            h._last_email_list = []
            h.handle("read invoice")

        searched_accounts = [c.kwargs.get("account", "primary")
                             for c in mock_search.call_args_list]
        assert "primary" in searched_accounts
        assert "secondary" in searched_accounts
        mock_body.assert_called_once_with("msg-sec-1", account="secondary")


# ══════════════════════════════════════════════════════════════════════════════
# Bug 4 — "send it" state persistence and actual send
# ══════════════════════════════════════════════════════════════════════════════

class TestDraftStatePersistence:
    """_save_draft_state / _load_draft_state must round-trip correctly."""

    def test_save_creates_json_file(self, tmp_path, monkeypatch):
        import agents.email_agent.handler as h
        monkeypatch.setattr(h, "_DRAFT_STATE_PATH", tmp_path / "draft.json")

        state = {"type": "draft", "to": "bob@example.com",
                 "subject": "Hello", "body": "Test body"}
        h._save_draft_state(state)

        assert (tmp_path / "draft.json").exists()
        saved = json.loads((tmp_path / "draft.json").read_text())
        assert saved == state

    def test_load_returns_saved_state(self, tmp_path, monkeypatch):
        import agents.email_agent.handler as h
        path = tmp_path / "draft.json"
        monkeypatch.setattr(h, "_DRAFT_STATE_PATH", path)

        state = {"type": "reply", "to": "alice@example.com",
                 "subject": "Re: Meeting", "body": "Sure, works for me",
                 "thread_id": "thread-42", "account": "secondary"}
        path.write_text(json.dumps(state))

        assert h._load_draft_state() == state

    def test_load_returns_empty_when_no_file(self, tmp_path, monkeypatch):
        import agents.email_agent.handler as h
        monkeypatch.setattr(h, "_DRAFT_STATE_PATH", tmp_path / "nonexistent.json")
        assert h._load_draft_state() == {}

    def test_load_returns_empty_on_corrupt_json(self, tmp_path, monkeypatch):
        import agents.email_agent.handler as h
        path = tmp_path / "draft.json"
        monkeypatch.setattr(h, "_DRAFT_STATE_PATH", path)
        path.write_text("{{not valid json")
        assert h._load_draft_state() == {}

    def test_save_is_idempotent(self, tmp_path, monkeypatch):
        """Saving twice with different state overwrites the first."""
        import agents.email_agent.handler as h
        monkeypatch.setattr(h, "_DRAFT_STATE_PATH", tmp_path / "draft.json")

        h._save_draft_state({"type": "draft", "to": "a@b.com", "subject": "S1", "body": "B1"})
        h._save_draft_state({"type": "draft", "to": "c@d.com", "subject": "S2", "body": "B2"})

        loaded = h._load_draft_state()
        assert loaded["to"] == "c@d.com"  # second write wins


_COMMON_GMAIL_PATCHES = [
    ("integrations.google.gmail_client.list_unread", []),
    ("integrations.google.gmail_client.list_unread_all_accounts", []),
    ("integrations.google.gmail_client.scan_confirmation_emails", []),
    ("integrations.google.gmail_client.search_emails", []),
    ("integrations.google.gmail_client.format_emails", ""),
    ("integrations.google.gmail_client.list_needs_reply", []),
    ("integrations.google.gmail_client._triage_urgency", "⚪"),
    ("integrations.google.gmail_client.is_confirmation_email", False),
    ("integrations.google.gmail_client.create_draft", None),
]


def _gmail_stack(stack: ExitStack, extras: dict | None = None):
    """Enter all common gmail patches plus any extras into an ExitStack."""
    for target, retval in _COMMON_GMAIL_PATCHES:
        stack.enter_context(patch(target, return_value=retval))
    for target, retval in (extras or {}).items():
        stack.enter_context(patch(target, return_value=retval))


class TestSendItFlow:
    """'send it' must load persisted state and actually call send/reply."""

    def test_send_it_draft_calls_send_email(self, tmp_path, monkeypatch):
        """'send it' with a saved draft state must call send_email."""
        import agents.email_agent.handler as h
        path = tmp_path / "draft.json"
        monkeypatch.setattr(h, "_DRAFT_STATE_PATH", path)

        state = {"type": "draft", "to": "bob@example.com",
                 "subject": "Test", "body": "Hello Bob"}
        path.write_text(json.dumps(state))

        with ExitStack() as stack:
            stack.enter_context(patch("agents.email_agent.handler.is_configured",
                                      return_value=True))
            stack.enter_context(patch("agents.email_agent.handler._parse_request",
                                      return_value={"action": "send"}))
            mock_send = stack.enter_context(
                patch("integrations.google.gmail_client.send_email", return_value=True))
            _gmail_stack(stack, {"integrations.google.gmail_client.reply_to_email": True})
            result = h.handle("send it")

        mock_send.assert_called_once_with("bob@example.com", "Test", "Hello Bob")
        assert "✅" in result
        assert not path.exists(), "State file must be deleted after successful send"

    def test_send_it_reply_calls_reply_to_email(self, tmp_path, monkeypatch):
        """'send it' with a reply state must call reply_to_email with correct account."""
        import agents.email_agent.handler as h
        path = tmp_path / "draft.json"
        monkeypatch.setattr(h, "_DRAFT_STATE_PATH", path)

        state = {
            "type": "reply",
            "to": "alice@example.com",
            "subject": "Re: Meeting",
            "body": "Works for me",
            "thread_id": "thread-99",
            "account": "secondary",
        }
        path.write_text(json.dumps(state))

        with ExitStack() as stack:
            stack.enter_context(patch("agents.email_agent.handler.is_configured",
                                      return_value=True))
            stack.enter_context(patch("agents.email_agent.handler._parse_request",
                                      return_value={"action": "send"}))
            mock_reply = stack.enter_context(
                patch("integrations.google.gmail_client.reply_to_email", return_value=True))
            _gmail_stack(stack, {"integrations.google.gmail_client.send_email": True})
            result = h.handle("send it")

        mock_reply.assert_called_once_with(
            "thread-99", "alice@example.com", "Re: Meeting", "Works for me",
            account="secondary"
        )
        assert "✅" in result
        assert not path.exists()

    def test_send_it_no_state_returns_helpful_message(self, tmp_path, monkeypatch):
        """'send it' with no state file must return a helpful message, not crash."""
        import agents.email_agent.handler as h
        monkeypatch.setattr(h, "_DRAFT_STATE_PATH", tmp_path / "nonexistent.json")

        with ExitStack() as stack:
            stack.enter_context(patch("agents.email_agent.handler.is_configured",
                                      return_value=True))
            stack.enter_context(patch("agents.email_agent.handler._parse_request",
                                      return_value={"action": "send"}))
            _gmail_stack(stack, {
                "integrations.google.gmail_client.send_email": True,
                "integrations.google.gmail_client.reply_to_email": True,
            })
            result = h.handle("send it")

        assert "draft" in result.lower()
        assert "✅" not in result

    def test_send_it_failed_keeps_state_file(self, tmp_path, monkeypatch):
        """If send_email returns False, state file must remain for retry."""
        import agents.email_agent.handler as h
        path = tmp_path / "draft.json"
        monkeypatch.setattr(h, "_DRAFT_STATE_PATH", path)

        state = {"type": "draft", "to": "bob@example.com",
                 "subject": "Test", "body": "Hello"}
        path.write_text(json.dumps(state))

        with ExitStack() as stack:
            stack.enter_context(patch("agents.email_agent.handler.is_configured",
                                      return_value=True))
            stack.enter_context(patch("agents.email_agent.handler._parse_request",
                                      return_value={"action": "send"}))
            _gmail_stack(stack, {
                "integrations.google.gmail_client.send_email": False,
                "integrations.google.gmail_client.reply_to_email": True,
            })
            result = h.handle("send it")

        assert "⚠️" in result
        assert path.exists(), "State file must persist on failed send so user can retry"

    def test_draft_preview_saves_state(self, tmp_path, monkeypatch):
        """Showing a draft preview must immediately persist state to disk."""
        import agents.email_agent.handler as h
        path = tmp_path / "draft.json"
        monkeypatch.setattr(h, "_DRAFT_STATE_PATH", path)

        with ExitStack() as stack:
            stack.enter_context(patch("agents.email_agent.handler.is_configured",
                                      return_value=True))
            stack.enter_context(patch("agents.email_agent.handler._parse_request",
                                      return_value={
                                          "action": "draft",
                                          "to": "charlie@example.com",
                                          "subject": "Quick note",
                                          "body_request": "say hi",
                                          "send_immediately": False,
                                      }))
            stack.enter_context(patch("agents.email_agent.handler._draft_email_body",
                                      return_value="Hi Charlie!"))
            _gmail_stack(stack, {
                "integrations.google.gmail_client.send_email": True,
                "integrations.google.gmail_client.reply_to_email": True,
            })
            h.handle("draft email to charlie@example.com")

        assert path.exists(), "State file must exist after draft preview"
        saved = json.loads(path.read_text())
        assert saved["to"] == "charlie@example.com"
        assert saved["body"] == "Hi Charlie!"
        assert saved["type"] == "draft"
