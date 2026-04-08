"""Tests for ethical guardrails across the pipeline.

Covers:
- Applicant: weak match warnings, submit gating
- Cover letter: company mention validation
- Outreach: 300 char limit enforcement
"""

import json
import logging

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from job_hunter.database import Job
from job_hunter.apply.applicant import Applicant, WEAK_MATCH_THRESHOLD
from job_hunter.outreach.generator import generate_outreach, _truncate_to_limit


def _make_job(url="https://example.com/1", **kwargs) -> Job:
    defaults = dict(
        url=url,
        title="Software Engineer",
        company="TestCo",
        location="Tokyo",
        source="indeed",
        description="Python developer needed.",
        status="tailored",
        resume_path="/path/to/resume.pdf",
        cover_letter_path="/path/to/cover.pdf",
    )
    defaults.update(kwargs)
    return Job(**defaults)


SAMPLE_PROFILE = {
    "name": "Test User",
    "email": "test@example.com",
    "phone": "+1-555-0100",
    "skills": ["Python", "React"],
}


# --- Applicant: weak match warning ---


class TestApplicantWeakMatchWarning:
    def test_weak_match_threshold_is_3(self):
        assert WEAK_MATCH_THRESHOLD == 3

    @pytest.mark.asyncio
    async def test_warns_on_weak_match(self, tmp_path, caplog):
        """Applicant should log a warning when score < WEAK_MATCH_THRESHOLD."""
        applicant = Applicant(
            profile=SAMPLE_PROFILE,
            session_dir=tmp_path / "sessions",
            dry_run=True,
        )
        job = _make_job(score=2)

        # async_playwright is imported lazily inside apply_to_job, so we
        # patch the import mechanism via playwright.async_api module.
        mock_async_pw_ctx = AsyncMock()
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_page = AsyncMock()

        mock_pw_instance = MagicMock()
        mock_pw_instance.chromium = MagicMock(launch=AsyncMock(return_value=mock_browser))
        mock_async_pw_ctx.__aenter__ = AsyncMock(return_value=mock_pw_instance)
        mock_async_pw_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_context.storage_state = AsyncMock(return_value={})

        mock_strategy = AsyncMock()
        mock_strategy.fill = AsyncMock(return_value=MagicMock(success=True, error=None))
        mock_strategy.upload_files = AsyncMock()
        mock_strategy.submit = AsyncMock(return_value=True)

        mock_async_playwright_fn = MagicMock(return_value=mock_async_pw_ctx)

        with patch.dict("sys.modules", {"playwright": MagicMock(), "playwright.async_api": MagicMock(async_playwright=mock_async_playwright_fn)}):
            with patch.object(applicant, "_select_strategy", return_value=mock_strategy):
                with caplog.at_level(logging.WARNING):
                    await applicant.apply_to_job(job)

        assert any("Weak match" in record.message for record in caplog.records)

    def test_no_warning_on_good_score(self):
        """Score >= threshold should not trigger weak match warning."""
        job = _make_job(score=7)
        assert job.score >= WEAK_MATCH_THRESHOLD


# --- Applicant: confirm_submit gate ---


class TestApplicantConfirmSubmit:
    @pytest.mark.asyncio
    async def test_blocks_submit_without_confirm(self, tmp_path, caplog):
        """Without confirm_submit, the application should be treated as dry_run."""
        applicant = Applicant(
            profile=SAMPLE_PROFILE,
            session_dir=tmp_path / "sessions",
            dry_run=False,
            confirm_submit=False,
        )
        job = _make_job(score=8)

        mock_async_pw_ctx = AsyncMock()
        mock_browser = AsyncMock()
        mock_context = AsyncMock()
        mock_page = AsyncMock()

        mock_pw_instance = MagicMock()
        mock_pw_instance.chromium = MagicMock(launch=AsyncMock(return_value=mock_browser))
        mock_async_pw_ctx.__aenter__ = AsyncMock(return_value=mock_pw_instance)
        mock_async_pw_ctx.__aexit__ = AsyncMock(return_value=False)

        mock_browser.new_context = AsyncMock(return_value=mock_context)
        mock_context.new_page = AsyncMock(return_value=mock_page)
        mock_context.storage_state = AsyncMock(return_value={})

        mock_strategy = AsyncMock()
        mock_strategy.fill = AsyncMock(return_value=MagicMock(success=True, error=None))
        mock_strategy.upload_files = AsyncMock()
        mock_strategy.submit = AsyncMock(return_value=True)

        mock_async_playwright_fn = MagicMock(return_value=mock_async_pw_ctx)

        with patch.dict("sys.modules", {"playwright": MagicMock(), "playwright.async_api": MagicMock(async_playwright=mock_async_playwright_fn)}):
            with patch.object(applicant, "_select_strategy", return_value=mock_strategy):
                with caplog.at_level(logging.WARNING):
                    result = await applicant.apply_to_job(job)

        # Should be treated as dry_run since confirm_submit is False
        assert result.status == "dry_run"
        assert any("confirm_submit" in record.message for record in caplog.records)
        # Submit should NOT have been called
        mock_strategy.submit.assert_not_called()

    def test_eligibility_check(self, tmp_path):
        applicant = Applicant(
            profile=SAMPLE_PROFILE,
            session_dir=tmp_path / "sessions",
        )
        # Eligible job
        eligible_job = _make_job(status="tailored")
        assert applicant.is_eligible(eligible_job) is True

        # Missing resume
        no_resume = _make_job(resume_path=None)
        assert applicant.is_eligible(no_resume) is False

        # Missing cover letter
        no_cl = _make_job(cover_letter_path=None)
        assert applicant.is_eligible(no_cl) is False

        # Wrong status
        wrong_status = _make_job(status="new")
        assert applicant.is_eligible(wrong_status) is False


# --- Cover letter: company mention validation ---


class TestCoverLetterCompanyMention:
    def test_validates_company_mention(self):
        from job_hunter.tailor.cover_letter import validate_cover_letter
        from job_hunter.tailor.validator import ValidationMode

        # Text that mentions the company
        good_text = (
            "At TestCo, the focus on distributed systems aligns with my experience "
            "building REST APIs at TechCo. I reduced API latency by 40% through "
            "strategic caching and am eager to apply similar techniques to your "
            "backend infrastructure."
        )
        result = validate_cover_letter(good_text, "TestCo", mode=ValidationMode.STRICT)
        # Should not have a company-mention error
        company_issues = [
            i for i in (result.errors + result.warnings)
            if "company" in i.message.lower() or "mention" in i.message.lower()
        ]
        assert len(company_issues) == 0

    def test_fails_without_company_mention(self):
        from job_hunter.tailor.cover_letter import validate_cover_letter
        from job_hunter.tailor.validator import ValidationMode

        # Text that does NOT mention the company
        bad_text = (
            "I have extensive experience building REST APIs and reducing latency. "
            "My work at TechCo involved Django and Redis caching strategies that "
            "improved performance significantly."
        )
        result = validate_cover_letter(bad_text, "TargetCorp", mode=ValidationMode.STRICT)
        # Should have a company-mention issue
        all_issues = result.errors + result.warnings
        company_issues = [
            i for i in all_issues
            if "company" in i.message.lower() or "TargetCorp" in i.message
        ]
        assert len(company_issues) > 0


# --- Outreach: 300 char limit enforcement ---


class TestOutreachCharLimit:
    @pytest.mark.asyncio
    async def test_enforces_300_char_limit(self):
        mock_llm = AsyncMock()
        # Return messages that exceed 300 chars
        long_msg = "A" * 250 + ". " + "B" * 100 + ". Short end."
        mock_llm.generate.return_value = json.dumps({
            "targets": [
                {
                    "role": "peer",
                    "name_suggestion": "Engineer",
                    "message": long_msg,
                    "char_count": len(long_msg),
                }
            ]
        })
        job = _make_job()
        result = await generate_outreach(
            job,
            {"name": "Test", "skills": ["Python"]},
            mock_llm,
        )
        for target in result["targets"]:
            assert len(target["message"]) <= 300

    def test_truncate_to_limit_respects_sentence_boundary(self):
        text = "First sentence. Second sentence. Third sentence that is really long."
        truncated = _truncate_to_limit(text, 40)
        assert len(truncated) <= 40
        # Should end at a sentence boundary if possible
        assert truncated.endswith(".") or truncated.endswith(" ")

    def test_truncate_to_limit_short_text_unchanged(self):
        text = "Short text."
        assert _truncate_to_limit(text, 300) == text
