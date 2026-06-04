"""PDF generation service for quizzes and results."""

import io
from fpdf import FPDF

from backend.app.models.schemas import Quiz, QuizResult


class QuizPDF(FPDF):
    """Custom PDF class for quiz documents."""

    def __init__(self):
        super().__init__()
        self.set_auto_page_break(auto=True, margin=20)

    def header(self):
        self.set_font("Helvetica", "B", 10)
        self.set_text_color(100, 100, 100)
        self.cell(0, 8, "YouTube Quiz Generator - UPSC Style", align="C", new_x="LMARGIN", new_y="NEXT")
        self.line(10, self.get_y(), 200, self.get_y())
        self.ln(4)

    def footer(self):
        self.set_y(-15)
        self.set_font("Helvetica", "I", 8)
        self.set_text_color(150, 150, 150)
        self.cell(0, 10, f"Page {self.page_no()}/{{nb}}", align="C")


def _safe_text(text: str) -> str:
    """Replace characters that fpdf2 can't handle with ASCII equivalents."""
    replacements = {
        "’": "'",   # Right single quote
        "‘": "'",   # Left single quote
        "“": '"',   # Left double quote
        "”": '"',   # Right double quote
        "–": "-",   # En dash
        "—": "--",  # Em dash
        "…": "...", # Ellipsis
        "•": "*",   # Bullet
        "✓": "v",   # Check mark
        "✗": "x",   # Cross mark
        "✚": "+",   # Heavy cross
        "●": "*",   # Black circle
        "○": "o",   # White circle
        " ": " ",   # Non-breaking space
        "→": "->",  # Right arrow
        "←": "<-",  # Left arrow
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)

    # Fallback: replace any remaining non-latin1 chars
    result = ""
    for ch in text:
        try:
            ch.encode("latin-1")
            result += ch
        except UnicodeEncodeError:
            result += "?"
    return result


def generate_quiz_pdf(quiz: dict, include_answers: bool = False) -> bytes:
    """Generate a PDF for a quiz.

    Args:
        quiz: Quiz dict (from Quiz.to_dict()).
        include_answers: If True, includes correct answers and explanations.
                        If False, produces a blank quiz for the student to fill.

    Returns:
        PDF file content as bytes.
    """
    pdf = QuizPDF()
    pdf.alias_nb_pages()
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(30, 30, 30)
    pdf.multi_cell(0, 10, _safe_text(quiz["title"]))
    pdf.ln(2)

    # Meta info
    pdf.set_font("Helvetica", "", 9)
    pdf.set_text_color(100, 100, 100)
    pdf.cell(0, 6, f"Video: https://youtube.com/watch?v={quiz['video_id']}", new_x="LMARGIN", new_y="NEXT")
    pdf.cell(0, 6, f"Questions: {len(quiz['questions'])}  |  Language: {quiz.get('language', 'en').upper()}", new_x="LMARGIN", new_y="NEXT")
    if include_answers:
        pdf.cell(0, 6, "ANSWER KEY INCLUDED", new_x="LMARGIN", new_y="NEXT")
    else:
        pdf.cell(0, 6, "BLANK QUIZ - Fill in your answers", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # Questions
    for i, q in enumerate(quiz["questions"], 1):
        # Check if we need a new page (rough estimate)
        if pdf.get_y() > 250:
            pdf.add_page()

        # Question number
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(99, 102, 241)  # Indigo
        pdf.cell(0, 7, f"Q{i}.", new_x="LMARGIN", new_y="NEXT")

        # Question text
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(30, 30, 30)
        pdf.multi_cell(0, 6, _safe_text(q["question"]))
        pdf.ln(2)

        # Options
        for j, opt in enumerate(q["options"]):
            letter = chr(65 + j)  # A, B, C, D

            if include_answers:
                is_correct = j == q["correct_index"]
                if is_correct:
                    pdf.set_font("Helvetica", "B", 10)
                    pdf.set_text_color(34, 197, 94)  # Green
                    pdf.cell(5, 6, "")  # indent
                    pdf.cell(0, 6, _safe_text(f"{letter}) {opt}  [CORRECT]"), new_x="LMARGIN", new_y="NEXT")
                else:
                    pdf.set_font("Helvetica", "", 10)
                    pdf.set_text_color(100, 100, 100)
                    pdf.cell(5, 6, "")
                    pdf.cell(0, 6, _safe_text(f"{letter}) {opt}"), new_x="LMARGIN", new_y="NEXT")
            else:
                pdf.set_font("Helvetica", "", 10)
                pdf.set_text_color(60, 60, 60)
                pdf.cell(5, 6, "")
                pdf.cell(0, 6, _safe_text(f"{letter}) {opt}"), new_x="LMARGIN", new_y="NEXT")

        # Explanation (only if answers included)
        if include_answers:
            pdf.ln(1)
            pdf.set_font("Helvetica", "I", 9)
            pdf.set_text_color(100, 100, 180)
            pdf.multi_cell(0, 5, _safe_text(f"Explanation: {q['explanation']}"))

        pdf.ln(4)

        # Separator line
        pdf.set_draw_color(220, 220, 220)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(4)

    # If no answers, add answer grid at the bottom
    if not include_answers:
        if pdf.get_y() > 220:
            pdf.add_page()
        pdf.ln(4)
        pdf.set_font("Helvetica", "B", 11)
        pdf.set_text_color(30, 30, 30)
        pdf.cell(0, 8, "Your Answers:", new_x="LMARGIN", new_y="NEXT")
        pdf.set_font("Helvetica", "", 10)
        pdf.set_text_color(100, 100, 100)

        # Grid: Q1: ___  Q2: ___ etc.
        col_width = 45
        for i in range(len(quiz["questions"])):
            if i > 0 and i % 4 == 0:
                pdf.ln(8)
            pdf.cell(col_width, 8, f"Q{i+1}: ______")
        pdf.ln(10)

    # Output
    buffer = io.BytesIO()
    pdf.output(buffer)
    return buffer.getvalue()


def generate_results_pdf(quiz: dict, result: dict) -> bytes:
    """Generate a PDF for quiz results with score and explanations.

    Args:
        quiz: Quiz dict (from Quiz.to_dict()).
        result: Result dict (from SubmitQuizResponse).

    Returns:
        PDF file content as bytes.
    """
    pdf = QuizPDF()
    pdf.alias_nb_pages()
    pdf.add_page()

    # Title
    pdf.set_font("Helvetica", "B", 16)
    pdf.set_text_color(30, 30, 30)
    pdf.multi_cell(0, 10, _safe_text(quiz["title"]))
    pdf.ln(2)

    # Score box
    pdf.set_fill_color(240, 240, 255)
    pdf.set_font("Helvetica", "B", 24)
    pdf.set_text_color(99, 102, 241)
    score_text = f"{result['score']}/{result['total']}"
    pdf.cell(0, 18, score_text, align="C", fill=True, new_x="LMARGIN", new_y="NEXT")

    pdf.set_font("Helvetica", "", 12)
    pdf.set_text_color(100, 100, 100)
    pct = result["percentage"]
    pdf.cell(0, 8, f"Score: {pct}%", align="C", new_x="LMARGIN", new_y="NEXT")

    # Badge text
    if pct >= 80:
        badge = "Great job!"
        pdf.set_text_color(34, 197, 94)
    elif pct >= 60:
        badge = "Good effort!"
        pdf.set_text_color(245, 158, 11)
    else:
        badge = "Keep studying!"
        pdf.set_text_color(239, 68, 68)

    pdf.set_font("Helvetica", "B", 12)
    pdf.cell(0, 10, badge, align="C", new_x="LMARGIN", new_y="NEXT")
    pdf.ln(6)

    # Per-question results
    for d in result["details"]:
        if pdf.get_y() > 250:
            pdf.add_page()

        q_idx = d["question_id"]
        q = quiz["questions"][q_idx]

        # Question header with icon
        pdf.set_font("Helvetica", "B", 11)
        if d["is_correct"]:
            pdf.set_text_color(34, 197, 94)  # Green
            icon = "[CORRECT]"
        else:
            pdf.set_text_color(239, 68, 68)  # Red
            icon = "[WRONG]"
        pdf.cell(0, 7, f"Q{q_idx + 1}. {icon}", new_x="LMARGIN", new_y="NEXT")

        # Question text
        pdf.set_font("Helvetica", "", 11)
        pdf.set_text_color(30, 30, 30)
        pdf.multi_cell(0, 6, _safe_text(q["question"]))
        pdf.ln(1)

        # Options with marking
        for j, opt in enumerate(q["options"]):
            letter = chr(65 + j)
            is_correct = j == d["correct"]
            was_selected = j == d["selected"]

            if is_correct:
                pdf.set_font("Helvetica", "B", 10)
                pdf.set_text_color(34, 197, 94)
                pdf.cell(5, 6, "")
                pdf.cell(0, 6, _safe_text(f"{letter}) {opt}  [CORRECT ANSWER]"), new_x="LMARGIN", new_y="NEXT")
            elif was_selected:
                pdf.set_font("Helvetica", "", 10)
                pdf.set_text_color(239, 68, 68)
                pdf.cell(5, 6, "")
                pdf.cell(0, 6, _safe_text(f"{letter}) {opt}  [YOUR ANSWER]"), new_x="LMARGIN", new_y="NEXT")
            else:
                pdf.set_font("Helvetica", "", 10)
                pdf.set_text_color(150, 150, 150)
                pdf.cell(5, 6, "")
                pdf.cell(0, 6, _safe_text(f"{letter}) {opt}"), new_x="LMARGIN", new_y="NEXT")

        # Explanation
        pdf.ln(1)
        pdf.set_font("Helvetica", "I", 9)
        pdf.set_text_color(100, 100, 180)
        pdf.multi_cell(0, 5, _safe_text(f"Explanation: {d['explanation']}"))

        pdf.ln(3)
        pdf.set_draw_color(220, 220, 220)
        pdf.line(10, pdf.get_y(), 200, pdf.get_y())
        pdf.ln(3)

    buffer = io.BytesIO()
    pdf.output(buffer)
    return buffer.getvalue()