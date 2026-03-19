#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Oracle Cloud VM Setup — Executive AI Assistant
# Run this ONCE on a fresh Ubuntu 22.04 ARM instance after SSH in:
#   bash oracle_setup.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e
echo "==> Updating system packages..."
sudo apt update -qq && sudo apt upgrade -y -qq

echo "==> Installing Python 3.12, pip, git, ffmpeg..."
sudo apt install -y -qq python3 python3-pip python3-venv python3-dev git ffmpeg curl

echo "==> Installing edge-tts system dependency (mpg123 not needed for bot)..."
# edge-tts is pure Python, no extra system deps needed

echo "==> Cloning repository..."
if [ -d "executive-ai-assistant" ]; then
    echo "    Repo already exists, pulling latest..."
    cd executive-ai-assistant
    git pull origin main
    cd ..
else
    git clone https://github.com/jng-ai/executive-ai-assistant.git
fi

echo "==> Creating Python virtual environment..."
cd executive-ai-assistant
python3 -m venv venv
source venv/bin/activate

echo "==> Installing Python dependencies..."
pip install --upgrade pip -q
pip install -r requirements.txt -q

echo "==> Creating data/ and logs/ directories..."
mkdir -p data logs

echo ""
echo "═══════════════════════════════════════════════════════════════"
echo "  NEXT STEP: Copy your .env file from your Mac to this server"
echo ""
echo "  Run this command FROM YOUR MAC (not this server):"
echo ""
echo "  scp -i ~/Downloads/ssh-key.key \\"
echo "    /Users/justinngai/workspace/executive-ai-assistant/.env \\"
echo "    ubuntu@YOUR_VM_IP:~/executive-ai-assistant/.env"
echo ""
echo "  Then come back here and run:"
echo "    bash scripts/oracle_service.sh"
echo "═══════════════════════════════════════════════════════════════"
