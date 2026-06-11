#!/usr/bin/env python3
"""Generate a comprehensive project documentation PDF for the YouTube Quiz Generator."""

import os
import sys
import io

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")

from fpdf import FPDF


class ProjectPDF(FPDF):
    def header(self):
        if self.page_no() > 1:
            self.set_font("Helvetica", "I", 8)
            self.set_text_color(128, 128, 128)
            self.cell(0, 10, "YouTube Quiz Generator - Project Documentation", align="C")
            self.ln(5)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(128, 128, 128)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")

    def title_page(self):
        self.add_page()
        self.ln(60)
        self.set_font("Helvetica", "B", 28)
        self.set_text_color(30, 60, 120)
        self.cell(0, 15, "YouTube Quiz Generator", align="C")
        self.ln(15)
        self.set_font("Helvetica", "", 16)
        self.set_text_color(80, 80, 80)
        self.cell(0, 10, "Project Documentation", align="C")
        self.ln(8)
        self.set_font("Helvetica", "I", 12)
        self.cell(0, 10, "AI-Powered UPSC Quiz Generation from YouTube Videos", align="C")
        self.ln(20)
        self.set_font("Helvetica", "", 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, "Deployed on Render (Free Tier)", align="C")
        self.ln(6)
        self.cell(0, 8, "Powered by NVIDIA NIM (Llama 3.3 70B)", align="C")
        self.ln(20)
        # Draw a separator line
        self.set_draw_color(30, 60, 120)
        self.set_line_width(0.5)
        self.line(30, self.get_y(), 180, self.get_y())
        self.ln(10)
        self.set_font("Helvetica", "I", 10)
        self.set_text_color(120, 120, 120)
        self.cell(0, 8, "June 2026", align="C")

    def section_title(self, title, level=1):
        if level == 1:
            self.set_font("Helvetica", "B", 16)
            self.set_text_color(30, 60, 120)
            self.ln(6)
            self.cell(0, 10, title)
            self.ln(4)
            self.set_draw_color(30, 60, 120)
            self.set_line_width(0.3)
            self.line(10, self.get_y(), 200, self.get_y())
            self.ln(4)
        elif level == 2:
            self.set_font("Helvetica", "B", 13)
            self.set_text_color(50, 90, 160)
            self.ln(4)
            self.cell(0, 8, title)
            self.ln(3)
        elif level == 3:
            self.set_font("Helvetica", "B", 11)
            self.set_text_color(70, 70, 70)
            self.ln(2)
            self.cell(0, 7, title)
            self.ln(2)

    def body_text(self, text):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(40, 40, 40)
        self.multi_cell(0, 5.5, text)
        self.ln(1)

    def bullet_point(self, text, indent=10):
        self.set_font("Helvetica", "", 10)
        self.set_text_color(40, 40, 40)
        x = self.get_x()
        self.set_x(x + indent)
        self.cell(5, 5.5, "-")  # bullet
        self.multi_cell(0, 5.5, text)
        self.ln(0.5)

    def code_block(self, text):
        self.set_font("Courier", "", 9)
        self.set_text_color(40, 40, 40)
        self.set_fill_color(240, 240, 240)
        self.set_draw_color(200, 200, 200)
        x = self.get_x() + 5
        w = self.w - 2 * self.l_margin - 10
        self.set_x(x)
        # Split into lines and render each
        lines = text.split("\n")
        self.rect(x - 2, self.get_y() - 1, w + 4, len(lines) * 5 + 4, style="DF")
        for line in lines:
            self.set_x(x)
            self.cell(w, 5, line)
            self.ln()
        self.ln(3)

    def info_box(self, title, text, color=(30, 60, 120)):
        self.set_fill_color(color[0], color[1], color[2])
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

    def table(self, headers, rows, col_widths=None):
        if col_widths is None:
            col_widths = [190 / len(headers)] * len(headers)

        # Header
        self.set_font("Helvetica", "B", 9)
        self.set_fill_color(30, 60, 120)
        self.set_text_color(255, 255, 255)
        for i, header in enumerate(headers):
            self.cell(col_widths[i], 7, header, border=1, fill=True, align="C")
        self.ln()

        # Rows
        self.set_font("Helvetica", "", 9)
        self.set_text_color(40, 40, 40)
        for row_idx, row in enumerate(rows):
            self.set_fill_color(245, 245, 250) if row_idx % 2 == 0 else self.set_fill_color(255, 255, 255)
            max_lines = 1
            for i, cell in enumerate(row):
                lines = self.multi_cell(col_widths[i], 5.5, str(cell), dry_run=True, output="LINES")
                max_lines = max(max_lines, len(lines))
            row_height = max_lines * 5.5
            y_start = self.get_y()
            for i, cell in enumerate(row):
                x = self.get_x()
                self.rect(x, y_start, col_widths[i], row_height, style="DF" if row_idx % 2 == 0 else "D")
                self.set_xy(x + 1, y_start + 1)
                self.multi_cell(col_widths[i] - 2, 5.5, str(cell))
                self.set_xy(x + col_widths[i], y_start)
            self.set_y(y_start + row_height)
        self.ln(3)


def build_pdf():
    pdf = ProjectPDF()
    pdf.alias_nb_pages()
    pdf.set_auto_page_break(auto=True, margin=20)

    # ===================== TITLE PAGE =====================
    pdf.title_page()

    # ===================== TABLE OF CONTENTS =====================
    pdf.add_page()
    pdf.section_title("Table of Contents")
    toc_items = [
        ("1. Project Overview", "3"),
        ("2. Architecture & Tech Stack", "3"),
        ("3. Project Structure", "4"),
        ("4. Core Features", "5"),
        ("5. Transcript Fetching Strategy", "6"),
        ("6. Quiz Generation Pipeline", "8"),
        ("7. API Endpoints", "9"),
        ("8. Frontend Design", "10"),
        ("9. PDF Export", "11"),
        ("10. Render Deployment", "11"),
        ("11. Deployment Issues & Fixes", "12"),
        ("12. Environment Variables", "14"),
        ("13. Future Roadmap", "14"),
    ]
    for item, page in toc_items:
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(40, 40, 40)
        pdf.cell(170, 7, item)
        pdf.cell(20, 7, page, align="R")
        pdf.ln()

    # ===================== 1. PROJECT OVERVIEW =====================
    pdf.add_page()
    pdf.section_title("1. Project Overview")
    pdf.body_text(
        "The YouTube Quiz Generator is a web application that automatically creates UPSC-style "
        "multiple-choice quizzes from YouTube video transcripts. Users paste a YouTube URL, "
        "select the number of questions (1-30) and difficulty level, and the system fetches the "
        "video's transcript, generates quiz questions using the Llama 3.3 70B model via NVIDIA NIM, "
        "and presents an interactive quiz-taking experience with real-time scoring and PDF export."
    )
    pdf.body_text(
        "The application features a 4-strategy fallback system for transcript fetching (critical for "
        "cloud deployments where YouTube blocks datacenter IPs), a sophisticated batch-generation "
        "pipeline with deduplication, and Server-Sent Events (SSE) for real-time progress feedback "
        "during quiz generation."
    )

    # ===================== 2. ARCHITECTURE & TECH STACK =====================
    pdf.section_title("2. Architecture & Tech Stack")
    pdf.section_title("Backend", level=2)
    pdf.table(
        ["Component", "Technology", "Purpose"],
        [
            ["Web Framework", "FastAPI + Uvicorn", "Async API server"],
            ["Validation", "Pydantic v2", "Request/response models"],
            ["LLM API", "NVIDIA NIM (Llama 3.3 70B)", "Quiz question generation"],
            ["Transcript (Primary)", "youtube-transcript-api", "Direct YouTube transcript fetch"],
            ["Transcript (Fallback)", "yt-dlp", "CLI subtitle download"],
            ["Transcript (Proxy)", "Cloudflare Worker", "Edge proxy bypassing IP blocks"],
            ["Transcript (Fallback)", "Invidious API", "Public proxy instances"],
            ["HTTP Client", "httpx (async) / requests", "API calls"],
            ["PDF Generation", "fpdf2", "Quiz PDF exports"],
        ],
        col_widths=[45, 55, 90],
    )

    pdf.section_title("Frontend", level=2)
    pdf.table(
        ["Component", "Technology", "Purpose"],
        [
            ["UI", "Vanilla HTML/CSS/JS", "Single-page quiz interface"],
            ["Streaming", "Server-Sent Events", "Real-time generation progress"],
            ["Fallback", "POST endpoint", "Non-streaming quiz generation"],
        ],
        col_widths=[40, 60, 90],
    )

    pdf.section_title("Deployment", level=2)
    pdf.table(
        ["Component", "Platform", "Purpose"],
        [
            ["Web Service", "Render (Free Tier)", "API + Frontend hosting"],
            ["Transcript Proxy", "Cloudflare Workers", "Edge proxy for YouTube transcripts"],
        ],
        col_widths=[50, 55, 85],
    )

    # ===================== 3. PROJECT STRUCTURE =====================
    pdf.add_page()
    pdf.section_title("3. Project Structure")
    pdf.code_block(
        "D:\\Videos to quiz\\\n"
        "+-- .env                          # Environment variables\n"
        "+-- .env.example                  # Template for .env\n"
        "+-- Procfile                      # Render start command\n"
        "+-- render.yaml                   # Render deployment config\n"
        "+-- requirements.txt              # Python dependencies\n"
        "+-- run_server.py                 # Server entry point (uvicorn)\n"
        "+-- cloudflare-worker.js          # Cloudflare Worker for proxy\n"
        "+-- quiz_generator.py             # CLI standalone script\n"
        "+-- frontend/\n"
        "|   +-- index.html                # Single-page quiz UI\n"
        "+-- backend/app/\n"
        "    +-- main.py                   # FastAPI app, CORS, health check\n"
        "    +-- models/\n"
        "    |   +-- schemas.py            # Pydantic + dataclass models\n"
        "    +-- services/\n"
        "    |   +-- transcript.py         # 4-strategy transcript fetch\n"
        "    |   +-- quiz_generator.py      # LLM batch generation\n"
        "    |   +-- pdf_generator.py       # PDF export (quiz/answers/results)\n"
        "    +-- routes/\n"
        "        +-- quiz.py               # Quiz API routes (SSE + REST)\n"
        "        +-- video.py              # Video language listing"
    )

    # ===================== 4. CORE FEATURES =====================
    pdf.add_page()
    pdf.section_title("4. Core Features")

    pdf.section_title("Quiz Generation", level=2)
    pdf.bullet_point("UPSC-style MCQ generation from YouTube video transcripts")
    pdf.bullet_point("1-30 questions per quiz, three difficulty levels (easy, moderate, hard)")
    pdf.bullet_point("Question formats: statement-based, assertion-reason, analytical, contextual")
    pdf.bullet_point("Always generates quizzes in English, regardless of source video language")
    pdf.bullet_point("In-memory caching with 1-hour TTL to avoid redundant LLM calls")

    pdf.section_title("Transcript Fetching", level=2)
    pdf.bullet_point("4-strategy fallback chain for maximum reliability on cloud IPs")
    pdf.bullet_point("Auto-detects best available caption language")
    pdf.bullet_point("Prefers manual captions over auto-generated ones")
    pdf.bullet_point("Lists available caption languages per video")

    pdf.section_title("Web Interface", level=2)
    pdf.bullet_point("Real-time SSE progress: progress bar, question counter, ETA countdown")
    pdf.bullet_point("Graceful SSE-to-POST fallback if streaming fails")
    pdf.bullet_point("Interactive quiz-taking with instant scoring and explanations")
    pdf.bullet_point("Mobile-responsive design with touch-friendly targets")

    pdf.section_title("PDF Export", level=2)
    pdf.bullet_point("Blank quiz (student handout with answer grid)")
    pdf.bullet_point("Answer key (correct answers highlighted with explanations)")
    pdf.bullet_point("Scored results report (per-question marking, percentage, badge)")

    # ===================== 5. TRANSCRIPT FETCHING =====================
    pdf.add_page()
    pdf.section_title("5. Transcript Fetching Strategy")
    pdf.body_text(
        "YouTube blocks transcript access from datacenter IPs (like Render's servers). "
        "The application implements a 4-strategy fallback chain to maximize reliability:"
    )

    pdf.table(
        ["Priority", "Method", "Cloud IPs?", "Setup Required"],
        [
            ["1", "youtube-transcript-api", "No (blocked)", "None"],
            ["2", "Cloudflare Worker proxy", "Yes (edge IPs)", "Deploy worker + set URL"],
            ["3", "Invidious instances", "Yes", "None (built-in defaults)"],
            ["4", "yt-dlp CLI tool", "Sometimes", "Install yt-dlp"],
        ],
        col_widths=[20, 60, 50, 60],
    )

    pdf.section_title("Strategy 1: youtube-transcript-api", level=2)
    pdf.body_text(
        "Direct Python API call to YouTube. Prefers manually created captions over auto-generated. "
        "Builds a language preference list and supports YouTube's built-in translation for unavailable languages. "
        "Fails on datacenter IPs with IP blocks or captchas."
    )

    pdf.section_title("Strategy 2: Cloudflare Worker Proxy", level=2)
    pdf.body_text(
        "Sends requests through a Cloudflare Worker deployed at the edge. The Worker fetches YouTube's timedtext "
        "API with a browser User-Agent, bypassing IP-based blocks. Returns the parsed caption text. "
        "Requires deploying cloudflare-worker.js and setting YOUTUBE_PROXY_URL env var."
    )

    pdf.section_title("Strategy 3: Invidious Instances", level=2)
    pdf.body_text(
        "Uses public Invidious instances (privacy-focused YouTube front-ends) as proxies. "
        "Dynamically discovers instances from api.invidious.io, filtering for ones with working APIs. "
        "Smart caption selection: manual target-lang > auto target-lang > manual English > auto English > first available. "
        "15-second timeout per instance, tries multiple instances on failure."
    )

    pdf.section_title("Strategy 4: yt-dlp", level=2)
    pdf.body_text(
        "Two-phase approach: first dumps video info JSON to extract subtitle URLs, then downloads via requests. "
        "Falls back to downloading subtitle files directly to a temp directory. "
        "Prefers manual subtitles. 60-second timeout per invocation."
    )

    pdf.section_title("Universal Subtitle Parsing", level=2)
    pdf.body_text(
        "Handles three formats: YouTube srv1/srv3 XML, SRT, and WebVTT. "
        "Strips timestamps, sequence numbers, HTML tags, and VTT metadata. "
        "Returns clean plain text joined by spaces."
    )

    # ===================== 6. QUIZ GENERATION PIPELINE =====================
    pdf.add_page()
    pdf.section_title("6. Quiz Generation Pipeline")

    pdf.section_title("Batch Sizing", level=2)
    pdf.table(
        ["Difficulty", "Question Count", "Batch Size", "Rationale"],
        [
            ["Easy/Moderate", "<= 20", "10", "Standard requests complete quickly"],
            ["Hard or > 20 Qs", "Any", "7", "Larger prompts need smaller batches"],
            ["Hard + > 20 Qs", "> 20", "5", "Complex prompts need smallest batches"],
        ],
        col_widths=[35, 35, 30, 90],
    )

    pdf.section_title("Multi-Batch Flow", level=2)
    pdf.bullet_point("Transcript is split into N sections with 200-char overlap windows")
    pdf.bullet_point("Each batch receives a different section, producing diverse questions")
    pdf.bullet_point("Later batches receive an 'exclude topics' list from earlier batches")
    pdf.bullet_point("After all batches complete, deduplication removes similar questions")
    pdf.bullet_point("Questions are trimmed to the requested count")

    pdf.section_title("LLM Configuration", level=2)
    pdf.table(
        ["Setting", "Value"],
        [
            ["Primary Model", "meta/llama-3.3-70b-instruct"],
            ["Fallback Model", "nvidia/llama-3.3-nemotron-super-49b-v1.5"],
            ["Temperature", "0.4"],
            ["Max Tokens", "min(num_questions * 250, 2000)"],
            ["Max Retries", "3 with exponential backoff (2s, 4s, 8s)"],
            ["Timeout", "120s + 5s per question in batch"],
        ],
        col_widths=[60, 130],
    )

    pdf.section_title("Deduplication", level=2)
    pdf.body_text(
        "Uses difflib.SequenceMatcher with a 0.7 similarity threshold on question text. "
        "When duplicates are found, the question with the longer explanation is kept. "
        "Returns both kept and removed questions for logging."
    )

    # ===================== 7. API ENDPOINTS =====================
    pdf.add_page()
    pdf.section_title("7. API Endpoints")

    pdf.section_title("Quiz Endpoints", level=2)
    pdf.table(
        ["Method", "Path", "Description"],
        [
            ["POST", "/api/quiz/generate", "Generate quiz (returns full JSON)"],
            ["GET", "/api/quiz/generate/stream", "SSE streaming quiz generation"],
            ["POST", "/api/quiz/submit", "Submit answers and get scored"],
            ["GET", "/api/quiz/{id}/pdf", "Download quiz as PDF (quiz/answers/results)"],
        ],
        col_widths=[25, 70, 95],
    )

    pdf.section_title("Video Endpoints", level=2)
    pdf.table(
        ["Method", "Path", "Description"],
        [
            ["GET", "/api/video/{id}/languages", "List available caption languages"],
        ],
        col_widths=[25, 80, 85],
    )

    pdf.section_title("Health & Debug", level=2)
    pdf.table(
        ["Method", "Path", "Description"],
        [
            ["GET", "/api/health", "Service health (yt-dlp, versions, config)"],
        ],
        col_widths=[25, 80, 85],
    )

    pdf.section_title("SSE Stream Events", level=2)
    pdf.body_text("The /api/quiz/generate/stream endpoint emits these SSE events:")
    pdf.bullet_point("progress: Step updates (transcript, generating, batch_done, dedup, done)")
    pdf.bullet_point("complete: Final quiz data in JSON format")
    pdf.bullet_point("error: Error message if generation fails")
    pdf.bullet_point(":keepalive: Comment-type pings every 12 seconds during LLM calls")

    # ===================== 8. FRONTEND DESIGN =====================
    pdf.section_title("8. Frontend Design")
    pdf.body_text(
        "The frontend is a single index.html file (~1043 lines) containing all HTML, CSS, and JavaScript. "
        "No build tools or frameworks are required."
    )
    pdf.section_title("Key Design Decisions", level=2)
    pdf.bullet_point("SSE streaming as primary path with POST fallback for incompatible browsers")
    pdf.bullet_point("Real-time progress: progress bar, step tracker, question counter, ETA countdown")
    pdf.bullet_point("Client-side ETA estimation during POST fallback (~8s per question)")
    pdf.bullet_point("Interactive quiz-taking with radio buttons and per-question scoring")
    pdf.bullet_point("Score badges: Great job! (>=80%), Good effort! (>=50%), Keep studying! (<50%)")
    pdf.bullet_point("Mobile-responsive: CSS media queries at 640px and 380px breakpoints")
    pdf.bullet_point("44px minimum touch target sizes for mobile usability")

    # ===================== 9. PDF EXPORT =====================
    pdf.add_page()
    pdf.section_title("9. PDF Export")
    pdf.body_text(
        "The PDF generator (backend/app/services/pdf_generator.py) uses fpdf2 to produce three export modes:"
    )

    pdf.section_title("Blank Quiz (mode=quiz)", level=3)
    pdf.bullet_point("Questions with lettered options (A/B/C/D)")
    pdf.bullet_point("Answer grid on the last page for students to fill in")

    pdf.section_title("Answer Key (mode=answers)", level=3)
    pdf.bullet_point("Correct answers highlighted in green")
    pdf.bullet_point("Explanations shown below each question")

    pdf.section_title("Results Report (mode=results)", level=3)
    pdf.bullet_point("Per-question correct/wrong marking")
    pdf.bullet_point("Selected vs. correct answer comparison")
    pdf.bullet_point("Score badge and percentage")

    pdf.section_title("Unicode Handling", level=2)
    pdf.body_text(
        "The PDF generator includes a character sanitization layer that replaces Unicode smart quotes, "
        "em dashes, bullets, and other special characters with ASCII equivalents. Remaining non-Latin-1 "
        "characters are replaced with '?' to prevent fpdf2 encoding errors."
    )

    # ===================== 10. RENDER DEPLOYMENT =====================
    pdf.section_title("10. Render Deployment")
    pdf.body_text(
        "The application is deployed on Render's free tier using the configuration in render.yaml:"
    )
    pdf.code_block(
        "services:\n"
        "  - type: web\n"
        "    name: youtube-quiz-generator\n"
        "    runtime: python\n"
        "    buildCommand: pip install -r requirements.txt\n"
        "    startCommand: python run_server.py\n"
        "    plan: free\n"
        "    envVars:\n"
        "      - key: NVIDIA_API_KEY\n"
        "        sync: false\n"
        "      - key: YOUTUBE_PROXY_URL\n"
        "        sync: false\n"
        "      - key: INVIDIOUS_INSTANCES\n"
        "        sync: false"
    )

    pdf.section_title("Key Render Constraints", level=2)
    pdf.bullet_point("Free tier: 750 hours/month, 512 MB RAM, spins down after inactivity")
    pdf.bullet_point("Request timeout: 30 seconds for standard HTTP requests")
    pdf.bullet_point("SSE connections have better longevity but still subject to proxy timeouts")
    pdf.bullet_point("Cold starts: ~30-60 seconds when the service spins up from idle")
    pdf.bullet_point("Dynamic port assignment via PORT environment variable")

    # ===================== 11. DEPLOYMENT ISSUES & FIXES =====================
    pdf.add_page()
    pdf.section_title("11. Deployment Issues & Fixes")
    pdf.info_box(
        "CRITICAL ISSUE: Connection Lost During Quiz Generation",
        "On Render's free tier, quiz generation fails with the error: "
        "'Quiz generation failed. The connection was lost - please try again.' "
        "This happens because Render's proxy drops connections after ~30 seconds of inactivity.",
        color=(180, 40, 40)
    )

    pdf.section_title("Root Cause", level=2)
    pdf.body_text(
        "Render's reverse proxy (nginx) closes connections that show no activity for approximately "
        "30 seconds. During quiz generation, a single LLM API call to NVIDIA NIM can take 30-120+ "
        "seconds. The original code sent a keepalive SSE comment BEFORE each batch call, but sent "
        "NOTHING during the call itself. This meant that if a single LLM call took longer than 30 "
        "seconds, the proxy would silently close the connection, causing the frontend to receive "
        "an EventSource error with no data - resulting in the 'connection was lost' message."
    )

    pdf.section_title("Fix: Periodic Keepalive During LLM Calls", level=2)
    pdf.body_text(
        "The fix runs each LLM batch call as an asyncio background task and sends keepalive "
        "SSE comments every 12 seconds while the task is running. This ensures Render's proxy "
        "always sees activity on the connection, preventing it from closing the connection."
    )
    pdf.code_block(
        "# Before (broken - only one keepalive before the call):\n"
        "yield ': keepalive\\n\\n'\n"
        "batch_quiz = await _generate_batch_async(...)\n"
        "\n"
        "# After (fixed - keepalive every 12s during the call):\n"
        "batch_task = asyncio.create_task(\n"
        "    _generate_batch_async(...)\n"
        ")\n"
        "while not batch_task.done():\n"
        "    yield ': keepalive\\n\\n'\n"
        "    done, _ = await asyncio.wait({batch_task}, timeout=12.0)\n"
        "    if done:\n"
        "        break\n"
        "batch_quiz = batch_task.result()"
    )

    pdf.section_title("Fix: Anti-Buffering Headers", level=2)
    pdf.body_text(
        "Added headers to the SSE StreamingResponse to prevent proxy buffering:"
    )
    pdf.code_block(
        "StreamingResponse(\n"
        "    event_stream(),\n"
        "    media_type='text/event-stream',\n"
        "    headers={\n"
        "        'Cache-Control': 'no-cache',\n"
        "        'X-Accel-Buffering': 'no',  # Prevent nginx/Render proxy buffering\n"
        "        'Connection': 'keep-alive',\n"
        "    },\n"
        ")"
    )

    pdf.section_title("Other Render Deployment Issues", level=2)

    pdf.section_title("YouTube Transcript Blocking on Cloud IPs", level=3)
    pdf.body_text(
        "Problem: YouTube blocks transcript requests from datacenter IP addresses. "
        "The youtube-transcript-api library fails with IP blocks on Render's servers."
    )
    pdf.body_text(
        "Solution: 3-layer fallback system - Cloudflare Worker proxy (uses CDN edge IPs), "
        "Invidious instances (public proxies), and yt-dlp (direct subtitle download). "
        "The system tries each strategy in order and falls through gracefully."
    )

    pdf.section_title("Service Cold Starts", level=3)
    pdf.body_text(
        "Problem: Render's free tier spins down after inactivity, causing 30-60 second cold starts "
        "when a user first visits the site."
    )
    pdf.body_text(
        "Mitigation: The frontend shows a loading indicator and gracefully handles delays. "
        "The SSE streaming approach also helps since the first progress event confirms the "
        "connection is alive."
    )

    pdf.section_title("Transcript Fallback Chain Failures", level=3)
    pdf.body_text(
        "Problem: Individual Invidious instances can go down or become unreliable over time."
    )
    pdf.body_text(
        "Solution: Dynamic instance discovery from api.invidious.io with filtering for working "
        "instances, plus 15-second timeout per instance and automatic failover to the next."
    )

    # ===================== 12. ENVIRONMENT VARIABLES =====================
    pdf.add_page()
    pdf.section_title("12. Environment Variables")
    pdf.table(
        ["Variable", "Required", "Description"],
        [
            ["NVIDIA_API_KEY", "Yes", "NVIDIA NIM API key for Llama 3.3 70B access"],
            ["YOUTUBE_PROXY_URL", "No", "Cloudflare Worker URL for transcript proxying"],
            ["INVIDIOUS_INSTANCES", "No", "Comma-separated custom Invidious instance URLs"],
            ["PORT", "Auto (Render)", "Server port (set by Render, default 8000)"],
        ],
        col_widths=[50, 25, 115],
    )

    # ===================== 13. FUTURE ROADMAP =====================
    pdf.section_title("13. Future Roadmap")
    pdf.section_title("Phase 4: Persistence & Auth", level=2)
    pdf.bullet_point("Add database storage (PostgreSQL) for quizzes and results")
    pdf.bullet_point("User authentication and quiz history")
    pdf.bullet_point("Persistent quiz sharing links")

    pdf.section_title("Phase 5: Enhanced Features", level=2)
    pdf.bullet_point("Support for more question types (fill-in-blank, matching, ordering)")
    pdf.bullet_point("Difficulty adaptive testing based on user performance")
    pdf.bullet_point("Topic-based quiz generation across multiple videos")
    pdf.bullet_point("Quiz export to Google Forms or Moodle format")

    pdf.section_title("Infrastructure Improvements", level=2)
    pdf.bullet_point("Upgrade to Render paid tier for longer timeouts and no cold starts")
    pdf.bullet_point("Add Redis for caching instead of in-memory storage")
    pdf.bullet_point("Rate limiting and abuse prevention")
    pdf.bullet_point("Comprehensive error monitoring (Sentry)")

    # Save
    output_path = os.path.join(os.path.dirname(os.path.abspath(__file__)), "project_documentation.pdf")
    pdf.output(output_path)
    print(f"PDF saved to: {output_path}")
    return output_path


if __name__ == "__main__":
    path = build_pdf()
    print(f"Done! Open: {path}")