"""
Google OAuth2 — shared auth for Calendar and Gmail.
Uses stored refresh token so the bot never needs a browser after initial setup.
"""

import os
from google.oauth2.credentials import Credentials
from google.auth.transport.requests import Request

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]


def get_credentials() -> Credentials:
    """Return valid Google credentials using stored refresh token."""
    client_id     = os.environ.get("GOOGLE_CLIENT_ID", "")
    client_secret = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    refresh_token = os.environ.get("GOOGLE_REFRESH_TOKEN", "")

    if not all([client_id, client_secret, refresh_token]):
        raise ValueError(
            "Missing GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, or GOOGLE_REFRESH_TOKEN in .env\n"
            "Run: python scripts/google_auth.py"
        )

    creds = Credentials(
        token=None,
        refresh_token=refresh_token,
        token_uri="https://oauth2.googleapis.com/token",
        client_id=client_id,
        client_secret=client_secret,
        scopes=SCOPES,
    )
    creds.refresh(Request())
    return creds


def is_configured() -> bool:
    return all([
        os.environ.get("GOOGLE_CLIENT_ID"),
        os.environ.get("GOOGLE_CLIENT_SECRET"),
        os.environ.get("GOOGLE_REFRESH_TOKEN"),
    ])
