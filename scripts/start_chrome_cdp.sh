#!/bin/bash
# start_chrome_cdp.sh — Launch Chrome with remote debugging on port 9222
# This lets the Origin scraper read your already-logged-in session via CDP.
#
# Usage:
#   ./scripts/start_chrome_cdp.sh          # launch Chrome with CDP
#   ./scripts/start_chrome_cdp.sh --check  # check if CDP is already running
#
# After running, say "origin refresh" in Telegram or run /origin refresh.

CDP_PORT=9222
CHROME="/Applications/Google Chrome.app/Contents/MacOS/Google Chrome"

if [[ "$1" == "--check" ]]; then
    if curl -s "http://localhost:${CDP_PORT}/json/version" > /dev/null 2>&1; then
        echo "✅ Chrome CDP is already running on port ${CDP_PORT}"
        curl -s "http://localhost:${CDP_PORT}/json/version" | python3 -m json.tool 2>/dev/null || true
    else
        echo "❌ Chrome CDP is NOT running on port ${CDP_PORT}"
        echo "   Run: ./scripts/start_chrome_cdp.sh"
    fi
    exit 0
fi

# Check if CDP is already available
if curl -s "http://localhost:${CDP_PORT}/json/version" > /dev/null 2>&1; then
    echo "✅ Chrome CDP already running on port ${CDP_PORT} — nothing to do."
    exit 0
fi

if [[ ! -f "$CHROME" ]]; then
    echo "❌ Chrome not found at: $CHROME"
    echo "   Update CHROME path in this script if installed elsewhere."
    exit 1
fi

echo "🚀 Launching Chrome with remote debugging on port ${CDP_PORT}..."
echo "   Log into Origin Financial at: https://app.useorigin.com"
echo "   Then say 'origin refresh' in Telegram."
echo ""

# Use a separate profile dir so it doesn't conflict with your main Chrome
PROFILE_DIR="$HOME/.chrome-cdp-profile"
mkdir -p "$PROFILE_DIR"

"$CHROME" \
    --remote-debugging-port=${CDP_PORT} \
    --user-data-dir="$PROFILE_DIR" \
    --no-first-run \
    --no-default-browser-check \
    "https://app.useorigin.com" &

echo "Chrome launched (PID $!). Log in if needed, then trigger 'origin refresh'."
