"""Tests for the Applicant orchestrator."""
from __future__ import annotations
import json
from pathlib import Path
import pytest
from job_hunter.apply.applicant import Applicant, ApplyResult, ELIGIBLE_STATUSES
from job_hunter.database import Job

@pytest.fixture
def sample_job(tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF")
    cl = tmp_path / "cover.txt"
    cl.write_text("Dear Manager")
    return Job(
        url="https://example.com/job/1",
        title="Software Engineer",
        company="Acme Corp",
        location="Tokyo",
        source="indeed",
        status="tailored",
        apply_url="https://boards.greenhouse.io/acme/jobs/1234",
        resume_path=str(resume),
        cover_letter_path=str(cl),
    )

@pytest.fixture
def sample_profile():
    return {"name": "Test User", "email": "test@example.com", "phone": "+1234567890"}

def test_apply_result_dataclass():
    r = ApplyResult(job_url="https://example.com", company="Acme", platform="greenhouse", status="applied")
    assert r.error is None
    assert r.status == "applied"

def test_apply_result_to_dict():
    r = ApplyResult(job_url="https://example.com", company="Acme", platform="greenhouse", status="applied")
    d = r.to_dict()
    assert d["company"] == "Acme"
    assert "timestamp" in d
    assert d["url"] == "https://example.com"

def test_select_strategy_greenhouse(sample_profile, tmp_path):
    a = Applicant(profile=sample_profile, session_dir=tmp_path / "sessions")
    strategy = a._select_strategy("https://boards.greenhouse.io/acme/1")
    assert strategy.__class__.__name__ == "GreenhouseFormFiller"

def test_select_strategy_workday(sample_profile, tmp_path):
    a = Applicant(profile=sample_profile, session_dir=tmp_path / "sessions")
    strategy = a._select_strategy("https://acme.myworkdayjobs.com/1")
    assert strategy.__class__.__name__ == "WorkdayFormFiller"

def test_select_strategy_lever(sample_profile, tmp_path):
    a = Applicant(profile=sample_profile, session_dir=tmp_path / "sessions")
    strategy = a._select_strategy("https://jobs.lever.co/acme")
    assert strategy.__class__.__name__ == "LeverFormFiller"

def test_select_strategy_generic(sample_profile, tmp_path):
    a = Applicant(profile=sample_profile, session_dir=tmp_path / "sessions")
    strategy = a._select_strategy("https://randomsite.com/apply")
    assert strategy.__class__.__name__ == "GenericFormFiller"

def test_is_eligible_true(sample_job, sample_profile, tmp_path):
    a = Applicant(profile=sample_profile, session_dir=tmp_path / "sessions")
    assert a.is_eligible(sample_job) is True

def test_is_eligible_no_resume(sample_job, sample_profile, tmp_path):
    sample_job.resume_path = None
    a = Applicant(profile=sample_profile, session_dir=tmp_path / "sessions")
    assert a.is_eligible(sample_job) is False

def test_is_eligible_wrong_status(sample_job, sample_profile, tmp_path):
    sample_job.status = "scored"
    a = Applicant(profile=sample_profile, session_dir=tmp_path / "sessions")
    assert a.is_eligible(sample_job) is False

def test_is_eligible_no_cover_letter(sample_job, sample_profile, tmp_path):
    sample_job.cover_letter_path = None
    a = Applicant(profile=sample_profile, session_dir=tmp_path / "sessions")
    assert a.is_eligible(sample_job) is False

def test_log_result(sample_profile, tmp_path):
    log_path = tmp_path / "apply_log.json"
    a = Applicant(profile=sample_profile, session_dir=tmp_path / "sessions", log_path=log_path)
    result = ApplyResult(job_url="https://example.com", company="Acme", platform="generic", status="applied")
    a._log_result(result)
    log = json.loads(log_path.read_text())
    assert len(log) == 1
    assert log[0]["status"] == "applied"

def test_log_result_appends(sample_profile, tmp_path):
    log_path = tmp_path / "apply_log.json"
    a = Applicant(profile=sample_profile, session_dir=tmp_path / "sessions", log_path=log_path)
    r1 = ApplyResult(job_url="https://a.com", company="A", platform="generic", status="applied")
    r2 = ApplyResult(job_url="https://b.com", company="B", platform="workday", status="apply_failed", error="timeout")
    a._log_result(r1)
    a._log_result(r2)
    log = json.loads(log_path.read_text())
    assert len(log) == 2
    assert log[1]["error"] == "timeout"
