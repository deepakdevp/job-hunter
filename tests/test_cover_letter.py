import pytest
from unittest.mock import AsyncMock
from job_hunter.database import Job
from job_hunter.tailor.cover_letter import (
    generate_cover_letter,
    validate_cover_letter,
    _clean_response,
)
from job_hunter.tailor.cover_letter_renderer import (
    _escape_latex,
    _text_to_latex_paragraphs,
    render_cover_letter,
)
from job_hunter.tailor.validator import ValidationMode


PROFILE = {
    "name": "Jane Doe",
    "email": "deepak@example.com",
    "phone": "+81-123-4567",
    "target_roles": ["Software Engineer", "Full Stack Developer"],
    "skills": ["Python", "React", "Django", "AWS"],
    "experience": [
        {
            "company": "Acme Corp",
            "title": "Full Stack Developer",
            "highlights": [
                "Built REST APIs serving 10K+ daily requests",
                "Migrated frontend to React",
            ],
        },
    ],
}


def _make_job(**kwargs) -> Job:
    defaults = dict(
        url="https://example.com/1",
        title="Python Developer",
        company="TestCo",
        location="Tokyo",
        source="indeed",
        description="Looking for a Python developer with Django experience to join our platform team.",
        tech_stack="Python, Django, PostgreSQL",
    )
    defaults.update(kwargs)
    return Job(**defaults)


GOOD_COVER_LETTER = """Your platform team's Python and Django stack at TestCo caught my attention — it's essentially what I've been building with for the past two years at Acme Corp, where I built REST APIs handling 10K+ daily requests.

What makes this role interesting is the focus on the platform layer. At Acme Corp, I migrated a legacy jQuery frontend to React while keeping the Django backend stable under load. That experience of working across the full stack while shipping to production daily is something I'd bring to your team from day one.

I'm based in Tokyo and ready to contribute. Happy to chat about how my experience maps to what you're building."""


FILLER_COVER_LETTER = """I am passionate about this role and have extensive experience. I spearheaded robust solutions at TestCo leveraging cutting-edge technology."""


FORMAL_COVER_LETTER = """I am writing to apply for the position of Python Developer at TestCo. Please accept this letter as my formal application."""


# --- validate_cover_letter ---


def test_validate_good_cover_letter():
    result = validate_cover_letter(GOOD_COVER_LETTER, "TestCo", ValidationMode.STRICT)
    assert result.passed is True


def test_validate_filler_cover_letter():
    result = validate_cover_letter(FILLER_COVER_LETTER, "TestCo", ValidationMode.STRICT)
    assert result.passed is False
    assert any(i.category == "filler" for i in result.errors)


def test_validate_missing_company():
    text = "Great role. I'd love to join the team. My Python skills are strong."
    result = validate_cover_letter(text, "TestCo", ValidationMode.STRICT)
    assert result.passed is False
    assert any("company" in i.message.lower() for i in result.errors)


def test_validate_formal_opener_strict():
    result = validate_cover_letter(FORMAL_COVER_LETTER, "TestCo", ValidationMode.STRICT)
    assert result.passed is False
    assert any("formal opener" in i.message.lower() for i in result.errors)


def test_validate_word_count_strict():
    long_text = "TestCo is great. " * 100  # ~300 words
    result = validate_cover_letter(long_text, "TestCo", ValidationMode.STRICT)
    assert any("too long" in i.message.lower() for i in result.issues)


def test_validate_lenient_passes_filler():
    result = validate_cover_letter(FILLER_COVER_LETTER, "TestCo", ValidationMode.LENIENT)
    filler_errors = [i for i in result.errors if i.category == "filler"]
    assert len(filler_errors) == 0


# --- _clean_response ---


def test_clean_response_strips_salutation():
    text = "Dear Hiring Manager,\n\nActual content here."
    result = _clean_response(text)
    assert "Dear" not in result
    assert "Actual content" in result


def test_clean_response_strips_closing():
    text = "Great content.\n\nSincerely,\nJane"
    result = _clean_response(text)
    assert "Sincerely" not in result
    assert "Great content" in result


def test_clean_response_strips_code_fences():
    text = "```\nContent here.\n```"
    result = _clean_response(text)
    assert "```" not in result
    assert "Content" in result


# --- generate_cover_letter ---


@pytest.mark.asyncio
async def test_generate_cover_letter_success():
    job = _make_job()
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = GOOD_COVER_LETTER
    result = await generate_cover_letter(job, PROFILE, mock_llm, ValidationMode.STRICT)
    assert result is not None
    assert "TestCo" in result
    mock_llm.generate.assert_called_once()


@pytest.mark.asyncio
async def test_generate_cover_letter_retries_on_filler():
    job = _make_job()
    mock_llm = AsyncMock()
    mock_llm.generate.side_effect = [FILLER_COVER_LETTER, GOOD_COVER_LETTER]
    result = await generate_cover_letter(job, PROFILE, mock_llm, ValidationMode.STRICT)
    assert result is not None
    assert mock_llm.generate.call_count == 2


@pytest.mark.asyncio
async def test_generate_cover_letter_fails_after_retries():
    job = _make_job()
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = FILLER_COVER_LETTER
    result = await generate_cover_letter(job, PROFILE, mock_llm, ValidationMode.STRICT)
    assert result is None
    assert mock_llm.generate.call_count == 3


@pytest.mark.asyncio
async def test_generate_cover_letter_llm_error():
    job = _make_job()
    mock_llm = AsyncMock()
    mock_llm.generate.side_effect = Exception("API error")
    result = await generate_cover_letter(job, PROFILE, mock_llm, ValidationMode.STRICT)
    assert result is None


# --- Renderer helpers ---


def test_escape_latex():
    assert _escape_latex("AT&T costs $50") == r"AT\&T costs \$50"
    assert _escape_latex("100%") == r"100\%"
    assert _escape_latex("C#") == r"C\#"


def test_text_to_latex_paragraphs():
    text = "First paragraph.\n\nSecond paragraph with $pecial chars."
    result = _text_to_latex_paragraphs(text)
    assert r"\$pecial" in result
    assert "First paragraph" in result


def test_render_cover_letter_saves_txt(tmp_path):
    pdf_path, txt_path = render_cover_letter(
        GOOD_COVER_LETTER,
        PROFILE,
        "Python Developer",
        "TestCo",
        tmp_path,
        "https://example.com/1",
    )
    assert txt_path is not None
    assert txt_path.exists()
    content = txt_path.read_text()
    assert "TestCo" in content
