"""Tests for ATS keyword extraction."""

import json

import pytest
from unittest.mock import AsyncMock

from job_hunter.database import Job
from job_hunter.tailor.tailor import extract_keywords


SAMPLE_PROFILE = {
    "skills": ["Python", "Django", "React", "AWS", "Docker"],
    "experience": [
        {
            "company": "TechCo",
            "title": "Full Stack Developer",
            "highlights": ["Built REST APIs with Django", "Deployed to AWS ECS"],
        },
        {
            "company": "StartupX",
            "title": "Backend Developer",
            "highlights": ["Designed microservices", "Set up CI/CD pipelines"],
        },
    ],
}


def _make_job(**kwargs) -> Job:
    defaults = dict(
        url="https://example.com/1",
        title="Software Engineer",
        company="TestCo",
        location="Tokyo",
        source="indeed",
        description="Looking for a Python developer with Django, React, and AWS experience. Must know Docker and Kubernetes.",
    )
    defaults.update(kwargs)
    return Job(**defaults)


# --- extract_keywords ---


class TestExtractKeywords:
    @pytest.mark.asyncio
    async def test_returns_keyword_list_with_coverage(self):
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = json.dumps({
            "keywords": [
                {"keyword": "Python", "in_resume": True, "source": "skills"},
                {"keyword": "Django", "in_resume": True, "source": "experience"},
                {"keyword": "Kubernetes", "in_resume": False, "source": None},
            ],
            "coverage_pct": 0.67,
        })
        job = _make_job()
        result = await extract_keywords(job, mock_llm, profile=SAMPLE_PROFILE)
        assert "keywords" in result
        assert "coverage_pct" in result
        assert isinstance(result["keywords"], list)
        assert 0.0 <= result["coverage_pct"] <= 1.0

    @pytest.mark.asyncio
    async def test_keywords_mapped_to_real_experience(self):
        """Keywords marked as in_resume should correspond to real skills/experience."""
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = json.dumps({
            "keywords": [
                {"keyword": "Python", "in_resume": True, "source": "skills section"},
                {"keyword": "Django", "in_resume": True, "source": "TechCo experience"},
                {"keyword": "Go", "in_resume": False, "source": None},
            ],
            "coverage_pct": 0.67,
        })
        job = _make_job()
        result = await extract_keywords(job, mock_llm, profile=SAMPLE_PROFILE)
        keywords = result["keywords"]
        for kw in keywords:
            if isinstance(kw, dict) and kw.get("in_resume"):
                # If marked as in resume, verify the keyword maps to something
                # in the candidate's actual profile
                keyword_text = kw["keyword"].lower()
                profile_text = json.dumps(SAMPLE_PROFILE).lower()
                assert keyword_text in profile_text, (
                    f"Keyword '{kw['keyword']}' marked as in_resume but not found in profile"
                )

    @pytest.mark.asyncio
    async def test_no_description_returns_empty(self):
        mock_llm = AsyncMock()
        job = _make_job(description=None)
        result = await extract_keywords(job, mock_llm, profile=SAMPLE_PROFILE)
        assert result["keywords"] == []
        assert result["coverage_pct"] == 0.0
        # LLM should not be called
        mock_llm.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_empty_description_returns_empty(self):
        mock_llm = AsyncMock()
        job = _make_job(description="")
        result = await extract_keywords(job, mock_llm, profile=SAMPLE_PROFILE)
        assert result["keywords"] == []

    @pytest.mark.asyncio
    async def test_handles_llm_failure(self):
        mock_llm = AsyncMock()
        mock_llm.generate.side_effect = Exception("API error")
        job = _make_job()
        result = await extract_keywords(job, mock_llm, profile=SAMPLE_PROFILE)
        assert result["keywords"] == []
        assert result["coverage_pct"] == 0.0

    @pytest.mark.asyncio
    async def test_handles_malformed_json(self):
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = "not valid json"
        job = _make_job()
        result = await extract_keywords(job, mock_llm, profile=SAMPLE_PROFILE)
        assert result["keywords"] == []
        assert result["coverage_pct"] == 0.0

    @pytest.mark.asyncio
    async def test_strips_code_fences(self):
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = '```json\n{"keywords": [{"keyword": "Python"}], "coverage_pct": 0.5}\n```'
        job = _make_job()
        result = await extract_keywords(job, mock_llm, profile=SAMPLE_PROFILE)
        assert len(result["keywords"]) == 1

    @pytest.mark.asyncio
    async def test_without_profile_uses_empty(self):
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = json.dumps({
            "keywords": [{"keyword": "Python"}],
            "coverage_pct": 0.5,
        })
        job = _make_job()
        result = await extract_keywords(job, mock_llm, profile=None)
        assert "keywords" in result
