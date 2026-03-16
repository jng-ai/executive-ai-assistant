"""
Run this once to create all Notion databases.
Usage: python -m integrations.notion.setup
"""

import os
import sys
from pathlib import Path
sys.path.insert(0, str(Path(__file__).parent.parent.parent))

from dotenv import load_dotenv
load_dotenv(Path(__file__).parent.parent.parent / ".env")

from integrations.notion.client import setup_databases, is_configured

if __name__ == "__main__":
    if not is_configured():
        print("Missing NOTION_API_KEY or NOTION_PARENT_PAGE_ID in .env")
        sys.exit(1)

    print("Setting up Notion databases...")
    db_ids = setup_databases()

    if db_ids:
        print(f"\n✅ Created {len(db_ids)} databases:")
        for key, db_id in db_ids.items():
            print(f"  • {key}: {db_id}")
        print("\nAll agents will now sync to Notion automatically.")
    else:
        print("No databases created. Check your API key and page permissions.")
