"""
Google OAuth2 — shared auth for Calendar and Gmail.
Uses stored refresh token so the bot never needs a browser after initial setup.
"""

import os
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

SCOPES_PRIMARY = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]
# Secondary account (jngai5.3) — Gmail only, no Calendar
SCOPES_SECONDARY = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]
# Keep backwards-compatible alias
SCOPES = SCOPES_PRIMARY


def get_credentials(account: str = "primary") -> Credentials:
    """
    Return valid Google credentials using stored refresh token.
    account: "primary" (jynpriority@gmail.com) or "secondary" (jngai5.3@gmail.com)
    """
    client_id     = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")

    if account == "secondary":
        refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN_JNGAI53", "")
        if not refresh_token:
            raise ValueError(
                "Missing GOOGLE_REFRESH_TOKEN_JNGAI53 in .env\n"
                "Run: python scripts/google_auth_jngai53.py"
            )
    else:
        refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN", "")
        if not all([client_id, client_secret, refresh_token]):
            raise ValueError(
                "Missing GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, or GOOGLE_REFRESH_TOKEN in .env\n"
                "Run: python scripts/google_auth.py"
            )

    scopes = SCOPES_SECONDARY if account == "secondary" else SCOPES_PRIMARY
    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=scopes,
    )
    creds.refresh(Request())
    return creds


def is_configured(account: str = "primary") -> bool:
    if account == "secondary":
        return bool(
            os.environ.get("GOOGLE_CLIENT_ID") and
            os.environ.get("GOOGLE_CLIENT_SECRET") and
            os.environ.get("GOOGLE_REFRESH_TOKEN_JNGAI53")
        )
    return all([
        os.environ.get("GOOGLE_CLIENT_ID"),
        os.environ.get("GOOGLE_CLIENT_SECRET"),
        os.environ.get("GOOGLE_REFRESH_TOKEN"),
    ])
