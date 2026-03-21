"""Tests that core modules import without optional dependencies."""


def test_core_imports_without_optional_deps():
    """Core modules should import without optional deps."""
    import job_hunter.cli
    import job_hunter.config
    import job_hunter.database
    import job_hunter.export


def test_llm_base_imports():
    """LLM base module should import without any provider SDK."""
    from job_hunter.llm.base import LLMProvider, get_provider


def test_discover_dedup_imports():
    """Dedup module should import without jobspy."""
    from job_hunter.discover.dedup import dedup_jobs


def test_tailor_renderer_imports():
    """Renderer module should import without weasyprint or LaTeX."""
    import job_hunter.tailor.renderer


def test_apply_session_imports():
    """Session module should import without playwright."""
    from job_hunter.apply.session import SessionManager
