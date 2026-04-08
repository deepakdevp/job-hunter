"""Tests for the negotiation intelligence module."""

import json

import pytest
from unittest.mock import AsyncMock

from job_hunter.database import Job, JobDB
from job_hunter.negotiate.intelligence import generate_negotiation, run_negotiation


SAMPLE_PROFILE = {
    "name": "Test User",
    "target_roles": ["Software Engineer"],
    "skills": ["Python", "React", "AWS"],
    "years_of_experience": 5,
    "location": "Tokyo, Japan",
}


def _make_job(url="https://example.com/1", **kwargs) -> Job:
    defaults = dict(
        url=url,
        title="Software Engineer",
        company="TestCo",
        location="Tokyo",
        source="indeed",
        description="Python developer needed.",
        salary_raw="8M-12M JPY",
    )
    defaults.update(kwargs)
    return Job(**defaults)


def _mock_negotiation_llm():
    """Return a mock LLM that produces valid negotiation JSON."""
    mock = AsyncMock()
    mock.generate.return_value = json.dumps({
        "market_data": {
            "salary_range": {
                "low": "8,000,000 JPY",
                "mid": "10,000,000 JPY",
                "high": "12,000,000 JPY",
                "currency": "JPY",
            },
            "sources": ["Glassdoor estimates for Tokyo backend roles"],
            "confidence": "MEDIUM",
            "factors": "Senior backend in Tokyo fintech",
        },
        "scripts": [
            {
                "scenario": "salary_expectations",
                "script": "Based on market data, I'm targeting 10-12M JPY.",
            },
            {
                "scenario": "geographic_discount_pushback",
                "script": "My output doesn't change based on location.",
            },
            {
                "scenario": "below_target_counter",
                "script": "I'm comparing with opportunities at 12M. Can we explore that range?",
            },
            {
                "scenario": "competing_offers",
                "script": "I have other opportunities in the 11-13M range.",
            },
            {
                "scenario": "benefits_negotiation",
                "script": "Could we discuss equity and remote flexibility?",
            },
        ],
        "contractor_rate": "15,000-18,000 JPY/hour (based on 30-50% premium)",
        "notes": "Tokyo market is competitive for backend engineers.",
    })
    return mock


# --- generate_negotiation ---


class TestGenerateNegotiation:
    @pytest.mark.asyncio
    async def test_returns_scripts_dict(self):
        mock_llm = _mock_negotiation_llm()
        job = _make_job()
        result = await generate_negotiation(job, SAMPLE_PROFILE, mock_llm)
        assert "scripts" in result
        assert isinstance(result["scripts"], list)
        assert len(result["scripts"]) > 0
        # Each script has scenario and script
        for script in result["scripts"]:
            assert "scenario" in script
            assert "script" in script

    @pytest.mark.asyncio
    async def test_returns_market_data(self):
        mock_llm = _mock_negotiation_llm()
        job = _make_job()
        result = await generate_negotiation(job, SAMPLE_PROFILE, mock_llm)
        assert "market_data" in result
        assert "salary_range" in result["market_data"]

    @pytest.mark.asyncio
    async def test_handles_llm_failure(self):
        mock_llm = AsyncMock()
        mock_llm.generate.side_effect = Exception("API error")
        job = _make_job()
        result = await generate_negotiation(job, SAMPLE_PROFILE, mock_llm)
        assert "error" in result
        assert result["scripts"] == []

    @pytest.mark.asyncio
    async def test_uses_evaluation_comp_data_when_available(self):
        eval_data = json.dumps({
            "blocks": {
                "comp_intelligence": {
                    "salary_range": {"low": 8e6, "mid": 10e6, "high": 12e6, "currency": "JPY"},
                    "company_comp_reputation": "above average",
                    "demand_trend": "high demand",
                    "sources": ["Glassdoor"],
                    "data_available": True,
                },
            },
        })
        mock_llm = _mock_negotiation_llm()
        job = _make_job(evaluation=eval_data)
        result = await generate_negotiation(job, SAMPLE_PROFILE, mock_llm)
        assert "scripts" in result
        # Verify the prompt included eval data
        call_args = mock_llm.generate.call_args[0][0]
        assert "above average" in call_args or "salary_range" in call_args

    @pytest.mark.asyncio
    async def test_without_evaluation_data(self):
        mock_llm = _mock_negotiation_llm()
        job = _make_job(evaluation=None)
        result = await generate_negotiation(job, SAMPLE_PROFILE, mock_llm)
        assert "scripts" in result
        call_args = mock_llm.generate.call_args[0][0]
        assert "No evaluation data available" in call_args


# --- run_negotiation ---


class TestRunNegotiation:
    @pytest.mark.asyncio
    async def test_stores_in_db(self, tmp_path):
        db = JobDB(tmp_path / "test.db")
        db.upsert_job(_make_job())
        mock_llm = _mock_negotiation_llm()

        result = await run_negotiation(db, SAMPLE_PROFILE, mock_llm, "https://example.com/1")
        assert "scripts" in result

        # Verify stored
        job = db.get_job("https://example.com/1")
        assert job.negotiation is not None
        stored = json.loads(job.negotiation)
        assert "scripts" in stored
        db.close()

    @pytest.mark.asyncio
    async def test_job_not_found(self, tmp_path):
        db = JobDB(tmp_path / "test.db")
        mock_llm = AsyncMock()
        result = await run_negotiation(db, SAMPLE_PROFILE, mock_llm, "https://nonexistent.com/1")
        assert "error" in result
        db.close()
