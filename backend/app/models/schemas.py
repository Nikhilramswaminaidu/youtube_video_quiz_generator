"""Data models for the quiz application.

Internal models use @dataclass (for service layer).
API models use Pydantic BaseModel (for FastAPI request/response validation).
"""

from dataclasses import dataclass, field
from typing import Optional

from pydantic import BaseModel, Field


# ─── Internal Dataclasses (service layer) ─────────────────────────────────


@dataclass
class QuizQuestion:
    """A single quiz question with multiple-choice options."""

    question: str
    options: list[str]
    correct_index: int  # 0-based index into options
    explanation: str

    def to_dict(self) -> dict:
        return {
            "question": self.question,
            "options": self.options,
            "correct_index": self.correct_index,
            "explanation": self.explanation,
        }


@dataclass
class Quiz:
    """A complete quiz generated from a video."""

    title: str
    video_id: str
    questions: list[QuizQuestion] = field(default_factory=list)
    language: str = "en"  # Language code the quiz was generated in

    def to_dict(self) -> dict:
        return {
            "title": self.title,
            "video_id": self.video_id,
            "questions": [q.to_dict() for q in self.questions],
            "language": self.language,
        }


@dataclass
class QuizResult:
    """Result of a student submitting quiz answers."""

    quiz_id: str
    answers: list[int]  # List of selected option indices
    score: int
    total: int
    details: list[dict] = field(default_factory=list)  # Per-question results

    @property
    def percentage(self) -> float:
        return (self.score / self.total * 100) if self.total > 0 else 0.0

    def to_dict(self) -> dict:
        return {
            "quiz_id": self.quiz_id,
            "score": self.score,
            "total": self.total,
            "percentage": round(self.percentage, 1),
            "details": self.details,
        }


@dataclass
class TranscriptResult:
    """Result of fetching a video transcript."""

    video_id: str
    text: str
    language: Optional[str] = None
    is_auto_generated: bool = False

    @property
    def char_count(self) -> int:
        return len(self.text)

    @property
    def estimated_tokens(self) -> int:
        """Rough estimate: ~4 chars per token for English."""
        return len(self.text) // 4


# ─── Pydantic Models (API request/response) ──────────────────────────────


class GenerateQuizRequest(BaseModel):
    """Request body for POST /api/quiz/generate."""

    youtube_url: str = Field(..., description="YouTube video URL")
    num_questions: int = Field(default=10, ge=1, le=30, description="Number of questions (1-30)")
    difficulty: str = Field(default="moderate", description="Difficulty: easy, moderate, or hard")


class QuestionResponse(BaseModel):
    """A single question in the quiz response."""

    id: int = Field(..., description="Question index (0-based)")
    question: str
    options: list[str]
    correct_index: int = Field(..., description="0-based index of the correct option")
    explanation: str


class QuizResponse(BaseModel):
    """Response for a generated quiz."""

    id: str = Field(..., description="Quiz ID (same as video ID)")
    title: str
    video_id: str
    language: str
    questions: list[QuestionResponse]


class SubmitQuizRequest(BaseModel):
    """Request body for POST /api/quiz/submit."""

    quiz_id: str = Field(..., description="Quiz ID (video ID)")
    answers: list[int] = Field(..., description="List of selected option indices (0-based)")


class QuestionResult(BaseModel):
    """Result for a single question after submission."""

    question_id: int
    question: str
    selected: int
    correct: int
    is_correct: bool
    selected_option: str
    correct_option: str
    explanation: str


class SubmitQuizResponse(BaseModel):
    """Response for a submitted quiz."""

    quiz_id: str
    score: int
    total: int
    percentage: float
    details: list[QuestionResult]


class LanguageInfo(BaseModel):
    """Available caption language for a video."""

    language_code: str
    language: str
    is_generated: bool
    is_translatable: bool = False
    translation_languages: list[str] = Field(default_factory=list)


class LanguagesResponse(BaseModel):
    """Response for GET /api/video/{video_id}/languages."""

    video_id: str
    languages: list[LanguageInfo]


class ErrorResponse(BaseModel):
    """Standard error response."""

    error: str
    detail: Optional[str] = None