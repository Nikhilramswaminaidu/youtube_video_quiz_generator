#!/bin/bash
# ============================================================================
# AWS EC2 User Data Script — YouTube Quiz Generator
# ============================================================================
# This script runs automatically on first boot of a new EC2 instance.
# It sets up everything from scratch: OS packages, Python, nginx, the app,
# and starts the service on port 80.
#
# Prerequisites:
#   - Ubuntu 22.04, 24.04, or 26.04 AMI
#   - t2.micro or t3.micro instance (free tier eligible)
#   - Security group allowing: SSH (22), HTTP (80), HTTPS (443)
#   - Paste this entire script into the "User data" field when launching
#
# After launch:
#   1. SSH in and set your NVIDIA_API_KEY:
#      sudo nano /opt/youtube-quiz-generator/.env
#      sudo systemctl restart quiz-generator
#   2. Visit http://<your-ec2-ip>/ in a browser
# ============================================================================

set -euo pipefail

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
APP_DIR="/opt/youtube-quiz-generator"
APP_USER="quizapp"
APP_GROUP="quizapp"
REPO_URL="https://github.com/Nikhilramswaminaidu/youtube_video_quiz_generator.git"
BRANCH="main"
SWAP_SIZE="2G"
GUNICORN_WORKERS=2
APP_PORT=8000

# ---------------------------------------------------------------------------
# Logging
# ---------------------------------------------------------------------------
LOG_FILE="/var/log/quiz-generator-setup.log"
exec > >(tee -a "$LOG_FILE") 2>&1

log()  { echo "[SETUP] $(date '+%Y-%m-%d %H:%M:%S') $*"; }
fail() { log "FATAL: $*"; exit 1; }

# ---------------------------------------------------------------------------
# Step 1: System update & essential packages
# ---------------------------------------------------------------------------
log "Updating system packages..."
export DEBIAN_FRONTEND=noninteractive
apt-get update -y
apt-get upgrade -y
apt-get install -y \
    curl wget git software-properties-common \
    build-essential libssl-dev zlib1g-dev \
    nginx certbot python3-certbot-nginx \
    ffmpeg \
    awscli

log "System packages installed."

# ---------------------------------------------------------------------------
# Step 2: Python 3.10+
# ---------------------------------------------------------------------------
# Auto-detect the best available Python version.
# Ubuntu 22.04 has python3.10, Ubuntu 24.04 has python3.12,
# Ubuntu 26.04 has python3.14. We prefer the system Python if >= 3.10.
log "Installing Python..."
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
    apt-get update -y
    apt-get install -y python3.11 python3.11-venv python3.11-dev python3-pip
    PYTHON_BIN="python3.11"
    PYTHON_VER="3.11"
    update-alternatives --install /usr/bin/python3 python3 /usr/bin/python3.11 1
fi

# Install venv support — on Ubuntu, python3-venv isn't always included
# On Ubuntu 26.04 we need the version-specific package (e.g. python3.14-venv)
if [ "$PYTHON_BIN" = "python3" ]; then
    VENV_PKG="python${PYTHON_VER}-venv"
    if ! dpkg -s "$VENV_PKG" &>/dev/null 2>&1; then
        apt-get install -y "$VENV_PKG" python3-dev python3-pip
    fi
fi

log "Python ready: $($PYTHON_BIN --version)"

# ---------------------------------------------------------------------------
# Step 3: Swap file (1 GB RAM on t2.micro is tight)
# ---------------------------------------------------------------------------
log "Creating ${SWAP_SIZE} swap file..."
if [ ! -f /swapfile ]; then
    fallocate -l "$SWAP_SIZE" /swapfile
    chmod 600 /swapfile
    mkswap /swapfile
    swapon /swapfile
    echo '/swapfile none swap sw 0 0' >> /etc/fstab
    log "Swap file created and enabled."
else
    log "Swap file already exists, skipping."
fi

# ---------------------------------------------------------------------------
# Step 4: Create application user
# ---------------------------------------------------------------------------
log "Creating application user: ${APP_USER}..."
if ! id "$APP_USER" &>/dev/null; then
    useradd --system --create-home --shell /bin/bash "$APP_USER"
    log "User ${APP_USER} created."
else
    log "User ${APP_USER} already exists, skipping."
fi

# ---------------------------------------------------------------------------
# Step 5: Clone repository
# ---------------------------------------------------------------------------
log "Cloning repository into ${APP_DIR}..."
if [ ! -d "$APP_DIR/.git" ]; then
    git clone -b "$BRANCH" "$REPO_URL" "$APP_DIR"
    log "Repository cloned."
else
    log "Repository already exists, pulling latest..."
    cd "$APP_DIR"
    git config --global --add safe.directory "$APP_DIR"
    sudo -u "$APP_USER" git pull origin "$BRANCH" || git pull origin "$BRANCH"
fi

chown -R "${APP_USER}:${APP_GROUP}" "$APP_DIR"

# ---------------------------------------------------------------------------
# Step 6: Python virtual environment & dependencies
# ---------------------------------------------------------------------------
log "Setting up Python virtual environment..."
cd "$APP_DIR"

if [ ! -d "venv" ]; then
    sudo -u "$APP_USER" $PYTHON_BIN -m venv venv
    log "Virtual environment created."
fi

log "Installing Python dependencies..."
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install --upgrade pip setuptools wheel
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install -r "$APP_DIR/requirements.txt"
sudo -u "$APP_USER" "$APP_DIR/venv/bin/pip" install gunicorn
log "Dependencies installed."

# ---------------------------------------------------------------------------
# Step 7: Environment variables
# ---------------------------------------------------------------------------
log "Writing .env template..."
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
    log ".env template created. EDIT IT to add your NVIDIA_API_KEY:"
    log "    sudo nano $APP_DIR/.env"
else
    log ".env already exists, preserving."
fi

chown "${APP_USER}:${APP_GROUP}" "$ENV_FILE"
chmod 600 "$ENV_FILE"

# ---------------------------------------------------------------------------
# Step 8: Systemd service
# ---------------------------------------------------------------------------
log "Installing systemd service..."
cat > /etc/systemd/system/quiz-generator.service << 'SVCEOF'
[Unit]
Description=YouTube Quiz Generator (gunicorn + uvicorn)
After=network.target

[Service]
Type=notify
User=quizapp
Group=quizapp
WorkingDirectory=/opt/youtube-quiz-generator
Environment=PORT=8000
Environment=PYTHONUNBUFFERED=1
EnvironmentFile=/opt/youtube-quiz-generator/.env
ExecStart=/opt/youtube-quiz-generator/venv/bin/gunicorn \
    backend.app.main:app \
    -w 2 \
    -k uvicorn.workers.UvicornWorker \
    -b 0.0.0.0:8000 \
    --timeout 300 \
    --graceful-timeout 30 \
    --access-logfile - \
    --error-logfile -
Restart=always
RestartSec=5

[Install]
WantedBy=multi-user.target
SVCEOF

systemctl daemon-reload
systemctl enable quiz-generator
log "Systemd service installed and enabled."

# ---------------------------------------------------------------------------
# Step 9: Nginx configuration
# ---------------------------------------------------------------------------
log "Installing nginx configuration..."
cat > /etc/nginx/sites-available/quiz-generator << 'NGINXEOF'
# ──────────────────────────────────────────────────────────────
# YouTube Quiz Generator — Nginx Reverse Proxy
# ──────────────────────────────────────────────────────────────

# Upstream gunicorn server
upstream quiz_app {
    server 127.0.0.1:8000;
}

server {
    listen 80;
    server_name _;  # Accepts any hostname / IP

    # ── Security headers ──────────────────────────────────────
    add_header X-Content-Type-Options "nosniff" always;
    add_header X-Frame-Options "SAMEORIGIN" always;
    add_header X-XSS-Protection "1; mode=block" always;

    # ── Gzip compression ──────────────────────────────────────
    gzip on;
    gzip_types application/json text/plain text/css application/javascript;
    gzip_min_length 256;

    # ── SSE streaming endpoint (long timeouts, no buffering) ──
    location /api/quiz/generate/stream {
        proxy_pass http://quiz_app;
        proxy_http_version 1.1;

        # Critical: prevent nginx from closing long SSE connections
        proxy_read_timeout 300s;
        proxy_send_timeout 300s;
        proxy_connect_timeout 60s;

        # Disable all buffering for SSE
        proxy_buffering off;
        proxy_cache off;

        # SSE requires chunked transfer
        proxy_set_header Connection '';
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # ── All other API and frontend routes ─────────────────────
    location / {
        proxy_pass http://quiz_app;
        proxy_http_version 1.1;
        proxy_set_header Host $host;
        proxy_set_header X-Real-IP $remote_addr;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;

        # Extended timeout for PDF generation and long API calls
        proxy_read_timeout 120s;
        proxy_send_timeout 120s;
    }
}
NGINXEOF

# Remove default site and enable quiz-generator
rm -f /etc/nginx/sites-enabled/default
ln -sf /etc/nginx/sites-available/quiz-generator /etc/nginx/sites-enabled/quiz-generator

# Test nginx config
nginx -t && log "Nginx config OK" || fail "Nginx config test failed!"

# ---------------------------------------------------------------------------
# Step 10: Start services
# ---------------------------------------------------------------------------
log "Starting quiz-generator service..."
systemctl start quiz-generator
log "Starting nginx..."
systemctl restart nginx

# Wait for the app to come up
log "Waiting for the app to start..."
for i in $(seq 1 30); do
    if curl -sf http://127.0.0.1:8000/api/health >/dev/null 2>&1; then
        log "App is up and healthy!"
        break
    fi
    log "Waiting for app... ($i/30)"
    sleep 2
done

# ---------------------------------------------------------------------------
# Done!
# ---------------------------------------------------------------------------
INSTANCE_IP=$(curl -sf http://169.254.169.254/latest/meta-data/public-ipv4 2>/dev/null || echo "<YOUR_EC2_IP>")
log ""
log "============================================================"
log "  YouTube Quiz Generator is deployed!"
log "============================================================"
log ""
log "  App:      http://${INSTANCE_IP}/"
log "  Health:   http://${INSTANCE_IP}/api/health"
log "  API docs: http://${INSTANCE_IP}/docs"
log ""
log "  NEXT STEP: Set your NVIDIA_API_KEY:"
log "    sudo nano ${APP_DIR}/.env"
log "    sudo systemctl restart quiz-generator"
log ""
log "  Useful commands:"
log "    sudo journalctl -u quiz-generator -f   # View app logs"
log "    sudo systemctl status quiz-generator    # Check status"
log "    sudo systemctl restart quiz-generator   # Restart app"
log "    sudo nginx -t && sudo systemctl reload nginx  # Reload nginx"
log ""
log "============================================================"