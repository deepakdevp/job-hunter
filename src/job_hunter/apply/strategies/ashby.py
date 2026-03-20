"""Ashby ATS form filler strategy."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from job_hunter.apply.strategies.base import BaseFormFiller, FillResult

if TYPE_CHECKING:
    from playwright.async_api import Page

    from job_hunter.database import Job

logger = logging.getLogger(__name__)


class AshbyFormFiller(BaseFormFiller):
    """Form filler for Ashby ATS (jobs.ashbyhq.com)."""

    FIELD_SELECTORS: dict[str, str] = {
        "name": 'input[name="name"]',
        "email": 'input[name="email"]',
        "phone": 'input[name="phone"]',
        "resume": 'input[type="file"]',
    }

    SUBMIT_BUTTON: str = 'button[type="submit"]'

    async def detect(self, page: Page) -> bool:
        """Return *True* if the page URL contains ashbyhq.com."""
        return "ashbyhq.com" in page.url

    async def fill(self, page: Page, job: Job, profile: dict) -> FillResult:
        """Fill the Ashby application form fields."""
        filled = 0
        skipped = 0

        for key, selector in self.FIELD_SELECTORS.items():
            if key == "resume":
                continue
            value = profile.get(key, "")
            if not value:
                skipped += 1
                continue
            element = await page.query_selector(selector)
            if element:
                await element.fill(value)
                filled += 1
                logger.debug("Filled %s via %s", key, selector)
            else:
                skipped += 1

        return FillResult(success=filled > 0, fields_filled=filled, fields_skipped=skipped)

    async def upload_files(self, page: Page, job: Job) -> bool:
        """Upload résumé via the file input."""
        selector = self.FIELD_SELECTORS["resume"]
        file_input = await page.query_selector(selector)
        if file_input and job.resume_path:
            path = Path(job.resume_path)
            if path.exists():
                await file_input.set_input_files(str(path))
                logger.info("Uploaded resume: %s", path.name)
                return True
        return False

    async def submit(self, page: Page) -> bool:
        """Click the Ashby submit button."""
        btn = await page.query_selector(self.SUBMIT_BUTTON)
        if btn and await btn.is_visible():
            await btn.click()
            logger.info("Clicked submit via %s", self.SUBMIT_BUTTON)
            return True
        logger.warning("Submit button not found: %s", self.SUBMIT_BUTTON)
        return False
