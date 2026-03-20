from job_hunter.tailor.validator import (
    validate_resume,
    ValidationMode,
    _check_filler_words,
    _check_llm_leaks,
    _check_fabrication,
)


CLEAN_RESUME = """
Full Stack Developer at Medikabazaar
- Built REST APIs serving 10K+ daily requests using Django and PostgreSQL
- Migrated frontend to React, improving load time by 40%

AI Engineer at DrishteAI
- Developed computer vision pipeline processing 500+ images/hour
"""

FILLER_RESUME = """
I am a passionate developer who spearheaded robust solutions.
Leveraged cutting-edge technology to build synergy-driven platforms.
"""

LEAK_RESUME = """
Here is the corrected resume as requested:
Full Stack Developer at Medikabazaar
I hope this helps with your application.
"""


# --- Full validation ---


def test_validate_clean_resume_passes():
    result = validate_resume(CLEAN_RESUME, mode=ValidationMode.STRICT)
    assert result.passed is True
    assert result.error_count == 0


def test_validate_filler_strict_fails():
    result = validate_resume(FILLER_RESUME, mode=ValidationMode.STRICT)
    assert result.passed is False
    assert result.error_count > 0
    assert any(i.category == "filler" for i in result.errors)


def test_validate_filler_normal_warns():
    result = validate_resume(FILLER_RESUME, mode=ValidationMode.NORMAL)
    # Filler words are warnings in normal mode
    assert result.warning_count > 0
    # But leaks are still errors... this resume has no leaks
    filler_errors = [i for i in result.errors if i.category == "filler"]
    assert len(filler_errors) == 0


def test_validate_filler_lenient_ignored():
    result = validate_resume(FILLER_RESUME, mode=ValidationMode.LENIENT)
    filler_issues = [i for i in result.issues if i.category == "filler"]
    assert len(filler_issues) == 0


def test_validate_llm_leaks_always_error():
    for mode in ValidationMode:
        result = validate_resume(LEAK_RESUME, mode=mode)
        assert result.passed is False
        assert any(i.category == "leak" for i in result.errors)


# --- Filler word detection ---


def test_check_filler_words_finds_matches():
    issues = _check_filler_words("I am passionate about this role", ValidationMode.STRICT)
    assert len(issues) >= 1
    assert issues[0].severity == "error"


def test_check_filler_words_normal_mode_warns():
    issues = _check_filler_words("I am passionate about this role", ValidationMode.NORMAL)
    assert len(issues) >= 1
    assert issues[0].severity == "warning"


def test_check_filler_no_match():
    issues = _check_filler_words("Built REST APIs using Django", ValidationMode.STRICT)
    assert len(issues) == 0


# --- LLM leak detection ---


def test_check_llm_leaks_finds_phrases():
    issues = _check_llm_leaks("Here is the corrected version of your resume")
    assert len(issues) >= 1


def test_check_llm_leaks_clean_text():
    issues = _check_llm_leaks("Full Stack Developer - Built APIs with Django")
    assert len(issues) == 0


# --- Fabrication detection ---


def test_check_fabrication_no_issues():
    text = "Full Stack Developer at Medikabazaar\nAI Engineer at DrishteAI"
    issues = _check_fabrication(text, ["Medikabazaar", "DrishteAI"], [], [])
    assert len(issues) == 0


def test_check_fabrication_detects_fake_company():
    text = "Senior Engineer at FakeCompanyInc, then at Medikabazaar"
    issues = _check_fabrication(text, ["Medikabazaar", "DrishteAI"], [], [])
    fabrication_issues = [i for i in issues if i.category == "fabrication"]
    assert len(fabrication_issues) >= 1
    assert "FakeCompanyInc" in fabrication_issues[0].match


def test_check_fabrication_handles_partial_match():
    text = "Developer at Medikabazaar Pvt Ltd"
    issues = _check_fabrication(text, ["Medikabazaar"], [], [])
    assert len(issues) == 0  # Partial match should be fine


# --- Combined scenarios ---


def test_validate_with_fabrication():
    text = "Software Engineer at FakeStartup\nBuilt amazing things."
    result = validate_resume(
        text,
        source_companies=["Medikabazaar", "DrishteAI"],
        mode=ValidationMode.STRICT,
    )
    # Should flag fabrication
    fabrication = [i for i in result.errors if i.category == "fabrication"]
    assert len(fabrication) >= 1


def test_validate_empty_source_lists():
    result = validate_resume(CLEAN_RESUME, source_companies=[], mode=ValidationMode.STRICT)
    assert result.passed is True
