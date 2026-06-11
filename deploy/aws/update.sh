#!/bin/bash
# ============================================================================
# YouTube Quiz Generator — Quick Update Script
# ============================================================================
# Pulls the latest code from git, updates dependencies, and restarts the service.
#
# Usage:
#   sudo bash deploy/aws/update.sh
#
# Or from the repo root:
#   sudo bash deploy/aws/update.sh
# ============================================================================

set -euo pipefail

APP_DIR="/opt/youtube-quiz-generator"
APP_USER="quizapp"
BRANCH="main"

echo "============================================"
echo "  YouTube Quiz Generator — Update"
echo "============================================"
echo ""

# Pull latest code
echo "[1/4] Pulling latest code..."
cd "$APP_DIR"
sudo -u "$APP_USER" git pull origin "$BRANCH" || {
    echo "ERROR: git pull failed. Check for local changes."
    echo "  cd $APP_DIR && sudo -u $APP_USER git status"
    exit 1
}

# Update Python dependencies
echo "[2/4] Updating Python dependencies..."
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install --upgrade pip setuptools wheel -qq
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" -qq

# Restart the service
echo "[3/4] Restarting quiz-generator service..."
systemctl restart quiz-generator

# Wait and verify
echo "[4/4] Verifying..."
sleep 3
if systemctl is-active --quiet quiz-generator; then
    echo ""
    echo "✓ Update complete! Service is running."
    echo ""
    echo "  Health check: curl http://localhost:8000/api/health"
    echo "  Logs:         sudo journalctl -u quiz-generator -f"
else
    echo ""
    echo "✗ Service failed to start. Check logs:"
    echo "  sudo journalctl -u quiz-generator -n 50"
    exit 1
fi