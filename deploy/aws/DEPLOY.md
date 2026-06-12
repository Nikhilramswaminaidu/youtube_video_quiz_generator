# YouTube Quiz Generator — AWS EC2 Deployment Guide

## Overview

This guide deploys the YouTube Quiz Generator to AWS EC2 using the free tier
(t2.micro, 12 months free). The setup uses:

- **gunicorn + uvicorn workers** — production ASGI server with 2 workers
- **nginx** — reverse proxy with SSE-optimized timeouts (300s)
- **systemd** — auto-restart on crash, start on boot

This eliminates the Render free tier's 30-second connection timeout that was
causing "connection was lost" errors during quiz generation.

---

## Option A: Automated (User Data) — Recommended

Paste the entire contents of `userdata.sh` into the EC2 **User data** field
when launching a new instance. The instance will configure itself automatically
on first boot.

### Steps

1. **Go to AWS EC2 Console** → Launch Instance

2. **Choose AMI**: Ubuntu 22.04 LTS or 24.04 LTS (Quick Start)

3. **Instance type**: `t2.micro` (free tier eligible) or `t3.micro`

4. **Configure Security Group** with these inbound rules:

   | Type  | Protocol | Port | Source      | Description          |
   |-------|----------|------|-------------|----------------------|
   | SSH   | TCP      | 22   | Your IP     | SSH access           |
   | HTTP  | TCP      | 80   | 0.0.0.0/0   | Web app access       |
   | HTTPS | TCP      | 443  | 0.0.0.0/0   | HTTPS (for certbot)  |

5. **Advanced Details** → **User data**: Paste the entire contents of
   `deploy/aws/userdata.sh`

6. **Launch** the instance and wait 3-5 minutes for setup to complete

7. **Set your NVIDIA API key**:

   ```bash
   ssh ubuntu@<your-ec2-ip>
   sudo nano /opt/youtube-quiz-generator/.env
   # Replace nvapi-paste-your-key-here with your actual key
   sudo systemctl restart quiz-generator
   ```

8. **Visit** `http://<your-ec2-ip>/` in a browser

---

## Option B: Manual (deploy.sh)

If you already have a running EC2 instance:

```bash
# SSH into your instance
ssh ubuntu@<your-ec2-ip>

# Clone the repo
git clone https://github.com/Nikhilramswaminaidu/youtube_video_quiz_generator.git
cd youtube_video_quiz_generator

# Run the deploy script
sudo bash deploy/aws/deploy.sh

# Set your NVIDIA API key
sudo nano /opt/youtube-quiz-generator/.env
sudo systemctl restart quiz-generator
```

---

## Option C: Step-by-Step Manual Setup

If you prefer to run each step individually:

### 1. Install System Packages

```bash
sudo apt-get update && sudo apt-get upgrade -y
sudo apt-get install -y python3.11 python3.11-venv python3.11-dev \
    python3-pip nginx ffmpeg git curl build-essential
sudo add-apt-repository -y ppa:deadsnakes/ppa
sudo apt-get update
sudo apt-get install -y python3.11 python3.11-venv python3.11-dev
```

### 2. Create Swap File (t2.micro has only 1GB RAM)

```bash
sudo fallocate -l 2G /swapfile
sudo chmod 600 /swapfile
sudo mkswap /swapfile
sudo swapon /swapfile
echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab
```

### 3. Create App User & Clone Repo

```bash
sudo useradd --system --create-home --shell /bin/bash quizapp
sudo git clone https://github.com/Nikhilramswaminaidu/youtube_video_quiz_generator.git /opt/youtube-quiz-generator
sudo chown -R quizapp:quizapp /opt/youtube-quiz-generator
```

### 4. Set Up Python Environment

```bash
cd /opt/youtube-quiz-generator
sudo -u quizapp python3.11 -m venv venv
sudo -u quizapp /opt/youtube-quiz-generator/venv/bin/pip install --upgrade pip setuptools wheel
sudo -u quizapp /opt/youtube-quiz-generator/venv/bin/pip install -r requirements.txt
sudo -u quizapp /opt/youtube-quiz-generator/venv/bin/pip install gunicorn
```

### 5. Configure Environment Variables

```bash
sudo nano /opt/youtube-quiz-generator/.env
```

Add:

```env
NVIDIA_API_KEY=nvapi-your-actual-key-here
YOUTUBE_PROXY_URL=
INVIDIOUS_INSTANCES=
```

```bash
sudo chmod 600 /opt/youtube-quiz-generator/.env
sudo chown quizapp:quizapp /opt/youtube-quiz-generator/.env
```

### 6. Install Systemd Service

```bash
sudo cp deploy/aws/quiz-generator.service /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable quiz-generator
sudo systemctl start quiz-generator
```

### 7. Install Nginx Config

```bash
sudo cp deploy/aws/nginx.conf /etc/nginx/sites-available/quiz-generator
sudo rm -f /etc/nginx/sites-enabled/default
sudo ln -sf /etc/nginx/sites-available/quiz-generator /etc/nginx/sites-enabled/
sudo nginx -t && sudo systemctl reload nginx
```

---

## HTTPS Setup (Optional)

To add HTTPS with a free Let's Encrypt certificate:

```bash
# Point a domain name to your EC2 instance's public IP first
# Then run:
sudo certbot --nginx -d your-domain.com

# Certbot will:
# 1. Generate an SSL certificate
# 2. Modify the nginx config to use HTTPS
# 3. Set up auto-renewal via cron
```

---

## Updating the App

To pull the latest code and restart:

```bash
cd /opt/youtube-quiz-generator
sudo -u quizapp git pull origin main
sudo -u quizapp /opt/youtube-quiz-generator/venv/bin/pip install -r requirements.txt
sudo systemctl restart quiz-generator
```

Or use the update script:

```bash
sudo bash deploy/aws/update.sh
```

---

## Troubleshooting

### Check if the app is running

```bash
sudo systemctl status quiz-generator
```

### View live logs

```bash
sudo journalctl -u quiz-generator -f
```

### View recent logs

```bash
sudo journalctl -u quiz-generator -n 100
```

### Check nginx status

```bash
sudo systemctl status nginx
sudo nginx -t  # Test configuration
```

### Health check endpoint

```bash
curl http://localhost:8000/api/health
```

Should return JSON with yt-dlp version, python version, and proxy status.

### Check from outside

```bash
curl http://<your-ec2-ip>/api/health
```

### Common Issues

| Problem | Cause | Fix |
|---------|-------|-----|
| 502 Bad Gateway | App not running | `sudo systemctl start quiz-generator` |
| Connection timeout | Security group | Add HTTP (80) inbound rule |
| yt-dlp not found | Not installed globally | `sudo -u quizapp /opt/youtube-quiz-generator/venv/bin/pip install yt-dlp` |
| NVIDIA API errors | Missing API key | Edit `/opt/youtube-quiz-generator/.env` |
| Out of memory | t2.micro only 1GB RAM | Check swap is active: `free -h` |
| App crashes on start | Python dependency issue | Check logs: `sudo journalctl -u quiz-generator -n 50` |

### Restart everything

```bash
sudo systemctl restart quiz-generator
sudo systemctl reload nginx
```

---

## Architecture Diagram

```
Internet → nginx (port 80) → gunicorn (port 8000) → FastAPI app
                                    ↓
                            Cloudflare Worker → YouTube (for transcripts)
                                    ↓
                            NVIDIA NIM API (for LLM quiz generation)
```

- **nginx** handles SSL termination, SSE timeout management, and compression
- **gunicorn** manages 2 uvicorn worker processes for the ASGI app
- **Cloudflare Worker** proxies YouTube transcript requests (stays on Cloudflare)
- **NVIDIA NIM** provides LLM inference for quiz generation



 http://51.21.128.178/
