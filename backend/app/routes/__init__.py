"""API route handlers."""

from backend.app.routes.quiz import router as quiz_router
from backend.app.routes.video import router as video_router

__all__ = ["quiz_router", "video_router"]