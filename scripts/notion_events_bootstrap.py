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
