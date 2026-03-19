#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Install the bot as a systemd service so it runs 24/7 and auto-restarts.
# Run AFTER oracle_setup.sh and after copying .env.
#   bash scripts/oracle_service.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e

REPO_DIR="$HOME/executive-ai-assistant"
VENV_PYTHON="$REPO_DIR/venv/bin/python3"
SERVICE_NAME="executive-ai"

echo "==> Verifying .env exists..."
if [ ! -f "$REPO_DIR/.env" ]; then
    echo "ERROR: .env not found at $REPO_DIR/.env"
    echo "Copy it from your Mac first (see oracle_setup.sh output)."
    exit 1
fi

echo "==> Quick smoke test (imports only)..."
cd "$REPO_DIR"
source venv/bin/activate
python3 -c "
import dotenv; dotenv.load_dotenv()
from core.command_router import classify
print('  Imports OK')
"

echo "==> Writing systemd service file..."
sudo tee /etc/systemd/system/${SERVICE_NAME}.service > /dev/null <<EOF
[Unit]
Description=Executive AI Assistant (Telegram Bot)
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
User=$USER
WorkingDirectory=$REPO_DIR
ExecStart=$VENV_PYTHON $REPO_DIR/main.py
Restart=always
RestartSec=10
StandardOutput=append:$REPO_DIR/logs/bot.log
StandardError=append:$REPO_DIR/logs/bot_error.log

[Install]
WantedBy=multi-user.target
EOF

echo "==> Enabling and starting service..."
sudo systemctl daemon-reload
sudo systemctl enable ${SERVICE_NAME}
sudo systemctl start ${SERVICE_NAME}

sleep 3
STATUS=$(sudo systemctl is-active ${SERVICE_NAME})
echo ""
if [ "$STATUS" = "active" ]; then
    echo "✅ Bot is running as a system service!"
    echo ""
    echo "Useful commands:"
    echo "  sudo systemctl status $SERVICE_NAME    # check status"
    echo "  sudo systemctl restart $SERVICE_NAME   # restart"
    echo "  tail -f $REPO_DIR/logs/bot.log         # live logs"
    echo "  sudo systemctl stop $SERVICE_NAME      # stop"
else
    echo "⚠️  Service status: $STATUS"
    echo "Check logs: sudo journalctl -u $SERVICE_NAME -n 50"
fi
