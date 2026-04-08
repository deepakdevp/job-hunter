"""Tests for the course/certification evaluator."""

import json

import pytest
from unittest.mock import AsyncMock

from job_hunter.evaluate.training import evaluate_training, TRAINING_DIMENSIONS


SAMPLE_PROFILE = {
    "target_roles": ["AI Engineer", "ML Engineer"],
    "skills": ["Python", "PyTorch", "TensorFlow"],
    "years_of_experience": 4,
    "gaps": ["production ML systems", "MLOps"],
}


def _mock_training_llm(verdict="DO", timebox_weeks=None):
    """Return a mock LLM that produces valid training evaluation JSON."""
    mock = AsyncMock()
    result = {
        "scores": {
            dim: {"score": 4, "reasoning": f"Good {dim} score."}
            for dim in TRAINING_DIMENSIONS
        },
        "verdict": verdict,
        "plan": [
            "Week 1: Setup environment and start fundamentals",
            "Week 2: Core concepts and exercises",
            "Week 3: Practice project",
            "Week 4: Capstone and review",
        ],
        "timebox_weeks": timebox_weeks,
        "alternative": None if verdict == "DO" else "Consider a more targeted cert.",
    }
    mock.generate.return_value = json.dumps(result)
    return mock


# --- evaluate_training ---


class TestEvaluateTraining:
    @pytest.mark.asyncio
    async def test_returns_scores_and_verdict(self):
        mock_llm = _mock_training_llm("DO")
        result = await evaluate_training(
            "AWS Solutions Architect Professional",
            SAMPLE_PROFILE,
            mock_llm,
        )
        assert "scores" in result
        assert "verdict" in result
        assert result["verdict"] in ("DO", "SKIP", "DO_WITH_TIMEBOX")

    @pytest.mark.asyncio
    async def test_do_verdict_includes_plan(self):
        mock_llm = _mock_training_llm("DO")
        result = await evaluate_training(
            "GCP ML Engineer cert",
            SAMPLE_PROFILE,
            mock_llm,
        )
        assert result["verdict"] == "DO"
        assert "plan" in result
        assert len(result["plan"]) > 0

    @pytest.mark.asyncio
    async def test_do_with_timebox_has_max_weeks(self):
        mock_llm = _mock_training_llm("DO_WITH_TIMEBOX", timebox_weeks=6)
        result = await evaluate_training(
            "Some course",
            SAMPLE_PROFILE,
            mock_llm,
        )
        assert result["verdict"] == "DO_WITH_TIMEBOX"
        assert result["timebox_weeks"] == 6

    @pytest.mark.asyncio
    async def test_skip_verdict_has_alternative(self):
        mock_llm = _mock_training_llm("SKIP")
        result = await evaluate_training(
            "Outdated certification",
            SAMPLE_PROFILE,
            mock_llm,
        )
        assert result["verdict"] == "SKIP"
        assert result.get("alternative") is not None

    @pytest.mark.asyncio
    async def test_handles_llm_failure(self):
        mock_llm = AsyncMock()
        mock_llm.generate.side_effect = Exception("API error")
        result = await evaluate_training("Some course", SAMPLE_PROFILE, mock_llm)
        assert "error" in result
        assert result["verdict"] == "SKIP"

    @pytest.mark.asyncio
    async def test_scores_validated(self):
        """Score values should be clamped to 1-5 range."""
        scores = {
            dim: {"score": 99, "reasoning": "Overinflated"}
            for dim in TRAINING_DIMENSIONS
        }
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = json.dumps({
            "scores": scores,
            "verdict": "DO",
            "plan": ["Week 1: Start"],
        })
        result = await evaluate_training("Some course", SAMPLE_PROFILE, mock_llm)
        for dim_name, dim_score in result["scores"].items():
            if isinstance(dim_score, dict) and "score" in dim_score:
                assert dim_score["score"] <= 5

    @pytest.mark.asyncio
    async def test_ensures_required_fields(self):
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = json.dumps({
            "scores": {
                dim: {"score": 3, "reasoning": "OK"}
                for dim in TRAINING_DIMENSIONS
            },
            "verdict": "DO",
        })
        result = await evaluate_training("Some course", SAMPLE_PROFILE, mock_llm)
        assert "plan" in result
        assert "timebox_weeks" in result
        assert "alternative" in result

    @pytest.mark.asyncio
    async def test_all_training_dimensions_present(self):
        """All defined dimensions should have corresponding scores."""
        mock_llm = _mock_training_llm("DO")
        result = await evaluate_training("Some course", SAMPLE_PROFILE, mock_llm)
        for dim in TRAINING_DIMENSIONS:
            assert dim in result["scores"]
