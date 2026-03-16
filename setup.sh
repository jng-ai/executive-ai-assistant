#!/bin/bash
# Setup script — run once after cloning

set -e

GREEN='\033[0;32m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo -e "${GREEN}Setting up Executive AI Assistant...${NC}\n"

# 1. Python virtual environment
if [ ! -d "venv" ]; then
  echo "Creating virtual environment..."
  python3 -m venv venv
fi

source venv/bin/activate

# 2. Install dependencies
echo "Installing dependencies..."
pip install -q -r requirements.txt

# 3. Create .env if missing
if [ ! -f ".env" ]; then
  cp .env.example .env
  echo -e "\n${YELLOW}Created .env from template.${NC}"
  echo -e "${YELLOW}Edit .env and add your API keys before running.${NC}\n"
else
  echo ".env already exists — skipping."
fi

# 4. Create data directory
mkdir -p data logs

echo -e "\n${GREEN}Setup complete.${NC}"
echo ""
echo "Next steps:"
echo "  1. Edit .env and add your keys"
echo "  2. source venv/bin/activate"
echo "  3. python main.py test    ← test command routing"
echo "  4. python main.py         ← start the Telegram bot"
echo ""
echo "Keys you need:"
echo "  ANTHROPIC_API_KEY  → console.anthropic.com"
echo "  TELEGRAM_BOT_TOKEN → message @BotFather on Telegram"
