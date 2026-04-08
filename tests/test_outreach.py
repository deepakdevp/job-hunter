"""Tests for the outreach message generator."""

import json

import pytest
from unittest.mock import AsyncMock

from job_hunter.database import Job, JobDB
from job_hunter.outreach.generator import generate_outreach, run_outreach


SAMPLE_PROFILE = {
    "name": "Test User",
    "title": "Full Stack Developer",
    "skills": ["Python", "React", "AWS"],
    "experience": [
        {
            "company": "TechCo",
            "title": "Developer",
            "highlights": ["Built REST APIs serving 10K req/day"],
        }
    ],
}


def _make_job(url="https://example.com/1", **kwargs) -> Job:
    defaults = dict(
        url=url,
        title="Software Engineer",
        company="TestCo",
        location="Tokyo",
        source="indeed",
        description="Python developer needed for backend team.",
    )
    defaults.update(kwargs)
    return Job(**defaults)


def _mock_outreach_llm():
    """Return a mock LLM that produces valid outreach JSON."""
    mock = AsyncMock()
    mock.generate.return_value = json.dumps({
        "targets": [
            {
                "role": "hiring_manager",
                "name_suggestion": "VP of Engineering",
                "message": "TestCo's recent API revamp caught my eye. I built REST APIs handling 10K req/day at TechCo. Would love a 15-min chat about your backend challenges.",
                "char_count": 165,
            },
            {
                "role": "recruiter",
                "name_suggestion": "Technical Recruiter",
                "message": "Noticed TestCo is scaling the backend team. My Django APIs at TechCo served 10K daily requests. Quick question about the stack you're using?",
                "char_count": 155,
            },
            {
                "role": "peer",
                "name_suggestion": "Senior Backend Engineer",
                "message": "TestCo's microservice migration is interesting. I ran a similar migration at TechCo, cutting latency 40%. Curious how your team handles service discovery.",
                "char_count": 170,
            },
        ]
    })
    return mock


# --- generate_outreach ---


class TestGenerateOutreach:
    @pytest.mark.asyncio
    async def test_returns_messages_under_300_chars(self):
        mock_llm = _mock_outreach_llm()
        job = _make_job()
        result = await generate_outreach(job, SAMPLE_PROFILE, mock_llm)
        assert "targets" in result
        for target in result["targets"]:
            assert len(target["message"]) <= 300, (
                f"Message for {target['role']} is {len(target['message'])} chars"
            )

    @pytest.mark.asyncio
    async def test_messages_no_phone_numbers(self):
        mock_llm = _mock_outreach_llm()
        job = _make_job()
        result = await generate_outreach(job, SAMPLE_PROFILE, mock_llm)
        import re
        phone_pattern = re.compile(r"\+?\d[\d\s\-]{7,}")
        for target in result["targets"]:
            assert not phone_pattern.search(target["message"]), (
                f"Phone number found in message for {target['role']}"
            )

    @pytest.mark.asyncio
    async def test_messages_no_passionate(self):
        mock_llm = _mock_outreach_llm()
        job = _make_job()
        result = await generate_outreach(job, SAMPLE_PROFILE, mock_llm)
        for target in result["targets"]:
            assert "I'm passionate" not in target["message"]
            assert "i'm passionate" not in target["message"].lower()

    @pytest.mark.asyncio
    async def test_truncates_over_300_chars(self):
        mock_llm = AsyncMock()
        long_message = "A" * 350 + ". Short sentence."
        mock_llm.generate.return_value = json.dumps({
            "targets": [
                {
                    "role": "peer",
                    "name_suggestion": "Engineer",
                    "message": long_message,
                    "char_count": len(long_message),
                }
            ]
        })
        job = _make_job()
        result = await generate_outreach(job, SAMPLE_PROFILE, mock_llm)
        assert len(result["targets"]) == 1
        assert len(result["targets"][0]["message"]) <= 300

    @pytest.mark.asyncio
    async def test_handles_llm_failure(self):
        mock_llm = AsyncMock()
        mock_llm.generate.side_effect = Exception("API error")
        job = _make_job()
        result = await generate_outreach(job, SAMPLE_PROFILE, mock_llm)
        assert result["targets"] == []
        assert "error" in result

    @pytest.mark.asyncio
    async def test_handles_invalid_json(self):
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = "not json at all"
        job = _make_job()
        result = await generate_outreach(job, SAMPLE_PROFILE, mock_llm)
        assert result["targets"] == []
        assert "error" in result


# --- run_outreach ---


class TestRunOutreach:
    @pytest.mark.asyncio
    async def test_stores_in_db(self, tmp_path):
        db = JobDB(tmp_path / "test.db")
        db.upsert_job(_make_job())
        mock_llm = _mock_outreach_llm()

        result = await run_outreach(db, SAMPLE_PROFILE, mock_llm, "https://example.com/1")
        assert "targets" in result
        assert len(result["targets"]) > 0

        # Verify stored in DB
        job = db.get_job("https://example.com/1")
        assert job.outreach is not None
        stored = json.loads(job.outreach)
        assert "targets" in stored
        db.close()

    @pytest.mark.asyncio
    async def test_job_not_found(self, tmp_path):
        db = JobDB(tmp_path / "test.db")
        mock_llm = AsyncMock()
        result = await run_outreach(db, SAMPLE_PROFILE, mock_llm, "https://nonexistent.com/1")
        assert "error" in result
        db.close()
