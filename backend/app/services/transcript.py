"""YouTube transcript extraction service.

Uses a multi-strategy approach to fetch transcripts:
1. youtube-transcript-api (works locally, often blocked on cloud IPs)
2. Cloudflare Worker proxy (if configured, routes through CDN edge IPs)
3. Invidious instances (public YouTube proxies, bypass cloud IP blocking)
4. yt-dlp fallback (works from some IPs)
"""

import json
import logging
import os
import re
import subprocess
from typing import Optional

import httpx
from youtube_transcript_api import YouTubeTranscriptApi
from youtube_transcript_api._errors import (
    CouldNotRetrieveTranscript,
    TranscriptsDisabled,
    NoTranscriptFound,
    VideoUnavailable,
)

from backend.app.models.schemas import TranscriptResult

logger = logging.getLogger(__name__)

# Invidious instances are public YouTube proxies, but most have disabled their API.
# We try them as a fallback, but the primary cloud-deployment solution is the
# Cloudflare Worker proxy (YOUTUBE_PROXY_URL env var).
# Override via INVIDIOUS_INSTANCES env var (comma-separated URLs).
_DEFAULT_INVIDIOUS_INSTANCES = [
    "https://inv.thepixora.com",
    "https://inv.nadeko.net",
    "https://invidious.nerdvpn.de",
    "https://iv.ggtyler.dev",
]

INVIDIOUS_INSTANCES = [
    url.strip().rstrip("/")
    for url in os.environ.get("INVIDIOUS_INSTANCES", "").split(",")
    if url.strip()
] or _DEFAULT_INVIDIOUS_INSTANCES

# Cache for dynamically discovered Invidious instances (refreshed periodically)
_discovered_instances: list[str] = []
_discovery_timestamp: float = 0


def _get_invidious_instances() -> list[str]:
    """Get Invidious instances, including dynamically discovered ones.

    Merges hardcoded defaults with instances discovered from the public registry.
    Discovery results are cached for 1 hour to avoid repeated lookups.
    """
    global _discovered_instances, _discovery_timestamp

    # Use cache if fresh (< 1 hour old)
    import time
    now = time.time()
    if _discovered_instances and (now - _discovery_timestamp) < 3600:
        return INVIDIOUS_INSTANCES + [i for i in _discovered_instances if i not in INVIDIOUS_INSTANCES]

    # Try to discover instances from the public registry
    try:
        import time as _time
        with httpx.Client(timeout=10, follow_redirects=True) as client:
            response = client.get("https://api.invidious.io/instances.json")
            if response.status_code == 200:
                instances_data = response.json()
                discovered = []
                for instance in instances_data:
                    # Each entry is [url, stats]
                    if not isinstance(instance, list) or len(instance) < 2:
                        continue
                    url = instance[0]
                    stats = instance[1] if isinstance(instance[1], dict) else {}

                    # Only include instances with API enabled and not flagged down
                    if not stats.get("api"):
                        continue
                    if stats.get("monitor", {}).get("down", True):
                        continue

                    clean_url = url.rstrip("/")
                    if clean_url not in INVIDIOUS_INSTANCES and clean_url not in discovered:
                        discovered.append(clean_url)

                if discovered:
                    _discovered_instances = discovered
                    _discovery_timestamp = now
                    logger.info(f"Discovered {len(discovered)} Invidious instances from registry")
    except Exception as e:
        logger.debug(f"Invidious instance discovery failed: {e}")

    return INVIDIOUS_INSTANCES + [i for i in _discovered_instances if i not in INVIDIOUS_INSTANCES]


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

    Uses youtube-transcript-api first, then falls back to Invidious instances
    and the Cloudflare Worker proxy when the primary API is blocked (common on
    cloud/datacenter IPs like Render).

    Includes both directly available captions and translatable languages.
    Direct captions are higher quality than translations.

    Args:
        video_id: The 11-character YouTube video ID.

    Returns:
        A list of dicts with keys: language_code, language, is_generated, is_translatable.

    Raises:
        RuntimeError: If transcripts are disabled, video is unavailable, or all methods fail.
    """
    # Strategy 1: youtube-transcript-api (works locally, blocked on cloud IPs)
    api = YouTubeTranscriptApi()
    api_error = None

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
    except CouldNotRetrieveTranscript as e:
        # IP blocks, rate limits, etc. — try fallbacks
        api_error = e
        logger.warning(
            f"youtube-transcript-api list failed for {video_id}: {type(e).__name__}: {e}. "
            "Trying fallbacks."
        )
        transcript_list = None

    if transcript_list is not None:
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
        languages.sort(key=lambda x: (x["is_generated"], x["language_code"]))
        return languages

    # Strategy 2: Cloudflare Worker proxy (if configured)
    worker_url = os.environ.get("YOUTUBE_PROXY_URL")
    if worker_url:
        logger.info(f"Trying Worker proxy for language list: {video_id}")
        worker_langs = _list_languages_via_worker(video_id, worker_url)
        if worker_langs is not None:
            return worker_langs

    # Strategy 3: Invidious instances
    logger.info(f"Trying Invidious for language list: {video_id}")
    invidious_langs = _list_languages_via_invidious(video_id)
    if invidious_langs is not None:
        return invidious_langs

    # All methods failed
    api_error_msg = f" youtube-transcript-api: {type(api_error).__name__}" if api_error else ""
    raise RuntimeError(
        f"Could not list languages for video {video_id}. "
        f"All methods failed.{api_error_msg} "
        "YouTube may be blocking requests from this server's IP address."
    )


def _list_languages_via_worker(video_id: str, proxy_url: str) -> Optional[list[dict]]:
    """List available caption languages via the Cloudflare Worker proxy.

    The worker proxies YouTube's timedtext API, which returns caption tracks
    in srv1 XML format. We parse the track list from the response.
    Returns None if the worker can't provide language info.
    """
    import xml.etree.ElementTree as ET

    # Try requesting transcript without a specific language to get all tracks
    params = {"v": video_id, "fmt": "srv1"}
    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            response = client.get(proxy_url, params=params)
            if response.status_code != 200:
                logger.debug(f"Worker proxy language list: returned {response.status_code}")
                return None

            # Parse the XML to find all available tracks
            try:
                root = ET.fromstring(response.text)
                # srv1 format: <transcript_list><track id="..." name="..." lang_code="en" .../>
                tracks = root.findall(".//track") if root.tag == "transcript_list" else []
                if not tracks:
                    # If we got a single transcript (not a list), we know at least
                    # one language exists but can't enumerate all. Return None to
                    # let other fallbacks try, or return a minimal entry.
                    logger.debug("Worker proxy: got single transcript, can't enumerate all languages")
                    return None

                languages = []
                for track in tracks:
                    lang_code = track.get("lang_code", "")
                    lang_name = track.get("name", track.get("lang_translated", lang_code))
                    kind = track.get("kind", "")
                    is_auto = kind == "asr"
                    languages.append({
                        "language_code": lang_code,
                        "language": lang_name,
                        "is_generated": is_auto,
                        "is_translatable": False,  # Can't determine from timedtext
                        "translation_languages": [],
                    })

                if languages:
                    logger.info(f"Worker proxy: found {len(languages)} languages for {video_id}")
                    languages.sort(key=lambda x: (x["is_generated"], x["language_code"]))
                    return languages
            except ET.ParseError:
                logger.debug("Worker proxy: response not valid XML for language listing")
                return None

    except Exception as e:
        logger.debug(f"Worker proxy language list failed: {type(e).__name__}: {e}")
        return None

    return None


def _list_languages_via_invidious(video_id: str) -> Optional[list[dict]]:
    """List available caption languages via Invidious instances.

    Returns None if all instances fail. Returns a list of language dicts
    similar to the youtube-transcript-api format.
    """
    instances = _get_invidious_instances()

    for instance in instances:
        try:
            captions_url = f"{instance}/api/v1/captions/{video_id}"
            with httpx.Client(timeout=15, follow_redirects=True) as client:
                response = client.get(captions_url)
                if response.status_code != 200:
                    logger.debug(f"Invidious {instance}: language list returned {response.status_code}")
                    continue

                data = response.json()
                captions = data.get("captions", [])
                if not captions:
                    logger.debug(f"Invidious {instance}: no captions in list response")
                    continue

                languages = []
                for cap in captions:
                    lang_code = cap.get("languageCode", cap.get("language_code", ""))
                    lang_name = cap.get("label", cap.get("name", lang_code))
                    is_auto = _is_auto_caption(cap)
                    languages.append({
                        "language_code": lang_code,
                        "language": lang_name,
                        "is_generated": is_auto,
                        "is_translatable": False,
                        "translation_languages": [],
                    })

                if languages:
                    logger.info(f"Invidious {instance}: found {len(languages)} languages for {video_id}")
                    languages.sort(key=lambda x: (x["is_generated"], x["language_code"]))
                    return languages

        except httpx.TimeoutException:
            logger.debug(f"Invidious {instance}: timed out during language listing")
            continue
        except Exception as e:
            logger.debug(f"Invidious {instance}: language list failed: {type(e).__name__}: {e}")
            continue

    logger.warning(f"All Invidious instances failed for language listing: {video_id}")
    return None


def get_transcript(
    video_id: str,
    languages: Optional[list[str]] = None,
    auto_detect: bool = True,
) -> TranscriptResult:
    """Fetch transcript for a YouTube video.

    Uses a multi-strategy fallback approach:
    1. youtube-transcript-api (works locally, often blocked on cloud IPs)
    2. Cloudflare Worker proxy (if YOUTUBE_PROXY_URL is set)
    3. Invidious instances (public YouTube proxies, bypass IP blocking)
    4. yt-dlp fallback (works from some IPs)

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

    # Only TranscriptsDisabled is truly terminal (video owner disabled captions).
    # Everything else gets fallback attempts.
    api_error = None
    try:
        result = _fetch_via_transcript_api(video_id, languages, auto_detect)
        if result:
            return result
    except TranscriptsDisabled as e:
        # Video owner disabled captions — no method can retrieve them.
        raise RuntimeError(str(e))
    except Exception as e:
        api_error = e
        logger.warning(
            f"youtube-transcript-api failed for {video_id}: {type(e).__name__}: {e}. "
            "Trying fallbacks."
        )

    # Cloudflare Worker proxy (if configured)
    worker_url = os.environ.get("YOUTUBE_PROXY_URL")
    if worker_url:
        logger.info(f"Trying Cloudflare Worker proxy for {video_id}")
        worker_result = _fetch_via_worker_proxy(video_id, target_lang, worker_url)
        if worker_result:
            return worker_result

    # Invidious instances (public YouTube proxies — bypass cloud IP blocking for free)
    logger.info(f"Trying Invidious fallback for {video_id}")
    invidious_result = _fetch_via_invidious(video_id, target_lang)
    if invidious_result:
        return invidious_result

    # yt-dlp fallback (works from some IPs)
    logger.info(f"Trying yt-dlp fallback for {video_id}")
    ytdlp_result = _fetch_transcript_ytdlp(video_id, target_lang)
    if ytdlp_result:
        return ytdlp_result

    # All methods failed — give a clear error message
    api_error_msg = f" youtube-transcript-api: {type(api_error).__name__}" if api_error else ""
    logger.error(f"All transcript methods failed for {video_id}.{api_error_msg}")
    raise RuntimeError(
        f"Could not retrieve transcript for video {video_id}. "
        f"All methods failed (youtube-transcript-api, Invidious, yt-dlp).{api_error_msg} "
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


def _fetch_via_invidious(
    video_id: str,
    language: str = "en",
) -> Optional[TranscriptResult]:
    """Fetch transcript via Invidious instances (public YouTube proxies).

    Invidious instances proxy YouTube content and serve captions from their own
    servers, bypassing YouTube's IP blocking of cloud/datacenter IPs.
    Note: Many public instances have disabled their API, so this fallback is
    unreliable. For cloud deployments, use the Cloudflare Worker proxy instead.

    Tries multiple instances (including dynamically discovered ones); returns on
    first success.
    """
    base_lang = language.split("-")[0]
    instances = _get_invidious_instances()

    for instance in instances:
        try:
            # Use the direct lang param to get caption content in one request
            # (avoids a separate list-then-fetch round-trip that often times out)
            captions_url = f"{instance}/api/v1/captions/{video_id}?lang={base_lang}"
            with httpx.Client(timeout=15, follow_redirects=True) as client:
                response = client.get(captions_url)
                if response.status_code != 200:
                    logger.debug(
                        f"Invidious {instance}: returned {response.status_code}"
                    )
                    continue

                content_type = response.headers.get("content-type", "")

                # Check if we got JSON (caption list) or caption content (VTT/XML)
                if "json" in content_type:
                    # Got a caption list — find the best track and fetch its content
                    data = response.json()
                    captions = data.get("captions", [])
                    if not captions:
                        logger.debug(f"Invidious {instance}: no captions in list")
                        continue

                    best = _pick_best_invidious_caption(captions, base_lang)
                    if not best:
                        continue

                    cap_url = best.get("url", best.get("url_vtt", ""))
                    if not cap_url:
                        label = best.get("label", best.get("name", ""))
                        cap_url = f"/api/v1/captions/{video_id}?label={label}&lang={best.get('languageCode', base_lang)}"
                    if not cap_url.startswith("http"):
                        cap_url = f"{instance}{cap_url}"

                    cap_response = client.get(cap_url, timeout=20)
                    if cap_response.status_code != 200:
                        logger.debug(
                            f"Invidious {instance}: caption content returned {cap_response.status_code}"
                        )
                        continue

                    text = _parse_subtitle_content(cap_response.text)
                    if text and len(text.strip()) >= 20:
                        logger.info(f"Invidious {instance}: fetched transcript for {video_id}")
                        return TranscriptResult(
                            video_id=video_id,
                            text=text,
                            language=best.get("languageCode", language),
                            is_auto_generated=_is_auto_caption(best),
                        )

                else:
                    # Got caption content directly (VTT, XML, or plain text)
                    text = _parse_subtitle_content(response.text)
                    if text and len(text.strip()) >= 20:
                        logger.info(f"Invidious {instance}: fetched transcript for {video_id}")
                        return TranscriptResult(
                            video_id=video_id,
                            text=text,
                            language=base_lang,
                            is_auto_generated=True,
                        )

                logger.debug(f"Invidious {instance}: content empty or too short, trying next")

        except httpx.TimeoutException:
            logger.debug(f"Invidious {instance}: timed out")
            continue
        except Exception as e:
            logger.debug(f"Invidious {instance}: {type(e).__name__}: {e}")
            continue

    logger.warning(f"All Invidious instances failed for {video_id}")
    return None


def _pick_best_invidious_caption(captions: list[dict], target_lang: str) -> Optional[dict]:
    """Select the best Invidious caption track for the target language.

    Preference order:
    1. Manual (non-auto) captions in the target language
    2. Auto-generated captions in the target language
    3. Manual English captions
    4. Auto-generated English captions
    5. First available caption track
    """
    lang_matches_manual = []
    lang_matches_auto = []
    en_manual = []
    en_auto = []

    for cap in captions:
        code = cap.get("languageCode", "")
        label = (cap.get("label") or cap.get("name", "")).lower()
        is_auto = "auto" in label or "generated" in label or cap.get("kind") == "asr"

        if code.startswith(target_lang):
            (lang_matches_auto if is_auto else lang_matches_manual).append(cap)
        elif code.startswith("en"):
            (en_auto if is_auto else en_manual).append(cap)

    # Return best match in priority order
    for pool in [lang_matches_manual, lang_matches_auto, en_manual, en_auto]:
        if pool:
            return pool[0]

    # Last resort: any available caption
    return captions[0] if captions else None


def _is_auto_caption(caption: dict) -> bool:
    """Check if an Invidious caption track is auto-generated."""
    label = (caption.get("label") or caption.get("name", "")).lower()
    return "auto" in label or "generated" in label or caption.get("kind") == "asr"


def _fetch_via_worker_proxy(
    video_id: str,
    language: str,
    proxy_url: str,
) -> Optional[TranscriptResult]:
    """Fetch transcript via a Cloudflare Worker proxy.

    A Cloudflare Worker deployed on Cloudflare's edge network can fetch YouTube
    captions without being IP-blocked, since Cloudflare's edge IPs are CDN nodes
    rather than traditional datacenter IPs. Free tier: 100,000 requests/day.

    Set the YOUTUBE_PROXY_URL env var to your Worker's URL to enable this.
    The Worker should accept ?v=VIDEO_ID&lang=LANG&fmt=srv1 and proxy
    YouTube's timedtext API.

    See cloudflare-worker.js for the Worker script.
    """
    params = {
        "v": video_id,
        "lang": language,
        "fmt": "srv1",
    }

    try:
        with httpx.Client(timeout=30, follow_redirects=True) as client:
            response = client.get(proxy_url, params=params)
            if response.status_code != 200:
                logger.warning(
                    f"Worker proxy returned {response.status_code} for {video_id}"
                )
                return None

            text = _parse_subtitle_content(response.text)
            if text and len(text.strip()) >= 20:
                logger.info(f"Worker proxy: successfully fetched transcript for {video_id}")
                return TranscriptResult(
                    video_id=video_id,
                    text=text,
                    language=language,
                    is_auto_generated=True,  # Can't determine from timedtext API
                )

            logger.warning(f"Worker proxy: parsed text too short for {video_id}")
            return None

    except Exception as e:
        logger.warning(f"Worker proxy failed for {video_id}: {type(e).__name__}: {e}")
        return None


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
            stderr_preview = result.stderr[:500] if result.stderr else "(no stderr)"
            logger.warning(f"yt-dlp returned non-zero exit code {result.returncode}: {stderr_preview}")
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
    logger.info(f"yt-dlp direct fallback: downloading subtitle file for {video_id}")

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