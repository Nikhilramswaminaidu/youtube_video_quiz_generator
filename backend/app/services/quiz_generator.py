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
REQUEST_TIMEOUT = 120  # seconds — large transcripts need time
BATCH_SIZE = 7  # questions per API call to avoid timeouts


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
    """Build the prompt sent to the LLM for quiz generation.

    Args:
        transcript: The video transcript text.
        num_questions: Number of questions to generate.
        difficulty: Quiz difficulty level.
        transcript_language: Language code of the transcript (e.g., "hi", "es").
                            Used to tell the LLM the transcript may not be in English.
    """
    # If the transcript isn't in English, tell the LLM to read it in that
    # language but write ALL quiz content in English
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
        language_instruction = (
            f"IMPORTANT: The transcript is in {lang_display}, but you MUST write the ENTIRE quiz in English. "
            f"Read and understand the {lang_display} transcript, then translate the concepts into English. "
            f"All questions, options, explanations, and the title must be in English."
        )
    else:
        language_instruction = (
            "Write the entire quiz in English."
        )

    return f"""You are a UPSC-style exam question setter. Given the following video transcript, create exactly {num_questions} multiple-choice questions at {difficulty} difficulty.

{language_instruction}

UPSC-STYLE QUESTION REQUIREMENTS:
- Each question must have exactly 4 options labeled A, B, C, D — only ONE is correct
- Questions MUST be UPSC-style: analytical, conceptual, and application-oriented
- Use these UPSC question formats (vary them across the quiz):
  1. STATEMENT-BASED: "Which of the following statements is/are correct?" with 2-3 numbered statements, and options like "1 only", "1 and 2 only", "1, 2 and 3", "None of the above"
  2. ASSERTION-REASON: "Assertion (A): ... Reason (R): ..." with options: "Both A and R are true and R is the correct explanation of A", "Both A and R are true but R is NOT the correct explanation of A", "A is true but R is false", "A is false but R is true"
  3. ANALYTICAL: Questions that test cause-effect, comparisons, implications — not just factual recall
  4. CONTEXTUAL: Questions that connect the video content to broader concepts, policies, or real-world implications
- Distractors must be plausible and closely related to the topic — avoid obviously wrong options
- Spread questions across DIFFERENT parts and topics in the transcript — don't cluster on one section
- Every explanation must clearly state WHY the correct answer is right and WHY each wrong option is wrong
- Use precise, formal language consistent with UPSC standards

Return ONLY valid JSON in this exact format (no other text, no markdown):
{{
  "title": "Quiz: [brief topic description]",
  "questions": [
    {{
      "question": "The question text?",
      "options": ["A) Option text", "B) Option text", "C) Option text", "D) Option text"],
      "correct_index": 0,
      "explanation": "Detailed explanation of why the correct answer is right and why each other option is wrong."
    }}
  ]
}}

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
    if num_questions <= BATCH_SIZE:
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

    for batch_num in range((num_questions + BATCH_SIZE - 1) // BATCH_SIZE):
        batch_count = min(BATCH_SIZE, remaining)
        print(f"  Batch {batch_num + 1}: generating {batch_count} questions...")

        batch_quiz = _generate_batch(
            transcript=transcript,
            video_id=video_id,
            num_questions=batch_count,
            difficulty=difficulty,
            transcript_language=transcript_language,
            model=model,
            batch_offset=batch_num * BATCH_SIZE,
        )

        if title is None:
            title = batch_quiz.title

        all_questions.extend(batch_quiz.questions)
        remaining -= batch_count

        # Small delay between batches to avoid rate limiting
        if remaining > 0:
            time.sleep(1)

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

    payload = {
        "model": model,
        "messages": [
            {
                "role": "system",
                "content": (
                    "You are a UPSC-style exam question setter. "
                    "Always respond with valid JSON only. "
                    "No markdown, no explanations outside the JSON."
                ),
            },
            {"role": "user", "content": prompt},
        ],
        "temperature": 0.4,
        "max_tokens": 4000,
        "stream": False,
    }

    last_error = None
    for attempt in range(MAX_RETRIES):
        try:
            response = requests.post(
                NIM_BASE_URL,
                headers=headers,
                json=payload,
                timeout=REQUEST_TIMEOUT,
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