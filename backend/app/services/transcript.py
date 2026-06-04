"""YouTube transcript extraction service."""

import re
from typing import Optional

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)

from backend.app.models.schemas import TranscriptResult


# Regex patterns for extracting video IDs from various YT URL formats
YOUTUBE_URL_PATTERNS = [
    r"(?:v=|/v/|youtu\.be/)([a-zA-Z0-9_-]{11})",  # Standard, short, old embed
    r"embed/([a-zA-Z0-9_-]{11})",                   # Embed URLs
    r"shorts/([a-zA-Z0-9_-]{11})",                  # Shorts
]


def extract_video_id(url: str) -> str:
    """Extract the 11-character video ID from a YouTube URL.

    Supports formats like:
      - https://www.youtube.com/watch?v=dQw4w9WgXcQ
      - https://youtu.be/dQw4w9WgXcQ
      - https://www.youtube.com/embed/dQw4w9WgXcQ
      - https://www.youtube.com/shorts/dQw4w9WgXcQ
      - https://www.youtube.com/v/dQw4w9WgXcQ
      - Just the video ID itself: dQw4w9WgXcQ

    Args:
        url: A YouTube video URL.

    Returns:
        The 11-character video ID string.

    Raises:
        ValueError: If no valid video ID can be extracted.
    """
    for pattern in YOUTUBE_URL_PATTERNS:
        match = re.search(pattern, url)
        if match:
            return match.group(1)

    # Maybe they just pasted the video ID directly
    if re.fullmatch(r"[a-zA-Z0-9_-]{11}", url.strip()):
        return url.strip()

    raise ValueError(f"Could not extract video ID from: {url}")


def list_available_languages(video_id: str) -> list[dict]:
    """List all available transcript languages for a YouTube video.

    Includes both directly available captions and translatable languages.
    Direct captions are higher quality than translations.

    Args:
        video_id: The 11-character YouTube video ID.

    Returns:
        A list of dicts with keys: language_code, language, is_generated, is_translatable.

    Raises:
        RuntimeError: If transcripts are disabled or video is unavailable.
    """
    api = YouTubeTranscriptApi()

    try:
        transcript_list = api.list(video_id)
    except TranscriptsDisabled:
        raise RuntimeError(
            f"Transcripts are disabled for video {video_id}. "
            "The video owner has not made captions available."
        )
    except VideoUnavailable:
        raise RuntimeError(
            f"Video {video_id} is unavailable. "
            "It may be private, age-restricted, or deleted."
        )

    languages = []
    for transcript in transcript_list:
        languages.append({
            "language_code": transcript.language_code,
            "language": transcript.language,
            "is_generated": transcript.is_generated,
            "is_translatable": transcript.is_translatable,
            "translation_languages": [
                tl.language_code for tl in transcript.translation_languages
            ] if transcript.is_translatable else [],
        })

    # Sort: manually-created first, then alphabetical by language code
    languages.sort(key=lambda x: (x["is_generated"], x["language_code"]))
    return languages


def get_transcript(
    video_id: str,
    languages: Optional[list[str]] = None,
    auto_detect: bool = True,
) -> TranscriptResult:
    """Fetch transcript for a YouTube video.

    Uses the youtube-transcript-api v1.x API (instance-based).
    Prefers manually created captions over auto-generated ones.
    Supports YouTube's built-in translation for languages that don't have
    direct captions but are available as translation targets.

    Args:
        video_id: The 11-character YouTube video ID.
        languages: Preferred language codes (e.g., ["en", "es", "hi"]).
                   If None and auto_detect=True, will try all available
                   languages in order of preference.
        auto_detect: If True and no languages specified, automatically
                    picks the best available language for the video.

    Returns:
        A TranscriptResult containing the full transcript text.

    Raises:
        RuntimeError: If transcripts are disabled, not found, or video unavailable.
    """
    api = YouTubeTranscriptApi()

    try:
        transcript_list = api.list(video_id)

        # If no specific language requested, auto-detect the best one
        if languages is None and auto_detect:
            languages = _build_language_preference(transcript_list)

        if languages is None:
            languages = ["en", "en-US", "en-GB"]

        try:
            # Prefer manually created captions (higher quality)
            transcript = transcript_list.find_manually_created_transcript(languages)
            is_auto = False
        except NoTranscriptFound:
            # Fall back to generated captions (auto-generated)
            transcript = transcript_list.find_generated_transcript(languages)
            is_auto = True

        fetched = transcript.fetch()
        # fetched.snippets is a list of FetchedTranscriptSnippet objects
        # Each has .text, .start, .duration
        text = " ".join(snippet.text for snippet in fetched.snippets)
        lang = fetched.language_code

        return TranscriptResult(
            video_id=video_id,
            text=text,
            language=lang,
            is_auto_generated=is_auto,
        )

    except NoTranscriptFound:
        # Direct captions not found in requested language.
        # Try translating from an available caption.
        target_lang = languages[0] if languages else "en"
        translated = _try_translate(transcript_list, target_lang, video_id)
        if translated:
            return translated

        # No direct captions and translation didn't work
        available = _format_available_languages(transcript_list)
        raise RuntimeError(
            f"No transcript found for video {video_id} in language: {target_lang}.\n"
            f"Available direct captions:\n{available}\n\n"
            "Tip: This video may have translation support (shown as 'translatable'). "
            "Translation works from a home internet connection but may be blocked "
            "from cloud/datacenter IPs. Try running from your local machine.\n\n"
            "Alternatively, use the English transcript (auto-detected by default) "
            "and the quiz will still be generated in English."
        )

    except TranscriptsDisabled:
        raise RuntimeError(
            f"Transcripts are disabled for video {video_id}. "
            "The video owner has not made captions available."
        )
    except VideoUnavailable:
        raise RuntimeError(
            f"Video {video_id} is unavailable. "
            "It may be private, age-restricted, or deleted."
        )


def _try_translate(transcript_list, target_lang: str, video_id: str) -> Optional[TranscriptResult]:
    """Try to get a transcript by translating from an available caption.

    YouTube supports translating captions to many languages. This uses
    that feature when direct captions aren't available in the target language.

    Args:
        transcript_list: The TranscriptList from the API.
        target_lang: The desired language code (e.g., "hi", "es").
        video_id: The video ID (for error messages).

    Returns:
        A TranscriptResult if translation succeeds, None if not possible.
    """
    # Find any translatable caption that supports our target language
    for transcript in transcript_list:
        if not transcript.is_translatable:
            continue

        # Check if this transcript can be translated to our target language
        translation_codes = [tl.language_code for tl in transcript.translation_languages]
        base_target = target_lang.split("-")[0]  # "es-419" -> "es"

        # Check exact match or base match
        can_translate = (
            target_lang in translation_codes
            or base_target in translation_codes
            or any(tc.startswith(base_target) for tc in translation_codes)
        )

        if can_translate:
            try:
                translated = transcript.translate(target_lang)
                fetched = translated.fetch()
                text = " ".join(snippet.text for snippet in fetched.snippets)
                return TranscriptResult(
                    video_id=video_id,
                    text=text,
                    language=target_lang,
                    is_auto_generated=True,  # Translated captions are auto-generated
                )
            except Exception as e:
                # YouTube may block translation requests from cloud IPs.
                # Log and continue — the caller will show a helpful message.
                import logging
                logging.warning(
                    f"Could not translate transcript to {target_lang}: {e}. "
                    "YouTube may be blocking translation requests from this IP."
                )
                # Don't try other transcripts if translation is blocked —
                # they'll all fail with the same IP block
                if "IpBlocked" in type(e).__name__ or "blocked" in str(e).lower():
                    return None
                continue

    return None


def _build_language_preference(transcript_list) -> list[str]:
    """Build a language preference list from available transcripts.

    Prioritizes: manual English > auto English > manual anything > auto anything.
    """
    languages = []

    # First pass: English variants
    for transcript in transcript_list:
        if not transcript.is_generated and transcript.language_code.startswith("en"):
            languages.append(transcript.language_code)

    for transcript in transcript_list:
        if transcript.is_generated and transcript.language_code.startswith("en"):
            languages.append(transcript.language_code)

    # Second pass: all other manually-created transcripts
    for transcript in transcript_list:
        if not transcript.is_generated and not transcript.language_code.startswith("en"):
            languages.append(transcript.language_code)

    # Third pass: all other auto-generated transcripts
    for transcript in transcript_list:
        if transcript.is_generated and not transcript.language_code.startswith("en"):
            languages.append(transcript.language_code)

    return languages if languages else None


def _format_available_languages(transcript_list) -> str:
    """Format available languages as a readable string for error messages."""
    lines = []
    for transcript in transcript_list:
        kind = "auto" if transcript.is_generated else "manual"
        translatable = " (translatable)" if transcript.is_translatable else ""
        lines.append(f"  - {transcript.language_code} ({transcript.language}) [{kind}]{translatable}")
    return "\n".join(lines)