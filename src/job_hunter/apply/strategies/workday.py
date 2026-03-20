"""Workday multi-step wizard form filler strategy."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from job_hunter.apply.strategies.base import BaseFormFiller, FillResult

if TYPE_CHECKING:
    from playwright.async_api import Page

    from job_hunter.database import Job

logger = logging.getLogger(__name__)

_MAX_WIZARD_STEPS = 6


class WorkdayFormFiller(BaseFormFiller):
    """Form filler for Workday ATS multi-step application wizards."""

    NEXT_BUTTON = 'button[data-automation-id="bottom-navigation-next-button"]'
    SUBMIT_BUTTON = 'button[data-automation-id="bottom-navigation-next-button"]'

    STEP_SELECTORS: list[str] = [
        '[data-automation-id="myExperience"]',
        '[data-automation-id="voluntaryDisclosures"]',
        '[data-automation-id="selfIdentification"]',
    ]

    FIELD_SELECTORS: dict[str, str] = {
        "first_name": 'input[data-automation-id="legalNameSection_firstName"]',
        "last_name": 'input[data-automation-id="legalNameSection_lastName"]',
        "email": 'input[data-automation-id="email"]',
        "phone": 'input[data-automation-id="phone-number"]',
        "resume": 'input[data-automation-id="file-upload-input-ref"]',
    }

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    async def detect(self, page: Page) -> bool:
        """Return *True* if the current page is a Workday application."""
        return "myworkdayjobs.com" in page.url

    # ------------------------------------------------------------------
    # Core actions
    # ------------------------------------------------------------------

    async def fill(self, page: Page, job: Job, profile: dict) -> FillResult:
        """Fill known Workday fields from *profile*.

        Splits the profile ``name`` into first and last name components.
        """
        filled = 0
        skipped = 0

        # Split full name into first / last.
        full_name = profile.get("name", "")
        parts = full_name.strip().split(None, 1)
        first_name = parts[0] if parts else ""
        last_name = parts[1] if len(parts) > 1 else ""

        values: dict[str, str] = {
            "first_name": first_name,
            "last_name": last_name,
            "email": profile.get("email", ""),
            "phone": profile.get("phone", ""),
        }

        for key, selector in self.FIELD_SELECTORS.items():
            if key == "resume":
                continue  # handled by upload_files

            value = values.get(key, "")
            if not value:
                skipped += 1
                continue

            try:
                el = await page.query_selector(selector)
                if el:
                    await el.fill(value)
                    filled += 1
                    logger.debug("Filled %s via %s", key, selector)
                else:
                    skipped += 1
                    logger.debug("Selector not found for %s: %s", key, selector)
            except Exception:  # noqa: BLE001
                skipped += 1
                logger.warning("Failed to fill %s", key, exc_info=True)

        return FillResult(success=filled > 0, fields_filled=filled, fields_skipped=skipped)

    async def upload_files(self, page: Page, job: Job) -> bool:
        """Upload resume via the Workday file input."""
        selector = self.FIELD_SELECTORS["resume"]

        if not job.resume_path:
            logger.info("No resume path set on job; skipping upload")
            return False

        path = Path(job.resume_path)
        if not path.exists():
            logger.warning("Resume file not found: %s", path)
            return False

        try:
            el = await page.query_selector(selector)
            if el:
                await el.set_input_files(str(path))
                logger.info("Uploaded resume: %s", path.name)
                return True
            logger.warning("File upload input not found: %s", selector)
        except Exception:  # noqa: BLE001
            logger.warning("Failed to upload resume", exc_info=True)

        return False

    async def submit(self, page: Page) -> bool:
        """Click the Workday submit button (same as next on the last page)."""
        try:
            btn = await page.query_selector(self.SUBMIT_BUTTON)
            if btn and await btn.is_visible():
                await btn.click()
                logger.info("Clicked Workday submit button")
                return True
        except Exception:  # noqa: BLE001
            logger.warning("Failed to click submit", exc_info=True)

        logger.warning("Workday submit button not found or not visible")
        return False

    # ------------------------------------------------------------------
    # Wizard navigation
    # ------------------------------------------------------------------

    async def handle_wizard(self, page: Page) -> bool:
        """Navigate up to *_MAX_WIZARD_STEPS* steps by clicking the next button.

        Returns *True* if the wizard was navigated (or there were no steps),
        *False* if navigation failed.
        """
        for step in range(_MAX_WIZARD_STEPS):
            try:
                btn = await page.query_selector(self.NEXT_BUTTON)
                if not btn or not await btn.is_visible():
                    logger.debug("No next button visible at step %d; wizard done", step)
                    return True

                await btn.click()
                logger.info("Clicked next at wizard step %d", step)
                # Wait briefly for the next page to load.
                await page.wait_for_load_state("networkidle")
            except Exception:  # noqa: BLE001
                logger.warning("Wizard navigation failed at step %d", step, exc_info=True)
                return False

        logger.info("Completed all %d wizard steps", _MAX_WIZARD_STEPS)
        return True
