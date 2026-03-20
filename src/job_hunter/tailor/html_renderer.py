from __future__ import annotations

import hashlib
import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader, BaseLoader

logger = logging.getLogger(__name__)

# Fallback inline template used when config/resume_template.html is not found
_FALLBACK_TEMPLATE = """\
<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<title>{{ name }} — Resume</title>
<style>
@page { size: letter; margin: 1in; }
body { font-family: "Helvetica Neue", Helvetica, Arial, sans-serif; font-size: 11pt; line-height: 1.4; color: #222; }
h1 { font-size: 18pt; margin: 0 0 4pt; }
h2 { font-size: 13pt; border-bottom: 1px solid #999; padding-bottom: 2pt; margin: 12pt 0 6pt; }
ul { margin: 4pt 0; padding-left: 18pt; }
li { margin-bottom: 2pt; }
.contact { font-size: 9pt; color: #555; margin-bottom: 10pt; }
</style>
</head>
<body>
<h1>{{ name }}</h1>
{% for section in sections %}
<h2>{{ section.heading }}</h2>
{% if section.bullets %}
<ul>
{% for item in section.bullets %}
<li>{{ item }}</li>
{% endfor %}
</ul>
{% endif %}
{% if section.text %}
<p>{{ section.text }}</p>
{% endif %}
{% endfor %}
</body>
</html>
"""


def render_html_resume(name: str, sections: list[dict]) -> str:
    """Render resume data to HTML using Jinja2.

    Args:
        name: Candidate name.
        sections: List of dicts with 'heading' and either 'items' (list[str]) or 'text' (str).

    Returns:
        Rendered HTML string.
    """
    # Try to load the external template first
    template_dir = Path(__file__).resolve().parents[3] / "config"
    template_file = template_dir / "resume_template.html"

    if template_file.exists():
        env = Environment(loader=FileSystemLoader(str(template_dir)), autoescape=True)
        template = env.get_template("resume_template.html")
    else:
        env = Environment(loader=BaseLoader(), autoescape=True)
        template = env.from_string(_FALLBACK_TEMPLATE)

    return template.render(name=name, sections=sections)


def render_html_to_pdf(html_content: str, output_dir: Path, job_url: str) -> Path | None:
    """Render HTML string to PDF using weasyprint.

    Args:
        html_content: Full HTML document string.
        output_dir: Directory to write the PDF into.
        job_url: Job URL used to generate a unique filename.

    Returns:
        Path to generated PDF, or None on failure.
    """
    try:
        from weasyprint import HTML  # lazy import — optional dep
    except ImportError:
        logger.error("weasyprint is not installed. pip install job-hunter[pdf]")
        return None

    output_dir.mkdir(parents=True, exist_ok=True)
    url_hash = hashlib.md5(job_url.encode()).hexdigest()[:12]
    pdf_path = output_dir / f"{url_hash}_resume.pdf"

    try:
        HTML(string=html_content).write_pdf(str(pdf_path))
        logger.info(f"Generated HTML-based PDF: {pdf_path}")
        return pdf_path
    except Exception as exc:
        logger.error(f"HTML-to-PDF rendering failed: {exc}")
        return None


def render_to_pdf(
    preamble: str,
    tailored_body: str,
    output_dir: Path,
    job_url: str,
) -> Path | None:
    """Fallback entry-point called from renderer.py when no LaTeX compiler is found.

    We ignore the LaTeX preamble/body and instead produce a minimal HTML resume
    by extracting plain text from the LaTeX body.
    """
    # Simple extraction: strip common LaTeX commands, keep text
    import re

    text = tailored_body
    # Remove LaTeX commands but keep their arguments
    text = re.sub(r"\\(?:textbf|textit|emph|underline)\{([^}]*)\}", r"\1", text)
    text = re.sub(r"\\(?:section|subsection)\*?\{([^}]*)\}", r"\n## \1\n", text)
    text = re.sub(r"\\item\s*", "- ", text)
    text = re.sub(r"\\[a-zA-Z]+\*?(?:\[[^\]]*\])?\{[^}]*\}", "", text)
    text = re.sub(r"\\[a-zA-Z]+\*?", "", text)
    text = re.sub(r"[{}]", "", text)

    # Build sections from ## markers
    sections: list[dict] = []
    current_heading = "Resume"
    current_items: list[str] = []

    for line in text.split("\n"):
        line = line.strip()
        if line.startswith("## "):
            if current_items:
                sections.append({"heading": current_heading, "bullets": current_items})
                current_items = []
            current_heading = line[3:].strip()
        elif line.startswith("- "):
            current_items.append(line[2:].strip())
        elif line:
            current_items.append(line)

    if current_items:
        sections.append({"heading": current_heading, "bullets": current_items})

    html = render_html_resume("Candidate", sections)
    return render_html_to_pdf(html, output_dir, job_url)
