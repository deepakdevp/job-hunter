"""Tests that core modules import without optional dependencies."""


def test_core_imports_without_optional_deps():
    """Core modules should import without optional deps."""


def test_llm_base_imports():
    """LLM base module should import without any provider SDK."""


def test_discover_dedup_imports():
    """Dedup module should import without jobspy."""


def test_tailor_renderer_imports():
    """Renderer module should import without weasyprint or LaTeX."""


def test_apply_session_imports():
    """Session module should import without playwright."""
