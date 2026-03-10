import pytest
from job_hunter.tailor.parser import parse_latex_resume, _strip_latex, _extract_items


SAMPLE_LATEX = r"""
\documentclass[letterpaper,11pt]{article}
\usepackage{fullpage}
\begin{document}

\textbf{Deepak Dev Panwar} \\
Software Engineer | Tokyo, Japan

\section{Experience}
\textbf{Full Stack Developer} at \textbf{Medikabazaar} \hfill 2023--2024
\begin{itemize}
\item Built REST APIs serving 10K+ daily requests using Django and PostgreSQL
\item Migrated legacy jQuery frontend to React, improving load time by 40\%
\item Implemented CI/CD pipeline with GitHub Actions reducing deploy time by 60\%
\end{itemize}

\textbf{AI Engineer} at \textbf{DrishteAI} \hfill 2022--2023
\begin{itemize}
\item Developed computer vision pipeline processing 500+ images/hour
\item Built real-time dashboard with React and WebSocket
\end{itemize}

\section{Education}
\textbf{B.Tech Computer Science} -- Bennett University \hfill 2019--2023

\section{Skills}
Python, JavaScript, TypeScript, React, Django, FastAPI, AWS, Docker, PostgreSQL

\end{document}
"""


def test_parse_latex_resume_finds_sections():
    result = parse_latex_resume(SAMPLE_LATEX)
    assert len(result.sections) >= 3
    section_names = [s.name for s in result.sections]
    assert "Experience" in section_names
    assert "Education" in section_names
    assert "Skills" in section_names


def test_parse_latex_resume_extracts_preamble():
    result = parse_latex_resume(SAMPLE_LATEX)
    assert "documentclass" in result.preamble


def test_parse_latex_resume_extracts_items():
    result = parse_latex_resume(SAMPLE_LATEX)
    exp = result.get_section("Experience")
    assert exp is not None
    assert len(exp.items) >= 4  # 3 from Medikabazaar + 2 from DrishteAI


def test_parse_latex_resume_to_plain_text():
    result = parse_latex_resume(SAMPLE_LATEX)
    plain = result.to_plain_text()
    assert "Experience" in plain
    assert "REST APIs" in plain
    assert "Bennett University" in plain


def test_parse_latex_resume_get_section():
    result = parse_latex_resume(SAMPLE_LATEX)
    assert result.get_section("experience") is not None  # case insensitive
    assert result.get_section("nonexistent") is None


def test_strip_latex_removes_commands():
    text = r"\textbf{Hello} \textit{world} \href{url}{link}"
    result = _strip_latex(text)
    assert "Hello" in result
    assert "world" in result
    assert "link" in result
    assert "\\textbf" not in result


def test_strip_latex_removes_comments():
    text = "Real content % this is a comment\nMore content"
    result = _strip_latex(text)
    assert "Real content" in result
    assert "comment" not in result


def test_extract_items():
    latex = r"""
    \begin{itemize}
    \item Built a REST API with Django
    \item Deployed to AWS using Docker containers
    \item Short
    \end{itemize}
    """
    items = _extract_items(latex)
    assert len(items) == 2  # "Short" is <= 5 chars, filtered
    assert "REST API" in items[0]
    assert "AWS" in items[1]


def test_parse_latex_resume_no_sections():
    plain = r"""
    \documentclass{article}
    \begin{document}
    Just some plain content without any sections.
    This is a minimal resume with no structure.
    \end{document}
    """
    result = parse_latex_resume(plain)
    assert len(result.sections) >= 1  # Falls back to single section
