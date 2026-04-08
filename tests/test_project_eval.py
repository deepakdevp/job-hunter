"""Tests for the portfolio project evaluator."""

import json

import pytest
from unittest.mock import AsyncMock

from job_hunter.evaluate.project import evaluate_project, DIMENSIONS


SAMPLE_PROFILE = {
    "target_roles": ["AI Engineer", "Full Stack Developer"],
    "skills": ["Python", "React", "PyTorch", "LangChain"],
    "years_of_experience": 5,
    "experience": [
        {"title": "Full Stack Developer", "company": "TechCo"},
        {"title": "AI Engineer", "company": "MLStartup"},
    ],
}


def _mock_project_llm(verdict="BUILD", scores=None):
    """Return a mock LLM that produces valid project evaluation JSON."""
    if scores is None:
        scores = {
            dim: {"score": 4, "reasoning": f"Good {dim} score."} for dim in DIMENSIONS
        }

    mock = AsyncMock()
    result = {
        "scores": scores,
        "weighted_total": 4.0,
        "verdict": verdict,
        "milestones": [
            "Week 1: Setup and data pipeline",
            "Week 2: Core model implementation",
            "Week 3: API and frontend",
            "Week 4: Testing and deployment",
        ],
        "interview_pack": {
            "one_pager": "Key architecture decisions and metrics.",
            "demo_script": "2-minute walkthrough of the RAG pipeline.",
            "postmortem_outline": "What went wrong and lessons learned.",
        },
        "alternative": None if verdict == "BUILD" else "Build a different project instead.",
    }
    mock.generate.return_value = json.dumps(result)
    return mock


# --- Weights ---


class TestDimensions:
    def test_weights_sum_to_one(self):
        total = sum(dim["weight"] for dim in DIMENSIONS.values())
        assert abs(total - 1.0) < 1e-6

    def test_all_dimensions_have_weight(self):
        for name, dim in DIMENSIONS.items():
            assert "weight" in dim
            assert 0 < dim["weight"] <= 1.0


# --- evaluate_project ---


class TestEvaluateProject:
    @pytest.mark.asyncio
    async def test_returns_scores_and_verdict(self):
        mock_llm = _mock_project_llm("BUILD")
        result = await evaluate_project(
            "Build a RAG pipeline for job descriptions",
            SAMPLE_PROFILE,
            mock_llm,
        )
        assert "scores" in result
        assert "verdict" in result
        assert result["verdict"] in ("BUILD", "SKIP", "PIVOT")
        assert "weighted_total" in result

    @pytest.mark.asyncio
    async def test_build_verdict_includes_milestones(self):
        mock_llm = _mock_project_llm("BUILD")
        result = await evaluate_project(
            "Build a RAG pipeline",
            SAMPLE_PROFILE,
            mock_llm,
        )
        assert result["verdict"] == "BUILD"
        assert "milestones" in result
        assert len(result["milestones"]) > 0

    @pytest.mark.asyncio
    async def test_build_verdict_includes_interview_pack(self):
        mock_llm = _mock_project_llm("BUILD")
        result = await evaluate_project(
            "Build a RAG pipeline",
            SAMPLE_PROFILE,
            mock_llm,
        )
        assert "interview_pack" in result
        pack = result["interview_pack"]
        assert "one_pager" in pack or len(pack) > 0

    @pytest.mark.asyncio
    async def test_skip_verdict_includes_alternative(self):
        mock_llm = _mock_project_llm("SKIP")
        result = await evaluate_project(
            "Build a todo app",
            SAMPLE_PROFILE,
            mock_llm,
        )
        assert result["verdict"] == "SKIP"
        assert result.get("alternative") is not None

    @pytest.mark.asyncio
    async def test_recomputes_weighted_total(self):
        """The engine should recompute weighted_total from scores for consistency."""
        scores = {
            dim: {"score": 5, "reasoning": "Perfect"} for dim in DIMENSIONS
        }
        mock_llm = _mock_project_llm("BUILD", scores)
        result = await evaluate_project("Ideal project", SAMPLE_PROFILE, mock_llm)
        # 5 * sum(weights) = 5 * 1.0 = 5.0
        assert abs(result["weighted_total"] - 5.0) < 0.01

    @pytest.mark.asyncio
    async def test_handles_llm_failure(self):
        mock_llm = AsyncMock()
        mock_llm.generate.side_effect = Exception("API error")
        result = await evaluate_project("Some project", SAMPLE_PROFILE, mock_llm)
        assert "error" in result
        assert result["verdict"] == "SKIP"

    @pytest.mark.asyncio
    async def test_scores_clamped_to_1_5(self):
        scores = {
            dim: {"score": 99, "reasoning": "Overinflated"} for dim in DIMENSIONS
        }
        mock_llm = _mock_project_llm("BUILD", scores)
        result = await evaluate_project("Some project", SAMPLE_PROFILE, mock_llm)
        # Scores should be clamped to 5
        assert result["weighted_total"] <= 5.01

    @pytest.mark.asyncio
    async def test_ensures_required_fields_exist(self):
        """Even with minimal LLM output, required fields should exist."""
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = json.dumps({
            "scores": {dim: {"score": 3, "reasoning": "OK"} for dim in DIMENSIONS},
            "verdict": "PIVOT",
        })
        result = await evaluate_project("Some project", SAMPLE_PROFILE, mock_llm)
        assert "milestones" in result
        assert "interview_pack" in result
        assert "alternative" in result
