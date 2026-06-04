"""Quiz generation service using NVIDIA NIM API."""

import json
import os
import time
import re as regex
from typing import Optional

import requests
from dotenv import load_dotenv

from backend.app.models.schemas import Quiz, QuizQuestion

# Load environment variables from .env file
load_dotenv()

# ─── NVIDIA NIM Configuration ───────────────────────────────────────────────

NIM_BASE_URL = "https://integrate.api.nvidia.com/v1/chat/completions"
DEFAULT_MODEL = "meta/llama-3.3-70b-instruct"
FALLBACK_MODEL = "nvidia/llama-3.3-nemotron-super-49b-v1.5"

# Rate limiting: max retries with exponential backoff
MAX_RETRIES = 3
INITIAL_BACKOFF_SECONDS = 2
REQUEST_TIMEOUT = 120  # seconds — enough for 7-question batches
BATCH_SIZE = 7  # questions per API call — sweet spot for speed + reliability
MAX_TRANSCRIPT_CHARS = 4000  # truncate long transcripts to avoid token bloat


def _batch_size_for(num_questions: int, difficulty: str) -> int:
    """Pick batch size that won't timeout. Hard/long quizzes need smaller batches
    because each question is longer and the LLM output is bigger."""
    if difficulty == "hard" and num_questions > 20:
        return 5
    if difficulty == "hard" or num_questions > 20:
        return 7
    return 10  # easy/moderate with <=20 questions — bigger batch, fewer calls


def _get_api_key() -> str:
    """Read the NVIDIA API key from environment."""
    api_key = os.environ.get("NVIDIA_API_KEY")
    if not api_key:
        raise EnvironmentError(
            "NVIDIA_API_KEY environment variable is not set. "
            "Get your free key at https://build.nvidia.com"
        )
    return api_key


def _build_prompt(transcript: str, num_questions: int, difficulty: str, transcript_language: str = None) -> str:
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
    # so the LLM sees the full scope of the video, not just the first few minutes
    if len(transcript) > MAX_TRANSCRIPT_CHARS:
        third = MAX_TRANSCRIPT_CHARS // 3
        start = transcript[:third]
        mid_start = (len(transcript) - third) // 2
        mid = transcript[mid_start:mid_start + third]
        end = transcript[-third:]
        transcript = f"{start}\n[...middle portion skipped...]\n{mid}\n[...skipped...]\n{end}"

    return f"""Create {num_questions} UPSC-style MCQs ({difficulty} difficulty) from this transcript. {lang_note}

Rules: 4 options (A-D), one correct. Use varied formats: statement-based ("Which is/are correct?"), assertion-reason, analytical, contextual. Plausible distractors. Spread across different topics. Explain why correct AND why others are wrong.

JSON only, no other text:
{{"title": "Quiz: [topic]", "questions": [{{"question": "...", "options": ["A) ...", "B) ...", "C) ...", "D) ..."], "correct_index": 0, "explanation": "..."}}]}}

TRANSCRIPT:
{transcript}"""


def _parse_quiz_response(raw_response: str, video_id: str) -> Quiz:
    """Parse the LLM response into a Quiz object.

    Handles common issues:
    - JSON wrapped in markdown code fences (```json ... ```)
    - Conversational text before/after JSON
    - Trailing commas or other minor JSON issues
    """
    text = raw_response.strip()

    # Strip markdown code fences if present
    if "```" in text:
        # Extract content between code fences
        fence_match = regex.search(r"```(?:json)?\s*\n?(.*?)```", text, regex.DOTALL)
        if fence_match:
            text = fence_match.group(1).strip()

    # Try to find JSON object in the response
    # Look for the outermost { ... } pair
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

    # Validate structure
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


def generate_quiz(
    transcript: str,
    video_id: str,
    num_questions: int = 5,
    difficulty: str = "moderate",
    model: Optional[str] = None,
    transcript_language: Optional[str] = None,
) -> Quiz:
    """Generate a quiz from a video transcript using NVIDIA NIM.

    The quiz is ALWAYS generated in English. If the transcript is in a
    non-English language, the LLM will translate concepts into English.

    Args:
        transcript: The full transcript text from the video.
        video_id: YouTube video ID (used for reference in the quiz title).
        num_questions: Number of questions to generate (1-20).
        difficulty: Quiz difficulty — "easy", "moderate", or "hard".
        model: NVIDIA NIM model to use. Defaults to llama-3.3-70b-instruct.
        transcript_language: Language code of the transcript (e.g., "hi", "es").
                  Used to tell the LLM the transcript may not be in English.
                  If None, assumes English.

    Returns:
        A Quiz object with generated questions.

    Raises:
        EnvironmentError: If NVIDIA_API_KEY is not set.
        ValueError: If the LLM response cannot be parsed.
        RuntimeError: If all retry attempts fail.
    """
    if not 1 <= num_questions <= 30:
        raise ValueError("num_questions must be between 1 and 30")

    if difficulty not in ("easy", "moderate", "hard"):
        raise ValueError("difficulty must be 'easy', 'moderate', or 'hard'")

    # For large question counts, split into batches to avoid timeouts
    effective_batch = _batch_size_for(num_questions, difficulty)

    if num_questions <= effective_batch:
        # Single batch — generate all at once
        return _generate_batch(
            transcript=transcript,
            video_id=video_id,
            num_questions=num_questions,
            difficulty=difficulty,
            transcript_language=transcript_language,
            model=model,
            batch_offset=0,
        )

    # Multiple batches — generate in groups and combine
    all_questions = []
    title = None
    remaining = num_questions

    for batch_num in range((num_questions + effective_batch - 1) // effective_batch):
        batch_count = min(effective_batch, remaining)
        print(f"  Batch {batch_num + 1}: generating {batch_count} questions...")

        batch_quiz = _generate_batch(
            transcript=transcript,
            video_id=video_id,
            num_questions=batch_count,
            difficulty=difficulty,
            transcript_language=transcript_language,
            model=model,
            batch_offset=batch_num * effective_batch,
        )

        if title is None:
            title = batch_quiz.title

        all_questions.extend(batch_quiz.questions)
        remaining -= batch_count

    return Quiz(
        title=title or f"Quiz: Video {video_id}",
        video_id=video_id,
        questions=all_questions,
        language="en",
    )


def _generate_batch(
    transcript: str,
    video_id: str,
    num_questions: int,
    difficulty: str,
    transcript_language: Optional[str] = None,
    model: Optional[str] = None,
    batch_offset: int = 0,
) -> Quiz:
    """Generate a single batch of questions via the NVIDIA NIM API.

    Args:
        transcript: The transcript text.
        video_id: YouTube video ID.
        num_questions: Number of questions for THIS batch.
        difficulty: Quiz difficulty.
        transcript_language: Language of the transcript.
        model: LLM model to use.
        batch_offset: Question number offset (e.g., "questions 8-14 of 15").
    """
    api_key = _get_api_key()
    model = model or DEFAULT_MODEL

    # Adjust prompt for batches — tell the model which questions to focus on
    if batch_offset > 0:
        prompt = _build_prompt(transcript, num_questions, difficulty, transcript_language)
        # Add instruction to avoid repeating earlier questions
        prompt += f"\n\nIMPORTANT: These are questions {batch_offset + 1} through {batch_offset + num_questions} of a larger quiz. Cover DIFFERENT topics/sections than earlier questions."
    else:
        prompt = _build_prompt(transcript, num_questions, difficulty, transcript_language)

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
    timeout = REQUEST_TIMEOUT + (num_questions * 5)  # extra 5s per question

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
            # Don't retry on auth errors
            if status == 401:
                raise EnvironmentError(
                    f"NVIDIA API returned 401 Unauthorized. "
                    f"Check your NVIDIA_API_KEY in .env"
                ) from e
            # Retry on rate limit or server errors
            if attempt < MAX_RETRIES - 1:
                wait = INITIAL_BACKOFF_SECONDS * (2 ** attempt)
                print(f"  Attempt {attempt + 1} failed (HTTP {status}): {e}. Retrying in {wait}s...")
                time.sleep(wait)
            # Try fallback model on last attempt
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