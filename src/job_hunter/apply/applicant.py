"""Applicant orchestrator — drives the full browser-based apply flow."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import TYPE_CHECKING
from urllib.parse import urlparse

from job_hunter.apply.session import SessionManager
from job_hunter.apply.strategies.ashby import AshbyFormFiller
from job_hunter.apply.strategies.base import BaseFormFiller, FillResult, detect_platform
from job_hunter.apply.strategies.generic import GenericFormFiller
from job_hunter.apply.strategies.greenhouse import GreenhouseFormFiller
from job_hunter.apply.strategies.indeed import IndeedFormFiller
from job_hunter.apply.strategies.japan import (
    CareerCrossFormFiller,
    GreenFormFiller,
    WantedlyFormFiller,
)
from job_hunter.apply.strategies.lever import LeverFormFiller
from job_hunter.apply.strategies.workday import WorkdayFormFiller

if TYPE_CHECKING:
    from job_hunter.database import Job

log = logging.getLogger(__name__)

# Score threshold below which the candidate is warned about weak match.
WEAK_MATCH_THRESHOLD = 3


@dataclass
class ApplyResult:
    """Outcome of a single application attempt."""

    job_url: str
    company: str
    platform: str
    status: str  # applied / apply_failed / dry_run / skipped
    error: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        """Return a plain dict suitable for JSON serialisation."""
        return {
            "timestamp": self.timestamp,
            "url": self.job_url,
            "company": self.company,
            "platform": self.platform,
            "status": self.status,
            "error": self.error,
        }


STRATEGY_MAP: dict[str, type[BaseFormFiller]] = {
    "indeed": IndeedFormFiller,
    "workday": WorkdayFormFiller,
    "greenhouse": GreenhouseFormFiller,
    "lever": LeverFormFiller,
    "ashby": AshbyFormFiller,
    "wantedly": WantedlyFormFiller,
    "green": GreenFormFiller,
    "careercross": CareerCrossFormFiller,
    "generic": GenericFormFiller,
}

ELIGIBLE_STATUSES = {"tailored", "synced"}


class Applicant:
    """Orchestrates the end-to-end job application flow.

    Parameters
    ----------
    profile:
        Candidate profile dict (name, email, phone, etc.).
    session_dir:
        Directory where per-domain browser sessions are stored.
    llm:
        Optional LLM client for intelligent field mapping.
    log_path:
        Path to a JSON file where apply results are appended.
    dry_run:
        When *True*, fill forms but skip the final submit click.
    """

    def __init__(
        self,
        profile: dict,
        session_dir: Path | str,
        llm: object | None = None,
        log_path: Path | str | None = None,
        dry_run: bool = False,
        confirm_submit: bool = False,
    ) -> None:
        self.profile = profile
        self.session_mgr = SessionManager(Path(session_dir))
        self.llm = llm
        self.log_path = Path(log_path) if log_path else None
        self.dry_run = dry_run
        self.confirm_submit = confirm_submit

    def _select_strategy(self, url: str) -> BaseFormFiller:
        """Return the appropriate form-filler strategy for *url*."""
        platform = detect_platform(url)
        cls = STRATEGY_MAP.get(platform, GenericFormFiller)
        return cls()

    def is_eligible(self, job: Job) -> bool:
        """Return *True* if *job* is ready for application."""
        if job.status not in ELIGIBLE_STATUSES:
            return False
        if not job.resume_path:
            return False
        if not job.cover_letter_path:
            return False
        return True

    def _parse_evaluation_data(self, job: Job) -> dict | None:
        """Parse evaluation JSON from a job, returning *None* on failure."""
        if not job.evaluation:
            return None
        try:
            return json.loads(job.evaluation)
        except (json.JSONDecodeError, TypeError):
            log.warning("Could not parse evaluation data for %s", job.url)
            return None

    async def apply_to_job(self, job: Job) -> ApplyResult:
        """Run the full browser automation flow for a single *job*.

        Ethical guardrails
        ------------------
        * Warns on weak matches (score < WEAK_MATCH_THRESHOLD).
        * In non-dry-run mode, requires ``confirm_submit=True`` to actually
          click submit — otherwise the run is treated as a dry-run.
        """
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise ImportError(
                "Auto-apply requires playwright. Install with:\n"
                "  pip install job-hunter[apply]"
            )

        # --- Ethical guardrail: weak-match warning ---
        if job.score is not None and job.score < WEAK_MATCH_THRESHOLD:
            log.warning(
                "Weak match (score %d/%d) for %s at %s — consider skipping "
                "unless you have a specific reason to apply.",
                job.score,
                10,
                job.title,
                job.company,
            )

        log.info(
            "Quality-over-speed: tailoring application for %s at %s (score=%s)",
            job.title,
            job.company,
            job.score,
        )

        # --- Parse evaluation data for FieldMapper context ---
        evaluation_data = self._parse_evaluation_data(job)

        url = job.apply_url or job.url
        platform = detect_platform(url)
        strategy = self._select_strategy(url)
        domain = urlparse(url).netloc

        try:
            async with async_playwright() as pw:
                browser = await pw.chromium.launch(headless=False)

                # Restore session if available.
                context_kwargs: dict = {}
                if self.session_mgr.has_session(domain):
                    state = self.session_mgr.load_session(domain)
                    context_kwargs["storage_state"] = state

                context = await browser.new_context(**context_kwargs)
                page = await context.new_page()

                await page.goto(url, wait_until="domcontentloaded")

                # Inject evaluation context into strategy if supported.
                if evaluation_data and hasattr(strategy, "set_evaluation_data"):
                    strategy.set_evaluation_data(evaluation_data)

                # Fill the form.
                fill_result: FillResult = await strategy.fill(page, job, self.profile)
                if not fill_result.success:
                    result = ApplyResult(
                        job_url=job.url,
                        company=job.company,
                        platform=platform,
                        status="apply_failed",
                        error=fill_result.error or "fill failed",
                    )
                    self._log_result(result)
                    return result

                # Upload files.
                await strategy.upload_files(page, job)

                # --- Ethical guardrail: confirm-submit gate ---
                if self.dry_run:
                    status = "dry_run"
                elif not self.confirm_submit:
                    log.warning(
                        "Submit blocked — confirm_submit is False. "
                        "Re-run with --confirm or confirm_submit=True to submit."
                    )
                    status = "dry_run"
                else:
                    submitted = await strategy.submit(page)
                    status = "applied" if submitted else "apply_failed"

                # Save session for next time.
                state = await context.storage_state()
                self.session_mgr.save_session(domain, state)

                await browser.close()

            result = ApplyResult(
                job_url=job.url,
                company=job.company,
                platform=platform,
                status=status,
            )

            # Suggest outreach after successful application
            if status == "applied":
                log.info(
                    "Application submitted! Consider running "
                    "`hunt outreach --job-url %s` to find and contact hiring "
                    "managers on LinkedIn.",
                    job.url,
                )

        except Exception as exc:  # noqa: BLE001
            log.exception("apply_to_job failed for %s", job.url)
            result = ApplyResult(
                job_url=job.url,
                company=job.company,
                platform=platform,
                status="apply_failed",
                error=str(exc),
            )

        self._log_result(result)
        return result

    def _log_result(self, result: ApplyResult) -> None:
        """Append *result* to the JSON log file."""
        if self.log_path is None:
            return
        entries: list[dict] = []
        if self.log_path.exists():
            entries = json.loads(self.log_path.read_text())
        entries.append(result.to_dict())
        self.log_path.write_text(json.dumps(entries, indent=2))

    async def login_and_save(self, domain: str) -> None:
        """Open a browser for manual login, then save the session on close."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            raise ImportError(
                "Auto-apply requires playwright. Install with:\n"
                "  pip install job-hunter[apply]"
            )

        async with async_playwright() as pw:
            browser = await pw.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(f"https://{domain}", wait_until="domcontentloaded")

            log.info("Log in manually, then close the browser window.")
            await page.wait_for_event("close", timeout=0)

            state = await context.storage_state()
            self.session_mgr.save_session(domain, state)
            await browser.close()
