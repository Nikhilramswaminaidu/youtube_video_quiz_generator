#!/usr/bin/env python3
"""
YouTube → Quiz Generator (Phase 1)

Pastes a YouTube video URL, fetches the transcript,
and generates a multiple-choice quiz using NVIDIA NIM.

Works with videos in ANY language — quizzes are always in English.

Usage:
    python quiz_generator.py

Requirements:
    pip install -r requirements.txt

Environment:
    Your NVIDIA_API_KEY is loaded from .env automatically.
    Get your free key at: https://build.nvidia.com
"""

import json
import os
import sys

from dotenv import load_dotenv

# Fix Windows console encoding for emoji/unicode
if sys.platform == "win32":
    sys.stdout = open(sys.stdout.fileno(), mode="w", encoding="utf-8", buffering=1)

# Load .env before any service imports (so they get the key)
load_dotenv()

from backend.app.services.transcript import extract_video_id, get_transcript, list_available_languages
from backend.app.services.quiz_generator import generate_quiz

# Language display names for common codes
LANGUAGE_NAMES = {
    "en": "English", "es": "Spanish", "fr": "French", "de": "German",
    "hi": "Hindi", "ja": "Japanese", "ko": "Korean", "pt": "Portuguese",
    "ru": "Russian", "zh": "Chinese", "zh-Hans": "Chinese (Simplified)",
    "zh-Hant": "Chinese (Traditional)", "ar": "Arabic", "it": "Italian",
    "nl": "Dutch", "pl": "Polish", "tr": "Turkish", "vi": "Vietnamese",
    "th": "Thai", "id": "Indonesian", "uk": "Ukrainian", "ta": "Tamil",
    "te": "Telugu", "bn": "Bengali", "mr": "Marathi", "sv": "Swedish",
    "da": "Danish", "fi": "Finnish", "no": "Norwegian", "cs": "Czech",
    "el": "Greek", "he": "Hebrew", "ms": "Malay", "ro": "Romanian",
    "hu": "Hungarian", "bg": "Bulgarian", "hr": "Croatian", "sk": "Slovak",
    "ur": "Urdu", "fa": "Persian", "tl": "Filipino",
}


def get_language_display(code: str) -> str:
    """Get a human-readable language name from a code."""
    base_code = code.split("-")[0]  # e.g., "en-US" -> "en"
    return LANGUAGE_NAMES.get(code, LANGUAGE_NAMES.get(base_code, code))


def print_quiz(quiz) -> None:
    """Pretty-print a quiz to the terminal."""
    print(f"\n{'=' * 60}")
    print(f"  {quiz.title}")
    print(f"  Video: https://youtube.com/watch?v={quiz.video_id}")
    print(f"  Questions: {len(quiz.questions)}")
    print(f"{'=' * 60}\n")

    for i, q in enumerate(quiz.questions, 1):
        print(f"Q{i}. {q.question}")
        for opt in q.options:
            print(f"   {opt}")
        print()


def take_quiz(quiz) -> None:
    """Interactive quiz mode — student picks answers and gets scored."""
    print(f"\n{'=' * 60}")
    print(f"  📝 {quiz.title}")
    print(f"  Answer the questions below. Type A, B, C, or D.")
    print(f"{'=' * 60}\n")

    score = 0

    for i, q in enumerate(quiz.questions, 1):
        print(f"Q{i}. {q.question}")
        for opt in q.options:
            print(f"   {opt}")

        # Map letter to index
        letter_map = {"a": 0, "b": 1, "c": 2, "d": 3}

        while True:
            answer = input("\n   Your answer (A/B/C/D): ").strip().lower()
            if answer in letter_map:
                break
            print("   Please enter A, B, C, or D.")

        selected = letter_map[answer]
        correct = q.correct_index
        is_correct = selected == correct

        if is_correct:
            score += 1
            print(f"   ✅ Correct!")
        else:
            correct_letter = chr(65 + correct)
            print(f"   ❌ Wrong. Correct answer: {correct_letter}")

        print(f"   💡 {q.explanation}\n")
        print("-" * 60)

    total = len(quiz.questions)
    pct = (score / total * 100) if total > 0 else 0

    print(f"\n{'=' * 60}")
    print(f"  🏁 Results: {score}/{total} ({pct:.0f}%)")
    if pct >= 80:
        print("  🌟 Great job!")
    elif pct >= 60:
        print("  👍 Good effort!")
    else:
        print("  📚 Keep studying!")
    print(f"{'=' * 60}\n")


def main():
    """Main entry point."""
    print("\n🎬 YouTube → Quiz Generator")
    print("   Powered by NVIDIA NIM (free LLM API)")
    print("   Works with ANY language video → English quiz 🌍\n")

    # Get YouTube URL from user
    url = input("Enter a YouTube video URL: ").strip()
    if not url:
        print("No URL provided. Exiting.")
        sys.exit(1)

    # Extract video ID
    try:
        video_id = extract_video_id(url)
        print(f"📹 Video ID: {video_id}")
    except ValueError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Check available languages
    print("🌐 Checking available captions...")
    try:
        available = list_available_languages(video_id)
        if available:
            print("   Available captions:")
            for lang in available:
                kind = "auto" if lang["is_generated"] else "manual"
                display = get_language_display(lang["language_code"])
                translatable = " ✓ translatable" if lang.get("is_translatable") else ""
                print(f"     - {lang['language_code']:8s} ({display}) [{kind}]{translatable}")
                # Show translation targets
                if lang.get("translation_languages"):
                    targets = ", ".join(lang["translation_languages"][:8])
                    extra = "..." if len(lang["translation_languages"]) > 8 else ""
                    print(f"       ↳ Can translate to: {targets}{extra}")
        else:
            print("   No captions found.")
    except RuntimeError as e:
        print(f"   Warning: {e}")

    # Fetch transcript (auto-detect best language)
    print("\n📥 Fetching transcript...")
    try:
        result = get_transcript(video_id)
        transcript = result.text
        auto_tag = " (auto-generated)" if result.is_auto_generated else ""
        lang_display = get_language_display(result.language)
        print(f"   Language: {lang_display} ({result.language}){auto_tag}")
        print(f"   Got transcript: {result.char_count:,} chars")
        print(f"   Estimated tokens: ~{result.estimated_tokens:,}")
    except RuntimeError as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Configure quiz
    print("\n⚙️  Quiz Settings (UPSC-style):")
    try:
        num_q = input("   Number of questions (1-30, default 10): ").strip()
        num_questions = int(num_q) if num_q else 10
    except ValueError:
        num_questions = 10

    difficulty = input("   Difficulty (easy/moderate/hard, default moderate): ").strip()
    difficulty = difficulty if difficulty in ("easy", "moderate", "hard") else "moderate"

    # Generate quiz — always in English, passing transcript language for context
    transcript_lang = result.language
    print(f"\n🧠 Generating {num_questions} UPSC-style {difficulty} questions (in English)...")
    if transcript_lang != "en":
        print(f"   Transcript is in {get_language_display(transcript_lang)} — translating concepts to English")

    try:
        quiz = generate_quiz(
            transcript=transcript,
            video_id=video_id,
            num_questions=num_questions,
            difficulty=difficulty,
            transcript_language=transcript_lang,
        )
        quiz.language = "en"
    except (EnvironmentError, RuntimeError, ValueError) as e:
        print(f"Error: {e}")
        sys.exit(1)

    # Show quiz
    print_quiz(quiz)

    # Offer interactive quiz mode
    mode = input("Take the quiz interactively? (y/n, default y): ").strip().lower()
    if mode != "n":
        take_quiz(quiz)

    # Save quiz to file
    output_file = f"quiz_{video_id}.json"
    with open(output_file, "w", encoding="utf-8") as f:
        json.dump(quiz.to_dict(), f, indent=2, ensure_ascii=False)
    print(f"💾 Quiz saved to: {output_file}")


if __name__ == "__main__":
    main()