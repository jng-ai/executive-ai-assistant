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
    return bool(os.environ.get("GOOGLE_SHEETS_CC_WEBHOOK") or
                os.environ.get("GOOGLE_SHEETS_BANK_WEBHOOK"))


def _post(url: str, payload: dict) -> bool:
    """POST JSON payload to an Apps Script webhook."""
    if not _requests or not url:
        return False
    try:
        resp = _requests.post(url, json=payload, timeout=10)
        return resp.status_code == 200
    except Exception as e:
        print(f"Google Sheets webhook error: {e}")
        return False


def append_cc_row(entry: dict) -> bool:
    """Add a row to the CC Tracker sheet."""
    url = os.environ.get("GOOGLE_SHEETS_CC_WEBHOOK", "")
    return _post(url, {
        "action": "append",
        "tab": "CC Tracker",
        "row": [
            entry.get("bank_issuer", ""),
            entry.get("card_name", entry.get("card_or_bank", "")),
            entry.get("date_opened", datetime.date.today().isoformat()),
            entry.get("annual_fee", ""),
            entry.get("annual_fee_date", ""),
            entry.get("sign_up_bonus", entry.get("bonus_amount", "")),
            entry.get("min_spend", ""),
            entry.get("spend_deadline", ""),
            entry.get("sub_status", ""),
            entry.get("sub_earned_date", ""),
            entry.get("card_status", "Active"),
            entry.get("action_by_date", ""),
            entry.get("downgrade_to", ""),
            entry.get("re_eligibility", ""),
            entry.get("historical_normal_sub", entry.get("bonus_amount", "")),
            entry.get("notes", entry.get("note", "")),
        ],
        "headers": [
            "Bank/Issuer", "Card Name", "Date Opened", "Annual Fee", "Annual Fee Date",
            "Sign-Up Bonus", "Min Spend", "Spend Deadline", "SUB Status", "SUB Earned Date",
            "Card Status", "Action By Date", "Downgrade To", "Re-Eligibility",
            "Historical Normal SUB", "Notes",
        ],
    })


def append_bank_row(entry: dict) -> bool:
    """Add a row to the Bank Tracker sheet."""
    url = os.environ.get("GOOGLE_SHEETS_BANK_WEBHOOK", "")
    return _post(url, {
        "action": "append",
        "tab": "Bank Tracker",
        "row": [
            entry.get("bank", entry.get("card_or_bank", "")),
            entry.get("account_type", ""),
            entry.get("date_opened", datetime.date.today().isoformat()),
            entry.get("bonus_amount", ""),
            entry.get("min_deposit", entry.get("min_spend", "")),
            entry.get("days_to_qualify", ""),
            entry.get("bonus_deadline", ""),
            entry.get("apy", ""),
            entry.get("monthly_fee", ""),
            entry.get("fee_waiver", ""),
            entry.get("early_closure_penalty", ""),
            entry.get("status", "Active"),
            entry.get("bonus_received_date", ""),
            entry.get("date_closed", ""),
            entry.get("re_eligibility", ""),
            entry.get("notes", entry.get("note", "")),
            entry.get("source", ""),
        ],
        "headers": [
            "Bank", "Account Type", "Date Opened", "Bonus Amount", "Min Deposit",
            "Days to Qualify", "Bonus Deadline", "APY", "Monthly Fee", "Fee Waiver",
            "Early Closure Penalty", "Status", "Bonus Received Date", "Date Closed",
            "Re-Eligibility", "Notes", "Source",
        ],
    })


def append_bonus_row(entry: dict) -> bool:
    """Route to CC or Bank sheet based on entry type."""
    bonus_type = entry.get("type", "credit_card")
    if bonus_type == "credit_card":
        return append_cc_row(entry)
    else:
        return append_bank_row(entry)


def append_budget_row(entry: dict) -> bool:
    """Add a row to the Budget tab (uses CC sheet webhook)."""
    url = os.environ.get("GOOGLE_SHEETS_CC_WEBHOOK", "")
    return _post(url, {
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
    """Read both sheets and merge results."""
    if not _requests:
        return {}
    result = {}
    TAB_MAP = {
        "GOOGLE_SHEETS_CC_WEBHOOK": "CC Tracker",
        "GOOGLE_SHEETS_BANK_WEBHOOK": "Bank Tracker",
    }
    for env_var in ("GOOGLE_SHEETS_CC_WEBHOOK", "GOOGLE_SHEETS_BANK_WEBHOOK"):
        url = os.environ.get(env_var, "")
        if not url:
            continue
        try:
            resp = _requests.get(url + "?action=read", timeout=10)
            if resp.status_code == 200:
                result.update(resp.json())
        except Exception:
            pass
    return result
