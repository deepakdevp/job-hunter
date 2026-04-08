"""Tests for the job comparison engine."""

import json

import pytest
from unittest.mock import AsyncMock

from job_hunter.database import Job
from job_hunter.evaluate.compare import (
    compare_jobs,
    format_comparison_table,
    DIMENSIONS,
)


SAMPLE_PROFILE = {
    "name": "Test User",
    "target_roles": ["Software Engineer"],
    "skills": ["Python", "React"],
    "experience": [{"company": "TechCo", "title": "Developer"}],
}


def _make_job(url="https://example.com/1", **kwargs) -> Job:
    defaults = dict(
        url=url,
        title="Software Engineer",
        company="TestCo",
        location="Tokyo",
        source="indeed",
        description="Looking for a Python developer.",
        score=7,
    )
    defaults.update(kwargs)
    return Job(**defaults)


def _mock_comparison_llm(scores=None):
    """Return a mock LLM that produces comparison scores."""
    if scores is None:
        scores = {dim: 4 for dim in DIMENSIONS}

    mock_llm = AsyncMock()
    mock_llm.generate.return_value = json.dumps({
        "scores": scores,
        "notes": "Good match overall.",
    })
    return mock_llm


# --- Weights ---


class TestWeights:
    def test_weights_sum_to_one(self):
        total = sum(dim["weight"] for dim in DIMENSIONS.values())
        assert abs(total - 1.0) < 1e-6

    def test_all_dimensions_have_weight(self):
        for name, dim in DIMENSIONS.items():
            assert "weight" in dim, f"Dimension {name} missing weight"
            assert 0 < dim["weight"] <= 1.0


# --- compare_jobs ---


class TestCompareJobs:
    @pytest.mark.asyncio
    async def test_returns_ranked_list(self):
        mock_llm = _mock_comparison_llm()
        jobs = [
            _make_job(url="https://a.com/1", company="Alpha"),
            _make_job(url="https://a.com/2", company="Beta"),
        ]
        results = await compare_jobs(jobs, SAMPLE_PROFILE, mock_llm)
        assert len(results) == 2
        # Both have rank assigned
        ranks = {r["rank"] for r in results}
        assert ranks == {1, 2}

    @pytest.mark.asyncio
    async def test_results_contain_all_dimensions(self):
        mock_llm = _mock_comparison_llm()
        jobs = [_make_job()]
        results = await compare_jobs(jobs, SAMPLE_PROFILE, mock_llm)
        assert len(results) == 1
        scores = results[0]["scores"]
        for dim in DIMENSIONS:
            assert dim in scores, f"Missing dimension: {dim}"

    @pytest.mark.asyncio
    async def test_weighted_total_computed(self):
        scores = {dim: 5 for dim in DIMENSIONS}
        mock_llm = _mock_comparison_llm(scores)
        jobs = [_make_job()]
        results = await compare_jobs(jobs, SAMPLE_PROFILE, mock_llm)
        # All 5s * weights summing to 1.0 = 5.0
        assert abs(results[0]["weighted_total"] - 5.0) < 0.01

    @pytest.mark.asyncio
    async def test_ranking_is_by_weighted_total_desc(self):
        """Higher weighted total gets rank 1."""
        call_count = {"n": 0}
        mock_llm = AsyncMock()

        async def vary_scores(prompt, **kwargs):
            call_count["n"] += 1
            if "Alpha" in prompt:
                scores = {dim: 5 for dim in DIMENSIONS}
            else:
                scores = {dim: 2 for dim in DIMENSIONS}
            return json.dumps({"scores": scores, "notes": "test"})

        mock_llm.generate = AsyncMock(side_effect=vary_scores)

        jobs = [
            _make_job(url="https://a.com/1", company="Beta"),
            _make_job(url="https://a.com/2", company="Alpha"),
        ]
        results = await compare_jobs(jobs, SAMPLE_PROFILE, mock_llm)
        # Alpha should be rank 1
        alpha = next(r for r in results if r["company"] == "Alpha")
        beta = next(r for r in results if r["company"] == "Beta")
        assert alpha["rank"] < beta["rank"]
        assert alpha["weighted_total"] > beta["weighted_total"]

    @pytest.mark.asyncio
    async def test_empty_jobs_returns_empty(self):
        mock_llm = AsyncMock()
        results = await compare_jobs([], SAMPLE_PROFILE, mock_llm)
        assert results == []

    @pytest.mark.asyncio
    async def test_uses_evaluation_data_when_available(self):
        eval_data = json.dumps({
            "blocks": {
                "role_summary": {"domain": "fintech", "seniority": "senior", "remote": "hybrid", "tldr": "Build stuff"},
                "cv_match": {"match_percentage": 80, "gaps": []},
                "level_strategy": {"jd_level": "senior", "strategy": "aligned"},
                "comp_intelligence": {
                    "salary_range": {"mid": 10000000, "currency": "JPY"},
                    "company_comp_reputation": "above average",
                },
            },
        })
        mock_llm = _mock_comparison_llm()
        jobs = [_make_job(evaluation=eval_data)]
        results = await compare_jobs(jobs, SAMPLE_PROFILE, mock_llm)
        assert len(results) == 1
        # Verify LLM was called (the eval data is fed into the prompt)
        mock_llm.generate.assert_called_once()
        prompt = mock_llm.generate.call_args[0][0]
        assert "fintech" in prompt or "senior" in prompt

    @pytest.mark.asyncio
    async def test_handles_llm_failure_gracefully(self):
        mock_llm = AsyncMock()
        mock_llm.generate.side_effect = Exception("API error")
        jobs = [_make_job()]
        results = await compare_jobs(jobs, SAMPLE_PROFILE, mock_llm)
        assert len(results) == 1
        assert results[0]["weighted_total"] == 0.0
        assert "failed" in results[0]["notes"].lower()

    @pytest.mark.asyncio
    async def test_scores_clamped_to_1_5(self):
        scores = {dim: 99 for dim in DIMENSIONS}
        mock_llm = _mock_comparison_llm(scores)
        jobs = [_make_job()]
        results = await compare_jobs(jobs, SAMPLE_PROFILE, mock_llm)
        for dim_name, score in results[0]["scores"].items():
            assert 1 <= score <= 5


# --- format_comparison_table ---


class TestFormatComparisonTable:
    def test_produces_string_output(self):
        results = [
            {
                "rank": 1,
                "company": "TestCo",
                "title": "SWE",
                "scores": {dim: 4 for dim in DIMENSIONS},
                "weighted_total": 4.0,
                "notes": "Good match.",
            },
        ]
        table = format_comparison_table(results)
        assert isinstance(table, str)
        assert "TestCo" in table
        assert "Job Comparison Matrix" in table

    def test_empty_results(self):
        table = format_comparison_table([])
        assert "No jobs to compare" in table

    def test_multiple_jobs_in_table(self):
        results = [
            {
                "rank": i + 1,
                "company": f"Company{i}",
                "title": "SWE",
                "scores": {dim: 3 for dim in DIMENSIONS},
                "weighted_total": 3.0,
                "notes": f"Note {i}",
            }
            for i in range(3)
        ]
        table = format_comparison_table(results)
        assert "Company0" in table
        assert "Company1" in table
        assert "Company2" in table
