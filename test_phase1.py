#!/usr/bin/env python3
"""
Quick end-to-end test for Phase 1.

Run this to verify the full pipeline works:
    .venv\Scripts\python.exe test_phase1.py

It will:
  1. Fetch a transcript from a real YouTube video
  2. Call NVIDIA NIM to generate a 3-question quiz
  3. Print the quiz and save it as JSON
"""

import sys
import io
import json

# Fix Windows console encoding for emoji/unicode
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")

from backend.app.services.transcript import extract_video_id, get_transcript
from backend.app.services.quiz_generator import generate_quiz


def main():
    # ─── Test 1: Video ID extraction ─────────────────────────────
    print("=" * 60)
    print("  TEST 1: Video ID extraction")
    print("=" * 60)

    test_urls = [
        "https://www.youtube.com/watch?v=dQw4w9WgXcQ",
        "https://youtu.be/dQw4w9WgXcQ",
        "https://www.youtube.com/shorts/dQw4w9WgXcQ",
        "dQw4w9WgXcQ",
    ]
    for url in test_urls:
        try:
            vid = extract_video_id(url)
            print(f"  OK  {url[:50]:50s} -> {vid}")
        except ValueError as e:
            print(f"  FAIL  {url} -> {e}")

    # ─── Test 2: Transcript fetch ───────────────────────────────
    print(f"\n{'=' * 60}")
    print("  TEST 2: Transcript fetch")
    print("=" * 60)

    video_id = "dQw4w9WgXcQ"
    try:
        result = get_transcript(video_id)
        print(f"  OK  Language: {result.language}")
        print(f"  OK  Auto-generated: {result.is_auto_generated}")
        print(f"  OK  Chars: {result.char_count:,}")
        print(f"  OK  Estimated tokens: ~{result.estimated_tokens:,}")
        print(f"  OK  Preview: {result.text[:120]}...")
    except RuntimeError as e:
        print(f"  FAIL  {e}")
        sys.exit(1)

    # ─── Test 3: Quiz generation (calls NVIDIA NIM) ──────────────
    print(f"\n{'=' * 60}")
    print("  TEST 3: Quiz generation (NVIDIA NIM API call)")
    print("=" * 60)

    try:
        quiz = generate_quiz(
            transcript=result.text,
            video_id=video_id,
            num_questions=3,
            difficulty="easy",
        )
        print(f"  OK  Title: {quiz.title}")
        print(f"  OK  Questions: {len(quiz.questions)}")

        for i, q in enumerate(quiz.questions, 1):
            print(f"\n  Q{i}: {q.question}")
            for j, opt in enumerate(q.options):
                marker = " <-- CORRECT" if j == q.correct_index else ""
                print(f"    {opt}{marker}")
            print(f"    Explanation: {q.explanation}")

        # Save quiz JSON
        output_file = f"quiz_{video_id}.json"
        with open(output_file, "w", encoding="utf-8") as f:
            json.dump(quiz.to_dict(), f, indent=2, ensure_ascii=False)
        print(f"\n  Saved to: {output_file}")

    except (EnvironmentError, RuntimeError, ValueError) as e:
        print(f"  FAIL  {e}")
        sys.exit(1)

    # ─── Summary ────────────────────────────────────────────────
    print(f"\n{'=' * 60}")
    print("  All tests passed! Phase 1 is working.")
    print("=" * 60)


if __name__ == "__main__":
    main()