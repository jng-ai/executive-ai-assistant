"""
One-time OAuth2 authorization for the jngai5.3@gmail.com account.
Saves token as GOOGLE_REFRESH_TOKEN_JNGAI53 in .env.

Usage:
  cd /Users/justinngai/workspace/executive-ai-assistant
  python scripts/google_auth_jngai53.py

When the browser opens, make sure to log in as jngai5.3@gmail.com.
"""

import os
import sys
import glob
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
from dotenv import load_dotenv
load_dotenv()

from google_auth_oauthlib.flow import InstalledAppFlow

SCOPES = [
    "https://www.googleapis.com/auth/gmail.modify",
    "https://www.googleapis.com/auth/gmail.send",
]

ENV_KEY = "GOOGLE_REFRESH_TOKEN_JNGAI53"

print("=" * 60)
print("Authorizing jngai5.3@gmail.com")
print("When the browser opens, make sure to sign in as jngai5.3@gmail.com")
print("=" * 60)

json_files = sorted(
    glob.glob(str(Path.home() / "Downloads" / "client_secret_*.json")),
    key=os.path.getmtime, reverse=True
)

if json_files:
    print(f"Using credentials file: {json_files[0]}")
    flow = InstalledAppFlow.from_client_secrets_file(json_files[0], SCOPES)
else:
    CLIENT_ID     = os.environ.get("GOOGLE_CLIENT_ID", "")
    CLIENT_SECRET = os.environ.get("GOOGLE_CLIENT_SECRET", "")
    if not CLIENT_ID or not CLIENT_SECRET:
        print("ERROR: No client_secret JSON in Downloads and no .env credentials")
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

print("\n" + "=" * 60)
print("Authorization successful!")
print("=" * 60)
print(f"\nAdd this to your .env:\n{ENV_KEY}={creds.refresh_token}\n")

env_path = Path(__file__).parent.parent / ".env"
if env_path.exists():
    content = env_path.read_text()
    if ENV_KEY not in content:
        with open(env_path, "a") as f:
            f.write(f"\n{ENV_KEY}={creds.refresh_token}\n")
        print(f"Auto-added {ENV_KEY} to {env_path}")
    else:
        lines = content.splitlines()
        new_lines = [f"{ENV_KEY}={creds.refresh_token}" if l.startswith(f"{ENV_KEY}=") else l for l in lines]
        env_path.write_text("\n".join(new_lines) + "\n")
        print(f"Updated {ENV_KEY} in {env_path}")
