#!/usr/bin/env python3
"""Generate a step-by-step AWS EC2 deployment guide PDF for the YouTube Quiz Generator."""

import os
import sys
import io

if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from fpdf import FPDF


class DeployPDF(FPDF):
    def header(self):
        if self.page_no() > 1:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(128, 128, 128)
            self.cell(0, 10, "YouTube Quiz Generator - AWS EC2 Deployment Guide", align="C")
            self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    def title_page(self):
        self.add_page()
        self.ln(50)
        self.set_font("Helvetica", "B", 28)
        self.set_text_color(30, 60, 120)
        self.cell(0, 15, "AWS EC2 Deployment Guide", align="C")
        self.ln(15)
        self.set_font("Helvetica", "", 16)
        self.set_text_color(80, 80, 80)
        self.cell(0, 10, "YouTube Quiz Generator", align="C")
        self.ln(8)
        self.set_font("Helvetica", "I", 12)
        self.set_text_color(100, 100, 100)
        self.cell(0, 10, "Step-by-Step Guide for Free Tier Deployment", align="C")
        self.ln(20)
        self.set_draw_color(30, 60, 120)
        self.set_line_width(0.5)
        self.line(30, self.get_y(), 180, self.get_y())
        self.ln(10)
        self.set_font("Helvetica", "", 11)
        self.set_text_color(70, 70, 70)
        self.multi_cell(0, 6, "This guide walks you through deploying the YouTube Quiz Generator\n"
                               "on an AWS EC2 t2.micro instance (12 months free).\n\n"
                               "Why AWS instead of Render?\n"
                               "Render's free tier drops connections after 30 seconds of inactivity,\n"
                               "causing 'connection was lost' errors during quiz generation.\n"
                               "On EC2, you control the timeout settings (300s), eliminating this issue.", align="C")

    def h1(self, text):
        self.set_font("Helvetica", "B", 16)
        self.set_text_color(30, 60, 120)
        self.ln(6)
        self.cell(0, 10, text)
        self.ln(4)
        self.set_draw_color(30, 60, 120)
        self.set_line_width(0.3)
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def h2(self, text):
        self.set_font("Helvetica", "B", 13)
        self.set_text_color(50, 90, 160)
        self.ln(4)
        self.cell(0, 8, text)
        self.ln(3)

    def h3(self, text):
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(70, 70, 70)
        self.ln(2)
        self.cell(0, 7, text)
        self.ln(2)

    def body(self, text):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(40, 40, 40)
        self.multi_cell(0, 5.5, text)
        self.ln(1)

    def bullet(self, text, indent=10):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(40, 40, 40)
        x = self.get_x()
        self.set_x(x + indent)
        self.cell(5, 5.5, "-")
        self.multi_cell(0, 5.5, text)
        self.ln(0.5)

    def code_block(self, text):
        self.set_font("Courier", "", 8.5)
        self.set_text_color(40, 40, 40)
        self.set_fill_color(245, 245, 248)
        self.set_draw_color(200, 200, 210)
        lines = text.strip().split("\n")
        x = self.get_x() + 5
        w = self.w - 2 * self.l_margin - 10
        block_h = len(lines) * 4.5 + 6
        # Check if we need a page break
        if self.get_y() + block_h > self.h - 20:
            self.add_page()
        y_start = self.get_y()
        self.rect(x - 2, y_start, w + 4, block_h, style="DF")
        self.set_xy(x, y_start + 3)
        for line in lines:
            self.set_x(x)
            self.cell(w, 4.5, line)
            self.ln()
        self.ln(3)

    def info_box(self, title, text, color=None):
        if color is None:
            color = (30, 60, 120)
        self.set_fill_color(*color)
        y_start = self.get_y()
        self.rect(10, y_start, 190, 8, style="F")
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(255, 255, 255)
        self.set_xy(12, y_start + 1.5)
        self.cell(0, 5, title)
        self.ln(9)
        self.set_fill_color(min(255, color[0] + 230), min(255, color[1] + 230), min(255, color[2] + 230))
        self.set_text_color(40, 40, 40)
        self.set_font("Helvetica", "", 10)
        self.multi_cell(0, 5.5, text, fill=True)
        self.ln(3)

    def step(self, number, title, content=""):
        self.set_font("Helvetica", "B", 11)
        self.set_text_color(30, 60, 120)
        self.set_fill_color(230, 240, 255)
        self.cell(0, 7, f"  Step {number}: {title}", fill=True)
        self.ln(8)
        if content:
            self.body(content)

    def table(self, headers, rows, col_widths=None):
        if col_widths is None:
            col_widths = [190 / len(headers)] * len(headers)
        self.set_font("Helvetica", "B", 9)
        self.set_fill_color(30, 60, 120)
        self.set_text_color(255, 255, 255)
        for i, header in enumerate(headers):
            self.cell(col_widths[i], 7, header, border=1, fill=True, align="C")
        self.ln()
        self.set_font("Helvetica", "", 9)
        self.set_text_color(40, 40, 40)
        for row_idx, row in enumerate(rows):
            self.set_fill_color(245, 245, 250) if row_idx % 2 == 0 else self.set_fill_color(255, 255, 255)
            row_h = 6
            for i, cell in enumerate(row):
                self.cell(col_widths[i], row_h, str(cell), border=1, fill=(row_idx % 2 == 0))
            self.ln()
        self.ln(3)


def build_pdf():
    pdf = DeployPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)

    # ===================== TITLE PAGE =====================
    pdf.title_page()

    # ===================== TABLE OF CONTENTS =====================
    pdf.add_page()
    pdf.h1("Table of Contents")
    toc = [
        ("1. Prerequisites", "3"),
        ("2. Architecture Overview", "3"),
        ("3. Launch an EC2 Instance", "4"),
        ("4. Option A: Automated Deployment (Recommended)", "6"),
        ("5. Option B: Manual Deployment Script", "8"),
        ("6. Option C: Step-by-Step Manual Setup", "9"),
        ("7. Set Your API Key", "12"),
        ("8. Verify the Deployment", "13"),
        ("9. HTTPS Setup (Optional)", "14"),
        ("10. Updating the App", "14"),
        ("11. Troubleshooting", "15"),
        ("12. Common Issues & Fixes", "16"),
        ("13. Useful Commands Reference", "17"),
    ]
    for item, page in toc:
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(40, 40, 40)
        pdf.cell(170, 7, item)
        pdf.cell(20, 7, page, align="R")
        pdf.ln()

    # ===================== 1. PREREQUISITES =====================
    pdf.add_page()
    pdf.h1("1. Prerequisites")
    pdf.body("Before you begin, you need the following:")
    pdf.bullet("An AWS account (free tier eligible) - sign up at https://aws.amazon.com/")
    pdf.bullet("A NVIDIA NIM API key - get one free at https://build.nvidia.com/")
    pdf.bullet("An SSH client (Terminal on Mac/Linux, PuTTY or WSL on Windows)")
    pdf.bullet("A web browser to access the AWS EC2 console")
    pdf.ln(3)

    pdf.info_box("Cost", "AWS EC2 t2.micro is FREE for 12 months (750 hours/month). After 12 months, it costs ~$8.50/month. "
                 "Data transfer is also free within the first 100GB/month.", color=(40, 130, 60))

    # ===================== 2. ARCHITECTURE =====================
    pdf.h1("2. Architecture Overview")
    pdf.body("The deployment architecture on AWS EC2:")
    pdf.ln(2)
    pdf.code_block(
        "  Internet Users\n"
        "       |\n"
        "       v\n"
        "  +-------------------+\n"
        "  |   nginx (port 80) |  <-- Reverse proxy, timeouts, compression\n"
        "  +-------------------+\n"
        "       |\n"
        "       v\n"
        "  +-----------------------------+\n"
        "  |  gunicorn (port 8000)      |  <-- 2 uvicorn worker processes\n"
        "  |  + uvicorn workers         |\n"
        "  |  + FastAPI application      |\n"
        "  +-----------------------------+\n"
        "       |                |\n"
        "       v                v\n"
        "  NVIDIA NIM API    Cloudflare Worker --> YouTube\n"
        "  (Quiz Generation)  (Transcript Proxy)"
    )
    pdf.ln(2)

    pdf.h3("Why This Fixes the Connection Issue")
    pdf.table(
        ["Problem", "Render Free Tier", "AWS EC2 (This Setup)"],
        [
            ["Connection timeout", "30 seconds (fixed)", "300 seconds (configurable)"],
            ["Proxy buffering", "Enabled (kills SSE)", "Disabled for SSE endpoint"],
            ["Keepalive control", "None", "Full control (12s pings)"],
            ["RAM", "512 MB", "1 GB + 2 GB swap"],
            ["Cold starts", "30-60 seconds", "None (always-on)"],
            ["Cost", "Free forever", "Free 12 months, ~$8.50/mo after"],
        ],
        col_widths=[40, 70, 80],
    )

    # ===================== 3. LAUNCH EC2 INSTANCE =====================
    pdf.add_page()
    pdf.h1("3. Launch an EC2 Instance")
    pdf.body("Follow these steps to create your EC2 instance on AWS:")

    pdf.step(1, "Log in to AWS Console")
    pdf.body("Go to https://console.aws.amazon.com/ec2/ and sign in with your AWS account.")

    pdf.step(2, "Launch a New Instance")
    pdf.body("Click the 'Launch Instance' button (orange button, top right).")

    pdf.step(3, "Configure Instance Settings")
    pdf.h3("Name and Tags")
    pdf.body("Enter a name like 'youtube-quiz-generator'.")

    pdf.h3("AMI (Operating System)")
    pdf.body("Select 'Ubuntu 22.04 LTS' or 'Ubuntu 24.04 LTS' from the Quick Start list. "
             "This should be the default option.")

    pdf.h3("Instance Type")
    pdf.body("Select 't2.micro' (Free tier eligible). If you see 't3.micro' as the default, "
             "change it to t2.micro - both work, but t2.micro is guaranteed free tier.")

    pdf.step(4, "Create a Key Pair (for SSH access)")
    pdf.body("Under 'Key pair (login)', click 'Create new key pair'.")
    pdf.bullet("Name: quiz-generator-key (or any name you prefer)")
    pdf.bullet("Type: RSA")
    pdf.bullet("Format: .pem (for Mac/Linux/WSL) or .ppk (for PuTTY on Windows)")
    pdf.body("Click 'Create key pair' and save the downloaded file. "
             "Move it to a secure location (~/.ssh/ on Mac/Linux).")
    pdf.code_block("# Mac/Linux: set correct permissions\nchmod 400 ~/Downloads/quiz-generator-key.pem\nmv ~/Downloads/quiz-generator-key.pem ~/.ssh/")

    pdf.step(5, "Configure Security Group (Network Settings)")
    pdf.body("Under 'Network settings', configure the firewall:")
    pdf.table(
        ["Type", "Protocol", "Port", "Source", "Why"],
        [
            ["SSH", "TCP", "22", "Your IP", "SSH access to manage the server"],
            ["HTTP", "TCP", "80", "0.0.0.0/0", "Web app access from browsers"],
            ["HTTPS", "TCP", "443", "0.0.0.0/0", "HTTPS (for certbot later)"],
        ],
        col_widths=[20, 25, 20, 40, 85],
    )

    pdf.info_box("Security Tip", "For SSH, restricting the source to 'Your IP' is more secure than 0.0.0.0/0. "
                 "If your IP changes, you can update the security group rule later.", color=(180, 130, 20))

    pdf.step(6, "Add User Data (for automated setup)")
    pdf.body("Scroll down to 'Advanced details' and find the 'User data' text box at the bottom. "
             "This is where you paste the automated setup script.")
    pdf.ln(2)
    pdf.info_box("Option A vs B vs C", "Option A (Recommended): Paste userdata.sh into the User data field - fully automated.\n"
                 "Option B: Skip user data, SSH in after launch, and run deploy.sh manually.\n"
                 "Option C: Follow the step-by-step manual setup in Section 6.", color=(30, 60, 120))

    pdf.step(7, "Launch!")
    pdf.body("Click 'Launch instance'. Wait 3-5 minutes for the instance to start and the "
             "setup script to complete. Then proceed to Section 7 to set your API key.")

    # ===================== 4. OPTION A: AUTOMATED =====================
    pdf.add_page()
    pdf.h1("4. Option A: Automated Deployment (Recommended)")
    pdf.body("This is the fastest way to deploy. The entire server is configured automatically "
             "when the EC2 instance first boots.")
    pdf.ln(2)

    pdf.step(1, "Get the User Data Script")
    pdf.body("The file is located at deploy/aws/userdata.sh in the repository. You can either:")
    pdf.bullet("Open it from the cloned repo")
    pdf.bullet("Or view it on GitHub: https://github.com/Nikhilramswaminaidu/youtube_video_quiz_generator/blob/main/deploy/aws/userdata.sh")
    pdf.body("Copy the ENTIRE contents of userdata.sh to your clipboard.")

    pdf.step(2, "Paste into EC2 User Data")
    pdf.body("During EC2 instance launch (Step 6 above), paste the entire userdata.sh script "
             "into the 'User data' text box under 'Advanced details'.")
    pdf.code_block(
        "# The user data field looks like this:\n"
        "#\n"
        "# +------------------------------------------+\n"
        "# | User data                                |\n"
        "# |                                          |\n"
        "# | #!/bin/bash                              |\n"
        "# | # Paste the userdata.sh content here    |\n"
        "# | set -euo pipefail                         |\n"
        "# | ...                                      |\n"
        "# +------------------------------------------+"
    )

    pdf.step(3, "Launch and Wait")
    pdf.body("Launch the instance. The setup script runs automatically on first boot. "
             "It takes approximately 3-5 minutes to complete. The script will:")
    pdf.bullet("Update system packages and install Python 3.11, nginx, ffmpeg, git")
    pdf.bullet("Create a 2GB swap file (t2.micro has only 1GB RAM)")
    pdf.bullet("Create a 'quizapp' system user")
    pdf.bullet("Clone the repository into /opt/youtube-quiz-generator")
    pdf.bullet("Set up a Python virtual environment and install all dependencies")
    pdf.bullet("Configure nginx as a reverse proxy with SSE-optimized timeouts")
    pdf.bullet("Install a systemd service for auto-restart on crash")
    pdf.bullet("Start both the app and nginx")

    pdf.step(4, "Set Your API Key (REQUIRED)")
    pdf.body("The app won't work without your NVIDIA API key. SSH into your instance and edit the .env file:")
    pdf.code_block(
        "# SSH into your instance (replace with your key and IP)\n"
        "ssh -i ~/.ssh/quiz-generator-key.pem ubuntu@<YOUR_EC2_PUBLIC_IP>\n"
        "\n"
        "# Edit the .env file\n"
        "sudo nano /opt/youtube-quiz-generator/.env\n"
        "\n"
        "# Replace the placeholder with your actual key:\n"
        "#   NVIDIA_API_KEY=nvapi-paste-your-key-here\n"
        "# becomes:\n"
        "#   NVIDIA_API_KEY=nvapi-your-actual-key-here\n"
        "\n"
        "# Save and exit (Ctrl+X, Y, Enter)\n"
        "\n"
        "# Restart the app to pick up the new key\n"
        "sudo systemctl restart quiz-generator"
    )

    pdf.step(5, "Visit Your App")
    pdf.body("Open your browser and go to:")
    pdf.code_block("http://<YOUR_EC2_PUBLIC_IP>/")
    pdf.body("You can find your EC2 public IP in the AWS Console under your instance details, "
             "or by running this command on the instance:")
    pdf.code_block("curl http://169.254.169.254/latest/meta-data/public-ipv4")

    # ===================== 5. OPTION B: DEPLOY.SH =====================
    pdf.add_page()
    pdf.h1("5. Option B: Manual Deployment Script")
    pdf.body("If you already have a running EC2 instance without user data, use the deploy.sh script.")
    pdf.ln(2)

    pdf.step(1, "SSH Into Your Instance")
    pdf.code_block("ssh -i ~/.ssh/quiz-generator-key.pem ubuntu@<YOUR_EC2_PUBLIC_IP>")

    pdf.step(2, "Clone the Repository")
    pdf.code_block(
        "git clone https://github.com/Nikhilramswaminaidu/youtube_video_quiz_generator.git\n"
        "cd youtube_video_quiz_generator"
    )

    pdf.step(3, "Run the Deploy Script")
    pdf.code_block("sudo bash deploy/aws/deploy.sh")
    pdf.body("The script runs through the same steps as userdata.sh but with colored output and progress indicators. "
             "It takes 3-5 minutes to complete.")

    pdf.step(4, "Set Your API Key")
    pdf.code_block(
        "sudo nano /opt/youtube-quiz-generator/.env\n"
        "# Replace NVIDIA_API_KEY=nvapi-paste-your-key-here\n"
        "# with your actual key\n"
        "sudo systemctl restart quiz-generator"
    )

    # ===================== 6. OPTION C: STEP-BY-STEP =====================
    pdf.add_page()
    pdf.h1("6. Option C: Step-by-Step Manual Setup")
    pdf.body("If you want full control over every step, follow this guide.")
    pdf.ln(2)

    pdf.step(1, "SSH Into Your Instance")
    pdf.code_block("ssh -i ~/.ssh/quiz-generator-key.pem ubuntu@<YOUR_EC2_PUBLIC_IP>")

    pdf.step(2, "Update System & Install Packages")
    pdf.code_block(
        "sudo apt-get update && sudo apt-get upgrade -y\n"
        "sudo apt-get install -y curl wget git software-properties-common \\\n"
        "    build-essential libssl-dev zlib1g-dev nginx ffmpeg\n"
        "\n"
        "# Install Python 3.11\n"
        "sudo add-apt-repository -y ppa:deadsnakes/ppa\n"
        "sudo apt-get update\n"
        "sudo apt-get install -y python3.11 python3.11-venv python3.11-dev python3-pip"
    )

    pdf.step(3, "Create Swap File (t2.micro has only 1GB RAM)")
    pdf.code_block(
        "sudo fallocate -l 2G /swapfile\n"
        "sudo chmod 600 /swapfile\n"
        "sudo mkswap /swapfile\n"
        "sudo swapon /swapfile\n"
        "echo '/swapfile none swap sw 0 0' | sudo tee -a /etc/fstab\n"
        "\n"
        "# Verify swap is active\n"
        "free -h"
    )

    pdf.step(4, "Create App User & Clone Repository")
    pdf.code_block(
        "sudo useradd --system --create-home --shell /bin/bash quizapp\n"
        "sudo git clone https://github.com/Nikhilramswaminaidu/youtube_video_quiz_generator.git /opt/youtube-quiz-generator\n"
        "sudo chown -R quizapp:quizapp /opt/youtube-quiz-generator"
    )

    pdf.step(5, "Set Up Python Virtual Environment")
    pdf.code_block(
        "cd /opt/youtube-quiz-generator\n"
        "sudo -u quizapp python3.11 -m venv venv\n"
        "sudo -u quizapp /opt/youtube-quiz-generator/venv/bin/pip install --upgrade pip setuptools wheel\n"
        "sudo -u quizapp /opt/youtube-quiz-generator/venv/bin/pip install -r requirements.txt\n"
        "sudo -u quizapp /opt/youtube-quiz-generator/venv/bin/pip install gunicorn"
    )

    pdf.step(6, "Configure Environment Variables")
    pdf.code_block(
        "sudo nano /opt/youtube-quiz-generator/.env"
    )
    pdf.body("Add the following content (replace the API key with your actual key):")
    pdf.code_block(
        "# Required: Get your key at https://build.nvidia.com/\n"
        "NVIDIA_API_KEY=nvapi-your-actual-key-here\n"
        "\n"
        "# Optional: Cloudflare Worker URL for transcript proxying\n"
        "YOUTUBE_PROXY_URL=\n"
        "\n"
        "# Optional: Comma-separated custom Invidious instances\n"
        "INVIDIOUS_INSTANCES="
    )
    pdf.code_block(
        "# Secure the .env file\n"
        "sudo chmod 600 /opt/youtube-quiz-generator/.env\n"
        "sudo chown quizapp:quizapp /opt/youtube-quiz-generator/.env"
    )

    pdf.step(7, "Install Systemd Service")
    pdf.body("The systemd service runs the app automatically and restarts it on crashes:")
    pdf.code_block(
        "sudo cp /opt/youtube-quiz-generator/deploy/aws/quiz-generator.service /etc/systemd/system/\n"
        "sudo systemctl daemon-reload\n"
        "sudo systemctl enable quiz-generator\n"
        "sudo systemctl start quiz-generator"
    )

    pdf.step(8, "Install Nginx Configuration")
    pdf.body("This is the critical config that fixes the SSE connection timeout issue:")
    pdf.code_block(
        "sudo cp /opt/youtube-quiz-generator/deploy/aws/nginx.conf /etc/nginx/sites-available/quiz-generator\n"
        "sudo rm -f /etc/nginx/sites-enabled/default\n"
        "sudo ln -sf /etc/nginx/sites-available/quiz-generator /etc/nginx/sites-enabled/\n"
        "sudo nginx -t && sudo systemctl reload nginx"
    )

    # ===================== 7. SET API KEY =====================
    pdf.add_page()
    pdf.h1("7. Set Your API Key")
    pdf.body("Regardless of which deployment method you used, you MUST set your NVIDIA API key "
             "before the app will work.")
    pdf.ln(2)

    pdf.h3("Get Your NVIDIA NIM API Key")
    pdf.bullet("Go to https://build.nvidia.com/")
    pdf.bullet("Sign in or create a free account")
    pdf.bullet("Search for 'Llama 3.3 70B Instruct'")
    pdf.bullet("Click 'Get API Key' and copy it")
    pdf.ln(2)

    pdf.h3("Add the Key to Your Server")
    pdf.code_block(
        "# SSH into your instance\n"
        "ssh -i ~/.ssh/quiz-generator-key.pem ubuntu@<YOUR_EC2_PUBLIC_IP>\n"
        "\n"
        "# Edit the .env file\n"
        "sudo nano /opt/youtube-quiz-generator/.env\n"
        "\n"
        "# Replace the placeholder:\n"
        "#   NVIDIA_API_KEY=nvapi-paste-your-key-here\n"
        "# With your actual key:\n"
        "#   NVIDIA_API_KEY=nvapi-xxxxxxxxxxxxxxxxxxxx\n"
        "\n"
        "# Save (Ctrl+X, Y, Enter) and restart\n"
        "sudo systemctl restart quiz-generator"
    )

    pdf.info_box("Important", "The app will NOT generate quizzes without a valid NVIDIA_API_KEY. "
                 "The health endpoint (/api/health) will still respond, but quiz generation will fail "
                 "with an authentication error.", color=(180, 40, 40))

    # ===================== 8. VERIFY DEPLOYMENT =====================
    pdf.h1("8. Verify the Deployment")
    pdf.body("After setting your API key, verify everything is working:")

    pdf.h3("Check Service Status")
    pdf.code_block(
        "sudo systemctl status quiz-generator\n"
        "# Should show: active (running)"
    )

    pdf.h3("Check Health Endpoint")
    pdf.code_block(
        "# From the server itself\n"
        "curl http://localhost:8000/api/health\n"
        "\n"
        "# From your local machine (replace IP)\n"
        "curl http://<YOUR_EC2_PUBLIC_IP>/api/health"
    )
    pdf.body("You should see a JSON response with yt-dlp version, python version, and status info.")

    pdf.h3("Open in Browser")
    pdf.code_block("http://<YOUR_EC2_PUBLIC_IP>/")
    pdf.body("You should see the YouTube Quiz Generator interface. Try generating a quiz!")

    pdf.h3("Check Nginx is Proxying Correctly")
    pdf.code_block(
        "sudo nginx -t          # Should show 'test is successful'\n"
        "sudo systemctl status nginx  # Should show 'active (running)'"
    )

    # ===================== 9. HTTPS =====================
    pdf.add_page()
    pdf.h1("9. HTTPS Setup (Optional)")
    pdf.body("The app works fine over HTTP. If you have a domain name, you can add free HTTPS "
             "with Let's Encrypt:")
    pdf.ln(2)

    pdf.step(1, "Point Your Domain to the EC2 IP")
    pdf.body("In your DNS provider (Route 53, Cloudflare, Namecheap, etc.), create an A record "
             "pointing your domain to the EC2 instance's public IP.")
    pdf.code_block(
        "# Example DNS record:\n"
        "# Type: A\n"
        "# Name: quiz (for quiz.yourdomain.com)\n"
        "# Value: <YOUR_EC2_PUBLIC_IP>"
    )

    pdf.step(2, "Update Nginx Server Name")
    pdf.code_block(
        "# Edit the nginx config\n"
        "sudo nano /etc/nginx/sites-available/quiz-generator\n"
        "\n"
        "# Change: server_name _;\n"
        "# To:     server_name quiz.yourdomain.com;\n"
        "\n"
        "sudo nginx -t && sudo systemctl reload nginx"
    )

    pdf.step(3, "Install SSL Certificate")
    pdf.code_block(
        "# Install certbot if not already installed\n"
        "sudo apt-get install -y certbot python3-certbot-nginx\n"
        "\n"
        "# Get and install the certificate\n"
        "sudo certbot --nginx -d quiz.yourdomain.com\n"
        "\n"
        "# Certbot will automatically:\n"
        "# - Generate an SSL certificate\n"
        "# - Modify nginx config for HTTPS\n"
        "# - Set up auto-renewal via systemd timer"
    )

    pdf.info_box("Auto-Renewal", "Certbot sets up automatic certificate renewal. You can verify it with:\n"
                 "sudo certbot renew --dry-run", color=(40, 130, 60))

    # ===================== 10. UPDATING =====================
    pdf.h1("10. Updating the App")
    pdf.body("To pull the latest code and restart the service:")
    pdf.code_block(
        "# Option 1: Use the update script\n"
        "sudo bash /opt/youtube-quiz-generator/deploy/aws/update.sh\n"
        "\n"
        "# Option 2: Manual update\n"
        "cd /opt/youtube-quiz-generator\n"
        "sudo -u quizapp git pull origin main\n"
        "sudo -u quizapp /opt/youtube-quiz-generator/venv/bin/pip install -r requirements.txt\n"
        "sudo systemctl restart quiz-generator"
    )

    # ===================== 11. TROUBLESHOOTING =====================
    pdf.add_page()
    pdf.h1("11. Troubleshooting")

    pdf.h3("App Not Starting")
    pdf.code_block(
        "# Check the service status\n"
        "sudo systemctl status quiz-generator\n"
        "\n"
        "# View detailed logs\n"
        "sudo journalctl -u quiz-generator -n 100\n"
        "\n"
        "# Follow live logs\n"
        "sudo journalctl -u quiz-generator -f"
    )

    pdf.h3("502 Bad Gateway")
    pdf.body("This means nginx is running but can't reach the app. Check:")
    pdf.bullet("Is the quiz-generator service running? `sudo systemctl status quiz-generator`")
    pdf.bullet("Is gunicorn listening on port 8000? `curl http://localhost:8000/api/health`")
    pdf.bullet("Check the app logs: `sudo journalctl -u quiz-generator -n 50`")

    pdf.h3("Connection Refused / Timeout from Browser")
    pdf.body("This usually means the security group is blocking HTTP traffic:")
    pdf.bullet("Go to AWS Console > EC2 > Security Groups")
    pdf.bullet("Find the security group attached to your instance")
    pdf.bullet("Add an inbound rule: Type=HTTP, Port=80, Source=0.0.0.0/0")

    pdf.h3("NVIDIA API Errors (401 Unauthorized)")
    pdf.body("Your NVIDIA_API_KEY is missing or invalid:")
    pdf.code_block(
        "# Check the .env file\n"
        "cat /opt/youtube-quiz-generator/.env\n"
        "\n"
        "# Make sure NVIDIA_API_KEY is set (not the placeholder)\n"
        "# Restart after editing\n"
        "sudo systemctl restart quiz-generator"
    )

    pdf.h3("yt-dlp Not Found")
    pdf.code_block(
        "# Reinstall yt-dlp in the virtual environment\n"
        "sudo -u quizapp /opt/youtube-quiz-generator/venv/bin/pip install yt-dlp\n"
        "sudo systemctl restart quiz-generator"
    )

    pdf.h3("Out of Memory")
    pdf.body("t2.micro only has 1GB RAM. Check if swap is active:")
    pdf.code_block(
        "free -h\n"
        "# Should show Swap: 2.0G\n"
        "\n"
        "# If swap is missing, create it:\n"
        "sudo fallocate -l 2G /swapfile\n"
        "sudo chmod 600 /swapfile\n"
        "sudo mkswap /swapfile\n"
        "sudo swapon /swapfile"
    )

    # ===================== 12. COMMON ISSUES =====================
    pdf.add_page()
    pdf.h1("12. Common Issues & Fixes")
    pdf.table(
        ["Problem", "Likely Cause", "Fix"],
        [
            ["502 Bad Gateway", "App not running", "sudo systemctl start quiz-generator"],
            ["Connection timeout", "Security group", "Add HTTP (80) inbound rule"],
            ["401 NVIDIA API error", "Missing/wrong API key", "Edit .env, restart service"],
            ["yt-dlp not found", "Not in venv PATH", "pip install yt-dlp in venv"],
            ["Out of memory", "t2.micro = 1GB RAM", "Check swap: free -h"],
            ["App crashes on start", "Python deps missing", "pip install -r requirements.txt"],
            ["SSE connection drops", "nginx buffering", "Check proxy_buffering off in config"],
            ["Quiz generation slow", "Normal for LLM", "Expect 30-120s per batch"],
        ],
        col_widths=[35, 50, 105],
    )

    # ===================== 13. COMMANDS REFERENCE =====================
    pdf.h1("13. Useful Commands Reference")
    pdf.code_block(
        "# == Service Management ==\n"
        "sudo systemctl start quiz-generator     # Start the app\n"
        "sudo systemctl stop quiz-generator      # Stop the app\n"
        "sudo systemctl restart quiz-generator   # Restart the app\n"
        "sudo systemctl status quiz-generator    # Check status\n"
        "\n"
        "# == Logs ==\n"
        "sudo journalctl -u quiz-generator -f    # Follow live logs\n"
        "sudo journalctl -u quiz-generator -n 100 # Last 100 lines\n"
        "sudo journalctl -u quiz-generator --since today\n"
        "\n"
        "# == Nginx ==\n"
        "sudo nginx -t                           # Test config\n"
        "sudo systemctl reload nginx              # Reload config\n"
        "sudo systemctl restart nginx             # Full restart\n"
        "\n"
        "# == Health Check ==\n"
        "curl http://localhost:8000/api/health   # From server\n"
        "curl http://<EC2_IP>/api/health          # From outside\n"
        "\n"
        "# == Update the App ==\n"
        "sudo bash /opt/youtube-quiz-generator/deploy/aws/update.sh\n"
        "\n"
        "# == Edit Environment Variables ==\n"
        "sudo nano /opt/youtube-quiz-generator/.env\n"
        "sudo systemctl restart quiz-generator\n"
        "\n"
        "# == EC2 Instance IP ==\n"
        "curl http://169.254.169.254/latest/meta-data/public-ipv4"
    )

    # Save
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "AWS_EC2_Deployment_Guide.pdf")
    pdf.output(output_path)
    print(f"PDF saved to: {output_path}")
    return output_path


if __name__ == "__main__":
    path = build_pdf()
    print(f"Done! Open: {path}")