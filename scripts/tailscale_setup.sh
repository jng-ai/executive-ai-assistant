#!/bin/bash
# =============================================================================
# Tailscale Setup for The Justin Brief Podcast
# Run this AFTER installing Tailscale on Mac and signing in.
#
# What it does:
#   1. Gets your Mac's Tailscale IP (100.x.x.x)
#   2. Updates PODCAST_HOST in .env
#   3. Rebuilds the RSS feed XML with the new URL
#   4. Prints the RSS URL to copy into Overcast / Pocket Casts / Apple Podcasts
# =============================================================================

set -e
cd "$(dirname "$0")/.."

echo ""
echo "🎙  The Justin Brief — Tailscale Setup"
echo "======================================="

# Check Tailscale is installed
if ! command -v tailscale &>/dev/null; then
  # Try common macOS paths
  TAILSCALE_BIN=""
  for p in /Applications/Tailscale.app/Contents/MacOS/Tailscale \
            /usr/local/bin/tailscale \
            /opt/homebrew/bin/tailscale; do
    [ -x "$p" ] && TAILSCALE_BIN="$p" && break
  done
  if [ -z "$TAILSCALE_BIN" ]; then
    echo ""
    echo "❌  Tailscale not found. Please install it first:"
    echo "    Mac App Store: search 'Tailscale'"
    echo "    Or: https://tailscale.com/download/mac"
    echo ""
    exit 1
  fi
else
  TAILSCALE_BIN="tailscale"
fi

# Get Tailscale IP
TS_IP=$("$TAILSCALE_BIN" ip --4 2>/dev/null || echo "")
if [ -z "$TS_IP" ]; then
  echo ""
  echo "❌  Tailscale is installed but not connected."
  echo "    Open the Tailscale menu bar app and sign in, then re-run this script."
  echo ""
  exit 1
fi

PODCAST_PORT="${PODCAST_PORT:-8765}"
PODCAST_HOST="http://${TS_IP}:${PODCAST_PORT}"

echo "✅  Tailscale connected. Your Mac's Tailscale IP: ${TS_IP}"
echo ""

# Update .env
ENV_FILE=".env"
if grep -q "^PODCAST_HOST=" "$ENV_FILE" 2>/dev/null; then
  sed -i '' "s|^PODCAST_HOST=.*|PODCAST_HOST=${PODCAST_HOST}|" "$ENV_FILE"
  echo "✅  Updated PODCAST_HOST in .env → ${PODCAST_HOST}"
else
  echo "" >> "$ENV_FILE"
  echo "# Podcast server — Tailscale URL (accessible from all your devices)" >> "$ENV_FILE"
  echo "PODCAST_HOST=${PODCAST_HOST}" >> "$ENV_FILE"
  echo "✅  Added PODCAST_HOST to .env → ${PODCAST_HOST}"
fi

# Rebuild RSS feed with new base URL
echo ""
echo "🔄  Rebuilding RSS feed with Tailscale URL..."
source venv/bin/activate
python - <<PYEOF
import sys
sys.path.insert(0, '.')
from dotenv import load_dotenv
load_dotenv('.env')
from agents.podcast_agent.rss_feed import build_feed
import os

host = os.getenv('PODCAST_HOST', '').rstrip('/')
if not host:
    print("ERROR: PODCAST_HOST not set")
    sys.exit(1)

path = build_feed(host)
print(f"RSS feed rebuilt: {path}")
PYEOF

RSS_URL="${PODCAST_HOST}/feed.xml"
ARCHIVE_URL="${PODCAST_HOST}"

echo ""
echo "============================================================"
echo "🎉  Setup complete! Here's what to do next:"
echo ""
echo "  1. Make sure Tailscale is running on this Mac (menu bar)"
echo "  2. Make sure Tailscale is running on your iPhone"
echo ""
echo "  📡  RSS Feed URL (copy this into your podcast app):"
echo ""
echo "      ${RSS_URL}"
echo ""
echo "  📚  Episode Archive (open in browser):"
echo "      ${ARCHIVE_URL}"
echo ""
echo "  Supported apps: Overcast, Pocket Casts, Apple Podcasts,"
echo "  Castro, Spotify (private feeds), any RSS podcast app"
echo ""
echo "  Restart the bot to apply the new PODCAST_HOST:"
echo "      launchctl bootout gui/\$(id -u) ~/Library/LaunchAgents/com.justinngai.executive-ai.plist"
echo "      launchctl bootstrap gui/\$(id -u) ~/Library/LaunchAgents/com.justinngai.executive-ai.plist"
echo "============================================================"
echo ""
