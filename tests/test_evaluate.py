"""Tests for the evaluation engine: archetype detection, blocks, orchestration."""

import json

import pytest
from unittest.mock import AsyncMock

from job_hunter.database import Job, JobDB
from job_hunter.evaluate.archetype import detect_archetype, ARCHETYPES
from job_hunter.evaluate.blocks import (
    block_a_role_summary,
    block_b_cv_match,
    block_c_level_strategy,
    block_d_comp_intelligence,
    block_e_personalization,
    block_f_interview_prep,
    block_g_draft_answers,
)
from job_hunter.evaluate.engine import evaluate_job, format_evaluation_markdown, run_evaluation


SAMPLE_PROFILE = {
    "name": "Test User",
    "target_roles": ["Software Engineer", "AI Engineer"],
    "skills": ["Python", "React", "TypeScript", "Django", "AWS"],
    "experience": [
        {
            "company": "TechCo",
            "title": "Full Stack Developer",
            "highlights": ["Built REST APIs", "Led frontend migration"],
        }
    ],
    "education": [{"school": "MIT", "degree": "BS Computer Science"}],
}


def _make_job(**kwargs) -> Job:
    defaults = dict(
        url="https://example.com/1",
        title="Software Engineer",
        company="TestCo",
        location="Tokyo, Japan",
        source="indeed",
        description="Looking for a Python developer with React and AWS experience.",
        score=7,
    )
    defaults.update(kwargs)
    return Job(**defaults)


def _mock_llm_for_evaluation():
    """Create a mock LLM that returns appropriate JSON for each block."""
    mock_llm = AsyncMock()

    call_count = {"n": 0}

    async def side_effect(prompt, **kwargs):
        call_count["n"] += 1
        # Detect which block based on prompt content
        if "classification expert" in prompt or "archetype" in prompt.lower()[:100]:
            return json.dumps({
                "primary": "backend",
                "secondary": "full_stack",
                "confidence": 0.85,
            })
        elif "role information" in prompt or "Block A" in prompt:
            return json.dumps({
                "archetype": "backend",
                "domain": "fintech",
                "function": "product development",
                "seniority": "senior",
                "remote": "hybrid",
                "team_size": "5-10",
                "tldr": "Build backend services for financial products.",
            })
        elif "resume-matching" in prompt or "CV" in prompt:
            return json.dumps({
                "matches": [
                    {"requirement": "Python", "cv_line": "Built REST APIs", "strength": "strong"}
                ],
                "gaps": [
                    {"requirement": "Go", "is_blocker": False, "adjacent_experience": "Python", "mitigation": "Learn Go"}
                ],
                "match_percentage": 72.0,
            })
        elif "career-level" in prompt or "seniority" in prompt.lower()[:100]:
            return json.dumps({
                "jd_level": "senior",
                "candidate_level": "mid",
                "strategy": "uplevel",
                "downlevel_plan": "Emphasize leadership experience and system design skills.",
            })
        elif "compensation" in prompt:
            return json.dumps({
                "salary_range": {"low": 8000000, "mid": 10000000, "high": 12000000, "currency": "JPY"},
                "company_comp_reputation": "average",
                "demand_trend": "high demand",
                "sources": ["Glassdoor estimates"],
                "data_available": True,
            })
        elif "resume and LinkedIn" in prompt or "personalization" in prompt.lower()[:100]:
            return json.dumps({
                "resume_changes": [
                    {"section": "skills", "current": "Python", "proposed": "Python, Go", "why": "JD requires Go"}
                ],
                "linkedin_changes": [
                    {"section": "headline", "current": "Developer", "proposed": "Backend Engineer", "why": "Match JD"}
                ],
            })
        elif "interview preparation" in prompt or "STAR" in prompt:
            return json.dumps({
                "stories": [
                    {
                        "requirement": "Python experience",
                        "title": "REST API at TechCo",
                        "situation": "TechCo needed a new API",
                        "task": "Design scalable API",
                        "action": "Built with Django REST Framework",
                        "result": "Handled 10K requests/day",
                        "reflection": "Learned importance of caching",
                    }
                ],
                "case_study": {"project": "REST API", "demo_plan": "Live demo"},
                "red_flag_questions": [
                    {"question": "Why leave?", "response": "Seeking growth."}
                ],
            })
        elif "application-answer" in prompt or "draft answers" in prompt.lower()[:100]:
            return json.dumps({
                "answers": [
                    {"question_type": "why_role", "question": "Why this role?", "answer": "I built APIs at TechCo."},
                    {"question_type": "why_company", "question": "Why this company?", "answer": "Strong engineering culture."},
                    {"question_type": "relevant_experience", "question": "Relevant experience?", "answer": "3 years Python dev."},
                    {"question_type": "good_fit", "question": "Why are you a good fit?", "answer": "Skills match well."},
                    {"question_type": "how_heard", "question": "How did you hear?", "answer": "Job board."},
                ],
            })
        else:
            # Default fallback
            return json.dumps({"primary": "full_stack", "secondary": None, "confidence": 0.5})

    mock_llm.generate = AsyncMock(side_effect=side_effect)
    return mock_llm


# --- detect_archetype ---


class TestDetectArchetype:
    @pytest.mark.asyncio
    async def test_returns_valid_archetype(self):
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = json.dumps({
            "primary": "backend",
            "secondary": "full_stack",
            "confidence": 0.9,
        })
        result = await detect_archetype("Python backend developer needed", "Backend Engineer", mock_llm)
        assert result["primary"] in ARCHETYPES
        assert result["secondary"] is None or result["secondary"] in ARCHETYPES
        assert 0.0 <= result["confidence"] <= 1.0

    @pytest.mark.asyncio
    async def test_defaults_on_invalid_primary(self):
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = json.dumps({
            "primary": "nonexistent_archetype",
            "secondary": None,
            "confidence": 0.5,
        })
        result = await detect_archetype("Some JD", "Some Title", mock_llm)
        assert result["primary"] == "full_stack"

    @pytest.mark.asyncio
    async def test_defaults_on_llm_failure(self):
        mock_llm = AsyncMock()
        mock_llm.generate.side_effect = Exception("API error")
        result = await detect_archetype("Some JD", "Some Title", mock_llm)
        assert result["primary"] == "full_stack"
        assert result["confidence"] == 0.0

    @pytest.mark.asyncio
    async def test_clamps_confidence(self):
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = json.dumps({
            "primary": "ai_ml",
            "secondary": None,
            "confidence": 1.5,
        })
        result = await detect_archetype("ML JD", "ML Engineer", mock_llm)
        assert result["confidence"] <= 1.0


# --- Block functions ---


class TestBlocks:
    @pytest.mark.asyncio
    async def test_block_a_returns_expected_structure(self):
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = json.dumps({
            "archetype": "backend",
            "domain": "fintech",
            "function": "platform engineering",
            "seniority": "senior",
            "remote": "hybrid",
            "team_size": "5-10",
            "tldr": "Build backend services.",
        })
        job = _make_job()
        archetype = {"primary": "backend", "secondary": None, "confidence": 0.9}
        result = await block_a_role_summary(job, SAMPLE_PROFILE, mock_llm, archetype)
        assert "archetype" in result
        assert "domain" in result
        assert "seniority" in result
        assert "tldr" in result

    @pytest.mark.asyncio
    async def test_block_b_returns_matches_and_gaps(self):
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = json.dumps({
            "matches": [{"requirement": "Python", "cv_line": "Built APIs", "strength": "strong"}],
            "gaps": [{"requirement": "Go", "is_blocker": False, "adjacent_experience": "Python", "mitigation": "Learn Go"}],
            "match_percentage": 72.0,
        })
        job = _make_job()
        archetype = {"primary": "backend"}
        result = await block_b_cv_match(job, SAMPLE_PROFILE, mock_llm, archetype)
        assert "matches" in result
        assert "gaps" in result
        assert "match_percentage" in result

    @pytest.mark.asyncio
    async def test_block_c_returns_level_strategy(self):
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = json.dumps({
            "jd_level": "senior",
            "candidate_level": "mid",
            "strategy": "uplevel",
            "downlevel_plan": "Emphasize leadership.",
        })
        job = _make_job()
        archetype = {"primary": "backend"}
        result = await block_c_level_strategy(job, SAMPLE_PROFILE, mock_llm, archetype)
        assert result["strategy"] in ("aligned", "sell_senior", "uplevel")

    @pytest.mark.asyncio
    async def test_block_d_returns_comp_data(self):
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = json.dumps({
            "salary_range": {"low": 8000000, "mid": 10000000, "high": 12000000, "currency": "JPY"},
            "company_comp_reputation": "average",
            "demand_trend": "high demand",
            "sources": ["Glassdoor"],
            "data_available": True,
        })
        job = _make_job()
        archetype = {"primary": "backend"}
        result = await block_d_comp_intelligence(job, SAMPLE_PROFILE, mock_llm, archetype)
        assert "salary_range" in result
        assert "data_available" in result

    @pytest.mark.asyncio
    async def test_block_e_returns_personalization(self):
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = json.dumps({
            "resume_changes": [{"section": "skills", "current": "X", "proposed": "Y", "why": "Z"}],
            "linkedin_changes": [{"section": "headline", "current": "A", "proposed": "B", "why": "C"}],
        })
        job = _make_job()
        archetype = {"primary": "backend"}
        result = await block_e_personalization(job, SAMPLE_PROFILE, mock_llm, archetype)
        assert "resume_changes" in result
        assert "linkedin_changes" in result

    @pytest.mark.asyncio
    async def test_block_f_returns_stories(self):
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = json.dumps({
            "stories": [{"title": "API Story", "situation": "X", "task": "Y", "action": "Z", "result": "W", "reflection": "R", "requirement": "Python"}],
            "case_study": {"project": "API", "demo_plan": "Demo"},
            "red_flag_questions": [{"question": "Q", "response": "A"}],
        })
        job = _make_job()
        archetype = {"primary": "backend"}
        result = await block_f_interview_prep(job, SAMPLE_PROFILE, mock_llm, archetype)
        assert "stories" in result
        assert len(result["stories"]) > 0
        assert "case_study" in result

    @pytest.mark.asyncio
    async def test_block_g_returns_answers(self):
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = json.dumps({
            "answers": [
                {"question_type": "why_role", "question": "Why?", "answer": "Because."},
            ],
        })
        job = _make_job()
        archetype = {"primary": "backend"}
        result = await block_g_draft_answers(job, SAMPLE_PROFILE, mock_llm, archetype)
        assert "answers" in result
        assert len(result["answers"]) > 0

    @pytest.mark.asyncio
    async def test_block_graceful_failure(self):
        """Each block returns a fallback dict on LLM failure."""
        mock_llm = AsyncMock()
        mock_llm.generate.side_effect = Exception("API error")
        job = _make_job()
        archetype = {"primary": "backend"}

        result_a = await block_a_role_summary(job, SAMPLE_PROFILE, mock_llm, archetype)
        assert result_a["domain"] == "unknown"

        result_b = await block_b_cv_match(job, SAMPLE_PROFILE, mock_llm, archetype)
        assert result_b["matches"] == []

        result_c = await block_c_level_strategy(job, SAMPLE_PROFILE, mock_llm, archetype)
        assert result_c["strategy"] == "aligned"


# --- evaluate_job orchestration ---


class TestEvaluateJob:
    @pytest.mark.asyncio
    async def test_orchestrates_all_blocks(self):
        mock_llm = _mock_llm_for_evaluation()
        job = _make_job(score=7)
        result = await evaluate_job(job, SAMPLE_PROFILE, mock_llm, score_threshold=5)
        assert result is not None
        assert "archetype" in result
        assert "blocks" in result
        blocks = result["blocks"]
        assert "role_summary" in blocks
        assert "cv_match" in blocks
        assert "level_strategy" in blocks
        assert "comp_intelligence" in blocks
        assert "personalization" in blocks
        assert "interview_prep" in blocks
        assert "draft_answers" in blocks

    @pytest.mark.asyncio
    async def test_returns_none_without_description(self):
        mock_llm = AsyncMock()
        job = _make_job(description=None)
        result = await evaluate_job(job, SAMPLE_PROFILE, mock_llm)
        assert result is None

    @pytest.mark.asyncio
    async def test_block_g_skipped_below_threshold(self):
        mock_llm = _mock_llm_for_evaluation()
        job = _make_job(score=3)
        result = await evaluate_job(job, SAMPLE_PROFILE, mock_llm, score_threshold=5)
        assert result is not None
        draft = result["blocks"]["draft_answers"]
        assert draft.get("skipped") is True
        assert "below threshold" in draft.get("reason", "").lower() or "3" in draft.get("reason", "")

    @pytest.mark.asyncio
    async def test_block_g_runs_above_threshold(self):
        mock_llm = _mock_llm_for_evaluation()
        job = _make_job(score=8)
        result = await evaluate_job(job, SAMPLE_PROFILE, mock_llm, score_threshold=5)
        assert result is not None
        draft = result["blocks"]["draft_answers"]
        assert draft.get("skipped") is not True
        assert "answers" in draft


# --- run_evaluation stores in DB ---


class TestRunEvaluation:
    @pytest.mark.asyncio
    async def test_stores_evaluation_in_db(self, tmp_path):
        db = JobDB(tmp_path / "test.db")
        db.upsert_job(_make_job(score=7, description="Python developer needed."))

        mock_llm = _mock_llm_for_evaluation()
        evaluated, total = await run_evaluation(
            db, SAMPLE_PROFILE, mock_llm, min_score=5,
        )
        assert total == 1
        assert evaluated == 1

        job = db.get_job("https://example.com/1")
        assert job.evaluation is not None
        eval_data = json.loads(job.evaluation)
        assert "archetype" in eval_data
        assert "blocks" in eval_data
        db.close()

    @pytest.mark.asyncio
    async def test_run_evaluation_single_job(self, tmp_path):
        db = JobDB(tmp_path / "test.db")
        db.upsert_job(_make_job(score=7, description="Python developer."))

        mock_llm = _mock_llm_for_evaluation()
        evaluated, total = await run_evaluation(
            db, SAMPLE_PROFILE, mock_llm, job_url="https://example.com/1",
        )
        assert evaluated == 1
        assert total == 1
        db.close()


# --- format_evaluation_markdown ---


class TestFormatEvaluationMarkdown:
    def test_produces_valid_markdown(self):
        job = _make_job(score=7)
        evaluation = {
            "evaluated_at": "2025-01-01T00:00:00",
            "archetype": {"primary": "backend", "secondary": None, "confidence": 0.85},
            "blocks": {
                "role_summary": {
                    "archetype": "backend",
                    "domain": "fintech",
                    "function": "platform",
                    "seniority": "senior",
                    "remote": "hybrid",
                    "team_size": "5-10",
                    "tldr": "Build things.",
                },
                "cv_match": {
                    "matches": [{"requirement": "Python", "cv_line": "Built APIs", "strength": "strong"}],
                    "gaps": [],
                    "match_percentage": 80.0,
                },
                "level_strategy": {
                    "jd_level": "senior",
                    "candidate_level": "mid",
                    "strategy": "uplevel",
                    "downlevel_plan": "Emphasize leadership.",
                },
                "comp_intelligence": {
                    "salary_range": {"low": 8e6, "mid": 10e6, "high": 12e6, "currency": "JPY"},
                    "company_comp_reputation": "average",
                    "demand_trend": "high",
                    "sources": ["Glassdoor"],
                    "data_available": True,
                },
                "personalization": {"resume_changes": [], "linkedin_changes": []},
                "interview_prep": {"stories": [], "case_study": {}, "red_flag_questions": []},
                "draft_answers": {"answers": []},
            },
        }
        md = format_evaluation_markdown(job, evaluation)
        assert isinstance(md, str)
        assert "# Evaluation:" in md
        assert "TestCo" in md
        assert "Backend" in md or "backend" in md
        assert "## Role Summary" in md
        assert "## CV Match" in md
        assert "## Level Strategy" in md
        assert "## Compensation Intelligence" in md

    def test_handles_skipped_block_g(self):
        job = _make_job(score=3)
        evaluation = {
            "evaluated_at": "2025-01-01",
            "archetype": {"primary": "full_stack", "confidence": 0.5},
            "blocks": {
                "role_summary": {"error": "failed"},
                "cv_match": {"error": "failed"},
                "level_strategy": {"error": "failed"},
                "comp_intelligence": {"error": "failed"},
                "personalization": {"error": "failed"},
                "interview_prep": {"error": "failed"},
                "draft_answers": {"skipped": True, "reason": "Score 3 below threshold 5"},
            },
        }
        md = format_evaluation_markdown(job, evaluation)
        assert "Skipped" in md
