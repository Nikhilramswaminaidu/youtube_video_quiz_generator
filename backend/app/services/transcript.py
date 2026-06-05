"""YouTube transcript extraction service."""

import json
import logging
import re
import subprocess
from typing import Optional

from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)

from backend.app.models.schemas import TranscriptResult

logger = logging.getLogger(__name__)


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

    Uses the youtube-transcript-api v1.x API (instance-based) first,
    then falls back to yt-dlp if blocked by cloud/datacenter IP restrictions.

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
    target_lang = (languages or ["en"])[0].split("-")[0]

    # Strategy: try youtube-transcript-api first, fall back to yt-dlp on ANY failure.
    # Cloud IPs (AWS, GCP, Azure, Render) get blocked by YouTube, so the API
    # call can fail in many ways — always attempt yt-dlp as a fallback.
    try:
        result = _fetch_via_transcript_api(video_id, languages, auto_detect)
        if result:
            return result
    except (TranscriptsDisabled, VideoUnavailable) as e:
        # These are video-level problems (no captions, private video) —
        # yt-dlp won't help either, so raise immediately.
        raise RuntimeError(str(e))
    except Exception as e:
        # IP blocks, rate limits, unexpected errors — try yt-dlp
        logger.warning(
            f"youtube-transcript-api failed for {video_id}: {type(e).__name__}: {e}. "
            "Falling back to yt-dlp."
        )

    # yt-dlp fallback (works from cloud IPs because it downloads subtitle files directly)
    logger.info(f"Trying yt-dlp fallback for {video_id}")
    ytdlp_result = _fetch_transcript_ytdlp(video_id, target_lang)
    if ytdlp_result:
        return ytdlp_result

    # Both methods failed
    raise RuntimeError(
        f"Could not retrieve transcript for video {video_id}. "
        "YouTube may be blocking requests from this server's IP address. "
        "Try again later or use a video with manually uploaded captions."
    )


def _fetch_via_transcript_api(
    video_id: str,
    languages: Optional[list[str]] = None,
    auto_detect: bool = True,
) -> Optional[TranscriptResult]:
    """Try fetching transcript using youtube-transcript-api.

    Returns a TranscriptResult on success, or raises on failure.
    Caller should catch exceptions and fall back to yt-dlp.
    """
    api = YouTubeTranscriptApi()

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
    text = " ".join(snippet.text for snippet in fetched.snippets)
    lang = fetched.language_code

    return TranscriptResult(
        video_id=video_id,
        text=text,
        language=lang,
        is_auto_generated=is_auto,
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


def _fetch_transcript_ytdlp(video_id: str, language: str = "en") -> Optional[TranscriptResult]:
    """Fallback: fetch transcript using yt-dlp when youtube-transcript-api fails.

    yt-dlp downloads subtitles directly from YouTube and works from cloud IPs
    where the youtube-transcript-api Python library gets blocked.

    Args:
        video_id: The 11-character YouTube video ID.
        language: Preferred language code (e.g., "en", "es"). Defaults to "en".

    Returns:
        A TranscriptResult if subtitles are found, None if not available.
    """
    url = f"https://www.youtube.com/watch?v={video_id}"

    # Build yt-dlp command: dump subtitle info as JSON, prefer manual subs
    # --write-subs --write-auto-subs ensures both manual and auto captions are considered
    # --skip-download avoids downloading the video itself
    # -j dumps video info JSON including available subtitles
    # --no-check-certificates and User-Agent help bypass cloud IP restrictions
    cmd = [
        "yt-dlp",
        "--skip-download",
        "--write-subs",
        "--write-auto-subs",
        "--sub-langs", f"{language},{language[:2]},en,en-US,en-GB",
        "--no-check-certificates",
        "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
        "--output", "-",  # output to stdout
        "--print", "requested_subtitles",  # print subtitle URLs
        "-j",  # dump full video info as JSON
        url,
    ]

    try:
        result = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=60,
        )

        if result.returncode != 0:
            logger.warning(f"yt-dlp returned non-zero exit code: {result.stderr[:500]}")
            # Try alternative approach: download subtitle file directly
            return _fetch_transcript_ytdlp_direct(video_id, language)

        # Parse JSON output from yt-dlp
        # -j outputs one JSON object per line (playlist entries), take last one
        lines = result.stdout.strip().splitlines()
        video_info = None
        for line in reversed(lines):
            try:
                parsed = json.loads(line)
                if "requested_subtitles" in parsed or "subtitles" in parsed:
                    video_info = parsed
                    break
            except json.JSONDecodeError:
                continue

        if not video_info:
            logger.warning("yt-dlp: could not parse video info JSON")
            return _fetch_transcript_ytdlp_direct(video_id, language)

        # Try to find subtitle URL in requested_subtitles, then subtitles, then automatic_captions
        subtitle_url = None
        sub_lang = language

        # requested_subtitles has the resolved subtitle info
        requested = video_info.get("requested_subtitles") or {}
        for lang_key in [language, language.split("-")[0], "en", "en-US"]:
            if lang_key in requested:
                sub_info = requested[lang_key]
                if isinstance(sub_info, dict):
                    subtitle_url = sub_info.get("url") or sub_info.get("path")
                else:
                    subtitle_url = str(sub_info)
                sub_lang = lang_key
                break

        if not subtitle_url:
            # Fall back to automatic_captions
            auto_caps = video_info.get("automatic_captions") or {}
            for lang_key in [language, language.split("-")[0], "en"]:
                if lang_key in auto_caps:
                    subs = auto_caps[lang_key]
                    # Prefer srv1 (YouTube's native format), then vtt, then any
                    for fmt_key in ["srv1", "srv2", "srv3", "vtt", "ttml"]:
                        for sub in subs:
                            if sub.get("ext") == fmt_key or fmt_key in (sub.get("url") or ""):
                                subtitle_url = sub.get("url")
                                sub_lang = lang_key
                                break
                        if subtitle_url:
                            break
                    if not subtitle_url and subs:
                        subtitle_url = subs[0].get("url")
                        sub_lang = lang_key
                    break

        if not subtitle_url:
            logger.warning(f"yt-dlp: no subtitle URL found for language '{language}'")
            return _fetch_transcript_ytdlp_direct(video_id, language)

        # Download the subtitle content
        import requests
        sub_response = requests.get(subtitle_url, timeout=30)
        sub_response.raise_for_status()
        sub_content = sub_response.text

        # Parse subtitle content (YouTube srv1 format is XML, vtt is text)
        text = _parse_subtitle_content(sub_content)

        if not text or len(text.strip()) < 20:
            logger.warning(f"yt-dlp: parsed subtitle text too short ({len(text)} chars)")
            return _fetch_transcript_ytdlp_direct(video_id, language)

        return TranscriptResult(
            video_id=video_id,
            text=text,
            language=sub_lang,
            is_auto_generated=True,
        )

    except subprocess.TimeoutExpired:
        logger.warning("yt-dlp: timed out after 60s")
        return _fetch_transcript_ytdlp_direct(video_id, language)
    except Exception as e:
        logger.warning(f"yt-dlp fallback failed: {e}")
        return _fetch_transcript_ytdlp_direct(video_id, language)


def _fetch_transcript_ytdlp_direct(video_id: str, language: str = "en") -> Optional[TranscriptResult]:
    """Download subtitle file directly via yt-dlp and parse it.

    Used as a second fallback when the JSON info dump approach doesn't work.
    Downloads the subtitle file to a temp location, reads it, and cleans up.
    """
    import tempfile
    import os

    url = f"https://www.youtube.com/watch?v={video_id}"
    base_lang = language.split("-")[0]

    with tempfile.TemporaryDirectory() as tmpdir:
        # Try manual subs first, then auto subs
        for auto_flag in [["--write-subs", "--no-write-auto-subs"], ["--write-auto-subs", "--no-write-subs"]]:
            cmd = [
                "yt-dlp",
                "--skip-download",
                *auto_flag,
                "--sub-langs", f"{base_lang},en",
                "--convert-subs", "srt",  # Convert to SRT for easy parsing
                "--no-check-certificates",
                "--user-agent", "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125.0.0.0 Safari/537.36",
                "-o", os.path.join(tmpdir, "sub"),
                url,
            ]

            try:
                result = subprocess.run(
                    cmd,
                    capture_output=True,
                    text=True,
                    timeout=60,
                )

                # Find any subtitle files written
                sub_files = [
                    f for f in os.listdir(tmpdir)
                    if f.startswith("sub") and (f.endswith(".srt") or f.endswith(".vtt"))
                ]

                if sub_files:
                    sub_path = os.path.join(tmpdir, sub_files[0])
                    with open(sub_path, encoding="utf-8", errors="replace") as f:
                        sub_content = f.read()

                    text = _parse_subtitle_content(sub_content)
                    if text and len(text.strip()) >= 20:
                        # Determine language from filename
                        fname = sub_files[0]
                        sub_lang = language
                        if "." in fname and fname.rstrip(".srt").rstrip(".vtt").split(".")[-1] not in ("sub",):
                            sub_lang = fname.rstrip(".srt").rstrip(".vtt").split(".")[-1]

                        return TranscriptResult(
                            video_id=video_id,
                            text=text,
                            language=sub_lang,
                            is_auto_generated="--write-auto-subs" in auto_flag,
                        )
            except subprocess.TimeoutExpired:
                logger.warning("yt-dlp direct: timed out")
                continue
            except Exception as e:
                logger.warning(f"yt-dlp direct fallback error: {e}")
                continue

    return None


def _parse_subtitle_content(content: str) -> str:
    """Parse subtitle content from SRT, VTT, or XML (srv1) formats.

    Extracts plain text from subtitle files, stripping timestamps and formatting.
    """
    text_parts = []

    if "<transcript>" in content or "<?xml" in content:
        # YouTube srv1/srv3 XML format
        import re as _re
        # Remove XML tags, keep text content
        text = _re.sub(r"<[^>]+>", " ", content)
        # Clean up whitespace
        text = _re.sub(r"\s+", " ", text).strip()
        return text

    # SRT or VTT format — extract text lines, skip timestamps and numbers
    for line in content.splitlines():
        line = line.strip()
        # Skip timestamp lines (e.g., "00:01:23,456 --> 00:01:25,789")
        if "-->" in line:
            continue
        # Skip sequence numbers (standalone digits on a line)
        if line.isdigit():
            continue
        # Skip WEBVTT header and other metadata
        if line.startswith(("WEBVTT", "Kind:", "Language:", "NOTE")):
            continue
        # Skip empty lines
        if not line:
            continue
        # Strip HTML tags that may be in the subtitles
        import re as _re
        clean = _re.sub(r"<[^>]+>", "", line)
        # Strip VTT positioning tags like <c> or alignment info
        clean = clean.strip()
        if clean:
            text_parts.append(clean)

    return " ".join(text_parts)


def _is_ip_blocked_error(error: Exception) -> bool:
    """Check if an error is likely caused by YouTube blocking cloud/datacenter IPs."""
    err_type = type(error).__name__
    err_msg = str(error).lower()
    # Specific error patterns from youtube-transcript-api on cloud IPs
    return (
        "ipblocked" in err_type.lower()
        or "ipblockedexception" in err_type.lower()
        or "blocked" in err_msg and "transcript" in err_msg
        or "access denied" in err_msg
        or "not allowed" in err_msg
        or "request was rejected" in err_msg
    )


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