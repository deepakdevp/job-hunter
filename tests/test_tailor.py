import json
import pytest
from unittest.mock import AsyncMock
from job_hunter.database import Job
from job_hunter.tailor.tailor import tailor_resume, _clean_llm_response, _extract_companies_from_profile
from job_hunter.tailor.parser import parse_latex_resume
from job_hunter.tailor.validator import ValidationMode


SAMPLE_LATEX = r"""
\documentclass{article}
\begin{document}
\section{Experience}
\textbf{Full Stack Developer} at Medikabazaar
\begin{itemize}
\item Built REST APIs with Django
\item Migrated frontend to React
\end{itemize}
\section{Skills}
Python, React, Django
\end{document}
"""

TAILORED_RESPONSE = r"""
\begin{document}
\section{Experience}
\textbf{Full Stack Developer} at Medikabazaar
\begin{itemize}
\item Built REST APIs with Django serving 10K+ daily requests
\item Migrated frontend to React, improving performance by 40\%
\end{itemize}
\section{Skills}
Python, React, Django, PostgreSQL
\end{document}
"""

PROFILE = {
    "target_roles": ["Software Engineer", "Full Stack Developer"],
    "skills": ["Python", "React", "Django"],
    "experience": [
        {"company": "Medikabazaar", "title": "Full Stack Developer"},
        {"company": "DrishteAI", "title": "AI Engineer"},
    ],
    "education": [
        {"institution": "Bennett University"},
    ],
}


def _make_job(**kwargs) -> Job:
    defaults = dict(
        url="https://example.com/1", title="Python Developer",
        company="TestCo", location="Tokyo", source="indeed",
        description="Looking for a Python developer with Django and React experience.",
        tech_stack="Python, Django, React",
    )
    defaults.update(kwargs)
    return Job(**defaults)


# --- _clean_llm_response ---

def test_clean_llm_response_extracts_document():
    response = r"Some preamble\n\begin{document}\nContent\n\end{document}\nExtra"
    result = _clean_llm_response(response)
    assert "\\begin{document}" in result
    assert "\\end{document}" in result


def test_clean_llm_response_strips_code_fences():
    response = "```latex\n\\begin{document}\nContent\n\\end{document}\n```"
    result = _clean_llm_response(response)
    assert "```" not in result


def test_clean_llm_response_plain():
    response = "Just plain text without document environment"
    result = _clean_llm_response(response)
    assert result == "Just plain text without document environment"


# --- _extract_companies_from_profile ---

def test_extract_companies_from_profile():
    companies = _extract_companies_from_profile(PROFILE)
    assert "Medikabazaar" in companies
    assert "DrishteAI" in companies
    assert "Bennett University" in companies


def test_extract_companies_empty_profile():
    companies = _extract_companies_from_profile({})
    assert companies == []


# --- tailor_resume ---

@pytest.mark.asyncio
async def test_tailor_resume_success():
    job = _make_job()
    resume = parse_latex_resume(SAMPLE_LATEX)
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = TAILORED_RESPONSE

    result = await tailor_resume(job, resume, PROFILE, mock_llm, mode=ValidationMode.STRICT)
    assert result is not None
    assert "\\begin{document}" in result
    assert "Medikabazaar" in result
    mock_llm.generate.assert_called_once()


@pytest.mark.asyncio
async def test_tailor_resume_retries_on_filler():
    job = _make_job()
    resume = parse_latex_resume(SAMPLE_LATEX)
    mock_llm = AsyncMock()

    # First call returns filler, second call is clean
    filler_response = r"\begin{document}I am passionate about this role at Medikabazaar.\end{document}"
    mock_llm.generate.side_effect = [filler_response, TAILORED_RESPONSE]

    result = await tailor_resume(job, resume, PROFILE, mock_llm, mode=ValidationMode.STRICT)
    assert result is not None
    assert mock_llm.generate.call_count == 2


@pytest.mark.asyncio
async def test_tailor_resume_returns_none_after_max_retries():
    job = _make_job()
    resume = parse_latex_resume(SAMPLE_LATEX)
    mock_llm = AsyncMock()

    # All calls return filler
    filler = r"\begin{document}I am passionate and spearheaded robust solutions.\end{document}"
    mock_llm.generate.return_value = filler

    result = await tailor_resume(job, resume, PROFILE, mock_llm, mode=ValidationMode.STRICT)
    assert result is None
    assert mock_llm.generate.call_count == 3  # initial + 2 retries


@pytest.mark.asyncio
async def test_tailor_resume_lenient_passes_filler():
    job = _make_job()
    resume = parse_latex_resume(SAMPLE_LATEX)
    mock_llm = AsyncMock()

    # Filler response — passes in lenient mode
    filler = r"\begin{document}I am passionate about working at Medikabazaar.\end{document}"
    mock_llm.generate.return_value = filler

    result = await tailor_resume(job, resume, PROFILE, mock_llm, mode=ValidationMode.LENIENT)
    assert result is not None
    mock_llm.generate.assert_called_once()
