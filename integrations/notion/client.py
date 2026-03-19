"""
Notion client — shared wrapper used by all agents.

Databases are auto-created on first run and IDs cached in data/notion_db_ids.json.
One API key serves all agents.
"""

import os
import json
import datetime
import requests
from pathlib import Path

NOTION_VERSION = "2022-06-28"
NOTION_BASE = "https://api.notion.com/v1"


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {os.environ.get('NOTION_API_KEY', '')}",
        "Notion-Version": NOTION_VERSION,
        "Content-Type": "application/json",
    }

DB_CACHE = Path(__file__).parent.parent.parent / "data" / "notion_db_ids.json"

# Database schemas
DATABASES = {
    "health_log": {
        "title": "🏥 Health Log",
        "properties": {
            "Date":    {"date": {}},
            "Metric":  {"select": {"options": [
                {"name": "weight", "color": "blue"},
                {"name": "sleep",  "color": "purple"},
                {"name": "workout","color": "green"},
                {"name": "meal",   "color": "orange"},
            ]}},
            "Value":   {"rich_text": {}},
            "Unit":    {"rich_text": {}},
            "Notes":   {"rich_text": {}},
            "vs Target": {"rich_text": {}},
        },
    },
    "tasks": {
        "title": "✅ Tasks",
        "properties": {
            "Due Date": {"date": {}},
            "Priority": {"select": {"options": [
                {"name": "high",   "color": "red"},
                {"name": "normal", "color": "yellow"},
                {"name": "low",    "color": "gray"},
            ]}},
            "Status": {"select": {"options": [
                {"name": "open",   "color": "blue"},
                {"name": "done",   "color": "green"},
            ]}},
            "Source": {"rich_text": {}},
        },
    },
    "mortgage_deals": {
        "title": "🏠 Mortgage Note Deals",
        "properties": {
            "State":      {"rich_text": {}},
            "UPB":        {"number": {"format": "dollar"}},
            "Ask Price":  {"number": {"format": "dollar"}},
            "Discount %": {"number": {"format": "percent"}},
            "Est Yield":  {"rich_text": {}},
            "Rating":     {"select": {"options": [
                {"name": "STRONG", "color": "green"},
                {"name": "GOOD",   "color": "yellow"},
                {"name": "PASS",   "color": "red"},
            ]}},
            "Status": {"select": {"options": [
                {"name": "New",         "color": "blue"},
                {"name": "Reviewing",   "color": "yellow"},
                {"name": "Passed",      "color": "gray"},
                {"name": "Purchased",   "color": "green"},
            ]}},
            "Link":   {"url": {}},
            "Notes":  {"rich_text": {}},
        },
    },
    "investment_ideas": {
        "title": "📈 Investment Ideas",
        "properties": {
            "Ticker":   {"rich_text": {}},
            "Thesis":   {"rich_text": {}},
            "Catalyst": {"rich_text": {}},
            "Risk":     {"rich_text": {}},
            "Action":   {"select": {"options": [
                {"name": "BUY",   "color": "green"},
                {"name": "WATCH", "color": "yellow"},
                {"name": "PASS",  "color": "red"},
            ]}},
            "Urgency":  {"select": {"options": [
                {"name": "HIGH",   "color": "red"},
                {"name": "MEDIUM", "color": "yellow"},
                {"name": "LOW",    "color": "gray"},
            ]}},
            "Date":     {"date": {}},
        },
    },
    "consulting_leads": {
        "title": "🏥 Consulting Leads",
        "properties": {
            "Organization": {"rich_text": {}},
            "Signal":       {"rich_text": {}},
            "Priority":     {"select": {"options": [
                {"name": "HIGH",   "color": "red"},
                {"name": "MEDIUM", "color": "yellow"},
                {"name": "LOW",    "color": "gray"},
            ]}},
            "Infusion Angle": {"rich_text": {}},
            "Outreach":       {"rich_text": {}},
            "Status":         {"select": {"options": [
                {"name": "New",         "color": "blue"},
                {"name": "Contacted",   "color": "yellow"},
                {"name": "In Progress", "color": "orange"},
                {"name": "Closed",      "color": "green"},
                {"name": "Passed",      "color": "gray"},
            ]}},
            "Link":  {"url": {}},
            "Notes": {"rich_text": {}},
            "Date":  {"date": {}},
        },
    },
    "finance_bonuses": {
        "title": "💳 Finance Bonuses Tracker",
        "properties": {
            "Type":           {"select": {"options": [
                {"name": "credit_card", "color": "blue"},
                {"name": "bank",        "color": "green"},
            ]}},
            "Bonus":          {"rich_text": {}},
            "Min Spend":      {"rich_text": {}},
            "Annual Fee":     {"rich_text": {}},
            "Re-Eligibility": {"rich_text": {}},
            "Date Received":  {"date": {}},
            "Status":         {"select": {"options": [
                {"name": "Tracking",  "color": "blue"},
                {"name": "Applied",   "color": "yellow"},
                {"name": "Received",  "color": "green"},
                {"name": "Closed",    "color": "gray"},
            ]}},
            "Source": {"url": {}},
            "Notes":  {"rich_text": {}},
        },
    },
}


def _get_notion():
    """Get authenticated Notion client."""
    from notion_client import Client
    api_key = os.environ.get("NOTION_API_KEY", "")
    if not api_key:
        return None
    return Client(auth=api_key)


def _load_db_ids() -> dict:
    DB_CACHE.parent.mkdir(exist_ok=True)
    if DB_CACHE.exists():
        return json.loads(DB_CACHE.read_text())
    return {}


def _save_db_ids(ids: dict):
    DB_CACHE.parent.mkdir(exist_ok=True)
    DB_CACHE.write_text(json.dumps(ids, indent=2))


def setup_databases() -> dict:
    """Create all databases in Notion if they don't exist yet. Returns db_ids dict."""
    parent_id = os.environ.get("NOTION_PARENT_PAGE_ID", "").replace("-", "")
    if not parent_id or not os.environ.get("NOTION_API_KEY"):
        return {}

    db_ids = _load_db_ids()
    created = []

    for key, schema in DATABASES.items():
        if key in db_ids:
            continue  # already exists

        try:
            properties = {"Name": {"title": {}}}
            properties.update(schema["properties"])

            payload = {
                "parent": {"type": "page_id", "page_id": parent_id},
                "title": [{"type": "text", "text": {"content": schema["title"]}}],
                "properties": properties,
            }
            resp = requests.post(
                f"{NOTION_BASE}/databases",
                headers=_headers(),
                json=payload,
            )
            resp.raise_for_status()
            db = resp.json()
            db_ids[key] = db["id"]
            created.append(schema["title"])
        except Exception as e:
            print(f"Notion setup error for {key}: {e}")

    if created:
        _save_db_ids(db_ids)
        print(f"Notion: created databases: {', '.join(created)}")

    return db_ids


def add_row(db_key: str, name: str, properties: dict) -> bool:
    """Add a row to a Notion database. Returns True on success."""
    notion = _get_notion()
    if not notion:
        return False

    db_ids = _load_db_ids()
    if db_key not in db_ids:
        db_ids = setup_databases()

    db_id = db_ids.get(db_key)
    if not db_id:
        return False

    try:
        # Build Notion property payload
        props = {"Name": {"title": [{"text": {"content": name[:100]}}]}}

        for k, v in properties.items():
            if v is None or v == "":
                continue
            if k in ("Date", "Due Date"):
                props[k] = {"date": {"start": str(v)}}
            elif isinstance(v, (int, float)):
                props[k] = {"number": v}
            elif k in ("Rating", "Status", "Priority", "Action", "Urgency", "Metric"):
                props[k] = {"select": {"name": str(v)}}
            elif k == "Link" and v:
                props[k] = {"url": str(v)}
            else:
                props[k] = {"rich_text": [{"text": {"content": str(v)[:2000]}}]}

        notion.pages.create(
            parent={"database_id": db_id},
            properties=props,
        )
        return True
    except Exception as e:
        print(f"Notion write error ({db_key}): {e}")
        return False


def repair_databases() -> dict[str, str]:
    """
    Ensure all cached databases have the correct properties.
    Uses raw requests (notion-client library silently drops properties).
    Returns dict of {db_key: "ok" | "error: ..."}.
    """
    if not os.environ.get("NOTION_API_KEY"):
        return {}

    db_ids = _load_db_ids()
    results = {}

    for key, schema in DATABASES.items():
        db_id = db_ids.get(key)
        if not db_id:
            continue
        try:
            # Fetch actual properties
            resp = requests.get(f"{NOTION_BASE}/databases/{db_id}", headers=_headers())
            resp.raise_for_status()
            existing = set(resp.json().get("properties", {}).keys())

            missing = {
                col: defn
                for col, defn in schema["properties"].items()
                if col not in existing
            }

            if missing:
                patch = requests.patch(
                    f"{NOTION_BASE}/databases/{db_id}",
                    headers=_headers(),
                    json={"properties": missing},
                )
                patch.raise_for_status()
                results[key] = f"added {list(missing.keys())}"
            else:
                results[key] = "ok"
        except Exception as e:
            results[key] = f"error: {e}"

    return results


def is_configured() -> bool:
    return bool(os.environ.get("NOTION_API_KEY")) and bool(os.environ.get("NOTION_PARENT_PAGE_ID"))
