"""Quiz generation service using NVIDIA NIM API — sequential batches with dedup."""

import asyncio
import difflib
import json
import logging
import os
import re as regex
import time
from typing import Optional

import requests
from dotenv import load_dotenv

from backend.app.models.schemas import Quiz, QuizQuestion

# Load environment variables from .env file
load_dotenv()

logger = logging.getLogger(__name__)

# ─── NVIDIA NIM Configuration ───────────────────────────────────────────────

NIM_BASE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
DEFAULT_MODEL = "meta/llama-3.3-70b-instruct"
FALLBACK_MODEL = "nvidia/llama-3.3-nemotron-super-49b-v1.5"

# Rate limiting: max retries with exponential backoff
MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 2
REQUEST_TIMEOUT = 90  # seconds — reduced from 120 for faster fail/retry
BATCH_SIZE = 7  # module-level constant (used by SSE import)
MAX_TRANSCRIPT_CHARS = 4000  # truncate long transcripts to avoid token bloat


# ─── Batch Sizing ────────────────────────────────────────────────────────────

def _batch_size_for(num_questions: int, difficulty: str) -> int:
    """Pick batch size that won't timeout. Hard/long quizzes need smaller batches
    because each question is longer and the LLM output is bigger."""
    if difficulty == "hard" and num_questions > 20:
        return 5
    if difficulty == "hard" or num_questions > 20:
        return 7
    return 15  # easy/moderate with <=20 questions — bigger batch, fewer API calls


# ─── API Key ─────────────────────────────────────────────────────────────────

def _get_api_key() -> str:
    """Read the NVIDIA API key from environment."""
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "NVIDIA_API_KEY environment variable is not set. "
            "Get your free key at https://build.nvidia.com"
        )
    return api_key


# ─── Prompt Building ────────────────────────────────────────────────────────

def _build_prompt(
    transcript: str,
    num_questions: int,
    difficulty: str,
    transcript_language: str = None,
    exclude_topics: list[str] | None = None,
) -> str:
    """Build the prompt sent to the LLM for quiz generation."""
    # Language instruction
    if transcript_language and transcript_language != "en":
        lang_names = {
            "es": "Spanish", "fr": "French", "de": "German",
            "hi": "Hindi", "ja": "Japanese", "ko": "Korean", "pt": "Portuguese",
            "ru": "Russian", "zh": "Chinese", "ar": "Arabic", "it": "Italian",
            "nl": "Dutch", "pl": "Polish", "tr": "Turkish", "vi": "Vietnamese",
            "th": "Thai", "id": "Indonesian", "uk": "Ukrainian", "ta": "Tamil",
            "te": "Telugu", "bn": "Bengali", "mr": "Marathi",
        }
        base_code = transcript_language.split("-")[0]
        lang_display = lang_names.get(transcript_language, lang_names.get(base_code, transcript_language))
        lang_note = f"Transcript is in {lang_display}. Write the ENTIRE quiz in English."
    else:
        lang_note = "Write the entire quiz in English."

    # Truncate long transcripts to save tokens — but sample from start, middle, and end
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        third = MAX_TRANSCRIPT_CHARS // 3
        start = transcript[:third]
        mid_start = (len(transcript) - third) // 2
        mid = transcript[mid_start:mid_start + third]
        end = transcript[-third:]
        transcript = f"{start}\n[...middle portion skipped...]\n{mid}\n[...skipped...]\n{end}"

    prompt = f"""Create {num_questions} UPSC-style MCQs ({difficulty} difficulty) from this transcript. {lang_note}

Rules: 4 options (A-D), one correct. Use varied formats: statement-based ("Which is/are correct?"), assertion-reason, analytical, contextual. Plausible distractors. Spread across different topics. Explain why correct AND why others are wrong.

JSON only, no other text:
{{"title": "Quiz: [topic]", "questions": [{{"question": "...", "options": ["A) ...", "B) ...", "C) ...", "D) ..."], "correct_index": 0, "explanation": "..."}}]}}

TRANSCRIPT:
{transcript}"""

    # Add exclusion list to prevent duplicate topics
    if exclude_topics:
        topic_list = "\n".join(f"- {t}" for t in exclude_topics)
        prompt += f"\n\nIMPORTANT: The following topics have already been covered in earlier questions. DO NOT create similar questions about these topics:\n{topic_list}\nFocus on DIFFERENT topics/sections of the transcript."

    return prompt


# ─── Transcript Sectioning ───────────────────────────────────────────────────

def _split_transcript(transcript: str, num_sections: int, overlap_chars: int = 200) -> list[str]:
    """Split transcript into N sections with overlap windows for context continuity.

    Each batch gets a different section of the video, producing naturally
    diverse questions while the overlap avoids cutting mid-sentence context.
    """
    if num_sections <= 1 or len(transcript) <= MAX_TRANSCRIPT_CHARS:
        return [transcript] * num_sections

    section_size = len(transcript) // num_sections
    sections = []
    for i in range(num_sections):
        start = max(0, i * section_size - overlap_chars)
        if i < num_sections - 1:
            end = min(len(transcript), (i + 1) * section_size + overlap_chars)
        else:
            end = len(transcript)
        sections.append(transcript[start:end])
    return sections


# ─── Deduplication ───────────────────────────────────────────────────────────

def _deduplicate_questions(
    questions: list[QuizQuestion],
    similarity_threshold: float = 0.85,
) -> tuple[list[QuizQuestion], list[QuizQuestion]]:
    """Remove near-identical questions. Returns (kept_questions, removed_questions).

    0.85 threshold = only remove questions that are nearly identical wording.
    Lower thresholds (0.7) are too aggressive and remove questions that test
    different concepts but happen to share some phrasing.

    When duplicates are found, keeps the one with the longer explanation.
    """
    kept: list[QuizQuestion] = []
    removed: list[QuizQuestion] = []

    for q in questions:
        is_dup = False
        for k_idx, k in enumerate(kept):
            ratio = difflib.SequenceMatcher(
                None,
                q.question.lower().strip(),
                k.question.lower().strip(),
            ).ratio()
            if ratio >= similarity_threshold:
                is_dup = True
                if len(q.explanation) > len(k.explanation):
                    removed.append(k)
                    kept[k_idx] = q
                else:
                    removed.append(q)
                break
        if not is_dup:
            kept.append(q)

    return kept, removed


# ─── Response Parsing ───────────────────────────────────────────────────────

def _parse_quiz_response(raw_response: str, video_id: str) -> Quiz:
    """Parse the LLM response into a Quiz object."""
    text = raw_response.strip()

    if "```" in text:
        fence_match = regex.search(r"```(?:json)?\s*\n?(.*?)```", text, regex.DOTALL)
        if fence_match:
            text = fence_match.group(1).strip()

    brace_start = text.find("{")
    brace_end = text.rfind("}")
    if brace_start != -1 and brace_end != -1 and brace_end > brace_start:
        text = text[brace_start : brace_end + 1]

    try:
        data = json.loads(text)
    except json.JSONDecodeError as e:
        raise ValueError(
            f"Failed to parse LLM response as JSON. Error: {e}\n"
            f"Raw response (first 500 chars): {raw_response[:500]}"
        )

    if "questions" not in data:
        raise ValueError("LLM response missing 'questions' key")

    questions = []
    for i, q in enumerate(data["questions"]):
        try:
            questions.append(
                QuizQuestion(
                    question=q["question"],
                    options=q["options"],
                    correct_index=q["correct_index"],
                    explanation=q["explanation"],
                )
            )
        except KeyError as e:
            raise ValueError(f"Question {i} missing required field: {e}")

    return Quiz(
        title=data.get("title", f"Quiz: Video {video_id}"),
        video_id=video_id,
        questions=questions,
    )


# ─── Sync Batch Generation ──────────────────────────────────────────────────

def _generate_batch(
    transcript: str,
    video_id: str,
    num_questions: int,
    difficulty: str,
    transcript_language: Optional[str] = None,
    model: Optional[str] = None,
    batch_offset: int = 0,
    exclude_topics: list[str] | None = None,
    transcript_section: str | None = None,
) -> Quiz:
    """Generate a single batch of questions via the NVIDIA NIM API.

    Args:
        transcript: The full transcript text (used if transcript_section is None).
        video_id: YouTube video ID.
        num_questions: Number of questions for THIS batch.
        difficulty: Quiz difficulty.
        transcript_language: Language of the transcript.
        model: LLM model to use.
        batch_offset: Question number offset for diversity instructions.
        exclude_topics: Topics already covered — the LLM will avoid these.
        transcript_section: A specific section of the transcript to use instead of the full one.
    """
    api_key = _get_api_key()
    model = model or DEFAULT_MODEL

    # Use section if provided, otherwise full transcript
    effective_transcript = transcript_section if transcript_section else transcript

    # Build prompt with optional topic exclusion
    prompt = _build_prompt(effective_transcript, num_questions, difficulty, transcript_language, exclude_topics=exclude_topics)

    # Add batch offset instruction for diversity
    if batch_offset > 0:
        prompt += f"\n\nIMPORTANT: These are questions {batch_offset + 1} through {batch_offset + num_questions} of a larger quiz. Cover DIFFERENT topics/sections than earlier questions."

    headers = {
        "Authorization": f"Bearer {api_key}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    # Scale max_tokens by batch size: fewer questions = smaller response = faster
    max_tokens = min(num_questions * 250, 2000)

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": "You are a UPSC exam question setter. Respond with valid JSON only. No markdown. Keep explanations concise (1-2 sentences).",
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.4,
        "max_tokens": max_tokens,
        "stream": False,
    }

    # Timeout: scale with batch size — bigger batches need more time
    timeout = REQUEST_TIMEOUT + (num_questions * 5)

    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(
                NIM_BASE_URL,
                headers=headers,
                json=payload,
                timeout=timeout,
            )
            response.raise_for_status()

            data = response.json()
            raw = data["choices"][0]["message"]["content"]
            return _parse_quiz_response(raw, video_id)

        except requests.exceptions.HTTPError as e:
            last_error = e
            status = e.response.status_code if e.response is not None else "unknown"
            if status == 401:
                raise EnvironmentError(
                    f"NVIDIA API returned 401 Unauthorized. "
                    f"Check your NVIDIA_API_KEY in .env"
                ) from e
            if attempt < MAX_RETRIES - 1:
                wait = INITIAL_BACKOFF_SECONDS * (2 ** attempt)
                print(f"  Attempt {attempt + 1} failed (HTTP {status}): {e}. Retrying in {wait}s...")
                time.sleep(wait)
            if attempt == MAX_RETRIES - 1 and model != FALLBACK_MODEL:
                print(f"  Trying fallback model: {FALLBACK_MODEL}")
                payload["model"] = FALLBACK_MODEL
                model = FALLBACK_MODEL
                continue

        except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
            last_error = e
            if attempt < MAX_RETRIES - 1:
                wait = INITIAL_BACKOFF_SECONDS * (2 ** attempt)
                print(f"  Attempt {attempt + 1} failed: {e}. Retrying in {wait}s...")
                time.sleep(wait)
            if attempt == MAX_RETRIES - 1 and model != FALLBACK_MODEL:
                print(f"  Trying fallback model: {FALLBACK_MODEL}")
                payload["model"] = FALLBACK_MODEL
                model = FALLBACK_MODEL
                continue

        except (KeyError, IndexError) as e:
            raise ValueError(
                f"Unexpected API response structure: {json.dumps(data)[:500]}"
            ) from e

    raise RuntimeError(
        f"Failed to generate quiz after {MAX_RETRIES} attempts. Last error: {last_error}"
    )


# ─── Async Quiz Generation (Main Entry Point) ────────────────────────────────

async def generate_quiz(
    transcript: str,
    video_id: str,
    num_questions: int = 5,
    difficulty: str = "moderate",
    model: Optional[str] = None,
    transcript_language: Optional[str] = None,
) -> Quiz:
    """Generate a quiz from a video transcript using NVIDIA NIM.

    Uses sequential batches (proven reliable on NVIDIA NIM free tier) with
    transcript sectioning for diversity and deduplication for quality.

    Args:
        transcript: The full transcript text from the video.
        video_id: YouTube video ID.
        num_questions: Number of questions to generate (1-30).
        difficulty: Quiz difficulty — "easy", "moderate", or "hard".
        model: NVIDIA NIM model to use.
        transcript_language: Language code of the transcript.

    Returns:
        A Quiz object with generated questions.
    """
    if not 1 <= num_questions <= 30:
        raise ValueError("num_questions must be between 1 and 30")
    if difficulty not in ("easy", "moderate", "hard"):
        raise ValueError("difficulty must be 'easy', 'moderate', or 'hard'")

    effective_batch = _batch_size_for(num_questions, difficulty)

    if num_questions <= effective_batch:
        # Single batch — generate all at once
        return await asyncio.to_thread(
            _generate_batch,
            transcript=transcript,
            video_id=video_id,
            num_questions=num_questions,
            difficulty=difficulty,
            transcript_language=transcript_language,
            model=model,
            batch_offset=0,
        )

    # Multiple batches — over-generate to account for dedup loss
    # Generate ~25% extra questions so dedup doesn't leave us short
    target_questions = num_questions
    generate_total = min(num_questions + max(5, num_questions // 3), 40)
    total_batches = (generate_total + effective_batch - 1) // effective_batch
    sections = _split_transcript(transcript, total_batches)

    all_questions: list[QuizQuestion] = []
    title = None
    remaining = generate_total

    for batch_num in range(total_batches):
        batch_count = min(effective_batch, remaining)
        print(f"  Batch {batch_num + 1}/{total_batches}: generating {batch_count} questions...")

        batch_quiz = await asyncio.to_thread(
            _generate_batch,
            transcript=transcript,
            video_id=video_id,
            num_questions=batch_count,
            difficulty=difficulty,
            transcript_language=transcript_language,
            model=model,
            batch_offset=batch_num * effective_batch,
            transcript_section=sections[batch_num],
        )

        if title is None:
            title = batch_quiz.title

        all_questions.extend(batch_quiz.questions)
        remaining -= batch_count

    # Deduplicate questions — removes duplicates across batches
    kept, removed = _deduplicate_questions(all_questions)

    if removed:
        logger.info(f"Dedup: removed {len(removed)} duplicate questions, {len(kept)} kept")

    # If dedup removed too many, generate supplemental batches to reach target
    max_supplement_batches = 5
    supplement_batch = 0
    already_covered_topics = [q.question for q in kept]

    while len(kept) < num_questions and supplement_batch < max_supplement_batches:
        shortfall = num_questions - len(kept)
        supplement_count = min(shortfall + 2, effective_batch)  # +2 buffer for potential dups
        supplement_batch += 1
        logger.info(f"Supplement batch {supplement_batch}: generating {supplement_count} more (shortfall={shortfall})")

        try:
            sup_quiz = await asyncio.to_thread(
                _generate_batch,
                transcript=transcript,
                video_id=video_id,
                num_questions=supplement_count,
                difficulty=difficulty,
                transcript_language=transcript_language,
                model=model,
                batch_offset=len(kept),
                exclude_topics=already_covered_topics,
            )

            if title is None:
                title = sup_quiz.title

            kept.extend(sup_quiz.questions)
            already_covered_topics.extend(q.question for q in sup_quiz.questions)

            # Re-dedup the combined set
            kept, sup_removed = _deduplicate_questions(kept)
            if sup_removed:
                logger.info(f"Supplement dedup: removed {len(sup_removed)}, {len(kept)} kept")

        except Exception as e:
            logger.warning(f"Supplement batch failed: {e}")
            break

    return Quiz(
        title=title or f"Quiz: Video {video_id}",
        video_id=video_id,
        questions=kept[:num_questions],  # trim to requested count
        language="en",
    )


# ─── Async wrapper for SSE endpoint ─────────────────────────────────────────

async def _generate_batch_async(
    transcript: str,
    video_id: str,
    num_questions: int,
    difficulty: str,
    transcript_language: Optional[str] = None,
    model: Optional[str] = None,
    batch_offset: int = 0,
    exclude_topics: list[str] | None = None,
    transcript_section: str | None = None,
) -> Quiz:
    """Async wrapper — runs _generate_batch in a thread."""
    return await asyncio.to_thread(
        _generate_batch,
        transcript=transcript,
        video_id=video_id,
        num_questions=num_questions,
        difficulty=difficulty,
        transcript_language=transcript_language,
        model=model,
        batch_offset=batch_offset,
        exclude_topics=exclude_topics,
        transcript_section=transcript_section,
    )


async def close_client():
    """No-op — we use requests, no async client to close."""
    pass