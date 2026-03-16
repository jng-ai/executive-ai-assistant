"""
Google Sheets integration — syncs finance tracker data to Justin's spreadsheet.

Setup:
1. Go to console.cloud.google.com → create project → enable Google Sheets API
2. Create Service Account → download JSON key → save as credentials/google_service_account.json
3. Share your Google Sheet with the service account email (Editor access)
4. Add GOOGLE_SHEETS_BONUS_ID=<spreadsheet_id> to .env
   (Sheet ID is the long string in the URL: docs.google.com/spreadsheets/d/<ID>/edit)

Tabs expected in your sheet:
- "CC Bonuses"   : credit card signup bonus tracker
- "Bank Bonuses" : bank account bonus tracker
- "Budget"       : monthly expense log (optional)
"""

import os
import json
import datetime
from pathlib import Path

CREDENTIALS_FILE = Path(__file__).parent.parent.parent / "credentials" / "google_service_account.json"


def _get_client():
    """Return authenticated gspread client, or None if not configured."""
    try:
        import gspread
        from google.oauth2.service_account import Credentials

        if not CREDENTIALS_FILE.exists():
            return None

        scope = [
            "https://spreadsheets.google.com/feeds",
            "https://www.googleapis.com/auth/drive",
        ]
        creds = Credentials.from_service_account_file(str(CREDENTIALS_FILE), scopes=scope)
        return gspread.authorize(creds)
    except ImportError:
        return None
    except Exception as e:
        print(f"Google Sheets auth error: {e}")
        return None


def is_configured() -> bool:
    """Check if Google Sheets is ready to use."""
    return (
        CREDENTIALS_FILE.exists()
        and bool(os.environ.get("GOOGLE_SHEETS_BONUS_ID"))
    )


def _get_spreadsheet():
    """Open the bonus tracker spreadsheet."""
    gc = _get_client()
    if not gc:
        return None
    sheet_id = os.environ.get("GOOGLE_SHEETS_BONUS_ID", "")
    if not sheet_id:
        return None
    try:
        return gc.open_by_key(sheet_id)
    except Exception as e:
        print(f"Google Sheets open error: {e}")
        return None


def _ensure_tab(spreadsheet, tab_name: str, headers: list):
    """Get or create a worksheet tab with headers."""
    try:
        ws = spreadsheet.worksheet(tab_name)
    except Exception:
        ws = spreadsheet.add_worksheet(title=tab_name, rows=1000, cols=20)
        ws.append_row(headers, value_input_option="USER_ENTERED")
    return ws


# ── Public functions ───────────────────────────────────────────────────────────

def append_bonus_row(entry: dict) -> bool:
    """
    Add a row to the CC Bonuses or Bank Bonuses tab.

    entry dict keys: card_or_bank, type, date_logged, status, bonus_amount,
                     min_spend, annual_fee, re_eligibility, notes
    """
    spreadsheet = _get_spreadsheet()
    if not spreadsheet:
        return False

    try:
        bonus_type = entry.get("type", "credit_card")
        tab_name = "CC Bonuses" if bonus_type == "credit_card" else "Bank Bonuses"
        headers = [
            "Card / Bank", "Bonus", "Date Applied", "Min Spend",
            "Annual Fee", "Re-Eligibility", "Status", "Notes", "Source"
        ]
        ws = _ensure_tab(spreadsheet, tab_name, headers)

        row = [
            entry.get("card_or_bank", ""),
            entry.get("bonus_amount", ""),
            entry.get("date_logged", datetime.date.today().isoformat()),
            entry.get("min_spend", ""),
            entry.get("annual_fee", ""),
            entry.get("re_eligibility", ""),
            entry.get("status", "received"),
            entry.get("note", entry.get("notes", "")),
            entry.get("source", ""),
        ]
        ws.append_row(row, value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        print(f"Google Sheets append error: {e}")
        return False


def append_budget_row(entry: dict) -> bool:
    """Add a row to the Budget tab."""
    spreadsheet = _get_spreadsheet()
    if not spreadsheet:
        return False

    try:
        headers = ["Date", "Type", "Amount", "Category", "Description"]
        ws = _ensure_tab(spreadsheet, "Budget", headers)

        row = [
            entry.get("date", datetime.date.today().isoformat()),
            entry.get("type", "expense"),
            entry.get("amount", 0),
            entry.get("category", "other"),
            entry.get("description", ""),
        ]
        ws.append_row(row, value_input_option="USER_ENTERED")
        return True
    except Exception as e:
        print(f"Google Sheets budget append error: {e}")
        return False


def read_bonus_tracker() -> dict:
    """
    Read current tracker data from the spreadsheet.
    Returns: {"cc_bonuses": [...rows...], "bank_bonuses": [...rows...]}
    """
    spreadsheet = _get_spreadsheet()
    if not spreadsheet:
        return {}

    result = {}
    for tab_name, key in [("CC Bonuses", "cc_bonuses"), ("Bank Bonuses", "bank_bonuses")]:
        try:
            ws = spreadsheet.worksheet(tab_name)
            records = ws.get_all_records()
            result[key] = records
        except Exception:
            result[key] = []

    return result
