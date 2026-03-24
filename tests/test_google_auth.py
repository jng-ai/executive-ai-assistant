"""
Tests for integrations/google/auth.py
"""

import pytest
from unittest.mock import patch, MagicMock


class TestIsConfigured:
    def test_primary_configured_when_all_vars_present(self, google_env):
        from integrations.google.auth import is_configured
        assert is_configured("primary") is True

    def test_primary_not_configured_missing_client_id(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "s")
        monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "r")
        monkeypatch.delenv("GOOGLE_CLIENT_ID", raising=False)
        from integrations.google.auth import is_configured
        assert is_configured("primary") is False

    def test_primary_not_configured_missing_secret(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "i")
        monkeypatch.setenv("GOOGLE_REFRESH_TOKEN", "r")
        monkeypatch.delenv("GOOGLE_CLIENT_SECRET", raising=False)
        from integrations.google.auth import is_configured
        assert is_configured("primary") is False

    def test_primary_not_configured_missing_refresh_token(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "i")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "s")
        monkeypatch.delenv("GOOGLE_REFRESH_TOKEN", raising=False)
        from integrations.google.auth import is_configured
        assert is_configured("primary") is False

    def test_secondary_configured_with_all_secondary_vars(self, google_env_secondary):
        from integrations.google.auth import is_configured
        assert is_configured("secondary") is True

    def test_secondary_not_configured_missing_token(self, google_env, monkeypatch):
        monkeypatch.delenv("GOOGLE_REFRESH_TOKEN_JNGAI53", raising=False)
        from integrations.google.auth import is_configured
        assert is_configured("secondary") is False

    def test_default_account_is_primary(self, google_env):
        from integrations.google.auth import is_configured
        assert is_configured() is True

    def test_no_vars_returns_false(self, monkeypatch):
        for k in ["GOOGLE_CLIENT_ID", "GOOGLE_CLIENT_SECRET", "GOOGLE_REFRESH_TOKEN"]:
            monkeypatch.delenv(k, raising=False)
        from integrations.google.auth import is_configured
        assert is_configured() is False


class TestGetCredentials:
    def test_primary_raises_without_refresh_token(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "id")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
        monkeypatch.delenv("GOOGLE_REFRESH_TOKEN", raising=False)
        from integrations.google.auth import get_credentials
        with pytest.raises(ValueError, match="GOOGLE_REFRESH_TOKEN"):
            get_credentials("primary")

    def test_secondary_raises_without_secondary_token(self, monkeypatch):
        monkeypatch.setenv("GOOGLE_CLIENT_ID", "id")
        monkeypatch.setenv("GOOGLE_CLIENT_SECRET", "secret")
        monkeypatch.delenv("GOOGLE_REFRESH_TOKEN_JNGAI53", raising=False)
        from integrations.google.auth import get_credentials
        with pytest.raises(ValueError, match="GOOGLE_REFRESH_TOKEN_JNGAI53"):
            get_credentials("secondary")

    def test_primary_returns_credentials_object(self, google_env):
        mock_creds = MagicMock()
        with patch("integrations.google.auth.Credentials", return_value=mock_creds):
            with patch("integrations.google.auth.Request"):
                from integrations.google.auth import get_credentials
                result = get_credentials("primary")
        assert result is mock_creds
        mock_creds.refresh.assert_called_once()

    def test_secondary_uses_secondary_scopes(self, google_env_secondary):
        mock_creds = MagicMock()
        captured = {}
        def fake_credentials(**kwargs):
            captured.update(kwargs)
            return mock_creds

        with patch("integrations.google.auth.Credentials", side_effect=fake_credentials):
            with patch("integrations.google.auth.Request"):
                from integrations.google import auth
                from importlib import reload
                result = auth.get_credentials("secondary")

        # refresh_token should be the secondary one
        assert captured.get("refresh_token") == "test-refresh-token-secondary"

    def test_scopes_alias_backward_compat(self):
        from integrations.google.auth import SCOPES, SCOPES_PRIMARY
        assert SCOPES == SCOPES_PRIMARY
