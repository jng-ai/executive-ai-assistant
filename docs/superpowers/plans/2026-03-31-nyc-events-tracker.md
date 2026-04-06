# NYC Events Tracker Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Build a Notion-backed NYC events tracker with daily multi-source scanning, calendar-aware auto-registration, progress dashboard, theme search, and friend collaboration.

**Architecture:** Notion "NYC Events 2026" database is the single source of truth. The existing social_agent is upgraded to scan daily and push structured events to Notion. The existing FastAPI dashboard gains an Events tab (progress, theme search, event feed) and a public /friends page. Telegram bot handles registration inline keyboards and post-event confirmation.

**Tech Stack:** Python 3.12, FastAPI, python-telegram-bot 20+, APScheduler, Playwright (already installed), Notion API (requests + notion-client), Tavily search, Groq LLM, Google Calendar API, Reddit JSON API

---

## File Map

| File | Role | Action |
|------|------|--------|
| `integrations/notion/client.py` | Notion wrapper — add events CRUD | Modify |
| `agents/social_agent/handler.py` | Daily scanner + intake + theme search | Modify |
| `integrations/telegram/bot.py` | Inline keyboard callbacks + new scheduler jobs | Modify |
| `integrations/web/server.py` | 6 new /api/events/* endpoints + /friends route | Modify |
| `integrations/web/static/index.html` | Events tab UI (progress + theme search + feed) | Modify |
| `integrations/web/static/friends.html` | Friend collaboration page | Create |
| `scripts/notion_events_bootstrap.py` | One-time Notion DB setup | Create |
| `data/events_friends_cache.json` | Friend RSVP change-detection cache | Create (auto) |
| `tests/test_events_notion.py` | Notion events client tests | Create |
| `tests/test_events_scanner.py` | Scanner + intake + theme search tests | Create |
| `tests/test_events_registration.py` | Playwright registration flow tests | Create |
| `tests/test_events_api.py` | FastAPI /api/events/* endpoint tests | Create |

---

## Task 1: Notion Events Database Schema + Client Functions

Extend `integrations/notion/client.py` with the "nyc_events" database schema and all event CRUD functions. Everything downstream depends on this.

**Files:**
- Modify: `integrations/notion/client.py`
- Create: `tests/test_events_notion.py`

- [ ] **Step 1.1: Write failing tests for Notion events client**

```python
# tests/test_events_notion.py
import json
import pytest
from unittest.mock import patch, MagicMock
from pathlib import Path


@pytest.fixture
def mock_notion_env(monkeypatch):
    monkeypatch.setenv("NOTION_API_KEY", "test-key")
    monkeypatch.setenv("NOTION_PARENT_PAGE_ID", "test-parent-id")
    monkeypatch.setenv("NOTION_EVENTS_DB_ID", "test-events-db-id")


@pytest.fixture
def sample_event():
    return {
        "name": "Brooklyn 5K Run",
        "date": "2026-04-05T10:00:00",
        "end_time": "2026-04-05T12:00:00",
        "venue": "Prospect Park",
        "address": "110 Eastern Pkwy, Brooklyn, NY 11238",
        "neighborhood": "Brooklyn",
        "category": "Fitness & Outdoors",
        "price": 0,
        "source": "Luma",
        "rsvp_link": "https://lu.ma/bk5k",
    }


class TestPushEvent:
    def test_push_event_returns_page_id(self, mock_notion_env, sample_event):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {"id": "page-abc-123"}
        mock_resp.raise_for_status = MagicMock()
        with patch("integrations.notion.client.requests.post", return_value=mock_resp):
            from integrations.notion import client
            result = client.push_event(sample_event)
        assert result == "page-abc-123"

    def test_push_event_skips_duplicate(self, mock_notion_env, sample_event):
        """If RSVP link already exists in Notion, returns None without posting."""
        with patch("integrations.notion.client.get_event_by_rsvp_link", return_value={"id": "existing"}):
            from integrations.notion import client
            result = client.push_event(sample_event)
        assert result is None

    def test_push_event_no_api_key_returns_none(self, monkeypatch, sample_event):
        monkeypatch.delenv("NOTION_API_KEY", raising=False)
        monkeypatch.delenv("NOTION_EVENTS_DB_ID", raising=False)
        from integrations.notion import client
        result = client.push_event(sample_event)
        assert result is None


class TestGetEvents:
    def test_get_events_returns_list(self, mock_notion_env):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {
                    "id": "page-1",
                    "properties": {
                        "Name": {"title": [{"plain_text": "Test Event"}]},
                        "Date": {"date": {"start": "2026-04-05T10:00:00"}},
                        "Status": {"select": {"name": "New"}},
                        "Category": {"select": {"name": "Fitness & Outdoors"}},
                        "Price": {"number": 0},
                        "RSVP Link": {"url": "https://lu.ma/test"},
                        "Address": {"rich_text": [{"plain_text": "123 Main St"}]},
                        "Venue": {"rich_text": [{"plain_text": "Prospect Park"}]},
                        "Source": {"select": {"name": "Luma"}},
                        "End Time": {"date": {"start": "2026-04-05T12:00:00"}},
                        "Friends Going": {"rich_text": [{"plain_text": ""}]},
                        "Registered": {"checkbox": False},
                    },
                }
            ],
            "has_more": False,
        }
        mock_resp.raise_for_status = MagicMock()
        with patch("integrations.notion.client.requests.post", return_value=mock_resp):
            from integrations.notion import client
            events = client.get_events()
        assert len(events) == 1
        assert events[0]["name"] == "Test Event"
        assert events[0]["notion_id"] == "page-1"

    def test_get_events_no_db_id_returns_empty(self, monkeypatch):
        monkeypatch.delenv("NOTION_EVENTS_DB_ID", raising=False)
        from importlib import reload
        import integrations.notion.client as c
        events = c.get_events()
        assert events == []


class TestUpdateEventStatus:
    def test_update_status_patches_correct_page(self, mock_notion_env):
        mock_resp = MagicMock()
        mock_resp.raise_for_status = MagicMock()
        with patch("integrations.notion.client.requests.patch", return_value=mock_resp) as m:
            from integrations.notion import client
            client.update_event_status("page-abc", "Attended")
        call_url = m.call_args[0][0]
        assert "page-abc" in call_url

    def test_update_status_no_key_is_noop(self, monkeypatch):
        monkeypatch.delenv("NOTION_API_KEY", raising=False)
        from integrations.notion import client
        # Should not raise
        client.update_event_status("page-abc", "Attended")


class TestGetProgress:
    def test_get_progress_counts_attended(self, mock_notion_env):
        mock_resp = MagicMock()
        mock_resp.json.return_value = {
            "results": [
                {"id": "p1", "properties": {
                    "Name": {"title": [{"plain_text": "Event A"}]},
                    "Status": {"select": {"name": "Attended"}},
                    "Category": {"select": {"name": "Fitness & Outdoors"}},
                    "Date": {"date": {"start": "2026-03-10T10:00:00"}},
                    "Price": {"number": 0}, "RSVP Link": {"url": "https://x.com/a"},
                    "Address": {"rich_text": [{"plain_text": ""}]},
                    "Venue": {"rich_text": [{"plain_text": ""}]},
                    "Source": {"select": {"name": "Luma"}},
                    "End Time": {"date": None},
                    "Friends Going": {"rich_text": [{"plain_text": ""}]},
                    "Registered": {"checkbox": False},
                }},
            ],
            "has_more": False,
        }
        mock_resp.raise_for_status = MagicMock()
        with patch("integrations.notion.client.requests.post", return_value=mock_resp):
            from integrations.notion import client
            progress = client.get_progress()
        assert progress["total_attended"] == 1
        assert progress["by_category"]["Fitness & Outdoors"] == 1
        assert progress["goal"] == 20


class TestAddFriendRsvp:
    def test_add_friend_appends_name(self, mock_notion_env):
        # First GET to read current Friends Going
        get_resp = MagicMock()
        get_resp.json.return_value = {"properties": {
            "Friends Going": {"rich_text": [{"plain_text": "Alice"}]}
        }}
        get_resp.raise_for_status = MagicMock()
        patch_resp = MagicMock()
        patch_resp.raise_for_status = MagicMock()
        with patch("integrations.notion.client.requests.get", return_value=get_resp):
            with patch("integrations.notion.client.requests.patch", return_value=patch_resp) as m:
                from integrations.notion import client
                client.add_friend_rsvp("page-abc", "Bob")
        patched_body = m.call_args[1]["json"]
        friends_text = patched_body["properties"]["Friends Going"]["rich_text"][0]["text"]["content"]
        assert "Alice" in friends_text
        assert "Bob" in friends_text

    def test_add_friend_rejects_url_in_name(self, mock_notion_env):
        from integrations.notion import client
        result = client.add_friend_rsvp("page-abc", "http://spam.com")
        assert result is False

    def test_add_friend_rejects_empty_name(self, mock_notion_env):
        from integrations.notion import client
        result = client.add_friend_rsvp("page-abc", "")
        assert result is False
```

- [ ] **Step 1.2: Run tests to verify they fail**

```bash
cd /Users/justinngai/workspace/executive-ai-assistant
source venv/bin/activate
pytest tests/test_events_notion.py -v 2>&1 | head -40
```

Expected: ImportError or AttributeError — functions don't exist yet.

- [ ] **Step 1.3: Add "nyc_events" to the DATABASES dict in `integrations/notion/client.py`**

Add this entry to the `DATABASES` dict after `"finance_bonuses"`:

```python
    "nyc_events": {
        "title": "🗓 NYC Events 2026",
        "properties": {
            "Date":          {"date": {}},
            "End Time":      {"date": {}},
            "Venue":         {"rich_text": {}},
            "Address":       {"rich_text": {}},
            "Neighborhood":  {"select": {"options": [
                {"name": "Manhattan",  "color": "blue"},
                {"name": "Brooklyn",   "color": "green"},
                {"name": "Queens",     "color": "yellow"},
                {"name": "Bronx",      "color": "orange"},
                {"name": "Staten Island", "color": "gray"},
                {"name": "LES",        "color": "purple"},
                {"name": "Midtown",    "color": "pink"},
                {"name": "UES/UWS",    "color": "brown"},
                {"name": "Williamsburg","color": "red"},
                {"name": "Bushwick",   "color": "default"},
            ]}},
            "Category":      {"select": {"options": [
                {"name": "Fitness & Outdoors",    "color": "green"},
                {"name": "Dating & Meetups",      "color": "pink"},
                {"name": "Food & Drinks",         "color": "orange"},
                {"name": "Painting & Visual Arts","color": "purple"},
                {"name": "Ceramics & Crafts",     "color": "yellow"},
                {"name": "Games & Trivia",        "color": "blue"},
                {"name": "Performing Arts",       "color": "red"},
                {"name": "Community & Clubs",     "color": "default"},
                {"name": "Professional",          "color": "gray"},
                {"name": "Nightlife",             "color": "brown"},
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
                {"name": "New",       "color": "blue"},
                {"name": "Interested","color": "yellow"},
                {"name": "Going",     "color": "green"},
                {"name": "Attended",  "color": "purple"},
                {"name": "Skipped",   "color": "gray"},
            ]}},
            "Registered":    {"checkbox": {}},
            "Friends Going": {"rich_text": {}},
            "Cal Event ID":  {"rich_text": {}},
            "Notes":         {"rich_text": {}},
        },
    },
```

- [ ] **Step 1.4: Add event CRUD functions at the bottom of `integrations/notion/client.py`**

Add before the final `is_configured()` function:

```python
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
        "notion_id":   page["id"],
        "name":        name,
        "date":        _date("Date"),
        "end_time":    _date("End Time"),
        "venue":       _text("Venue"),
        "address":     _text("Address"),
        "neighborhood":_select("Neighborhood"),
        "category":    _select("Category"),
        "price":       _number("Price"),
        "source":      _select("Source"),
        "rsvp_link":   _url("RSVP Link"),
        "status":      _select("Status"),
        "registered":  _checkbox("Registered"),
        "friends_going":_text("Friends Going"),
        "cal_event_id":_text("Cal Event ID"),
        "notes":       _text("Notes"),
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
    import re as _re
    if not os.environ.get("NOTION_API_KEY"):
        return False
    name = friend_name.strip()
    if not name or len(name) < 2 or len(name) > 40:
        return False
    if _re.search(r'https?://', name) or '<' in name:
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
```

- [ ] **Step 1.5: Run tests to verify they pass**

```bash
cd /Users/justinngai/workspace/executive-ai-assistant
pytest tests/test_events_notion.py -v
```

Expected: All green.

- [ ] **Step 1.6: Commit**

```bash
git add integrations/notion/client.py tests/test_events_notion.py
git commit -m "feat: add NYC events Notion schema and CRUD helpers"
```

---

## Task 2: Notion Bootstrap Script

One-time script that creates the database, saves the ID to `.env`. Run manually once before deploying.

**Files:**
- Create: `scripts/notion_events_bootstrap.py`

- [ ] **Step 2.1: Create the bootstrap script**

```python
# scripts/notion_events_bootstrap.py
"""
One-time setup: creates the "NYC Events 2026" Notion database.
Run once: python scripts/notion_events_bootstrap.py

Prerequisites:
  - NOTION_API_KEY in .env
  - NOTION_PARENT_PAGE_ID in .env (the Notion page ID to create the DB under)

After running: copy the printed NOTION_EVENTS_DB_ID into your .env file.
"""
import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from integrations.notion.client import setup_databases, _load_db_ids

def main():
    api_key = os.environ.get("NOTION_API_KEY")
    parent_id = os.environ.get("NOTION_PARENT_PAGE_ID")

    if not api_key:
        print("ERROR: NOTION_API_KEY not set in .env")
        sys.exit(1)
    if not parent_id:
        print("ERROR: NOTION_PARENT_PAGE_ID not set in .env")
        print("To find your page ID: open a Notion page, copy the URL.")
        print("The ID is the 32-char hex string after the last slash.")
        sys.exit(1)

    print("Creating NYC Events 2026 database in Notion...")
    db_ids = setup_databases()

    if "nyc_events" not in db_ids:
        print("ERROR: Failed to create database. Check your API key and parent page ID.")
        sys.exit(1)

    db_id = db_ids["nyc_events"]
    print(f"\n✅ Database created successfully!")
    print(f"\nAdd this to your .env file:")
    print(f"NOTION_EVENTS_DB_ID={db_id}")
    print(f"\nNotion URL: https://www.notion.so/{db_id.replace('-', '')}")

if __name__ == "__main__":
    main()
```

- [ ] **Step 2.2: Verify script is importable without error**

```bash
cd /Users/justinngai/workspace/executive-ai-assistant
python -c "import scripts.notion_events_bootstrap" 2>&1 || echo "check imports"
```

- [ ] **Step 2.3: Commit**

```bash
git add scripts/notion_events_bootstrap.py
git commit -m "feat: add Notion events database bootstrap script"
```

---

## Task 3: Daily Event Scanner

Upgrade `agents/social_agent/handler.py`: replace the Tue/Fri `run_event_scan()` with a daily `run_event_scan_daily()` that searches all sources, extracts structured event data, deduplicates via Notion, pushes new events, and sends a batched Telegram digest with [Sign me up] buttons.

**Files:**
- Modify: `agents/social_agent/handler.py`
- Create: `tests/test_events_scanner.py`

- [ ] **Step 3.1: Write failing tests for scanner**

```python
# tests/test_events_scanner.py
import json
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


SAMPLE_EXTRACTED = [
    {
        "name": "Brooklyn 5K Run",
        "date": "2026-04-05T10:00:00",
        "end_time": "2026-04-05T12:00:00",
        "venue": "Prospect Park",
        "address": "110 Eastern Pkwy, Brooklyn, NY",
        "neighborhood": "Brooklyn",
        "category": "Fitness & Outdoors",
        "price": 0,
        "source": "Luma",
        "rsvp_link": "https://lu.ma/bk5k",
    }
]


class TestExtractEventsFromResults:
    def test_extract_returns_list_of_dicts(self):
        with patch("agents.social_agent.handler.chat", return_value=json.dumps(SAMPLE_EXTRACTED)):
            from agents.social_agent.handler import _extract_events_from_results
            results = _extract_events_from_results("some search text", "Fitness & Outdoors")
        assert isinstance(results, list)
        assert results[0]["name"] == "Brooklyn 5K Run"

    def test_extract_filters_over_80(self):
        expensive = [{**SAMPLE_EXTRACTED[0], "price": 100, "rsvp_link": "https://lu.ma/exp"}]
        with patch("agents.social_agent.handler.chat", return_value=json.dumps(expensive)):
            from agents.social_agent.handler import _extract_events_from_results
            results = _extract_events_from_results("text", "Fitness & Outdoors")
        assert results == []

    def test_extract_handles_invalid_json_gracefully(self):
        with patch("agents.social_agent.handler.chat", return_value="not json at all"):
            from agents.social_agent.handler import _extract_events_from_results
            results = _extract_events_from_results("text", "Fitness & Outdoors")
        assert results == []

    def test_extract_requires_rsvp_link(self):
        no_link = [{**SAMPLE_EXTRACTED[0], "rsvp_link": ""}]
        with patch("agents.social_agent.handler.chat", return_value=json.dumps(no_link)):
            from agents.social_agent.handler import _extract_events_from_results
            results = _extract_events_from_results("text", "Fitness & Outdoors")
        assert results == []


class TestHandleIntake:
    def test_intake_url_extracts_and_pushes(self):
        extracted = SAMPLE_EXTRACTED[0]
        with patch("agents.social_agent.handler.fetch_page", return_value="event page html"):
            with patch("agents.social_agent.handler.chat", return_value=json.dumps(extracted)):
                with patch("agents.social_agent.handler.push_event", return_value="page-id-123") as mock_push:
                    from agents.social_agent.handler import handle_intake
                    result = handle_intake("https://lu.ma/bk5k")
        mock_push.assert_called_once()
        assert "Brooklyn 5K Run" in result

    def test_intake_duplicate_returns_already_tracked(self):
        with patch("agents.social_agent.handler.fetch_page", return_value="html"):
            with patch("agents.social_agent.handler.chat", return_value=json.dumps(SAMPLE_EXTRACTED[0])):
                with patch("agents.social_agent.handler.push_event", return_value=None):
                    from agents.social_agent.handler import handle_intake
                    result = handle_intake("https://lu.ma/bk5k")
        assert "already" in result.lower()

    def test_intake_fetch_failure_returns_error(self):
        with patch("agents.social_agent.handler.fetch_page", side_effect=Exception("timeout")):
            from agents.social_agent.handler import handle_intake
            result = handle_intake("https://lu.ma/bk5k")
        assert "couldn't" in result.lower() or "error" in result.lower()


class TestRunThemeSearch:
    def test_theme_search_returns_list(self):
        with patch("agents.social_agent.handler.search", return_value=[{"url": "x", "content": "event"}]):
            with patch("agents.social_agent.handler.chat", return_value=json.dumps(SAMPLE_EXTRACTED)):
                from agents.social_agent.handler import run_theme_search
                results = run_theme_search("salsa dancing")
        assert isinstance(results, list)

    def test_theme_search_empty_query_returns_empty(self):
        from agents.social_agent.handler import run_theme_search
        results = run_theme_search("")
        assert results == []
```

- [ ] **Step 3.2: Run tests to verify they fail**

```bash
pytest tests/test_events_scanner.py -v 2>&1 | head -30
```

- [ ] **Step 3.3: Add Reddit scan helper and event extraction to `agents/social_agent/handler.py`**

Add these imports at the top of the file (after existing imports):

```python
import requests as _requests
from integrations.notion.client import push_event, get_event_by_rsvp_link
```

Add these functions before `handle()`:

```python
# ── Category definitions ──────────────────────────────────────────────────────

CATEGORIES = [
    "Fitness & Outdoors", "Dating & Meetups", "Food & Drinks",
    "Painting & Visual Arts", "Ceramics & Crafts", "Games & Trivia",
    "Performing Arts", "Community & Clubs", "Professional", "Nightlife",
]

_EXTRACTION_SYSTEM = """You are an NYC event data extractor. Given search results text,
extract structured event data as a JSON array. Each event must have ALL these fields:
  name, date (ISO 8601 datetime or null), end_time (ISO 8601 or null),
  venue (string), address (full street address or ""), neighborhood (Manhattan/Brooklyn/Queens/Bronx/LES/Midtown/Williamsburg/Bushwick/UES-UWS or ""),
  category (MUST be one of: Fitness & Outdoors, Dating & Meetups, Food & Drinks,
    Painting & Visual Arts, Ceramics & Crafts, Games & Trivia, Performing Arts,
    Community & Clubs, Professional, Nightlife),
  price (number, 0 for free), source (Luma/Eventbrite/Partiful/Reddit/X/Tavily),
  rsvp_link (direct event URL, NOT a listing/browse page — empty string if not found)

RULES:
- Only include UPCOMING events (date >= today)
- price must be a number (not a string)
- rsvp_link must be a specific event page URL
- Return ONLY the JSON array, no other text
- If no valid events found, return []"""


def _extract_events_from_results(search_text: str, category_hint: str = "") -> list[dict]:
    """
    Use LLM to extract structured event dicts from raw search result text.
    Filters out: price > 80, missing rsvp_link, past dates.
    Returns list of event dicts.
    """
    import datetime as _dt
    user_prompt = (
        f"Today is {_dt.date.today().isoformat()}. "
        f"Category hint: {category_hint}\n\n"
        f"Search results:\n{search_text[:6000]}"
    )
    raw = chat(_EXTRACTION_SYSTEM, user_prompt, max_tokens=2000)
    try:
        # Strip markdown code fences if present
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        events = json.loads(raw)
        if not isinstance(events, list):
            return []
    except Exception:
        return []

    today = _dt.date.today().isoformat()
    filtered = []
    for ev in events:
        if not isinstance(ev, dict):
            continue
        if not ev.get("rsvp_link"):
            continue
        try:
            price = float(ev.get("price", 0) or 0)
        except (TypeError, ValueError):
            price = 0
        if price > 80:
            continue
        ev["price"] = price
        ev_date = ev.get("date", "") or ""
        if ev_date and ev_date[:10] < today:
            continue
        filtered.append(ev)
    return filtered


def _search_reddit_events() -> list[dict]:
    """
    Scrape r/nyc, r/nycmeetups, r/nycactivities, r/nycevents for event posts.
    Returns list of raw result strings for LLM extraction.
    """
    subreddits = ["nyc", "nycmeetups", "nycactivities", "nycevents"]
    texts = []
    for sub in subreddits:
        try:
            url = f"https://www.reddit.com/r/{sub}/new.json?limit=25"
            resp = _requests.get(url, headers={"User-Agent": "events-scout/1.0"}, timeout=10)
            resp.raise_for_status()
            posts = resp.json()["data"]["children"]
            for post in posts:
                d = post["data"]
                title = d.get("title", "")
                selftext = d.get("selftext", "")[:300]
                url_link = d.get("url", "")
                texts.append(f"Title: {title}\nText: {selftext}\nURL: {url_link}")
        except Exception as e:
            print(f"Reddit scan error ({sub}): {e}")
    return texts


def handle_intake(url: str) -> str:
    """
    Parse an event URL pasted by the user, extract fields, push to Notion.
    Returns a human-readable confirmation or error string.
    """
    if not url.startswith("http"):
        return "That doesn't look like a valid event URL."
    try:
        page_text = fetch_page(url)
    except Exception as e:
        return f"Couldn't fetch that URL ({e}). Paste the link again?"

    user_prompt = f"Today is {datetime.date.today().isoformat()}. Event URL: {url}\n\nPage content:\n{page_text[:5000]}"
    raw = chat(_EXTRACTION_SYSTEM, user_prompt, max_tokens=800)
    try:
        raw = raw.strip()
        if raw.startswith("```"):
            raw = raw.split("\n", 1)[1].rsplit("```", 1)[0]
        data = json.loads(raw)
        if isinstance(data, list) and data:
            event = data[0]
        elif isinstance(data, dict):
            event = data
        else:
            return "Couldn't extract event details from that page. Try a different link."
    except Exception:
        return "Couldn't parse event data from that page. Try a different link."

    if not event.get("rsvp_link"):
        event["rsvp_link"] = url
    event["source"] = "Manual"

    page_id = push_event(event)
    if page_id is None:
        # Could be a duplicate
        existing = get_event_by_rsvp_link(url)
        if existing:
            return f"✅ Already tracking: **{existing['name']}** on {(existing.get('date') or '')[:10]}"
        return "Couldn't save that event. Check the URL and try again."

    name = event.get("name", "Event")
    date_str = (event.get("date") or "")[:10]
    cat = event.get("category", "")
    return f"✅ Added: **{name}**{' on ' + date_str if date_str else ''} · {cat}"


def run_theme_search(theme: str) -> list[dict]:
    """
    Search for NYC events matching a freeform theme.
    Returns list of event dicts (NOT pushed to Notion — caller decides).
    """
    if not theme or not theme.strip():
        return []
    queries = [
        f"NYC {theme} events 2026 RSVP sign up",
        f"site:lu.ma NYC {theme}",
        f"site:eventbrite.com NYC {theme}",
    ]
    all_text = ""
    for q in queries:
        try:
            results = search(q, max_results=5)
            all_text += format_results(results) + "\n"
        except Exception:
            pass
    if not all_text.strip():
        return []
    return _extract_events_from_results(all_text, theme)
```

- [ ] **Step 3.4: Add `run_event_scan_daily()` to `agents/social_agent/handler.py`**

Add after `run_theme_search()`:

```python
async def run_event_scan_daily(bot=None, chat_id: str = None) -> str:
    """
    Daily 8:15 AM scanner. Searches all sources, pushes new events to Notion,
    sends batched Telegram digest with [Sign me up] inline buttons.
    Returns summary string (also sent via Telegram if bot + chat_id provided).
    """
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    import concurrent.futures

    today = datetime.date.today().isoformat()
    all_events: list[dict] = []

    # Search each category across sources
    source_queries = []
    for cat in CATEGORIES:
        cat_slug = cat.lower().replace(" & ", " ").replace(" ", "+")
        source_queries.extend([
            (f"NYC {cat_slug} events {today[:7]} RSVP sign up site:lu.ma OR site:eventbrite.com OR site:partiful.com", cat),
            (f"NYC {cat_slug} events upcoming 2026", cat),
        ])
    # Reddit (separate)
    reddit_texts = _search_reddit_events()

    def _run_query(args):
        q, cat = args
        try:
            results = search(q, max_results=5)
            text = format_results(results)
            return _extract_events_from_results(text, cat)
        except Exception:
            return []

    with concurrent.futures.ThreadPoolExecutor(max_workers=6) as pool:
        futures = [pool.submit(_run_query, args) for args in source_queries]
        for f in concurrent.futures.as_completed(futures):
            all_events.extend(f.result() or [])

    # Reddit extraction
    if reddit_texts:
        combined_reddit = "\n---\n".join(reddit_texts[:20])
        all_events.extend(_extract_events_from_results(combined_reddit, ""))

    # Dedup by rsvp_link within this batch
    seen_links: set[str] = set()
    unique_events: list[dict] = []
    for ev in all_events:
        link = ev.get("rsvp_link", "")
        if link and link not in seen_links:
            seen_links.add(link)
            unique_events.append(ev)

    # Push to Notion (skip duplicates)
    pushed: list[dict] = []
    for ev in unique_events:
        page_id = push_event(ev)
        if page_id:
            ev["notion_id"] = page_id
            pushed.append(ev)

    if not pushed:
        summary = "🗓 Daily scan complete — no new events found today."
        if bot and chat_id:
            await bot.send_message(chat_id=chat_id, text=summary)
        return summary

    # Build batched Telegram digest
    lines = [f"🗓 *{len(pushed)} new events found today:*\n"]
    keyboard_rows = []
    for i, ev in enumerate(pushed[:15], 1):  # cap at 15 per digest
        cat_emoji = {
            "Fitness & Outdoors": "💪", "Dating & Meetups": "💘",
            "Food & Drinks": "🍜", "Painting & Visual Arts": "🎨",
            "Ceramics & Crafts": "🏺", "Games & Trivia": "🎲",
            "Performing Arts": "🎭", "Community & Clubs": "🤝",
            "Professional": "💼", "Nightlife": "🎉",
        }.get(ev.get("category", ""), "📌")
        date_str = (ev.get("date") or "")[:10]
        price_str = "Free" if ev.get("price", 0) == 0 else f"${int(ev['price'])}"
        venue = ev.get("neighborhood") or ev.get("venue", "")
        lines.append(f"{i}. {cat_emoji} *{ev['name']}*")
        lines.append(f"   📍 {venue} · {price_str}" + (f" · {date_str}" if date_str else ""))
        notion_id = ev.get("notion_id", "")
        keyboard_rows.append([InlineKeyboardButton(
            f"✅ Sign me up ({i})",
            callback_data=f"event_register:{notion_id}"
        )])

    message_text = "\n".join(lines)
    if bot and chat_id:
        markup = InlineKeyboardMarkup(keyboard_rows)
        await bot.send_message(chat_id=chat_id, text=message_text,
                               parse_mode="Markdown", reply_markup=markup)
    return message_text
```

- [ ] **Step 3.5: Run scanner tests**

```bash
pytest tests/test_events_scanner.py -v
```

Expected: All green.

- [ ] **Step 3.6: Commit**

```bash
git add agents/social_agent/handler.py tests/test_events_scanner.py
git commit -m "feat: add daily event scanner, intake handler, theme search"
```

---

## Task 4: Playwright Registration Flow

Add `_register_for_event()` to `agents/social_agent/handler.py`. Uses Playwright headless to autofill registration forms. Handles CAPTCHA detection and timeout gracefully.

**Files:**
- Modify: `agents/social_agent/handler.py`
- Create: `tests/test_events_registration.py`

- [ ] **Step 4.1: Write failing tests for registration**

```python
# tests/test_events_registration.py
import pytest
from unittest.mock import patch, MagicMock, AsyncMock


SAMPLE_EVENT = {
    "notion_id": "page-abc",
    "name": "Brooklyn 5K Run",
    "date": "2026-04-05T10:00:00",
    "end_time": "2026-04-05T12:00:00",
    "address": "110 Eastern Pkwy, Brooklyn",
    "rsvp_link": "https://lu.ma/bk5k",
    "category": "Fitness & Outdoors",
    "price": 0,
}


class TestRegisterForEvent:
    def test_register_success_updates_notion_status(self):
        mock_page = MagicMock()
        mock_page.content.return_value = "<html><input name='email'/></html>"
        mock_page.goto = MagicMock()
        mock_page.fill = MagicMock()
        mock_page.click = MagicMock()
        mock_browser = MagicMock()
        mock_browser.new_page.return_value = mock_page
        mock_playwright = MagicMock()
        mock_playwright.__enter__ = MagicMock(return_value=mock_playwright)
        mock_playwright.__exit__ = MagicMock(return_value=False)
        mock_playwright.chromium.launch.return_value = mock_browser

        with patch("agents.social_agent.handler.sync_playwright", return_value=mock_playwright):
            with patch("agents.social_agent.handler.update_event_status") as mock_update:
                with patch("agents.social_agent.handler._check_calendar_conflict", return_value=None):
                    from agents.social_agent.handler import _register_for_event
                    result = _register_for_event(SAMPLE_EVENT)
        assert "success" in result.lower() or "registered" in result.lower() or "going" in result.lower()

    def test_register_captcha_detected_returns_link(self):
        mock_page = MagicMock()
        mock_page.content.return_value = "<html>recaptcha hcaptcha</html>"
        mock_page.goto = MagicMock()
        mock_browser = MagicMock()
        mock_browser.new_page.return_value = mock_page
        mock_playwright = MagicMock()
        mock_playwright.__enter__ = MagicMock(return_value=mock_playwright)
        mock_playwright.__exit__ = MagicMock(return_value=False)
        mock_playwright.chromium.launch.return_value = mock_browser

        with patch("agents.social_agent.handler.sync_playwright", return_value=mock_playwright):
            with patch("agents.social_agent.handler._check_calendar_conflict", return_value=None):
                from agents.social_agent.handler import _register_for_event
                result = _register_for_event(SAMPLE_EVENT)
        assert "captcha" in result.lower() or "manually" in result.lower() or "link" in result.lower()

    def test_register_calendar_conflict_noted_in_result(self):
        with patch("agents.social_agent.handler._check_calendar_conflict", return_value="Work meeting"):
            from agents.social_agent.handler import _register_for_event
            # Just check the conflict is surfaced — don't run Playwright
            result = _register_for_event(SAMPLE_EVENT, skip_playwright=True)
        assert "conflict" in result.lower() or "work meeting" in result.lower() or "calendar" in result.lower()


class TestCheckCalendarConflict:
    def test_no_conflict_returns_none(self):
        with patch("agents.social_agent.handler.list_events", return_value=[]):
            from agents.social_agent.handler import _check_calendar_conflict
            result = _check_calendar_conflict("2026-04-05T10:00:00", "2026-04-05T12:00:00")
        assert result is None

    def test_conflict_returns_event_name(self):
        mock_cal_event = {
            "summary": "Work meeting",
            "start": {"dateTime": "2026-04-05T10:30:00"},
            "end":   {"dateTime": "2026-04-05T11:30:00"},
        }
        with patch("agents.social_agent.handler.list_events", return_value=[mock_cal_event]):
            from agents.social_agent.handler import _check_calendar_conflict
            result = _check_calendar_conflict("2026-04-05T10:00:00", "2026-04-05T12:00:00")
        assert result == "Work meeting"
```

- [ ] **Step 4.2: Run tests to verify they fail**

```bash
pytest tests/test_events_registration.py -v 2>&1 | head -20
```

- [ ] **Step 4.3: Add registration functions to `agents/social_agent/handler.py`**

Add these imports at the top of the file (after existing imports):

```python
import os as _os
from playwright.sync_api import sync_playwright
from integrations.notion.client import update_event_status
from integrations.google.calendar_client import list_events, create_event
```

Add these functions after `run_event_scan_daily()`:

```python
def _check_calendar_conflict(start_iso: str, end_iso: str) -> str | None:
    """
    Check Google Calendar for conflicts in the given time window.
    Returns conflicting event name if found, else None.
    """
    try:
        events = list_events(days_ahead=30)
        start_dt = datetime.datetime.fromisoformat(start_iso)
        end_dt = datetime.datetime.fromisoformat(end_iso) if end_iso else start_dt + datetime.timedelta(hours=2)
        for ev in events:
            ev_start = ev.get("start", {}).get("dateTime") or ev.get("start", {}).get("date", "")
            ev_end   = ev.get("end",   {}).get("dateTime") or ev.get("end",   {}).get("date", "")
            if not ev_start:
                continue
            try:
                es = datetime.datetime.fromisoformat(ev_start.replace("Z", "+00:00")).replace(tzinfo=None)
                ee = datetime.datetime.fromisoformat(ev_end.replace("Z", "+00:00")).replace(tzinfo=None) if ev_end else es + datetime.timedelta(hours=1)
                # Overlap check
                if es < end_dt and ee > start_dt:
                    return ev.get("summary", "Existing event")
            except Exception:
                continue
    except Exception:
        pass
    return None


def _register_for_event(event: dict, skip_playwright: bool = False) -> str:
    """
    Attempt to auto-register for an event using Playwright headless.
    Updates Notion status on success/failure.
    Returns human-readable result string for Telegram.

    skip_playwright=True: only checks calendar conflict, returns early (for testing).
    """
    import pathlib

    name = event.get("name", "Event")
    rsvp_link = event.get("rsvp_link", "")
    notion_id = event.get("notion_id", "")
    start_iso = event.get("date") or ""
    end_iso = event.get("end_time") or ""
    address = event.get("address", "")

    # Calendar check
    conflict = _check_calendar_conflict(start_iso, end_iso) if start_iso else None
    conflict_note = f"\n⚠️ Note: you have '{conflict}' at that time." if conflict else ""

    if skip_playwright:
        return f"Calendar conflict: {conflict}" if conflict else "No conflict"

    # Playwright registration
    user_name = "Justin Ngai"
    user_email = _os.environ.get("JUSTIN_EMAIL", "jngai5.3@gmail.com")
    user_phone = _os.environ.get("JUSTIN_PHONE", "")

    failure_dir = pathlib.Path(__file__).parent.parent.parent / "data" / "reg_failures"
    failure_dir.mkdir(exist_ok=True)

    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(rsvp_link, timeout=30000)
            page.wait_for_load_state("domcontentloaded", timeout=15000)
            content = page.content()

            # CAPTCHA detection
            if any(kw in content.lower() for kw in ["recaptcha", "hcaptcha", "cf-turnstile"]):
                browser.close()
                if notion_id:
                    update_event_status(notion_id, "Interested")
                return (
                    f"⚠️ Couldn't auto-register for **{name}** — CAPTCHA detected.\n"
                    f"Register manually: {rsvp_link}{conflict_note}"
                )

            # Autofill common fields
            field_map = {
                "name":       user_name,
                "full_name":  user_name,
                "first_name": "Justin",
                "last_name":  "Ngai",
                "email":      user_email,
                "phone":      user_phone,
            }
            filled = False
            for attr_val, fill_val in field_map.items():
                if not fill_val:
                    continue
                for selector in [
                    f"input[name='{attr_val}']",
                    f"input[placeholder*='{attr_val}' i]",
                    f"input[id*='{attr_val}' i]",
                ]:
                    try:
                        locator = page.locator(selector)
                        if locator.count() > 0:
                            locator.first.fill(fill_val)
                            filled = True
                    except Exception:
                        pass

            if not filled:
                screenshot_path = failure_dir / f"{notion_id or 'unknown'}.png"
                try:
                    page.screenshot(path=str(screenshot_path))
                except Exception:
                    pass
                browser.close()
                if notion_id:
                    update_event_status(notion_id, "Interested")
                return (
                    f"⚠️ Couldn't find registration fields for **{name}**.\n"
                    f"Register manually: {rsvp_link}{conflict_note}"
                )

            # Submit: look for common submit buttons
            for submit_sel in ["button[type='submit']", "input[type='submit']", "button:has-text('Register')", "button:has-text('RSVP')", "button:has-text('Sign up')"]:
                try:
                    btn = page.locator(submit_sel)
                    if btn.count() > 0:
                        btn.first.click()
                        page.wait_for_load_state("networkidle", timeout=10000)
                        break
                except Exception:
                    pass

            browser.close()

        # Update Notion
        cal_event_id = ""
        if notion_id:
            if address and start_iso:
                try:
                    cal_ev = create_event(name, start_iso, end_iso or "", location=address)
                    cal_event_id = cal_ev.get("id", "")
                except Exception:
                    pass
            update_event_status(notion_id, "Going", registered=True, cal_event_id=cal_event_id)

        return (
            f"✅ Registered for **{name}**! Added to your Google Calendar.{conflict_note}\n"
            f"📍 {address}" if address else f"✅ Registered for **{name}**!{conflict_note}"
        )

    except Exception as e:
        screenshot_path = failure_dir / f"{notion_id or 'unknown'}_err.png"
        if notion_id:
            update_event_status(notion_id, "Interested")
        return (
            f"⚠️ Auto-registration failed for **{name}** ({type(e).__name__}).\n"
            f"Register manually: {rsvp_link}{conflict_note}"
        )
```

- [ ] **Step 4.4: Run registration tests**

```bash
pytest tests/test_events_registration.py -v
```

Expected: All green.

- [ ] **Step 4.5: Commit**

```bash
git add agents/social_agent/handler.py tests/test_events_registration.py
git commit -m "feat: add Playwright calendar-aware auto-registration flow"
```

---

## Task 5: Bot.py Wiring — Inline Keyboards, Post-Event Check, Scheduler

Wire up the Telegram inline keyboard callbacks for event registration and post-event confirmation. Add the daily scanner and post-event check to APScheduler. Update the `event_intake` intent in the command router.

**Files:**
- Modify: `integrations/telegram/bot.py`
- Modify: `core/command_router.py`

- [ ] **Step 5.1: Add `event_intake` intent to `core/command_router.py`**

Open `core/command_router.py`. Find the `INTENTS` list/string in the system prompt and add `event_intake` to it. Also update the classify function's system prompt to include:

```
event_intake: user pastes an event URL (starts with https://) to add to their events tracker
```

The classify function already handles JSON output — just add the new intent to the prompt's intent list.

- [ ] **Step 5.2: Add event callback handler to `integrations/telegram/bot.py`**

Add this import at the top of `bot.py` (with the other agent imports):

```python
from agents.social_agent.handler import (
    handle as social_handle,
    run_event_scan_daily,
    handle_intake,
    _register_for_event,
)
from integrations.notion.client import get_events, update_event_status
```

Replace the existing `run_event_scan` import with `run_event_scan_daily`.

Add this callback handler function (before or after the existing `handle_callback_query`):

```python
async def handle_event_callback(update: Update, context: ContextTypes.DEFAULT_TYPE):
    """Handle inline button callbacks for event registration and post-event confirmation."""
    query = update.callback_query
    await query.answer()
    data = query.data or ""
    chat_id = query.message.chat_id

    if data.startswith("event_register:"):
        notion_id = data.split(":", 1)[1]
        # Fetch event details from Notion
        events = get_events()
        event = next((e for e in events if e.get("notion_id") == notion_id), None)
        if not event:
            await query.edit_message_text("⚠️ Couldn't find that event. It may have been removed.")
            return
        await query.edit_message_text(f"⏳ Registering you for **{event['name']}**...", parse_mode="Markdown")
        result = await asyncio.to_thread(_register_for_event, event)
        await context.bot.send_message(chat_id=chat_id, text=result, parse_mode="Markdown")

    elif data.startswith("event_attended:"):
        notion_id = data.split(":", 1)[1]
        update_event_status(notion_id, "Attended")
        await query.edit_message_text("✅ Great! Marked as attended. Progress updated.")

    elif data.startswith("event_skipped:"):
        notion_id = data.split(":", 1)[1]
        update_event_status(notion_id, "Skipped")
        await query.edit_message_text("👎 No worries — marked as skipped.")
```

- [ ] **Step 5.3: Register the callback handler in `run_bot()` in `bot.py`**

In the `run_bot()` function where other handlers are registered, add:

```python
app.add_handler(CallbackQueryHandler(handle_event_callback, pattern="^event_"))
```

- [ ] **Step 5.4: Add post-event check job to `bot.py`**

Add this function:

```python
async def run_post_event_check(bot, chat_id: str):
    """
    Daily 9:00 AM: find Status=Going events that ended. Ask 'Did you go?'
    Caps at 3 per run to avoid spam.
    """
    import datetime as _dt
    from telegram import InlineKeyboardButton, InlineKeyboardMarkup
    from integrations.notion.client import get_events

    now = _dt.datetime.now()
    events = get_events(status_filter="Going", upcoming_only=False)
    to_check = []
    for ev in events:
        end = ev.get("end_time") or ev.get("date")
        if not end:
            continue
        try:
            end_dt = _dt.datetime.fromisoformat(end)
            days_ago = (now - end_dt).days
            if 0 < days_ago <= 3:
                to_check.append(ev)
        except Exception:
            pass

    for ev in to_check[:3]:
        keyboard = InlineKeyboardMarkup([[
            InlineKeyboardButton("👍 Yes!", callback_data=f"event_attended:{ev['notion_id']}"),
            InlineKeyboardButton("👎 No",   callback_data=f"event_skipped:{ev['notion_id']}"),
        ]])
        date_str = (ev.get("date") or "")[:10]
        await bot.send_message(
            chat_id=chat_id,
            text=f"Did you make it to **{ev['name']}**{' on ' + date_str if date_str else ''}? 🎉",
            parse_mode="Markdown",
            reply_markup=keyboard,
        )
```

- [ ] **Step 5.5: Replace Tue/Fri scheduler job with daily scan + add post-event job**

In `bot.py`, find where APScheduler jobs are registered.

**Remove** the existing `run_event_scan` Tue/Fri job (look for `job_queue.run_repeating` or `scheduler.add_job` referencing `run_event_scan`).

**Add** these two jobs in its place:

```python
# Daily event scan — 8:15 AM ET
job_queue.run_daily(
    lambda ctx: asyncio.create_task(run_event_scan_daily(ctx.bot, JUSTIN_CHAT_ID)),
    time=datetime.time(hour=8, minute=15, tzinfo=ET_TZ),
    name="daily_event_scan",
)

# Post-event confirmation — 9:00 AM ET
job_queue.run_daily(
    lambda ctx: asyncio.create_task(run_post_event_check(ctx.bot, JUSTIN_CHAT_ID)),
    time=datetime.time(hour=9, minute=0, tzinfo=ET_TZ),
    name="post_event_check",
)

# Friend RSVP poll — every 15 minutes
job_queue.run_repeating(
    lambda ctx: asyncio.create_task(_poll_friend_rsvps(ctx.bot, JUSTIN_CHAT_ID)),
    interval=900,  # 15 minutes in seconds
    name="friend_rsvp_poll",
)
```

Note: `JUSTIN_CHAT_ID` and `ET_TZ` should already be defined in `bot.py` — check the existing scheduler setup and match the pattern used.

- [ ] **Step 5.6: Add `_poll_friend_rsvps` to `bot.py`**

```python
async def _poll_friend_rsvps(bot, chat_id: str):
    """Poll Notion every 15 min for new friend RSVPs. Notify Justin on change."""
    import json
    from pathlib import Path
    from integrations.notion.client import get_events, get_friends_going

    cache_path = Path(__file__).parent.parent.parent / "data" / "events_friends_cache.json"
    try:
        cache = json.loads(cache_path.read_text()) if cache_path.exists() else {}
    except Exception:
        cache = {}

    going_events = get_events(status_filter="Going")
    updated = False

    for ev in going_events:
        nid = ev["notion_id"]
        current_friends = get_friends_going(nid)
        prev_friends = cache.get(nid, [])

        new_friends = [f for f in current_friends if f not in prev_friends]
        for friend in new_friends:
            date_str = (ev.get("date") or "")[:10]
            await bot.send_message(
                chat_id=chat_id,
                text=f"🎉 {friend} is joining you for **{ev['name']}**{' on ' + date_str if date_str else ''}!",
                parse_mode="Markdown",
            )

        if current_friends != prev_friends:
            cache[nid] = current_friends
            updated = True

    if updated:
        try:
            cache_path.write_text(json.dumps(cache, indent=2))
        except Exception:
            pass
```

- [ ] **Step 5.7: Handle `event_intake` intent in `bot.py` dispatch**

In the `dispatch()` function (or wherever intents are routed to agents), add a case for `event_intake`:

```python
elif intent == "event_intake":
    url = params.get("url") or message.strip()
    response = handle_intake(url)
```

- [ ] **Step 5.8: Commit**

```bash
git add integrations/telegram/bot.py core/command_router.py
git commit -m "feat: wire event registration callbacks, daily scanner, post-event check"
```

---

## Task 6: FastAPI Events API Endpoints

Add 6 new `/api/events/*` endpoints to `integrations/web/server.py`. These power the dashboard Events tab.

**Files:**
- Modify: `integrations/web/server.py`
- Create: `tests/test_events_api.py`

- [ ] **Step 6.1: Write failing tests for events API**

```python
# tests/test_events_api.py
import pytest
from unittest.mock import patch
from fastapi.testclient import TestClient


@pytest.fixture
def client():
    from integrations.web.server import app
    return TestClient(app)


SAMPLE_EVENTS = [
    {
        "notion_id": "page-1",
        "name": "Brooklyn 5K Run",
        "date": "2026-04-05T10:00:00",
        "end_time": "2026-04-05T12:00:00",
        "venue": "Prospect Park",
        "address": "110 Eastern Pkwy, Brooklyn",
        "neighborhood": "Brooklyn",
        "category": "Fitness & Outdoors",
        "price": 0,
        "source": "Luma",
        "rsvp_link": "https://lu.ma/bk5k",
        "status": "New",
        "registered": False,
        "friends_going": "",
        "cal_event_id": "",
        "notes": "",
    }
]

SAMPLE_PROGRESS = {
    "total_attended": 3,
    "goal": 20,
    "by_category": {"Fitness & Outdoors": 2, "Food & Drinks": 1},
    "heatmap": {"2026-03-10": "Fitness & Outdoors"},
    "categories_tried": ["Fitness & Outdoors", "Food & Drinks"],
    "categories_not_tried": ["Dating & Meetups"],
    "all_categories": ["Fitness & Outdoors", "Dating & Meetups", "Food & Drinks"],
}


class TestGetEvents:
    def test_returns_200_with_events_list(self, client):
        with patch("integrations.web.server.get_events", return_value=SAMPLE_EVENTS):
            resp = client.get("/api/events")
        assert resp.status_code == 200
        data = resp.json()
        assert "events" in data
        assert data["events"][0]["name"] == "Brooklyn 5K Run"

    def test_category_filter_passed_through(self, client):
        with patch("integrations.web.server.get_events", return_value=[]) as mock:
            client.get("/api/events?category=Fitness+%26+Outdoors")
        mock.assert_called_once_with(category_filter="Fitness & Outdoors", upcoming_only=True)

    def test_status_filter_passed_through(self, client):
        with patch("integrations.web.server.get_events", return_value=[]) as mock:
            client.get("/api/events?status=Going")
        mock.assert_called_once_with(status_filter="Going", upcoming_only=True)


class TestGetProgress:
    def test_returns_progress_data(self, client):
        with patch("integrations.web.server.get_progress", return_value=SAMPLE_PROGRESS):
            resp = client.get("/api/events/progress")
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_attended"] == 3
        assert data["goal"] == 20


class TestEventIntakeEndpoint:
    def test_valid_url_returns_success(self, client):
        with patch("integrations.web.server.handle_intake", return_value="✅ Added: Brooklyn 5K Run"):
            resp = client.post("/api/events/intake", json={"url": "https://lu.ma/bk5k"})
        assert resp.status_code == 200
        assert "Brooklyn" in resp.json()["message"]

    def test_missing_url_returns_422(self, client):
        resp = client.post("/api/events/intake", json={})
        assert resp.status_code == 422

    def test_non_url_returns_400(self, client):
        resp = client.post("/api/events/intake", json={"url": "not a url"})
        assert resp.status_code == 400


class TestThemeSearch:
    def test_valid_theme_returns_results(self, client):
        with patch("integrations.web.server.run_theme_search", return_value=[SAMPLE_EVENTS[0]]):
            resp = client.post("/api/events/theme-search", json={"theme": "salsa dancing"})
        assert resp.status_code == 200
        assert "results" in resp.json()

    def test_empty_theme_returns_400(self, client):
        resp = client.post("/api/events/theme-search", json={"theme": ""})
        assert resp.status_code == 400


class TestFriendRsvpEndpoint:
    def test_valid_rsvp_returns_success(self, client):
        with patch("integrations.web.server.add_friend_rsvp", return_value=True):
            resp = client.post("/api/events/friend-rsvp/page-1", json={"name": "Mike"})
        assert resp.status_code == 200

    def test_invalid_name_returns_400(self, client):
        with patch("integrations.web.server.add_friend_rsvp", return_value=False):
            resp = client.post("/api/events/friend-rsvp/page-1", json={"name": "http://spam.com"})
        assert resp.status_code == 400
```

- [ ] **Step 6.2: Run tests to verify they fail**

```bash
pytest tests/test_events_api.py -v 2>&1 | head -30
```

- [ ] **Step 6.3: Add imports to `integrations/web/server.py`**

At the top of `server.py`, add to the imports:

```python
from pydantic import BaseModel

class EventIntakeRequest(BaseModel):
    url: str

class ThemeSearchRequest(BaseModel):
    theme: str

class FriendRsvpRequest(BaseModel):
    name: str
```

Also add these function imports (lazy-imported inside endpoints to avoid circular imports at startup):

The Notion and agent functions will be imported inside each endpoint using `importlib` or direct imports — follow the existing pattern in `server.py` which already uses lazy imports for agent handlers.

- [ ] **Step 6.4: Add the 6 events API endpoints to `integrations/web/server.py`**

Add these endpoints after the existing `@app.get("/api/social")` endpoint:

```python
# ── Events tracker endpoints ───────────────────────────────────────────────────

@app.get("/api/events")
async def api_events(category: str = "", status: str = ""):
    """Upcoming events from Notion, with optional category/status filters."""
    try:
        from integrations.notion.client import get_events
        kwargs = {"upcoming_only": True}
        if category:
            kwargs["category_filter"] = category
        if status:
            kwargs["status_filter"] = status
        events = get_events(**kwargs)
        return JSONResponse({"events": events, "count": len(events)})
    except Exception as e:
        return JSONResponse({"events": [], "count": 0, "error": str(e)})


@app.get("/api/events/progress")
async def api_events_progress():
    """Progress stats: attended count, by category, heatmap, goal."""
    try:
        from integrations.notion.client import get_progress
        return JSONResponse(get_progress())
    except Exception as e:
        return JSONResponse({"total_attended": 0, "goal": 20, "error": str(e)})


@app.post("/api/events/intake")
async def api_events_intake(req: EventIntakeRequest):
    """Parse an event URL and add it to Notion."""
    from fastapi import HTTPException
    if not req.url or not req.url.startswith("http"):
        raise HTTPException(status_code=400, detail="Invalid URL")
    try:
        from agents.social_agent.handler import handle_intake
        result = await _run_sync(handle_intake, req.url)
        return JSONResponse({"message": result, "ok": True})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e), "ok": False})


@app.post("/api/events/rsvp/{notion_id}")
async def api_events_rsvp(notion_id: str):
    """Trigger auto-registration for a specific event."""
    try:
        from integrations.notion.client import get_events
        from agents.social_agent.handler import _register_for_event
        events = get_events(upcoming_only=False)
        event = next((e for e in events if e.get("notion_id") == notion_id), None)
        if not event:
            return JSONResponse(status_code=404, content={"message": "Event not found"})
        result = await _run_sync(_register_for_event, event)
        return JSONResponse({"message": result, "ok": True})
    except Exception as e:
        return JSONResponse(status_code=500, content={"message": str(e), "ok": False})


@app.post("/api/events/theme-search")
async def api_events_theme_search(req: ThemeSearchRequest):
    """Search for events by freeform theme. Does NOT push to Notion."""
    from fastapi import HTTPException
    if not req.theme or not req.theme.strip():
        raise HTTPException(status_code=400, detail="Theme cannot be empty")
    try:
        from agents.social_agent.handler import run_theme_search
        results = await _run_sync(run_theme_search, req.theme.strip())
        return JSONResponse({"results": results, "theme": req.theme, "count": len(results)})
    except Exception as e:
        return JSONResponse(status_code=500, content={"results": [], "error": str(e)})


@app.post("/api/events/add")
async def api_events_add(event: dict):
    """Push a pre-parsed event dict to Notion (used after theme search 'Add' click)."""
    try:
        from integrations.notion.client import push_event
        page_id = await _run_sync(push_event, event)
        if page_id:
            return JSONResponse({"ok": True, "notion_id": page_id})
        return JSONResponse({"ok": False, "message": "Duplicate or save failed"})
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})


@app.post("/api/events/friend-rsvp/{notion_id}")
async def api_friend_rsvp(notion_id: str, req: FriendRsvpRequest):
    """Add a friend's name to the Friends Going field."""
    from fastapi import HTTPException
    try:
        from integrations.notion.client import add_friend_rsvp
        ok = await _run_sync(add_friend_rsvp, notion_id, req.name)
        if not ok:
            raise HTTPException(status_code=400, detail="Invalid name or max friends reached")
        return JSONResponse({"ok": True, "message": f"✅ {req.name} added! See you there."})
    except HTTPException:
        raise
    except Exception as e:
        return JSONResponse(status_code=500, content={"ok": False, "error": str(e)})
```

- [ ] **Step 6.5: Add `/friends` route to `server.py`**

```python
@app.get("/friends", response_class=HTMLResponse)
async def friends_page():
    """Serve the friend collaboration page."""
    friends_html = STATIC_DIR / "friends.html"
    if friends_html.exists():
        return HTMLResponse(friends_html.read_text())
    return HTMLResponse("<h1>Friends page coming soon</h1>")
```

- [ ] **Step 6.6: Run API tests**

```bash
pytest tests/test_events_api.py -v
```

Expected: All green.

- [ ] **Step 6.7: Commit**

```bash
git add integrations/web/server.py tests/test_events_api.py
git commit -m "feat: add /api/events/* endpoints and /friends route to FastAPI server"
```

---

## Task 7: Dashboard Events Tab (Frontend)

Add the Events tab to `integrations/web/static/index.html`. Follows the exact dark-theme CSS already in the file.

**Files:**
- Modify: `integrations/web/static/index.html`

- [ ] **Step 7.1: Add the Events nav tab button**

In `index.html`, find the nav/tab bar (look for existing agent tab buttons). Add an Events tab button in the same style:

```html
<button class="tab-btn" data-tab="events" onclick="showTab('events')">🗓 Events</button>
```

- [ ] **Step 7.2: Add the Events tab panel to `index.html`**

After the last existing tab panel `<div>`, add:

```html
<!-- ── Events Tab ────────────────────────────────────────────────────────── -->
<div id="tab-events" class="tab-panel" style="display:none">

  <!-- Progress Section -->
  <div class="card" style="margin-bottom:.7rem">
    <div class="card-top-bar bar-green"></div>
    <div class="card-head"><span class="card-name"><span class="dot dot-green"></span>2026 Events Goal</span><span id="events-goal-chip" class="chip">Loading…</span></div>
    <div id="events-goal-bar-wrap" style="background:#1e3a52;border-radius:4px;height:6px;margin:.4rem 0">
      <div id="events-goal-bar" style="background:linear-gradient(90deg,#38bdf8,#4ade80);height:6px;border-radius:4px;width:0%;transition:width .4s"></div>
    </div>
    <div id="events-cat-grid" style="display:grid;grid-template-columns:repeat(auto-fill,minmax(160px,1fr));gap:.4rem;margin-top:.5rem"></div>
    <div id="events-nudge" style="margin-top:.5rem;display:none;background:#172c43;border:1px solid #1e6a52;border-radius:6px;padding:.5rem .7rem;font-size:.72rem;color:#34d399"></div>
  </div>

  <!-- Theme Search Section -->
  <div class="card" style="margin-bottom:.7rem">
    <div class="card-top-bar bar-warn"></div>
    <div class="card-head"><span class="card-name">🔍 Theme Search</span></div>
    <div style="display:flex;gap:.4rem;margin-bottom:.5rem">
      <input id="theme-input" type="text" placeholder="salsa dancing, pottery, chess club…"
        style="flex:1;background:#112236;border:1px solid #1e3a52;border-radius:6px;padding:.4rem .6rem;color:#e2e8f0;font-size:.75rem"
        onkeydown="if(event.key==='Enter')searchTheme()" />
      <button onclick="searchTheme()" style="background:#38bdf8;border:none;border-radius:6px;color:#070e1a;font-size:.72rem;font-weight:700;padding:.4rem .8rem;cursor:pointer">Search →</button>
    </div>
    <div style="display:flex;gap:.35rem;flex-wrap:wrap;margin-bottom:.6rem" id="theme-chips">
      <span class="chip" style="cursor:pointer" onclick="document.getElementById('theme-input').value=this.textContent;searchTheme()">salsa dancing</span>
      <span class="chip" style="cursor:pointer" onclick="document.getElementById('theme-input').value=this.textContent;searchTheme()">sake tasting</span>
      <span class="chip" style="cursor:pointer" onclick="document.getElementById('theme-input').value=this.textContent;searchTheme()">chess club</span>
      <span class="chip" style="cursor:pointer" onclick="document.getElementById('theme-input').value=this.textContent;searchTheme()">improv comedy</span>
      <span class="chip" style="cursor:pointer" onclick="document.getElementById('theme-input').value=this.textContent;searchTheme()">singles hiking</span>
    </div>
    <div id="theme-results" style="display:none">
      <div style="font-size:.65rem;color:#6b8099;margin-bottom:.4rem" id="theme-results-label"></div>
      <div id="theme-results-list" style="display:flex;flex-direction:column;gap:.4rem"></div>
    </div>
    <div id="theme-loading" style="display:none;font-size:.72rem;color:#6b8099">Searching…</div>
  </div>

  <!-- Event Feed -->
  <div class="card">
    <div class="card-top-bar bar-ok"></div>
    <div class="card-head"><span class="card-name">🗓 Upcoming Events</span><button onclick="loadEvents()" style="background:#112236;border:1px solid #1e3a52;color:#6b8099;padding:.2rem .5rem;border-radius:6px;font-size:.65rem;cursor:pointer">↻ Refresh</button></div>

    <!-- URL Drop Box -->
    <div style="display:flex;gap:.4rem;margin-bottom:.5rem">
      <input id="intake-url" type="text" placeholder="Paste any event link to add it…"
        style="flex:1;background:#112236;border:1px dashed #1e3a52;border-radius:6px;padding:.4rem .6rem;color:#6b8099;font-size:.72rem"
        onkeydown="if(event.key==='Enter')addEventUrl()" />
      <button onclick="addEventUrl()" style="background:#172c43;border:1px solid #1e3a52;border-radius:6px;color:#38bdf8;font-size:.72rem;padding:.4rem .7rem;cursor:pointer">Add ↵</button>
    </div>
    <div id="intake-msg" style="font-size:.7rem;margin-bottom:.4rem;display:none"></div>

    <!-- Filter Pills -->
    <div id="events-filters" style="display:flex;gap:.3rem;flex-wrap:wrap;margin-bottom:.5rem">
      <span class="chip" style="cursor:pointer;background:#1e3a52;color:#38bdf8" onclick="filterEvents('')">All</span>
      <span class="chip" style="cursor:pointer" onclick="filterEvents('Going')">Going ✓</span>
      <span class="chip" style="cursor:pointer" onclick="filterEvents('New')">New</span>
      <span class="chip" style="cursor:pointer" onclick="filterEvents('Fitness & Outdoors')">💪</span>
      <span class="chip" style="cursor:pointer" onclick="filterEvents('Dating & Meetups')">💘</span>
      <span class="chip" style="cursor:pointer" onclick="filterEvents('Food & Drinks')">🍜</span>
      <span class="chip" style="cursor:pointer" onclick="filterEvents('Painting & Visual Arts')">🎨</span>
      <span class="chip" style="cursor:pointer" onclick="filterEvents('Ceramics & Crafts')">🏺</span>
      <span class="chip" style="cursor:pointer" onclick="filterEvents('Games & Trivia')">🎲</span>
      <span class="chip" style="cursor:pointer" onclick="filterEvents('Performing Arts')">🎭</span>
      <span class="chip" style="cursor:pointer" onclick="filterEvents('Community & Clubs')">🤝</span>
    </div>

    <div id="events-feed" style="display:flex;flex-direction:column;gap:.5rem">
      <div style="font-size:.72rem;color:#6b8099">Loading events…</div>
    </div>
  </div>
</div>
```

- [ ] **Step 7.3: Add Events tab JavaScript to `index.html`**

In the `<script>` section at the bottom of `index.html`, add:

```javascript
// ── Events Tab ─────────────────────────────────────────────────────────────

let _allEvents = [];
const CAT_EMOJI = {
  "Fitness & Outdoors":"💪","Dating & Meetups":"💘","Food & Drinks":"🍜",
  "Painting & Visual Arts":"🎨","Ceramics & Crafts":"🏺","Games & Trivia":"🎲",
  "Performing Arts":"🎭","Community & Clubs":"🤝","Professional":"💼","Nightlife":"🎉"
};
const CAT_COLOR = {
  "Fitness & Outdoors":"#4ade80","Dating & Meetups":"#f472b6","Food & Drinks":"#fb923c",
  "Painting & Visual Arts":"#a78bfa","Ceramics & Crafts":"#fbbf24","Games & Trivia":"#34d399",
  "Performing Arts":"#f87171","Community & Clubs":"#38bdf8","Professional":"#94a3b8","Nightlife":"#e879f9"
};

async function loadEventsProgress() {
  try {
    const r = await fetch('/api/events/progress');
    const d = await r.json();
    const pct = Math.min(100, Math.round((d.total_attended / d.goal) * 100));
    document.getElementById('events-goal-chip').textContent = `${d.total_attended} / ${d.goal} events`;
    document.getElementById('events-goal-bar').style.width = pct + '%';

    const grid = document.getElementById('events-cat-grid');
    grid.innerHTML = '';
    (d.all_categories || []).forEach(cat => {
      const count = (d.by_category || {})[cat] || 0;
      const color = CAT_COLOR[cat] || '#6b8099';
      const emoji = CAT_EMOJI[cat] || '📌';
      const bar_pct = Math.min(100, count * 20);
      grid.innerHTML += `<div style="background:#112236;border:1px solid #1e3a52;border-radius:6px;padding:.4rem .5rem">
        <div style="display:flex;justify-content:space-between;align-items:center;margin-bottom:3px">
          <span style="font-size:.7rem">${emoji} ${cat.split(' ')[0]}</span>
          <span style="font-size:.72rem;font-weight:700;color:${color}">${count}</span>
        </div>
        <div style="background:#1e3a52;border-radius:2px;height:3px">
          <div style="background:${color};width:${bar_pct}%;height:3px;border-radius:2px"></div>
        </div>
      </div>`;
    });

    const nudge = document.getElementById('events-nudge');
    if (d.categories_not_tried && d.categories_not_tried.length > 0) {
      const cats = d.categories_not_tried.slice(0,3).map(c => `${CAT_EMOJI[c]||''} ${c}`).join(', ');
      nudge.textContent = `🎯 Not tried yet: ${cats} — check the feed for matching events`;
      nudge.style.display = 'block';
    }
  } catch(e) { console.error('Progress load error', e); }
}

async function loadEvents(statusFilter='', categoryFilter='') {
  const feed = document.getElementById('events-feed');
  feed.innerHTML = '<div style="font-size:.72rem;color:#6b8099">Loading…</div>';
  try {
    let url = '/api/events?';
    if (categoryFilter) url += `category=${encodeURIComponent(categoryFilter)}&`;
    if (statusFilter)   url += `status=${encodeURIComponent(statusFilter)}&`;
    const r = await fetch(url);
    const d = await r.json();
    _allEvents = d.events || [];
    renderEvents(_allEvents);
  } catch(e) {
    feed.innerHTML = '<div style="font-size:.72rem;color:#f87171">Failed to load events.</div>';
  }
}

function renderEvents(events) {
  const feed = document.getElementById('events-feed');
  if (!events.length) {
    feed.innerHTML = '<div style="font-size:.72rem;color:#6b8099">No events found.</div>';
    return;
  }
  feed.innerHTML = events.map(ev => {
    const emoji = CAT_EMOJI[ev.category] || '📌';
    const color = CAT_COLOR[ev.category] || '#6b8099';
    const price = ev.price === 0 ? 'Free' : `$${ev.price}`;
    const dateStr = ev.date ? ev.date.slice(0,10) : '';
    const timeStr = ev.date && ev.date.length > 10 ? ev.date.slice(11,16) : '';
    const statusBadge = ev.status === 'Going'
      ? `<span style="background:#1a2d25;border-radius:4px;padding:1px 5px;font-size:.65rem;color:#4ade80">Going ✓</span>`
      : ev.status === 'New'
        ? `<span style="background:#172c43;border-radius:4px;padding:1px 5px;font-size:.65rem;color:#fbbf24">New</span>`
        : `<span style="background:#1a2030;border-radius:4px;padding:1px 5px;font-size:.65rem;color:#6b8099">${ev.status}</span>`;
    const friendsBadge = ev.friends_going
      ? `<span style="font-size:.65rem;color:#f472b6">👥 ${ev.friends_going}</span>` : '';
    return `<div style="background:#112236;border:1px solid #1e3a52;border-radius:8px;padding:.55rem .7rem;display:flex;gap:.6rem;align-items:flex-start">
      <div style="background:#172c43;border-radius:4px;padding:.2rem .35rem;text-align:center;min-width:30px;flex-shrink:0">
        <div style="font-size:.55rem;color:#38bdf8;font-weight:700">${dateStr.slice(5,7)? ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'][parseInt(dateStr.slice(5,7))-1] : ''}</div>
        <div style="font-size:.85rem;font-weight:800;color:#e2e8f0">${dateStr.slice(8,10)||'?'}</div>
      </div>
      <div style="flex:1;min-width:0">
        <div style="font-size:.78rem;font-weight:600;white-space:nowrap;overflow:hidden;text-overflow:ellipsis">${ev.name}</div>
        <div style="font-size:.68rem;color:#6b8099;margin-top:.15rem">${ev.address || ev.venue || ''}${timeStr ? ' · '+timeStr : ''} · ${price} · ${ev.source||''}</div>
        <div style="display:flex;gap:.3rem;margin-top:.25rem;flex-wrap:wrap;align-items:center">
          <span style="background:#1a1a2e;border-radius:4px;padding:1px 5px;font-size:.65rem;color:${color}">${emoji} ${ev.category||''}</span>
          ${statusBadge}
          ${friendsBadge}
        </div>
      </div>
      <div style="display:flex;flex-direction:column;gap:.3rem;flex-shrink:0">
        ${ev.status !== 'Going' && ev.status !== 'Attended' ? `<button onclick="signMeUp('${ev.notion_id}')" style="background:#38bdf8;border:none;border-radius:5px;color:#070e1a;font-size:.65rem;font-weight:700;padding:.25rem .5rem;cursor:pointer">Sign me up</button>` : ''}
        ${ev.rsvp_link ? `<a href="${ev.rsvp_link}" target="_blank" style="background:#1e3a52;border-radius:5px;color:#38bdf8;font-size:.65rem;padding:.25rem .5rem;text-decoration:none;text-align:center">RSVP →</a>` : ''}
      </div>
    </div>`;
  }).join('');
}

function filterEvents(filter) {
  if (!filter) { renderEvents(_allEvents); return; }
  const filtered = _allEvents.filter(e => e.status === filter || e.category === filter);
  renderEvents(filtered);
}

async function signMeUp(notionId) {
  if (!confirm('Register you for this event?')) return;
  try {
    const r = await fetch(`/api/events/rsvp/${notionId}`, {method:'POST'});
    const d = await r.json();
    alert(d.message || 'Done!');
    loadEvents();
  } catch(e) { alert('Registration failed. Try the RSVP link directly.'); }
}

async function addEventUrl() {
  const url = document.getElementById('intake-url').value.trim();
  const msg = document.getElementById('intake-msg');
  if (!url) return;
  msg.style.display = 'block';
  msg.style.color = '#6b8099';
  msg.textContent = 'Adding…';
  try {
    const r = await fetch('/api/events/intake', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({url})
    });
    const d = await r.json();
    msg.style.color = d.ok ? '#4ade80' : '#f87171';
    msg.textContent = d.message || (d.ok ? 'Added!' : 'Failed');
    if (d.ok) { document.getElementById('intake-url').value=''; loadEvents(); }
  } catch(e) { msg.style.color='#f87171'; msg.textContent='Error adding event.'; }
}

async function searchTheme() {
  const theme = document.getElementById('theme-input').value.trim();
  if (!theme) return;
  document.getElementById('theme-loading').style.display = 'block';
  document.getElementById('theme-results').style.display = 'none';
  try {
    const r = await fetch('/api/events/theme-search', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify({theme})
    });
    const d = await r.json();
    document.getElementById('theme-loading').style.display = 'none';
    const results = d.results || [];
    const label = document.getElementById('theme-results-label');
    const list = document.getElementById('theme-results-list');
    label.textContent = `${results.length} result${results.length!==1?'s':''} for "${theme}"`;
    list.innerHTML = results.map((ev,i) => {
      const price = ev.price===0?'Free':`$${ev.price}`;
      const dateStr = (ev.date||'').slice(0,10);
      return `<div style="background:#112236;border:1px solid #1e3a52;border-radius:7px;padding:.5rem .6rem;display:flex;justify-content:space-between;align-items:center;gap:.5rem">
        <div>
          <div style="font-size:.75rem;font-weight:600">${ev.name}</div>
          <div style="font-size:.67rem;color:#6b8099">${dateStr} · ${ev.address||ev.venue||''} · ${price}</div>
          <div style="font-size:.67rem;color:#6b8099">📌 ${ev.source||''} · ${ev.category||''}</div>
        </div>
        <button onclick="addThemeEvent(${i})" style="background:#1e3a52;border:none;border-radius:5px;color:#38bdf8;font-size:.67rem;padding:.25rem .55rem;cursor:pointer;white-space:nowrap">+ Add</button>
      </div>`;
    }).join('');
    document.getElementById('theme-results').style.display = 'block';
    window._themeResults = results;
  } catch(e) {
    document.getElementById('theme-loading').style.display='none';
    document.getElementById('theme-results-label').textContent='Search failed.';
    document.getElementById('theme-results').style.display='block';
  }
}

async function addThemeEvent(idx) {
  const ev = (window._themeResults||[])[idx];
  if (!ev) return;
  try {
    const r = await fetch('/api/events/add', {
      method:'POST', headers:{'Content-Type':'application/json'},
      body: JSON.stringify(ev)
    });
    const d = await r.json();
    if (d.ok) { alert(`✅ Added: ${ev.name}`); loadEvents(); }
    else alert(d.message || 'Could not add event.');
  } catch(e) { alert('Failed to add event.'); }
}

// Load events when Events tab is shown
const _origShowTab = typeof showTab === 'function' ? showTab : null;
// Hook into tab switching — load events data when events tab is selected
document.addEventListener('DOMContentLoaded', () => {
  const evTabBtn = document.querySelector('[data-tab="events"]');
  if (evTabBtn) {
    evTabBtn.addEventListener('click', () => {
      loadEventsProgress();
      loadEvents();
    });
  }
});
```

- [ ] **Step 7.4: Verify the dashboard starts without JS errors**

```bash
cd /Users/justinngai/workspace/executive-ai-assistant
source venv/bin/activate
python -c "from integrations.web.server import app; print('OK')"
```

Expected: `OK`

- [ ] **Step 7.5: Commit**

```bash
git add integrations/web/static/index.html
git commit -m "feat: add Events tab to dashboard (progress, theme search, feed)"
```

---

## Task 8: Friends Page

Create `integrations/web/static/friends.html` — a standalone page friends can open to see upcoming events and RSVP.

**Files:**
- Create: `integrations/web/static/friends.html`

- [ ] **Step 8.1: Create the friends page**

```html
<!-- integrations/web/static/friends.html -->
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8"/>
<meta name="viewport" content="width=device-width,initial-scale=1"/>
<title>Justin's NYC Events — Join Me!</title>
<style>
*{box-sizing:border-box;margin:0;padding:0}
body{background:#070e1a;color:#e2e8f0;font-family:-apple-system,BlinkMacSystemFont,"Segoe UI",sans-serif;min-height:100vh;padding:1rem}
header{text-align:center;padding:1.5rem 1rem;margin-bottom:1.5rem}
header h1{font-size:1.2rem;font-weight:800;color:#38bdf8}
header p{font-size:.85rem;color:#6b8099;margin-top:.3rem}
.event-card{background:#0d1b2a;border:1px solid #1e3a52;border-radius:12px;padding:1rem 1.1rem;margin-bottom:.8rem;max-width:620px;margin-left:auto;margin-right:auto}
.event-name{font-size:.95rem;font-weight:700;margin-bottom:.3rem}
.event-meta{font-size:.78rem;color:#6b8099;margin-bottom:.5rem;line-height:1.6}
.event-meta strong{color:#e2e8f0}
.badges{display:flex;gap:.4rem;flex-wrap:wrap;margin-bottom:.7rem}
.badge{display:inline-block;border-radius:5px;padding:2px 8px;font-size:.7rem}
.rsvp-btn{display:inline-block;background:#1e3a52;border-radius:7px;color:#38bdf8;font-size:.78rem;padding:.4rem .8rem;text-decoration:none;margin-right:.4rem}
.join-form{margin-top:.8rem;padding-top:.8rem;border-top:1px solid #1e3a52;display:flex;gap:.4rem}
.join-input{flex:1;background:#112236;border:1px solid #1e3a52;border-radius:7px;padding:.4rem .6rem;color:#e2e8f0;font-size:.78rem}
.join-btn{background:#f472b6;border:none;border-radius:7px;color:#0d1b2a;font-size:.78rem;font-weight:700;padding:.4rem .8rem;cursor:pointer}
.join-success{font-size:.75rem;color:#4ade80;margin-top:.4rem}
.no-events{text-align:center;padding:3rem 1rem;color:#6b8099;font-size:.85rem}
</style>
</head>
<body>

<header>
  <h1>🗓 Justin's NYC Events</h1>
  <p>Upcoming events Justin is going to — join him!</p>
</header>

<div id="events-container">
  <div class="no-events">Loading events…</div>
</div>

<script>
const CAT_EMOJI = {
  "Fitness & Outdoors":"💪","Dating & Meetups":"💘","Food & Drinks":"🍜",
  "Painting & Visual Arts":"🎨","Ceramics & Crafts":"🏺","Games & Trivia":"🎲",
  "Performing Arts":"🎭","Community & Clubs":"🤝","Professional":"💼","Nightlife":"🎉"
};
const CAT_COLOR = {
  "Fitness & Outdoors":"#4ade80","Dating & Meetups":"#f472b6","Food & Drinks":"#fb923c",
  "Painting & Visual Arts":"#a78bfa","Ceramics & Crafts":"#fbbf24","Games & Trivia":"#34d399",
  "Performing Arts":"#f87171","Community & Clubs":"#38bdf8","Professional":"#94a3b8","Nightlife":"#e879f9"
};
const MONTHS = ['JAN','FEB','MAR','APR','MAY','JUN','JUL','AUG','SEP','OCT','NOV','DEC'];

async function loadEvents() {
  try {
    const r = await fetch('/api/events?status=Going');
    const d = await r.json();
    const events = d.events || [];
    const container = document.getElementById('events-container');

    if (!events.length) {
      container.innerHTML = '<div class="no-events">No upcoming events yet. Check back soon!</div>';
      return;
    }

    container.innerHTML = events.map(ev => {
      const dateStr = (ev.date || '').slice(0,10);
      const timeStr = ev.date && ev.date.length > 10 ? ev.date.slice(11,16) : '';
      const monthIdx = dateStr ? parseInt(dateStr.slice(5,7)) - 1 : -1;
      const day = dateStr ? dateStr.slice(8,10) : '?';
      const price = ev.price === 0 ? 'Free' : `$${ev.price}`;
      const emoji = CAT_EMOJI[ev.category] || '📌';
      const color = CAT_COLOR[ev.category] || '#6b8099';
      const friends = ev.friends_going ? ev.friends_going.split(',').map(s=>s.trim()).filter(Boolean) : [];
      const friendsStr = friends.length ? `👥 ${friends.join(', ')} going` : '';

      return `<div class="event-card" id="card-${ev.notion_id}">
        <div style="display:flex;gap:.7rem;align-items:flex-start;margin-bottom:.4rem">
          <div style="background:#172c43;border-radius:5px;padding:.2rem .4rem;text-align:center;min-width:34px;flex-shrink:0">
            <div style="font-size:.6rem;color:#38bdf8;font-weight:700">${monthIdx>=0?MONTHS[monthIdx]:''}</div>
            <div style="font-size:1rem;font-weight:800">${day}</div>
          </div>
          <div>
            <div class="event-name">${ev.name}</div>
            <div class="event-meta">
              ${ev.address ? `<strong>📍</strong> ${ev.address}<br>` : ev.venue ? `<strong>📍</strong> ${ev.venue}<br>` : ''}
              ${timeStr ? `<strong>🕐</strong> ${timeStr} &nbsp;` : ''}
              <strong>💰</strong> ${price} &nbsp;
              <strong>📌</strong> ${ev.source || ''}
              ${friendsStr ? `<br><span style="color:#f472b6">${friendsStr}</span>` : ''}
            </div>
          </div>
        </div>
        <div class="badges">
          <span class="badge" style="background:#1a1a2e;color:${color}">${emoji} ${ev.category||''}</span>
          <span class="badge" style="background:#1a2d25;color:#4ade80">Going ✓</span>
        </div>
        ${ev.rsvp_link ? `<a href="${ev.rsvp_link}" target="_blank" class="rsvp-btn">Get tickets →</a>` : ''}
        <div class="join-form">
          <input class="join-input" type="text" placeholder="Your name" id="name-${ev.notion_id}" maxlength="40" />
          <button class="join-btn" onclick="joinEvent('${ev.notion_id}')">I'm in! 🙋</button>
        </div>
        <div class="join-success" id="success-${ev.notion_id}" style="display:none"></div>
      </div>`;
    }).join('');
  } catch(e) {
    document.getElementById('events-container').innerHTML =
      '<div class="no-events">Couldn\'t load events. Try refreshing.</div>';
  }
}

async function joinEvent(notionId) {
  const input = document.getElementById(`name-${notionId}`);
  const name = input.value.trim();
  if (!name) { input.focus(); return; }
  try {
    const r = await fetch(`/api/events/friend-rsvp/${notionId}`, {
      method: 'POST',
      headers: {'Content-Type': 'application/json'},
      body: JSON.stringify({name})
    });
    const d = await r.json();
    const msg = document.getElementById(`success-${notionId}`);
    if (d.ok) {
      msg.textContent = d.message || `✅ You're in, ${name}! Justin will be notified.`;
      msg.style.display = 'block';
      input.value = '';
      input.disabled = true;
      document.querySelector(`#card-${notionId} .join-btn`).disabled = true;
    } else {
      msg.style.color = '#f87171';
      msg.textContent = d.detail || 'Could not add you. Try again.';
      msg.style.display = 'block';
    }
  } catch(e) {
    const msg = document.getElementById(`success-${notionId}`);
    msg.style.color = '#f87171';
    msg.textContent = 'Network error. Try refreshing.';
    msg.style.display = 'block';
  }
}

loadEvents();
</script>

</body>
</html>
```

- [ ] **Step 8.2: Verify the page renders (visual check)**

With the FastAPI server running, open `http://localhost:8080/friends` in a browser. Confirm the page loads with the dark theme, event cards (or "no events" message), and the "I'm in!" form per card.

- [ ] **Step 8.3: Commit**

```bash
git add integrations/web/static/friends.html
git commit -m "feat: add /friends collaboration page for sharing events"
```

---

## Task 9: Integration Smoke Test + Social Agent Status Update

Update `_social_status()` in `server.py` to reflect the new events data. Smoke-test the full flow end-to-end.

**Files:**
- Modify: `integrations/web/server.py`

- [ ] **Step 9.1: Update `_social_status()` in `server.py`**

Find the existing `_social_status()` function and replace it with:

```python
def _social_status():
    try:
        from integrations.notion.client import get_progress, _events_db_id
        if not _events_db_id():
            return {"label": "Events", "icon": "🗓", "status": "gray", "summary": "Run bootstrap script first"}
        progress = get_progress()
        total = progress.get("total_attended", 0)
        goal = progress.get("goal", 20)
        tried = len(progress.get("categories_tried", []))
        return {
            "label":   "Events",
            "icon":    "🗓",
            "status":  "ok" if total > 0 else "gray",
            "summary": f"{total}/{goal} events attended · {tried}/10 categories tried",
        }
    except Exception:
        return {"label": "Events", "icon": "🗓", "status": "gray", "summary": "Daily scan 8:15 AM ET"}
```

- [ ] **Step 9.2: Run the full test suite**

```bash
cd /Users/justinngai/workspace/executive-ai-assistant
pytest tests/ -v --tb=short 2>&1 | tail -30
```

Expected: All existing tests still pass; new tests pass.

- [ ] **Step 9.3: Run the bootstrap script against real Notion (manual step)**

```bash
python scripts/notion_events_bootstrap.py
```

Copy the printed `NOTION_EVENTS_DB_ID` into `.env`.

- [ ] **Step 9.4: Smoke-test `handle_intake` with a real Luma URL**

```bash
python -c "
import os; os.environ['NOTION_API_KEY']='your-key'; os.environ['NOTION_EVENTS_DB_ID']='your-db-id'
from agents.social_agent.handler import handle_intake
print(handle_intake('https://lu.ma/nyc'))
"
```

Expected: Either "Added: [event name]" or "Already tracking".

- [ ] **Step 9.5: Final commit**

```bash
git add integrations/web/server.py
git commit -m "feat: update social status tile to show events progress"
```

---

## Task 10: .env Documentation Update

- [ ] **Step 10.1: Add new env vars to the `.env.example` or README**

Ensure these two new keys are documented (add to `.env` file and any existing `.env.example`):

```
NOTION_EVENTS_DB_ID=          # from notion_events_bootstrap.py
JUSTIN_PHONE=                  # optional, for Playwright phone autofill
```

- [ ] **Step 10.2: Commit**

```bash
git add .env.example  # or wherever env vars are documented
git commit -m "docs: document new NOTION_EVENTS_DB_ID and JUSTIN_PHONE env vars"
```

---

## Execution Order

Run tasks in this order — each task's output is required by the next:

1. Task 1 (Notion client) → 2 (Bootstrap) → 3 (Scanner) → 4 (Registration) → 5 (Bot wiring) → 6 (API) → 7 (Dashboard UI) → 8 (Friends page) → 9 (Smoke test) → 10 (Docs)

Tasks 3 and 4 can be worked in parallel if splitting work across engineers, but Task 1 must complete first.
