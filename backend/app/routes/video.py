"""Video information API routes."""

import asyncio

from fastapi import APIRouter, HTTPException

from backend.app.models.schemas import (
    LanguagesResponse,
    LanguageInfo,
    ErrorResponse,
)
from backend.app.services.transcript import extract_video_id, list_available_languages

router = APIRouter(prefix="/api/video", tags=["video"])


@router.get(
    "/{video_id}/languages",
    response_model=LanguagesResponse,
    responses={404: {"model": ErrorResponse}},
    summary="List available caption languages for a video",
    description="Returns all available caption languages (manual and auto-generated) for a YouTube video.",
)
async def get_languages(video_id: str):
    """List available caption languages for a YouTube video.

    This is useful for:
    - Showing users which languages are available before generating a quiz
    - Determining if a video has captions before attempting to fetch them
    """
    try:
        languages = await asyncio.to_thread(list_available_languages, video_id)
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=str(e))

    return LanguagesResponse(
        video_id=video_id,
        languages=[
            LanguageInfo(
                language_code=lang["language_code"],
                language=lang["language"],
                is_generated=lang["is_generated"],
                is_translatable=lang.get("is_translatable", False),
                translation_languages=lang.get("translation_languages", []),
            )
            for lang in languages
        ],
    )