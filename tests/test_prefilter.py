from job_hunter.database import Job
from job_hunter.score.prefilter import pre_filter_job, _title_matches_roles

TARGET_ROLES = [
    "Software Engineer",
    "Full Stack Developer",
    "Frontend Engineer",
    "Backend Engineer",
    "AI Engineer",
    "AI Agent Engineer",
]


def _make_job(**kwargs) -> Job:
    defaults = dict(
        url="https://example.com/1",
        title="Software Engineer",
        company="TestCo",
        location="Tokyo",
        source="indeed",
        description="A great role for a software engineer.",
    )
    defaults.update(kwargs)
    return Job(**defaults)


# --- Title matching ---


def test_title_exact_match():
    assert _title_matches_roles("Software Engineer", TARGET_ROLES) is True


def test_title_substring_match():
    assert _title_matches_roles("Senior Software Engineer", TARGET_ROLES) is True


def test_title_fuzzy_word_overlap():
    assert _title_matches_roles("Full Stack Engineer", TARGET_ROLES) is True


def test_title_generic_patterns():
    assert _title_matches_roles("Python Developer", TARGET_ROLES) is True
    assert _title_matches_roles("React Frontend Developer", TARGET_ROLES) is True
    assert _title_matches_roles("LLM Platform Engineer", TARGET_ROLES) is True


def test_title_no_match():
    assert _title_matches_roles("Marketing Manager", TARGET_ROLES) is False
    assert _title_matches_roles("Sales Representative", TARGET_ROLES) is False


# --- Pre-filter pass ---


def test_prefilter_passes_good_job():
    job = _make_job(title="Senior Software Engineer", salary_min=6_000_000)
    result = pre_filter_job(job, TARGET_ROLES)
    assert result.passed is True


def test_prefilter_passes_no_salary():
    job = _make_job(title="AI Engineer", salary_min=None)
    result = pre_filter_job(job, TARGET_ROLES)
    assert result.passed is True


# --- Pre-filter reject: title blocklist ---


def test_prefilter_rejects_intern():
    job = _make_job(title="Software Engineering Intern")
    result = pre_filter_job(job, TARGET_ROLES)
    assert result.passed is False
    assert "Blocked title" in result.reason


def test_prefilter_rejects_director():
    job = _make_job(title="Director of Engineering")
    result = pre_filter_job(job, TARGET_ROLES)
    assert result.passed is False


def test_prefilter_rejects_vp():
    job = _make_job(title="VP of Engineering")
    result = pre_filter_job(job, TARGET_ROLES)
    assert result.passed is False


def test_prefilter_rejects_phd_required():
    job = _make_job(title="ML Engineer PhD Required")
    result = pre_filter_job(job, TARGET_ROLES)
    assert result.passed is False


# --- Pre-filter reject: title mismatch ---


def test_prefilter_rejects_unrelated_title():
    job = _make_job(title="Marketing Manager")
    result = pre_filter_job(job, TARGET_ROLES)
    assert result.passed is False
    assert "doesn't match" in result.reason


# --- Pre-filter reject: salary ---


def test_prefilter_rejects_low_salary():
    job = _make_job(title="Software Engineer", salary_min=3_000_000)
    result = pre_filter_job(job, TARGET_ROLES)
    assert result.passed is False
    assert "Salary" in result.reason


def test_prefilter_passes_salary_at_floor():
    job = _make_job(title="Software Engineer", salary_min=5_000_000)
    result = pre_filter_job(job, TARGET_ROLES)
    assert result.passed is True


# --- Pre-filter reject: description blocklist ---


def test_prefilter_rejects_10_plus_years():
    job = _make_job(description="Requires 10+ years of experience in distributed systems.")
    result = pre_filter_job(job, TARGET_ROLES)
    assert result.passed is False
    assert "Blocked description" in result.reason


def test_prefilter_rejects_security_clearance():
    job = _make_job(description="Security clearance required for this position.")
    result = pre_filter_job(job, TARGET_ROLES)
    assert result.passed is False


def test_prefilter_rejects_us_citizens_only():
    job = _make_job(description="US citizens only may apply for this role.")
    result = pre_filter_job(job, TARGET_ROLES)
    assert result.passed is False


def test_prefilter_passes_5_years():
    job = _make_job(description="Requires 5+ years of experience.")
    result = pre_filter_job(job, TARGET_ROLES)
    assert result.passed is True
