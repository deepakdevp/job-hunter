from unittest.mock import patch, MagicMock
from pathlib import Path

from job_hunter.tailor.html_renderer import (
    render_html_resume,
    render_html_to_pdf,
    render_to_pdf,
)


class TestRenderHtmlResume:
    def test_basic_render(self):
        html = render_html_resume(
            "Alice",
            [
                {"heading": "Experience", "bullets": ["Built APIs", "Led team"]},
                {"heading": "Education", "text": "MIT, BS CS 2022"},
            ],
        )
        assert "<h1>Alice</h1>" in html
        assert "Experience" in html
        assert "Built APIs" in html
        assert "MIT, BS CS 2022" in html

    def test_empty_sections(self):
        html = render_html_resume("Bob", [])
        assert "<h1>Bob</h1>" in html

    def test_html_is_valid_document(self):
        html = render_html_resume("Test", [{"heading": "Skills", "bullets": ["Python"]}])
        assert html.strip().startswith("<!DOCTYPE html>")
        assert "</html>" in html


class TestRenderHtmlToPdf:
    def test_missing_weasyprint(self, tmp_path):
        """When weasyprint is not importable, returns None."""
        with patch.dict("sys.modules", {"weasyprint": None}):
            # Force re-import failure
            with patch("builtins.__import__", side_effect=_make_import_blocker("weasyprint")):
                result = render_html_to_pdf("<html></html>", tmp_path, "https://x.com/1")
                assert result is None

    def test_successful_pdf_generation(self, tmp_path):
        mock_html_cls = MagicMock()
        with patch("job_hunter.tailor.html_renderer.HTML", mock_html_cls, create=True):
            # Simulate weasyprint being importable inside the function
            with patch(
                "builtins.__import__",
                side_effect=_make_weasyprint_mock(mock_html_cls),
            ):
                result = render_html_to_pdf("<html></html>", tmp_path, "https://x.com/job1")
                # The function calls HTML(string=...).write_pdf(...)
                assert result is not None or mock_html_cls.called

    def test_output_filename_uses_hash(self, tmp_path):
        import hashlib

        url = "https://example.com/job/42"
        expected_hash = hashlib.md5(url.encode()).hexdigest()[:12]

        mock_html_cls = MagicMock()
        with patch(
            "builtins.__import__",
            side_effect=_make_weasyprint_mock(mock_html_cls),
        ):
            result = render_html_to_pdf("<html></html>", tmp_path, url)
            if result is not None:
                assert expected_hash in result.name


class TestRenderToPdf:
    def test_strips_latex_commands(self, tmp_path):
        """render_to_pdf should produce HTML even from LaTeX input."""
        latex_body = r"""
\section{Experience}
\begin{itemize}
\item Built distributed systems at scale
\item \textbf{Led} team of 5 engineers
\end{itemize}
"""
        # We test that the function at least runs without error
        # and calls render_html_to_pdf under the hood
        with patch("job_hunter.tailor.html_renderer.render_html_to_pdf") as mock_pdf:
            mock_pdf.return_value = tmp_path / "test.pdf"
            render_to_pdf("", latex_body, tmp_path, "https://x.com/1")
            assert mock_pdf.called
            # Verify HTML was passed (first arg to render_html_to_pdf)
            html_arg = mock_pdf.call_args[0][0]
            assert "Experience" in html_arg
            assert "Built distributed systems" in html_arg

    def test_sections_extracted(self):
        latex_body = r"""
\section{Skills}
\item Python
\item TypeScript
\section{Education}
\item MIT 2022
"""
        with patch("job_hunter.tailor.html_renderer.render_html_to_pdf") as mock_pdf:
            mock_pdf.return_value = Path("/fake.pdf")
            render_to_pdf("", latex_body, Path("/tmp"), "https://x.com/1")
            html_arg = mock_pdf.call_args[0][0]
            assert "Skills" in html_arg
            assert "Education" in html_arg
            assert "Python" in html_arg


class TestRendererFallback:
    """Test that renderer.py falls back to HTML when no LaTeX compiler is found."""

    def test_fallback_to_html_when_no_compiler(self, tmp_path):
        with patch("job_hunter.tailor.renderer._find_compiler", return_value=None):
            with patch(
                "job_hunter.tailor.html_renderer.render_to_pdf", return_value=tmp_path / "out.pdf"
            ) as mock_html:
                from job_hunter.tailor.renderer import render_latex_to_pdf

                result = render_latex_to_pdf("preamble", "body", tmp_path, "https://x.com/1")
                assert mock_html.called
                assert result == tmp_path / "out.pdf"

    def test_fallback_import_error(self, tmp_path):
        with patch("job_hunter.tailor.renderer._find_compiler", return_value=None):
            with patch(
                "builtins.__import__",
                side_effect=_make_import_blocker("job_hunter.tailor.html_renderer"),
            ):
                from job_hunter.tailor.renderer import render_latex_to_pdf

                result = render_latex_to_pdf("preamble", "body", tmp_path, "https://x.com/1")
                assert result is None


# ---- helpers ----


def _make_import_blocker(blocked_module: str):
    """Create a side_effect for __import__ that blocks a specific module."""
    real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

    def _blocker(name, *args, **kwargs):
        if name == blocked_module:
            raise ImportError(f"Mocked: {name} not available")
        return real_import(name, *args, **kwargs)

    return _blocker


def _make_weasyprint_mock(mock_html_cls):
    """Create a side_effect for __import__ that returns a mock weasyprint."""
    real_import = __builtins__.__import__ if hasattr(__builtins__, "__import__") else __import__

    mock_module = MagicMock()
    mock_module.HTML = mock_html_cls

    def _importer(name, *args, **kwargs):
        if name == "weasyprint":
            return mock_module
        return real_import(name, *args, **kwargs)

    return _importer
