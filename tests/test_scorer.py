import json
import pytest
from unittest.mock import AsyncMock
from job_hunter.database import Job, JobDB
from job_hunter.score.scorer import (
    parse_score_response,
    score_job,
    run_scoring,
    _build_scoring_prompt,
)

SAMPLE_PROFILE = {
    "target_roles": ["Software Engineer", "AI Engineer", "Full Stack Developer"],
    "skills": ["Python", "React", "TypeScript", "Django", "AWS", "Docker"],
    "experience": [
        {
            "company": "TechCo",
            "title": "Full Stack Developer",
            "highlights": ["Built REST APIs", "Led frontend migration"],
        }
    ],
}


def _make_job(**kwargs) -> Job:
    defaults = dict(
        url="https://example.com/1",
        title="Software Engineer",
        company="TestCo",
        location="Tokyo, Japan",
        source="indeed",
        description="Looking for a Python developer with React and AWS experience. Visa sponsorship available.",
        salary_min=6_000_000,
        salary_raw="6M JPY",
        visa_sponsorship=True,
        remote_policy="hybrid",
        tech_stack="Python, React, AWS",
    )
    defaults.update(kwargs)
    return Job(**defaults)


# --- parse_score_response ---


def test_parse_score_response_valid():
    response = json.dumps(
        {
            "skills_match": 9,
            "role_fit": 8,
            "location_remote": 10,
            "visa_sponsorship": 10,
            "salary_fit": 8,
            "reason": "Strong Python/React match with 5/6 required skills. Tokyo hybrid with visa makes this ideal.",
        }
    )
    result = parse_score_response(response)
    assert result is not None
    assert 1 <= result.score <= 10
    assert "Python" in result.reason
    assert result.dimensions["skills_match"] == 9
    assert result.dimensions["visa_sponsorship"] == 10


def test_parse_score_response_computes_weighted_average():
    response = json.dumps(
        {
            "skills_match": 10,
            "role_fit": 10,
            "location_remote": 10,
            "visa_sponsorship": 10,
            "salary_fit": 10,
            "reason": "Perfect match.",
        }
    )
    result = parse_score_response(response)
    assert result.score == 10


def test_parse_score_response_low_scores():
    response = json.dumps(
        {
            "skills_match": 1,
            "role_fit": 1,
            "location_remote": 1,
            "visa_sponsorship": 1,
            "salary_fit": 1,
            "reason": "No match at all.",
        }
    )
    result = parse_score_response(response)
    assert result.score == 1


def test_parse_score_response_invalid_json():
    result = parse_score_response("not json")
    assert result is None


def test_parse_score_response_missing_dimension():
    response = json.dumps(
        {
            "skills_match": 8,
            "role_fit": 7,
            # missing location_remote, visa_sponsorship, salary_fit
            "reason": "Partial.",
        }
    )
    result = parse_score_response(response)
    assert result is None


def test_parse_score_response_out_of_range():
    response = json.dumps(
        {
            "skills_match": 15,  # out of range
            "role_fit": 8,
            "location_remote": 7,
            "visa_sponsorship": 9,
            "salary_fit": 6,
            "reason": "Bad score.",
        }
    )
    result = parse_score_response(response)
    assert result is None


# --- _build_scoring_prompt ---


def test_build_scoring_prompt_includes_profile():
    job = _make_job()
    prompt = _build_scoring_prompt(job, SAMPLE_PROFILE)
    assert "Python" in prompt
    assert "React" in prompt
    assert "Software Engineer" in prompt
    assert "Tokyo" in prompt
    assert "Yes, sponsored" in prompt


def test_build_scoring_prompt_handles_missing_data():
    job = _make_job(salary_min=None, salary_raw=None, visa_sponsorship=None, tech_stack=None)
    prompt = _build_scoring_prompt(job, SAMPLE_PROFILE)
    assert "Unknown" in prompt


# --- score_job ---


@pytest.mark.asyncio
async def test_score_job_success():
    job = _make_job()
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = json.dumps(
        {
            "skills_match": 9,
            "role_fit": 8,
            "location_remote": 10,
            "visa_sponsorship": 10,
            "salary_fit": 7,
            "reason": "Excellent skills overlap. Tokyo with visa is ideal.",
        }
    )
    result = await score_job(job, SAMPLE_PROFILE, mock_llm)
    assert result is not None
    assert 1 <= result.score <= 10
    mock_llm.generate.assert_called_once()


@pytest.mark.asyncio
async def test_score_job_llm_failure():
    job = _make_job()
    mock_llm = AsyncMock()
    mock_llm.generate.side_effect = Exception("API error")
    result = await score_job(job, SAMPLE_PROFILE, mock_llm)
    assert result is None


# --- run_scoring ---


@pytest.mark.asyncio
async def test_run_scoring_filters_and_scores(tmp_path):
    db = JobDB(tmp_path / "test.db")

    # Good job — should be scored
    db.upsert_job(
        Job(
            url="https://example.com/1",
            title="Software Engineer",
            company="A",
            location="Tokyo",
            source="indeed",
            description="Python developer needed. Visa sponsored.",
        )
    )
    # Bad job — should be filtered (Marketing Manager)
    db.upsert_job(
        Job(
            url="https://example.com/2",
            title="Marketing Manager",
            company="B",
            location="Tokyo",
            source="indeed",
            description="Marketing role.",
        )
    )

    mock_llm = AsyncMock()
    mock_llm.generate.return_value = json.dumps(
        {
            "skills_match": 8,
            "role_fit": 7,
            "location_remote": 10,
            "visa_sponsorship": 5,
            "salary_fit": 5,
            "reason": "Good skills match. Location ideal but visa unclear.",
        }
    )

    scored, filtered, total = await run_scoring(db, SAMPLE_PROFILE, mock_llm)
    assert total == 2
    assert filtered == 1
    assert scored == 1

    # Check filtered job
    job2 = db.get_job("https://example.com/2")
    assert job2.score == 0
    assert job2.status == "filtered"
    assert "Pre-filtered" in job2.score_reason

    # Check scored job
    job1 = db.get_job("https://example.com/1")
    assert job1.score > 0
    assert job1.status == "scored"

    db.close()
