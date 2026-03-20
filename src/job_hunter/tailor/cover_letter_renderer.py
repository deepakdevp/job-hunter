from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)

_COVER_LETTER_TEMPLATE = r"""
\documentclass[11pt]{{letter}}
\usepackage[margin=1in]{{geometry}}
\usepackage{{parskip}}
\usepackage[T1]{{fontenc}}
\usepackage{{lmodern}}

\begin{{document}}

\begin{{center}}
\textbf{{\large {name}}} \\
{email} \quad | \quad {phone} \quad | \quad {location}
\end{{center}}

\vspace{{0.5em}}

\textbf{{{job_title}}} --- {company} \\
{date}

\vspace{{0.5em}}

{body_latex}

\vspace{{1em}}

{name}

\end{{document}}
"""


def _escape_latex(text: str) -> str:
    """Escape special LaTeX characters in text."""
    replacements = {
        "&": r"\&",
        "%": r"\%",
        "$": r"\$",
        "#": r"\#",
        "_": r"\_",
        "~": r"\textasciitilde{}",
        "^": r"\textasciicircum{}",
    }
    for char, replacement in replacements.items():
        text = text.replace(char, replacement)
    return text


def _text_to_latex_paragraphs(text: str) -> str:
    """Convert plain text paragraphs to LaTeX."""
    paragraphs = text.strip().split("\n\n")
    escaped = [_escape_latex(p.strip().replace("\n", " ")) for p in paragraphs if p.strip()]
    return "\n\n".join(escaped)


def render_cover_letter(
    text: str,
    profile: dict,
    job_title: str,
    company: str,
    output_dir: Path,
    job_url: str,
) -> tuple[Path | None, Path | None]:
    """Render cover letter to both LaTeX PDF and plain text.

    Returns (pdf_path, txt_path).
    """
    output_dir.mkdir(parents=True, exist_ok=True)
    url_hash = hashlib.md5(job_url.encode()).hexdigest()[:12]

    # Save plain text
    txt_path = output_dir / f"{url_hash}_cover_letter.txt"
    txt_path.write_text(text, encoding="utf-8")
    logger.info(f"Saved cover letter text: {txt_path}")

    # Render LaTeX PDF
    name = profile.get("name", "Candidate")
    email = profile.get("email", "")
    phone = profile.get("phone", "")
    location = (
        profile.get("preferred_locations", [""])[0] if profile.get("preferred_locations") else ""
    )

    from datetime import date

    date_str = date.today().strftime("%B %d, %Y")

    body_latex = _text_to_latex_paragraphs(text)

    latex_source = _COVER_LETTER_TEMPLATE.format(
        name=_escape_latex(name),
        email=_escape_latex(email),
        phone=_escape_latex(phone),
        location=_escape_latex(location),
        job_title=_escape_latex(job_title),
        company=_escape_latex(company),
        date=date_str,
        body_latex=body_latex,
    )

    pdf_path = _compile_cover_letter(latex_source, output_dir, url_hash)

    return pdf_path, txt_path


def _compile_cover_letter(latex_source: str, output_dir: Path, url_hash: str) -> Path | None:
    """Compile LaTeX cover letter to PDF."""
    pdf_name = f"{url_hash}_cover_letter.pdf"
    pdf_path = output_dir / pdf_name

    compiler = None
    for cmd in ["pdflatex", "tectonic", "xelatex", "lualatex"]:
        if shutil.which(cmd):
            compiler = cmd
            break

    if not compiler:
        logger.warning("No LaTeX compiler found, skipping PDF generation")
        return None

    with tempfile.TemporaryDirectory() as tmp_dir:
        tex_path = Path(tmp_dir) / "cover_letter.tex"
        tex_path.write_text(latex_source, encoding="utf-8")

        if compiler == "tectonic":
            cmd = [compiler, str(tex_path)]
        else:
            cmd = [
                compiler,
                "-interaction=nonstopmode",
                "-output-directory",
                tmp_dir,
                str(tex_path),
            ]

        try:
            result = subprocess.run(cmd, cwd=tmp_dir, capture_output=True, text=True, timeout=60)
            if result.returncode != 0:
                logger.debug(f"Cover letter LaTeX stderr: {result.stderr[:500]}")
                # Try second pass
                if compiler != "tectonic":
                    subprocess.run(cmd, cwd=tmp_dir, capture_output=True, text=True, timeout=60)
        except (subprocess.TimeoutExpired, FileNotFoundError) as e:
            logger.warning(f"Cover letter PDF compilation failed: {e}")
            return None

        compiled_pdf = Path(tmp_dir) / "cover_letter.pdf"
        if compiled_pdf.exists():
            shutil.copy2(compiled_pdf, pdf_path)
            logger.info(f"Generated cover letter PDF: {pdf_path}")
            return pdf_path

    logger.warning("Cover letter PDF not generated")
    return None
