"""
Google Sheets integration — uses Google Apps Script Web App (100% free).
No billing, no service account, no Google Cloud Console needed.

Setup (one time, ~2 minutes):
1. Open your Google Sheet
2. Extensions → Apps Script
3. Paste the contents of scripts/google_apps_script.js into the editor
4. Click Deploy → New Deployment → Web App
   - Execute as: Me
   - Who has access: Anyone
5. Click Deploy → copy the Web App URL
6. Add to .env:  GOOGLE_SHEETS_WEBHOOK_URL=https://script.google.com/macros/s/YOUR_ID/exec
"""

import os
import json
import datetime

try:
    import requests as _requests
except ImportError:
    _requests = None


def is_configured() -> bool:
    return bool(os.environ.get("GOOGLE_SHEETS_WEBHOOK_URL"))


def _post(payload: dict) -> bool:
    """POST JSON payload to the Apps Script webhook."""
    if not _requests:
        return False
    url = os.environ.get("GOOGLE_SHEETS_WEBHOOK_URL", "")
    if not url:
        return False
    try:
        resp = _requests.post(url, json=payload, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        print(f"Google Sheets webhook error: {e}")
        return False


def append_bonus_row(entry: dict) -> bool:
    """Add a row to the CC Bonuses or Bank Bonuses tab."""
    bonus_type = entry.get("type", "credit_card")
    tab = "CC Bonuses" if bonus_type == "credit_card" else "Bank Bonuses"
    return _post({
        "action": "append",
        "tab": tab,
        "row": [
            entry.get("card_or_bank", ""),
            entry.get("bonus_amount", ""),
            entry.get("date_logged", datetime.date.today().isoformat()),
            entry.get("min_spend", ""),
            entry.get("annual_fee", ""),
            entry.get("re_eligibility", ""),
            entry.get("status", "received"),
            entry.get("note", entry.get("notes", "")),
            entry.get("source", ""),
        ],
        "headers": [
            "Card / Bank", "Bonus", "Date", "Min Spend",
            "Annual Fee", "Re-Eligibility", "Status", "Notes", "Source"
        ],
    })


def append_budget_row(entry: dict) -> bool:
    """Add a row to the Budget tab."""
    return _post({
        "action": "append",
        "tab": "Budget",
        "row": [
            entry.get("date", datetime.date.today().isoformat()),
            entry.get("type", "expense"),
            entry.get("amount", 0),
            entry.get("category", "other"),
            entry.get("description", ""),
        ],
        "headers": ["Date", "Type", "Amount", "Category", "Description"],
    })


def read_bonus_tracker() -> dict:
    """Read the bonus tracker from Google Sheets."""
    if not is_configured():
        return {}
    try:
        url = os.environ.get("GOOGLE_SHEETS_WEBHOOK_URL", "") + "?action=read"
        if _requests:
            resp = _requests.get(url, timeout=10)
            if resp.status_code == 200:
                return resp.json()
    except Exception:
        pass
    return {}
