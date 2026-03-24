#!/bin/bash
# ─────────────────────────────────────────────────────────────────────────────
# Oracle Cloud VM Setup — Executive AI Assistant
# Works on Oracle Linux 9 (default) and Ubuntu 22.04 ARM
#   bash oracle_setup.sh
# ─────────────────────────────────────────────────────────────────────────────

set -e
echo "==> Detecting OS..."
if [ -f /etc/redhat-release ]; then
    PKG="dnf"
    echo "    Oracle Linux / RHEL detected — using dnf"
else
    PKG="apt"
    echo "    Debian/Ubuntu detected — using apt"
fi

echo "==> Updating system packages..."
if [ "$PKG" = "dnf" ]; then
    sudo dnf update -y -q
    echo "==> Installing Python 3, pip, git, ffmpeg..."
    sudo dnf install -y python3 python3-pip python3-devel git ffmpeg curl
    # pip3 is the command on OL9; create symlink if needed
    sudo ln -sf /usr/bin/pip3 /usr/local/bin/pip 2>/dev/null || true
else
    sudo apt update -qq && sudo apt upgrade -y -qq
    echo "==> Installing Python 3, pip, git, ffmpeg..."
    sudo apt install -y -qq python3 python3-pip python3-venv python3-dev git ffmpeg curl
fi

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
echo "    opc@YOUR_VM_IP:~/executive-ai-assistant/.env"
echo ""
echo "  (Oracle Linux user = opc, Ubuntu user = ubuntu)"
echo ""
echo "  Then come back here and run:"
echo "    bash scripts/oracle_service.sh"
echo "═══════════════════════════════════════════════════════════════"
