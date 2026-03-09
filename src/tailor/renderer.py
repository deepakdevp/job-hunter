"""Render tailored resume to PDF using Jinja2 + WeasyPrint."""

from __future__ import annotations

from pathlib import Path
from datetime import datetime

from jinja2 import Environment, FileSystemLoader, select_autoescape

ROOT = Path(__file__).parent.parent.parent
TEMPLATES_DIR = ROOT / "templates"
OUTPUT_DIR = ROOT / "output"


def _slug(text: str) -> str:
    import re
    return re.sub(r"[^a-z0-9]+", "-", text.lower()).strip("-")[:50]


def render_resume_pdf(
    tailored_profile: dict,
    job: dict,
    output_dir: Path | None = None,
) -> Path:
    """
    Render a tailored resume to PDF.
    Returns the path to the generated PDF.
    """
    from weasyprint import HTML, CSS

    output_dir = output_dir or (OUTPUT_DIR / "resumes")
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate filename
    company_slug = _slug(job.get("company", "company"))
    title_slug = _slug(job.get("title", "role"))
    date_str = datetime.now().strftime("%Y%m%d")
    pdf_path = output_dir / f"resume_{company_slug}_{title_slug}_{date_str}.pdf"

    # Render HTML via Jinja2
    env = Environment(
        loader=FileSystemLoader(str(TEMPLATES_DIR)),
        autoescape=select_autoescape(["html"]),
    )
    template = env.get_template("resume.html")
    html_content = template.render(
        profile=tailored_profile,
        job=job,
        generated_date=datetime.now().strftime("%B %d, %Y"),
    )

    # Convert to PDF
    HTML(string=html_content, base_url=str(TEMPLATES_DIR)).write_pdf(str(pdf_path))

    return pdf_path


def render_cover_letter_pdf(
    cover_letter_text: str,
    profile: dict,
    job: dict,
    output_dir: Path | None = None,
) -> Path:
    """Render a plain cover letter to PDF."""
    from weasyprint import HTML

    output_dir = output_dir or (OUTPUT_DIR / "cover_letters")
    output_dir.mkdir(parents=True, exist_ok=True)

    company_slug = _slug(job.get("company", "company"))
    title_slug = _slug(job.get("title", "role"))
    date_str = datetime.now().strftime("%Y%m%d")
    pdf_path = output_dir / f"cover_{company_slug}_{title_slug}_{date_str}.pdf"

    # Simple HTML template for cover letter
    html = f"""<!DOCTYPE html>
<html>
<head>
<meta charset="UTF-8">
<style>
  body {{ font-family: Arial, sans-serif; font-size: 11pt; line-height: 1.6;
         margin: 2.5cm; color: #222; }}
  .header {{ margin-bottom: 2em; }}
  .name {{ font-size: 16pt; font-weight: bold; }}
  .contact {{ font-size: 10pt; color: #555; }}
  .date {{ margin: 1.5em 0; }}
  .salutation {{ margin-bottom: 1em; }}
  p {{ margin: 0.8em 0; }}
</style>
</head>
<body>
  <div class="header">
    <div class="name">{profile.get('name', '')}</div>
    <div class="contact">{profile.get('email', '')} | {profile.get('phone', '')} | {profile.get('location', '')}</div>
  </div>
  <div class="date">{datetime.now().strftime('%B %d, %Y')}</div>
  <div class="salutation">Dear Hiring Manager,</div>
  {''.join(f'<p>{para.strip()}</p>' for para in cover_letter_text.split('\n\n') if para.strip())}
  <p>Sincerely,<br><strong>{profile.get('name', '')}</strong></p>
</body>
</html>"""

    HTML(string=html).write_pdf(str(pdf_path))
    return pdf_path
