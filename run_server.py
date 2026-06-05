#!/usr/bin/env python3
"""Run the YouTube Quiz Generator API server.

Usage:
    python run_server.py

    Options:
        --host HOST       Host to bind to (default: 127.0.0.1)
        --port PORT       Port to bind to (default: 8000)
        --reload          Enable auto-reload for development
"""

import argparse
import os
import sys
import io
import uvicorn

# Fix Windows console encoding
if sys.platform == "win32":
    sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8", errors="replace")
    sys.stderr = io.TextIOWrapper(sys.stderr.buffer, encoding="utf-8", errors="replace")


def main():
    parser = argparse.ArgumentParser(description="YouTube Quiz Generator API Server")
    parser.add_argument("--host", default="0.0.0.0", help="Host to bind to (default: 0.0.0.0)")
    parser.add_argument("--port", type=int, default=int(os.environ.get("PORT", 8000)), help="Port to bind to (default: PORT env var or 8000)")
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload for development")
    args = parser.parse_args()

    print(f"Starting server at http://{args.host}:{args.port}")
    print(f"   API docs: http://{args.host}:{args.port}/docs")
    print()

    uvicorn.run(
        "backend.app.main:app",
        host=args.host,
        port=args.port,
        reload=args.reload,
    )


if __name__ == "__main__":
    main()