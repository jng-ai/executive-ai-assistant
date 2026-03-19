#!/bin/bash
# Google Sheets setup for Executive AI Assistant
# Run this once in your terminal: bash scripts/setup_google_sheets.sh

set -e

GCLOUD=/opt/homebrew/share/google-cloud-sdk/bin/gcloud
PROJECT_ID="executive-ai-assistant-$(date +%s | tail -c 5)"
SA_NAME="executive-ai-bot"
KEY_FILE="credentials/google_service_account.json"

echo ""
echo "=== Executive AI Assistant — Google Sheets Setup ==="
echo ""

# Step 1: Auth (opens browser)
echo "Step 1/6: Logging into Google..."
$GCLOUD auth login --quiet

# Step 2: Create project
echo ""
echo "Step 2/6: Creating Google Cloud project ($PROJECT_ID)..."
$GCLOUD projects create "$PROJECT_ID" --name="Executive AI Assistant" --quiet
$GCLOUD config set project "$PROJECT_ID" --quiet

# Step 3: Enable billing prompt (Sheets API requires billing enabled, but is free)
echo ""
echo "Step 3/6: Enabling Google Sheets + Drive APIs..."
$GCLOUD services enable sheets.googleapis.com drive.googleapis.com --quiet

# Step 4: Create service account
echo ""
echo "Step 4/6: Creating service account..."
$GCLOUD iam service-accounts create "$SA_NAME" \
  --display-name="Executive AI Bot" \
  --quiet

SA_EMAIL="$SA_NAME@$PROJECT_ID.iam.gserviceaccount.com"
echo "  Service account: $SA_EMAIL"

# Step 5: Download credentials
echo ""
echo "Step 5/6: Downloading credentials key..."
mkdir -p credentials
$GCLOUD iam service-accounts keys create "$KEY_FILE" \
  --iam-account="$SA_EMAIL" \
  --quiet

echo ""
echo "Step 6/6: Done! ✅"
echo ""
echo "============================================"
echo "Service account email (COPY THIS):"
echo "  $SA_EMAIL"
echo ""
echo "Credentials saved to: $KEY_FILE"
echo "============================================"
echo ""
echo "Next steps:"
echo "1. Open your Google Sheet (your bonus tracker)"
echo "2. Click Share → paste the service account email above → give Editor access"
echo "3. Copy the Sheet ID from the URL (the long string between /d/ and /edit)"
echo "4. Come back to Claude Code and paste the Sheet ID"
echo ""
