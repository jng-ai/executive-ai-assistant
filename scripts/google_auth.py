"""
One-time Google OAuth2 authorization script.
Run this once to get your refresh token, then add it to .env.

Usage:
  cd /Users/justinngai/workspace/executive-ai-assistant
  python scripts/google_auth.py
"""

import os
import sys
from pathlib import Path

# Add project root to path
sys.path.insert(0, str(Path(__file__).parent.parent))

from dotenv import load_dotenv
load_dotenv()

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]

import glob

# Try to use downloaded JSON file first (most reliable)
json_files = sorted(glob.glob(str(Path.home() / "Downloads" / "client_secret_*.json")), key=os.path.getmtime, reverse=True)

if json_files:
    print(f"Using credentials file: {json_files[0]}")
    flow = InstalledAppFlow.from_client_secrets_file(json_files[0], SCOPES)
else:
    CLIENT_ID = os.environ.get("GOOGLE_CLIENT_ID", "")
    CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    if not CLIENT_ID or not CLIENT_SECRET:
        print("ERROR: No credentials JSON found in Downloads and no .env credentials set")
        sys.exit(1)
    client_config = {
        "installed": {
            "client_id": CLIENT_ID,
            "client_secret": CLIENT_SECRET,
            "redirect_uris": ["urn:ietf:wg:oauth:2.0:oob", "http://localhost"],
            "auth_uri": "https://accounts.google.com/o/oauth2/auth",
            "token_uri": "https://oauth2.googleapis.com/token",
        }
    }
    flow = InstalledAppFlow.from_client_config(client_config, SCOPES)
creds = flow.run_local_server(port=0)

print("\n" + "="*60)
print("✅ Authorization successful!")
print("="*60)
print(f"\nAdd this to your .env file:\n")
print(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")
print("\n" + "="*60)

# Auto-append to .env if it exists
env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    content = env_path.read_text()
    if "GOOGLE_REFRESH_TOKEN" not in content:
        with open(env_path, "a") as f:
            f.write(f"\nGOOGLE_REFRESH_TOKEN={creds.refresh_token}\n")
        print(f"✅ Also auto-added to {env_path}")
    else:
        # Update existing
        lines = content.splitlines()
        new_lines = []
        for line in lines:
            if line.startswith("GOOGLE_REFRESH_TOKEN="):
                new_lines.append(f"GOOGLE_REFRESH_TOKEN={creds.refresh_token}")
            else:
                new_lines.append(line)
        env_path.write_text("\n".join(new_lines) + "\n")
        print(f"✅ Updated GOOGLE_REFRESH_TOKEN in {env_path}")
