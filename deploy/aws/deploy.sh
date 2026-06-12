#!/bin/bash
# ============================================================================
# YouTube Quiz Generator — Manual Deployment Script for AWS EC2
# ============================================================================
# Run this script on a fresh Ubuntu 22.04/24.04 EC2 instance:
#   wget -O deploy.sh https://raw.githubusercontent.com/Nikhilramswaminaidu/youtube_video_quiz_generator/main/deploy/aws/deploy.sh
#   chmod +x deploy.sh
#   sudo ./deploy.sh
#
# Or clone the repo first and run from there:
#   git clone https://github.com/Nikhilramswaminaidu/youtube_video_quiz_generator.git
#   cd youtube_video_quiz_generator
#   sudo bash deploy/aws/deploy.sh
# ============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Colors for output
# ---------------------------------------------------------------------------
RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'  # No Color

log()  { echo -e "${BLUE}[DEPLOY]${NC} $(date '+%H:%M:%S') $*"; }
ok()   { echo -e "${GREEN}[OK]${NC} $*"; }
warn() { echo -e "${YELLOW}[WARN]${NC} $*"; }
fail() { echo -e "${RED}[FAIL]${NC} $*"; exit 1; }

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
APP_DIR="/opt/youtube-quiz-generator"
APP_USER="quizapp"
APP_GROUP="quizapp"
REPO_URL="https://github.com/Nikhilramswaminaidu/youtube_video_quiz_generator.git"
BRANCH="main"
SWAP_SIZE="2G"
SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"

# ---------------------------------------------------------------------------
# Pre-flight checks
# ---------------------------------------------------------------------------
[ "$(id -u)" -ne 0 ] && fail "This script must be run as root (use sudo)."

log "YouTube Quiz Generator — AWS EC2 Deployment"
log "================================================"

# ---------------------------------------------------------------------------
# Step 1: System update & packages
# ---------------------------------------------------------------------------
log "Step 1/8: Updating system packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y -qq
apt-get upgrade -y -qq
apt-get install -y -qq \
    curl wget git software-properties-common \
    build-essential libssl-dev zlib1g-dev \
    nginx certbot python3-certbot-nginx \
    ffmpeg
ok "System packages installed."

# ---------------------------------------------------------------------------
# Step 2: Python 3.10+
# ---------------------------------------------------------------------------
# Auto-detect the best available Python version.
# Ubuntu 22.04 has python3.10, Ubuntu 24.04 has python3.12,
# Ubuntu 26.04 has python3.14. We prefer the system Python if >= 3.10.
log "Step 2/8: Installing Python..."
PYTHON_BIN=""
PYTHON_VER=""

# Check system python3 first
SYS_PYTHON_VER=$(python3 -c 'import sys; print(sys.version_info.major*100 + sys.version_info.minor)' 2>/dev/null || echo "0")
if [ "$SYS_PYTHON_VER" -ge 310 ]; then
    PYTHON_BIN="python3"
    PYTHON_VER=$(python3 -c 'import sys; print(f"{sys.version_info.major}.{sys.version_info.minor}")')
    log "Using system Python: $PYTHON_VER"
fi

# If system python is too old, try deadsnakes PPA for 3.11
if [ -z "$PYTHON_BIN" ]; then
    log "System Python is too old, installing Python 3.11 from deadsnakes PPA..."
    add-apt-repository -y ppa:deadsnakes/ppa
    apt-get update -y -qq
    apt-get install -y -qq python3.11 python3.11-venv python3.11-dev python3-pip
    PYTHON_BIN="python3.11"
    PYTHON_VER="3.11"
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
fi

# Install venv support — on Ubuntu, python3-venv isn't always included
# On Ubuntu 26.04 we need the version-specific package (e.g. python3.14-venv)
# Install the venv package separately to avoid conflicts with generic python3-dev/pip
if [ "$PYTHON_BIN" = "python3" ]; then
    VENV_PKG="python${PYTHON_VER}-venv"
    DEV_PKG="python${PYTHON_VER}-dev"
    if ! dpkg -s "$VENV_PKG" &>/dev/null 2>&1; then
        apt-get install -y -qq "$VENV_PKG"
    fi
    if ! dpkg -s "$DEV_PKG" &>/dev/null 2>&1; then
        apt-get install -y -qq "$DEV_PKG" || true
    fi
fi

ok "Python $($PYTHON_BIN --version) ready."

# ---------------------------------------------------------------------------
# Step 3: Swap file
# ---------------------------------------------------------------------------
log "Step 3/8: Setting up swap file..."
if [ ! -f /swapfile ]; then
    fallocate -l "$SWAP_SIZE" /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    ok "${SWAP_SIZE} swap file created."
else
    warn "Swap file already exists, skipping."
fi

# ---------------------------------------------------------------------------
# Step 4: Application user
# ---------------------------------------------------------------------------
log "Step 4/8: Creating application user..."
if ! id "$APP_USER" &>/dev/null; then
    useradd --system --create-home --shell /bin/bash "$APP_USER"
    ok "User ${APP_USER} created."
else
    warn "User ${APP_USER} already exists."
fi

# ---------------------------------------------------------------------------
# Step 5: Clone / update repository
# ---------------------------------------------------------------------------
log "Step 5/8: Setting up application code..."
# Mark repo directory as safe for ALL users (avoids "dubious ownership" errors
# when root runs git in a quizapp-owned directory after chown)
git config --system --add safe.directory "$APP_DIR"

if [ ! -d "${APP_DIR}/.git" ]; then
    git clone -b "$BRANCH" "$REPO_URL" "$APP_DIR"
    ok "Repository cloned to ${APP_DIR}."
else
    cd "$APP_DIR"
    git pull origin "$BRANCH"
    ok "Repository updated."
fi
chown -R "${APP_USER}:${APP_GROUP}" "$APP_DIR"

# ---------------------------------------------------------------------------
# Step 6: Python virtual environment & dependencies
# ---------------------------------------------------------------------------
log "Step 6/8: Installing Python dependencies..."
cd "$APP_DIR"

# Remove broken venv from a previous failed run (e.g. missing ensurepip)
if [ -d "venv" ] && [ ! -x "venv/bin/pip" ]; then
    warn "Removing broken venv from previous run..."
    rm -rf venv
fi

if [ ! -d "venv" ]; then
    sudo -u "$APP_USER" $PYTHON_BIN -m venv venv
    ok "Virtual environment created."
fi

sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install --upgrade pip setuptools wheel -qq
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt" -qq
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install gunicorn -qq
ok "Python dependencies installed."

# ---------------------------------------------------------------------------
# Step 7: Environment variables
# ---------------------------------------------------------------------------
log "Step 7/8: Configuring environment variables..."
ENV_FILE="$APP_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
    cat > "$ENV_FILE" << 'ENVEOF'
# ──────────────────────────────────────────────────────────────
# YouTube Quiz Generator — Environment Variables
# ──────────────────────────────────────────────────────────────
# REQUIRED: Get your key at https://build.nvidia.com/
NVIDIA_API_KEY=nvapi-paste-your-key-here

# OPTIONAL: Cloudflare Worker URL for transcript proxying
YOUTUBE_PROXY_URL=

# OPTIONAL: Comma-separated custom Invidious instances
INVIDIOUS_INSTANCES=
ENVEOF
    chown "${APP_USER}:${APP_GROUP}" "$ENV_FILE"
    chmod 600 "$ENV_FILE"
    ok ".env template created."
    warn "You MUST edit .env to add your NVIDIA_API_KEY!"
    warn "  sudo nano ${ENV_FILE}"
else
    ok ".env already exists, preserving current values."
fi

# ---------------------------------------------------------------------------
# Step 8: Install systemd service & nginx
# ---------------------------------------------------------------------------
log "Step 8/8: Installing systemd service & nginx config..."

# Copy service file
cp "${SCRIPT_DIR}/quiz-generator.service" /etc/systemd/system/quiz-generator.service
systemctl daemon-reload
systemctl enable quiz-generator
ok "Systemd service installed."

# Copy nginx config
cp "${SCRIPT_DIR}/nginx.conf" /etc/nginx/sites-available/quiz-generator
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/quiz-generator /etc/nginx/sites-enabled/quiz-generator

# Test nginx config
nginx -t && ok "Nginx config OK" || fail "Nginx config test failed!"

# ---------------------------------------------------------------------------
# Start services
# ---------------------------------------------------------------------------
log "Starting services..."
systemctl start quiz-generator
systemctl restart nginx

# Wait for the app to come up
log "Waiting for the app to start..."
for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
        ok "App is up and healthy!"
        break
    fi
    if [ "$i" -eq 30 ]; then
        warn "App didn't respond within 60 seconds. Check logs:"
        warn "  sudo journalctl -u quiz-generator -n 50"
    fi
    sleep 2
done

# ---------------------------------------------------------------------------
# Done!
# ---------------------------------------------------------------------------
INSTANCE_IP=$(curl -sf http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "<YOUR_EC2_PUBLIC_IP>")

echo ""
echo -e "${GREEN}============================================================${NC}"
echo -e "${GREEN}  YouTube Quiz Generator is deployed!${NC}"
echo -e "${GREEN}============================================================${NC}"
echo ""
echo -e "  App:      ${BLUE}http://${INSTANCE_IP}/${NC}"
echo -e "  Health:   ${BLUE}http://${INSTANCE_IP}/api/health${NC}"
echo -e "  API docs: ${BLUE}http://${INSTANCE_IP}/docs${NC}"
echo ""
echo -e "${YELLOW}  NEXT STEP: Set your NVIDIA_API_KEY:${NC}"
echo -e "    sudo nano ${APP_DIR}/.env"
echo -e "    sudo systemctl restart quiz-generator"
echo ""
echo "  Useful commands:"
echo "    sudo journalctl -u quiz-generator -f       # Live logs"
echo "    sudo systemctl status quiz-generator        # Check status"
echo "    sudo systemctl restart quiz-generator       # Restart app"
echo "    sudo nginx -t && sudo systemctl reload nginx  # Reload nginx"
echo ""