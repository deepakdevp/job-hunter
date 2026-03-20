from __future__ import annotations

import hashlib
import logging
import shutil
import subprocess
import tempfile
from pathlib import Path

logger = logging.getLogger(__name__)


def render_latex_to_pdf(
    preamble: str,
    tailored_body: str,
    output_dir: Path,
    job_url: str,
) -> Path | None:
    """Render tailored LaTeX to PDF using pdflatex or tectonic.

    Returns path to generated PDF, or None on failure.
    """
    output_dir.mkdir(parents=True, exist_ok=True)

    # Generate filename from job URL hash
    url_hash = hashlib.md5(job_url.encode()).hexdigest()[:12]
    pdf_name = f"{url_hash}_resume.pdf"
    pdf_path = output_dir / pdf_name

    # Combine preamble + tailored body
    full_latex = f"{preamble}\n{tailored_body}"

    # Write to temp directory and compile
    with tempfile.TemporaryDirectory() as tmp_dir:
        tex_path = Path(tmp_dir) / "resume.tex"
        tex_path.write_text(full_latex, encoding="utf-8")

        # Try pdflatex first, then tectonic
        compiler = _find_compiler()
        if not compiler:
            try:
                from job_hunter.tailor.html_renderer import render_to_pdf as html_render

                logger.info("No LaTeX compiler found — falling back to HTML renderer.")
                return html_render(preamble, tailored_body, output_dir, job_url)
            except ImportError:
                logger.error(
                    "No renderer available. Install pdflatex or pip install job-hunter[pdf]"
                )
                return None

        success = _compile_latex(compiler, tex_path, tmp_dir)
        if not success:
            # pdflatex sometimes needs two passes
            if compiler == "pdflatex":
                success = _compile_latex(compiler, tex_path, tmp_dir)

        if not success:
            logger.error(f"LaTeX compilation failed for {job_url}")
            return None

        # Copy PDF to output directory
        compiled_pdf = Path(tmp_dir) / "resume.pdf"
        if compiled_pdf.exists():
            shutil.copy2(compiled_pdf, pdf_path)
            logger.info(f"Generated PDF: {pdf_path}")
            return pdf_path
        else:
            logger.error("Compiled PDF not found after compilation")
            return None


def _find_compiler() -> str | None:
    """Find available LaTeX compiler."""
    for cmd in ["pdflatex", "tectonic", "xelatex", "lualatex"]:
        if shutil.which(cmd):
            return cmd
    return None


def _compile_latex(compiler: str, tex_path: Path, work_dir: str) -> bool:
    """Run LaTeX compiler and return success status."""
    if compiler == "tectonic":
        cmd = [compiler, str(tex_path)]
    else:
        cmd = [
            compiler,
            "-interaction=nonstopmode",
            "-output-directory",
            work_dir,
            str(tex_path),
        ]

    try:
        result = subprocess.run(
            cmd,
            cwd=work_dir,
            capture_output=True,
            text=True,
            timeout=60,
        )
        if result.returncode != 0:
            logger.debug(f"LaTeX compilation stderr: {result.stderr[:500]}")
            logger.debug(f"LaTeX compilation stdout: {result.stdout[-500:]}")
            return False
        return True
    except subprocess.TimeoutExpired:
        logger.warning("LaTeX compilation timed out")
        return False
    except FileNotFoundError:
        logger.warning(f"Compiler '{compiler}' not found")
        return False
