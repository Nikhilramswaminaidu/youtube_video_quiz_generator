"""FastAPI application for the YouTube Quiz Generator."""

import logging
import os
import subprocess
from contextlib import asynccontextmanager
from pathlib import Path

# Configure logging so INFO/WARNING messages appear on Render (default level is WARNING)
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)s [%(name)s] %(message)s",
    datefmt="%H:%M:%S",
)

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse, HTMLResponse

from backend.app.routes.quiz import router as quiz_router
from backend.app.routes.video import router as video_router

logger = logging.getLogger(__name__)

# Path to the frontend directory
FRONTEND_DIR = Path(__file__).parent.parent.parent / "frontend"


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan — startup and shutdown events."""
    print("YouTube Quiz Generator API starting up...")
    print("   Powered by NVIDIA NIM (free LLM API)")
    print(f"   App:      http://localhost:8000")
    print(f"   API docs: http://localhost:8000/docs")
    yield
    print("Shutting down...")


app = FastAPI(
    title="YouTube Quiz Generator",
    description=(
        "Generate UPSC-style multiple-choice quizzes from YouTube videos. "
        "Supports videos in any language - quizzes are always generated in English.\n\n"
        "Powered by NVIDIA NIM (free LLM API) and youtube-transcript-api."
    ),
    version="1.0.0",
    lifespan=lifespan,
)

# CORS — allow all origins for development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Register API routes FIRST (before catch-all frontend route)
app.include_router(quiz_router)
app.include_router(video_router)


# Health check endpoint for debugging on cloud deployments
@app.get("/api/health", tags=["system"])
async def health_check():
    """Health check — shows yt-dlp availability, library versions, and commit hash.

    Useful for debugging transcript issues on cloud deployments (Render, etc.).
    """
    health = {"status": "ok"}

    # Check yt-dlp availability
    try:
        result = subprocess.run(
            ["yt-dlp", "--version"],
            capture_output=True, text=True, timeout=10,
        )
        health["yt_dlp"] = {
            "available": True,
            "version": result.stdout.strip() or result.stderr.strip(),
        }
    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        health["yt_dlp"] = {"available": False, "error": str(e)}

    # Check youtube-transcript-api version
    try:
        import youtube_transcript_api
        health["youtube_transcript_api_version"] = getattr(
            youtube_transcript_api, "__version__", "unknown"
        )
    except ImportError:
        health["youtube_transcript_api_version"] = "not installed"

    # Git commit (if available)
    try:
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            capture_output=True, text=True, timeout=5,
        )
        health["git_commit"] = result.stdout.strip() or "unknown"
    except Exception:
        health["git_commit"] = "unknown"

    return JSONResponse(health)


# Serve the frontend HTML
@app.get("/", tags=["frontend"], include_in_schema=False)
async def serve_frontend():
    """Serve the quiz-taking frontend."""
    index_path = FRONTEND_DIR / "index.html"
    if index_path.exists():
        return FileResponse(index_path)
    return HTMLResponse(
        "<h1>YouTube Quiz Generator</h1>"
        "<p>Frontend not found. Use the API at <a href='/docs'>/docs</a></p>"
    )