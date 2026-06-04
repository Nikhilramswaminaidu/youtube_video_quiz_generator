"""Quiz generation, submission, and PDF export API routes."""

import asyncio
import json
import time
from typing import Optional

from fastapi import APIRouter, HTTPException
from fastapi.responses import Response, StreamingResponse

from backend.app.models.schemas import (
    GenerateQuizRequest,
    QuizResponse,
    QuestionResponse,
    SubmitQuizRequest,
    SubmitQuizResponse,
    QuestionResult,
    ErrorResponse,
)
from backend.app.services.transcript import extract_video_id, get_transcript
from backend.app.services.quiz_generator import generate_quiz, _generate_batch, _batch_size_for
from backend.app.services.pdf_generator import generate_quiz_pdf, generate_results_pdf

router = APIRouter(prefix="/api/quiz", tags=["quiz"])

# In-memory storage
_quizzes: dict[str, dict] = {}
_results: dict[str, dict] = {}
# Cache: keyed by (video_id, num_questions, difficulty) to avoid regenerating
_cache: dict[str, tuple[dict, float]] = {}  # value = (quiz_data, timestamp)
_CACHE_TTL = 3600  # 1 hour


def _cache_key(video_id: str, num_questions: int, difficulty: str) -> str:
    return f"{video_id}:{num_questions}:{difficulty}"


def _check_cache(video_id: str, num_questions: int, difficulty: str) -> Optional[dict]:
    """Return cached quiz if it exists and hasn't expired."""
    key = _cache_key(video_id, num_questions, difficulty)
    if key in _cache:
        quiz_data, timestamp = _cache[key]
        if time.time() - timestamp < _CACHE_TTL:
            return quiz_data
        del _cache[key]  # expired
    return None


def _store_cache(video_id: str, num_questions: int, difficulty: str, quiz_data: dict):
    key = _cache_key(video_id, num_questions, difficulty)
    _cache[key] = (quiz_data, time.time())


@router.post(
    "/generate",
    response_model=QuizResponse,
    responses={400: {"model": ErrorResponse}, 500: {"model": ErrorResponse}},
    summary="Generate a quiz from a YouTube video",
)
async def generate_quiz_endpoint(request: GenerateQuizRequest):
    """Generate a quiz. Returns cached result if the same video+settings were recently generated."""
    try:
        video_id = extract_video_id(request.youtube_url)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    # Check cache first
    cached = _check_cache(video_id, request.num_questions, request.difficulty)
    if cached:
        _quizzes[video_id] = cached
        questions = cached["questions"]
        return QuizResponse(
            id=video_id,
            title=cached["title"],
            video_id=video_id,
            language=cached.get("language", "en"),
            questions=[
                QuestionResponse(id=i, **q) for i, q in enumerate(questions)
            ],
        )

    # Fetch transcript
    try:
        result = await asyncio.to_thread(get_transcript, video_id)
    except RuntimeError as e:
        raise HTTPException(status_code=404, detail=str(e))

    # Generate quiz
    try:
        quiz = await asyncio.to_thread(
            generate_quiz,
            transcript=result.text,
            video_id=video_id,
            num_questions=request.num_questions,
            difficulty=request.difficulty,
            transcript_language=result.language,
        )
        quiz.language = "en"
    except EnvironmentError as e:
        raise HTTPException(status_code=401, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=502, detail=str(e))

    quiz_data = quiz.to_dict()
    _quizzes[video_id] = quiz_data
    _store_cache(video_id, request.num_questions, request.difficulty, quiz_data)

    return QuizResponse(
        id=video_id,
        title=quiz.title,
        video_id=quiz.video_id,
        language=quiz.language,
        questions=[
            QuestionResponse(id=i, question=q.question, options=q.options,
                             correct_index=q.correct_index, explanation=q.explanation)
            for i, q in enumerate(quiz.questions)
        ],
    )


@router.get(
    "/generate/stream",
    summary="Generate quiz with live progress (SSE)",
    description="Server-Sent Events endpoint that streams progress as the quiz is generated. Much better UX than the blocking endpoint.",
)
async def generate_quiz_stream(
    youtube_url: str,
    num_questions: int = 10,
    difficulty: str = "moderate",
):
    """Stream quiz generation progress via SSE.

    Events: progress, complete, error
    """
    try:
        video_id = extract_video_id(youtube_url)
    except ValueError as e:
        async def error_stream():
            yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
        return StreamingResponse(error_stream(), media_type="text/event-stream")

    async def event_stream():
        try:
            import time as _time
            gen_start = _time.time()

            # Check cache first
            cached = _check_cache(video_id, num_questions, difficulty)
            if cached:
                _quizzes[video_id] = cached
                yield f"event: progress\ndata: {json.dumps({'step': 'cache', 'message': 'Found cached quiz!'})}\n\n"
                yield f"event: complete\ndata: {json.dumps(_build_quiz_response(video_id, cached))}\n\n"
                return

            # Step 1: Fetch transcript
            yield f"event: progress\ndata: {json.dumps({'step': 'transcript', 'message': 'Fetching video transcript...'})}\n\n"
            try:
                result = await asyncio.to_thread(get_transcript, video_id)
            except RuntimeError as e:
                yield f"event: error\ndata: {json.dumps({'error': str(e)})}\n\n"
                return

            elapsed = round(_time.time() - gen_start, 1)
            yield f"event: progress\ndata: {json.dumps({'step': 'transcript_done', 'message': f'Transcript ready ({result.char_count:,} chars, {result.language})', 'elapsed': elapsed})}\n\n"

            # Step 2: Generate quiz in batches with progress
            all_questions = []
            title = None
            effective_batch = _batch_size_for(num_questions, difficulty)
            total_batches = (num_questions + effective_batch - 1) // effective_batch
            batch_times = []  # track how long each batch takes

            for batch_num in range(total_batches):
                batch_count = min(effective_batch, num_questions - len(all_questions))
                current_batch = batch_num + 1
                yield f"event: progress\ndata: {json.dumps({'step': 'generating', 'message': f'Generating questions (batch {current_batch}/{total_batches})...', 'batch': current_batch, 'total_batches': total_batches, 'done': len(all_questions), 'total': num_questions})}\n\n"

                # Keepalive ping before long LLM call
                yield f": keepalive\n\n"

                batch_start = _time.time()
                try:
                    batch_quiz = await asyncio.to_thread(
                        _generate_batch,
                        transcript=result.text,
                        video_id=video_id,
                        num_questions=batch_count,
                        difficulty=difficulty,
                        transcript_language=result.language,
                        batch_offset=batch_num * effective_batch,
                    )
                    batch_elapsed = _time.time() - batch_start
                    batch_times.append(batch_elapsed)
                    if title is None:
                        title = batch_quiz.title
                    all_questions.extend(batch_quiz.questions)

                    # Calculate ETA based on average batch time
                    done = len(all_questions)
                    remaining_batches = total_batches - (batch_num + 1)
                    avg_batch_time = sum(batch_times) / len(batch_times)
                    eta_seconds = round(remaining_batches * avg_batch_time)

                    yield f"event: progress\ndata: {json.dumps({'step': 'batch_done', 'message': f'{done}/{num_questions} questions generated', 'done': done, 'total': num_questions, 'eta': eta_seconds, 'elapsed': round(_time.time() - gen_start, 1)})}\n\n"
                except Exception as e:
                    yield f"event: error\ndata: {json.dumps({'error': f'Generation failed: {str(e)}'})}\n\n"
                    return

            # Build final quiz
            from backend.app.models.schemas import Quiz
            quiz = Quiz(
                title=title or f"Quiz: Video {video_id}",
                video_id=video_id,
                questions=all_questions,
                language="en",
            )
            quiz_data = quiz.to_dict()
            _quizzes[video_id] = quiz_data
            _store_cache(video_id, num_questions, difficulty, quiz_data)

            total_time = round(_time.time() - gen_start, 1)
            yield f"event: progress\ndata: {json.dumps({'step': 'done', 'message': f'Quiz ready! {len(all_questions)} questions generated.', 'elapsed': total_time})}\n\n"
            yield f"event: complete\ndata: {json.dumps(_build_quiz_response(video_id, quiz_data))}\n\n"

        except Exception as e:
            # Catch-all: any unhandled error still sends an SSE error event
            try:
                yield f"event: error\ndata: {json.dumps({'error': f'Server error: {str(e)}'})}\n\n"
            except Exception:
                pass

    return StreamingResponse(event_stream(), media_type="text/event-stream")


def _build_quiz_response(video_id: str, quiz_data: dict) -> dict:
    return {
        "id": video_id,
        "title": quiz_data["title"],
        "video_id": video_id,
        "language": quiz_data.get("language", "en"),
        "questions": [
            {"id": i, **q} for i, q in enumerate(quiz_data["questions"])
        ],
    }


@router.post(
    "/submit",
    response_model=SubmitQuizResponse,
    responses={404: {"model": ErrorResponse}},
    summary="Submit quiz answers and get scored",
)
async def submit_quiz_endpoint(request: SubmitQuizRequest):
    """Submit answers for a quiz and get scored."""
    quiz_id = request.quiz_id
    answers = request.answers

    if quiz_id not in _quizzes:
        raise HTTPException(status_code=404, detail=f"Quiz not found: {quiz_id}")

    quiz_data = _quizzes[quiz_id]
    questions = quiz_data["questions"]

    if len(answers) != len(questions):
        raise HTTPException(status_code=422, detail=f"Expected {len(questions)} answers, got {len(answers)}")

    details = []
    score = 0
    for i, (question, selected) in enumerate(zip(questions, answers)):
        correct = question["correct_index"]
        is_correct = selected == correct
        if is_correct:
            score += 1
        details.append(
            QuestionResult(
                question_id=i, question=question["question"],
                selected=selected, correct=correct, is_correct=is_correct,
                selected_option=question["options"][selected],
                correct_option=question["options"][correct],
                explanation=question["explanation"],
            )
        )

    total = len(questions)
    percentage = round((score / total * 100) if total > 0 else 0, 1)
    result = SubmitQuizResponse(quiz_id=quiz_id, score=score, total=total, percentage=percentage, details=details)
    _results[quiz_id] = result.model_dump()
    return result


@router.get(
    "/{quiz_id}/pdf",
    responses={404: {"model": ErrorResponse}},
    summary="Download quiz as PDF",
)
async def download_quiz_pdf(quiz_id: str, mode: str = "quiz"):
    """Download quiz as PDF. Modes: quiz (blank), answers (key), results (scored)."""
    if quiz_id not in _quizzes:
        raise HTTPException(status_code=404, detail=f"Quiz not found: {quiz_id}")

    quiz_data = _quizzes[quiz_id]

    if mode == "results":
        if quiz_id not in _results:
            raise HTTPException(status_code=404, detail="Submit answers first")
        pdf_bytes = await asyncio.to_thread(generate_results_pdf, quiz_data, _results[quiz_id])
        filename = f"quiz_{quiz_id}_results.pdf"
    elif mode == "answers":
        pdf_bytes = await asyncio.to_thread(generate_quiz_pdf, quiz_data, include_answers=True)
        filename = f"quiz_{quiz_id}_answers.pdf"
    else:
        pdf_bytes = await asyncio.to_thread(generate_quiz_pdf, quiz_data, include_answers=False)
        filename = f"quiz_{quiz_id}.pdf"

    return Response(content=pdf_bytes, media_type="application/pdf",
                    headers={"Content-Disposition": f'attachment; filename="{filename}"'})