"""
Notion client — shared wrapper used by all agents.

Databases are auto-created on first run and IDs cached in data/notion_db_ids.json.
One API key serves all agents.
"""

import os
import re
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
    "nyc_events": {
        "title": "🗓 NYC Events 2026",
        "properties": {
            "Date":          {"date": {}},
            "End Time":      {"date": {}},
            "Venue":         {"rich_text": {}},
            "Address":       {"rich_text": {}},
            "Neighborhood":  {"select": {"options": [
                {"name": "Manhattan",     "color": "blue"},
                {"name": "Brooklyn",      "color": "green"},
                {"name": "Queens",        "color": "yellow"},
                {"name": "Bronx",         "color": "orange"},
                {"name": "Staten Island", "color": "gray"},
                {"name": "LES",           "color": "purple"},
                {"name": "Midtown",       "color": "pink"},
                {"name": "UES/UWS",       "color": "brown"},
                {"name": "Williamsburg",  "color": "red"},
                {"name": "Bushwick",      "color": "default"},
            ]}},
            "Category":      {"select": {"options": [
                {"name": "Fitness & Outdoors",     "color": "green"},
                {"name": "Dating & Meetups",       "color": "pink"},
                {"name": "Food & Drinks",          "color": "orange"},
                {"name": "Painting & Visual Arts", "color": "purple"},
                {"name": "Ceramics & Crafts",      "color": "yellow"},
                {"name": "Games & Trivia",         "color": "blue"},
                {"name": "Performing Arts",        "color": "red"},
                {"name": "Community & Clubs",      "color": "default"},
                {"name": "Professional",           "color": "gray"},
                {"name": "Nightlife",              "color": "brown"},
            ]}},
            "Price":         {"number": {"format": "dollar"}},
            "Source":        {"select": {"options": [
                {"name": "Luma",       "color": "purple"},
                {"name": "Eventbrite", "color": "orange"},
                {"name": "Partiful",   "color": "pink"},
                {"name": "Reddit",     "color": "red"},
                {"name": "X",          "color": "default"},
                {"name": "Manual",     "color": "gray"},
                {"name": "Tavily",     "color": "blue"},
            ]}},
            "RSVP Link":     {"url": {}},
            "Status":        {"select": {"options": [
                {"name": "New",        "color": "blue"},
                {"name": "Interested", "color": "yellow"},
                {"name": "Going",      "color": "green"},
                {"name": "Attended",   "color": "purple"},
                {"name": "Skipped",    "color": "gray"},
            ]}},
            "Registered":    {"checkbox": {}},
            "Friends Going": {"rich_text": {}},
            "Cal Event ID":  {"rich_text": {}},
            "Notes":         {"rich_text": {}},
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


# ── Events database helpers ────────────────────────────────────────────────────

def _events_db_id() -> str | None:
    """Return the NYC Events 2026 Notion database ID from env or db cache."""
    db_id = os.environ.get("NOTION_EVENTS_DB_ID", "")
    if db_id:
        return db_id
    ids = _load_db_ids()
    return ids.get("nyc_events")


def _parse_event_page(page: dict) -> dict:
    """Convert a raw Notion page dict into a clean event dict."""
    props = page.get("properties", {})

    def _text(key):
        rt = props.get(key, {}).get("rich_text", [])
        return rt[0]["plain_text"] if rt else ""

    def _select(key):
        sel = props.get(key, {}).get("select")
        return sel["name"] if sel else ""

    def _date(key):
        d = props.get(key, {}).get("date")
        return d["start"] if d else None

    def _url(key):
        return props.get(key, {}).get("url") or ""

    def _number(key):
        return props.get(key, {}).get("number") or 0

    def _checkbox(key):
        return props.get(key, {}).get("checkbox", False)

    title_parts = props.get("Name", {}).get("title", [])
    name = title_parts[0]["plain_text"] if title_parts else ""

    return {
        "notion_id":    page["id"],
        "name":         name,
        "date":         _date("Date"),
        "end_time":     _date("End Time"),
        "venue":        _text("Venue"),
        "address":      _text("Address"),
        "neighborhood": _select("Neighborhood"),
        "category":     _select("Category"),
        "price":        _number("Price"),
        "source":       _select("Source"),
        "rsvp_link":    _url("RSVP Link"),
        "status":       _select("Status"),
        "registered":   _checkbox("Registered"),
        "friends_going":_text("Friends Going"),
        "cal_event_id": _text("Cal Event ID"),
        "notes":        _text("Notes"),
    }


def get_event_by_rsvp_link(rsvp_link: str) -> dict | None:
    """Return existing event page dict if RSVP link already in DB, else None."""
    db_id = _events_db_id()
    if not db_id or not os.environ.get("NOTION_API_KEY"):
        return None
    try:
        resp = requests.post(
            f"{NOTION_BASE}/databases/{db_id}/query",
            headers=_headers(),
            json={"filter": {"property": "RSVP Link", "url": {"equals": rsvp_link}}},
        )
        resp.raise_for_status()
        results = resp.json().get("results", [])
        return _parse_event_page(results[0]) if results else None
    except Exception:
        return None


def push_event(event: dict) -> str | None:
    """
    Push a new event to Notion. Returns page_id on success, None if duplicate or error.
    event dict keys: name, date, end_time, venue, address, neighborhood, category,
                     price, source, rsvp_link (+ optional: notes)
    """
    db_id = _events_db_id()
    if not db_id or not os.environ.get("NOTION_API_KEY"):
        return None

    # Dedup check
    if event.get("rsvp_link") and get_event_by_rsvp_link(event["rsvp_link"]):
        return None

    try:
        props: dict = {
            "Name": {"title": [{"text": {"content": event.get("name", "Untitled")[:100]}}]},
            "Status": {"select": {"name": "New"}},
            "Registered": {"checkbox": False},
        }
        if event.get("date"):
            props["Date"] = {"date": {"start": event["date"]}}
        if event.get("end_time"):
            props["End Time"] = {"date": {"start": event["end_time"]}}
        if event.get("venue"):
            props["Venue"] = {"rich_text": [{"text": {"content": event["venue"][:500]}}]}
        if event.get("address"):
            props["Address"] = {"rich_text": [{"text": {"content": event["address"][:500]}}]}
        if event.get("neighborhood"):
            props["Neighborhood"] = {"select": {"name": event["neighborhood"]}}
        if event.get("category"):
            props["Category"] = {"select": {"name": event["category"]}}
        if event.get("price") is not None:
            props["Price"] = {"number": float(event["price"])}
        if event.get("source"):
            props["Source"] = {"select": {"name": event["source"]}}
        if event.get("rsvp_link"):
            props["RSVP Link"] = {"url": event["rsvp_link"]}
        if event.get("notes"):
            props["Notes"] = {"rich_text": [{"text": {"content": event["notes"][:2000]}}]}

        resp = requests.post(
            f"{NOTION_BASE}/pages",
            headers=_headers(),
            json={"parent": {"database_id": db_id}, "properties": props},
        )
        resp.raise_for_status()
        return resp.json()["id"]
    except Exception as e:
        print(f"Notion push_event error: {e}")
        return None


def get_events(status_filter: str | None = None, category_filter: str | None = None,
               upcoming_only: bool = True) -> list[dict]:
    """
    Query the NYC Events 2026 database. Returns list of parsed event dicts.
    upcoming_only=True filters out events where Date < today.
    """
    db_id = _events_db_id()
    if not db_id or not os.environ.get("NOTION_API_KEY"):
        return []

    filters = []
    if status_filter:
        filters.append({"property": "Status", "select": {"equals": status_filter}})
    if category_filter:
        filters.append({"property": "Category", "select": {"equals": category_filter}})
    if upcoming_only:
        today = datetime.date.today().isoformat()
        filters.append({"property": "Date", "date": {"on_or_after": today}})

    query: dict = {"sorts": [{"property": "Date", "direction": "ascending"}]}
    if len(filters) == 1:
        query["filter"] = filters[0]
    elif len(filters) > 1:
        query["filter"] = {"and": filters}

    try:
        all_results = []
        has_more = True
        cursor = None
        while has_more:
            payload = dict(query)
            if cursor:
                payload["start_cursor"] = cursor
            resp = requests.post(
                f"{NOTION_BASE}/databases/{db_id}/query",
                headers=_headers(),
                json=payload,
            )
            resp.raise_for_status()
            data = resp.json()
            all_results.extend(data.get("results", []))
            has_more = data.get("has_more", False)
            cursor = data.get("next_cursor")
        return [_parse_event_page(p) for p in all_results]
    except Exception as e:
        print(f"Notion get_events error: {e}")
        return []


def update_event_status(notion_id: str, status: str,
                        registered: bool | None = None,
                        cal_event_id: str | None = None) -> bool:
    """Update Status (and optionally Registered + Cal Event ID) on an event page."""
    if not os.environ.get("NOTION_API_KEY"):
        return False
    try:
        props: dict = {"Status": {"select": {"name": status}}}
        if registered is not None:
            props["Registered"] = {"checkbox": registered}
        if cal_event_id:
            props["Cal Event ID"] = {"rich_text": [{"text": {"content": cal_event_id}}]}
        resp = requests.patch(
            f"{NOTION_BASE}/pages/{notion_id}",
            headers=_headers(),
            json={"properties": props},
        )
        resp.raise_for_status()
        return True
    except Exception as e:
        print(f"Notion update_event_status error: {e}")
        return False


def get_progress() -> dict:
    """
    Return progress stats derived from the events DB.
    {total_attended, goal, by_category, heatmap, categories_tried, categories_not_tried}
    """
    GOAL = 20
    ALL_CATEGORIES = [
        "Fitness & Outdoors", "Dating & Meetups", "Food & Drinks",
        "Painting & Visual Arts", "Ceramics & Crafts", "Games & Trivia",
        "Performing Arts", "Community & Clubs", "Professional", "Nightlife",
    ]
    attended = get_events(status_filter="Attended", upcoming_only=False)
    by_category: dict[str, int] = {}
    heatmap: dict[str, str] = {}  # date → category
    for ev in attended:
        cat = ev.get("category", "Other")
        by_category[cat] = by_category.get(cat, 0) + 1
        if ev.get("date"):
            heatmap[ev["date"][:10]] = cat

    tried = set(by_category.keys())
    not_tried = [c for c in ALL_CATEGORIES if c not in tried]

    return {
        "total_attended":       len(attended),
        "goal":                 GOAL,
        "by_category":          by_category,
        "heatmap":              heatmap,
        "categories_tried":     list(tried),
        "categories_not_tried": not_tried,
        "all_categories":       ALL_CATEGORIES,
    }


def add_friend_rsvp(notion_id: str, friend_name: str) -> bool:
    """
    Append friend_name to the Friends Going field on an event page.
    Validates name: 2-40 chars, no URLs, no HTML.
    """
    if not os.environ.get("NOTION_API_KEY"):
        return False
    name = friend_name.strip()
    if not name or len(name) < 2 or len(name) > 40:
        return False
    if re.search(r'https?://', name) or '<' in name:
        return False

    try:
        # Read current value
        resp = requests.get(f"{NOTION_BASE}/pages/{notion_id}", headers=_headers())
        resp.raise_for_status()
        current_rt = resp.json()["properties"].get("Friends Going", {}).get("rich_text", [])
        current = current_rt[0]["plain_text"] if current_rt else ""

        # Check max 10 friends
        existing = [n.strip() for n in current.split(",") if n.strip()]
        if len(existing) >= 10:
            return False
        if name in existing:
            return True  # Already added

        updated = ", ".join(existing + [name])
        patch_resp = requests.patch(
            f"{NOTION_BASE}/pages/{notion_id}",
            headers=_headers(),
            json={"properties": {"Friends Going": {"rich_text": [{"text": {"content": updated}}]}}},
        )
        patch_resp.raise_for_status()
        return True
    except Exception as e:
        print(f"Notion add_friend_rsvp error: {e}")
        return False


def get_friends_going(notion_id: str) -> list[str]:
    """Return list of friend names from the Friends Going field."""
    if not os.environ.get("NOTION_API_KEY"):
        return []
    try:
        resp = requests.get(f"{NOTION_BASE}/pages/{notion_id}", headers=_headers())
        resp.raise_for_status()
        rt = resp.json()["properties"].get("Friends Going", {}).get("rich_text", [])
        raw = rt[0]["plain_text"] if rt else ""
        return [n.strip() for n in raw.split(",") if n.strip()]
    except Exception:
        return []


def is_configured() -> bool:
    return bool(os.environ.get("NOTION_API_KEY")) and bool(os.environ.get("NOTION_PARENT_PAGE_ID"))
