"""Japan-specific form fillers: Wantedly, Green, CareerCross."""
from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from job_hunter.apply.strategies.base import BaseFormFiller, FillResult

if TYPE_CHECKING:
    from playwright.async_api import Page

    from job_hunter.database import Job

logger = logging.getLogger(__name__)


class WantedlyFormFiller(BaseFormFiller):
    """Form filler for Wantedly (wantedly.com).

    Wantedly uses a "talk to us" / interest flow — standard fill + submit.
    """

    FIELD_SELECTORS: dict[str, str] = {
        "name": 'input[name="name"]',
        "email": 'input[name="email"]',
        "resume": 'input[type="file"]',
    }
    SUBMIT_BUTTON: str = 'button[type="submit"]'

    async def detect(self, page: Page) -> bool:
        """Return *True* if the page URL contains wantedly.com."""
        return "wantedly.com" in page.url

    async def fill(self, page: Page, job: Job, profile: dict) -> FillResult:
        """Fill visible text fields by selector."""
        filled = 0
        skipped = 0

        field_values: dict[str, str] = {
            "name": profile.get("name", ""),
            "email": profile.get("email", ""),
        }

        for key, selector in self.FIELD_SELECTORS.items():
            if key == "resume":
                continue
            value = field_values.get(key, "")
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
            except Exception:  # noqa: BLE001
                skipped += 1

        return FillResult(success=filled > 0, fields_filled=filled, fields_skipped=skipped)

    async def upload_files(self, page: Page, job: Job) -> bool:
        """Upload resume via file input."""
        selector = self.FIELD_SELECTORS.get("resume", 'input[type="file"]')
        if not job.resume_path:
            return False
        path = Path(job.resume_path)
        if not path.exists():
            return False
        try:
            el = await page.query_selector(selector)
            if el:
                await el.set_input_files(str(path))
                logger.info("Uploaded resume: %s", path.name)
                return True
        except Exception:  # noqa: BLE001
            logger.exception("Failed to upload resume on Wantedly")
        return False

    async def submit(self, page: Page) -> bool:
        """Click the submit button."""
        try:
            btn = await page.query_selector(self.SUBMIT_BUTTON)
            if btn and await btn.is_visible():
                await btn.click()
                logger.info("Clicked submit on Wantedly")
                return True
        except Exception:  # noqa: BLE001
            logger.exception("Failed to submit on Wantedly")
        return False


class GreenFormFiller(BaseFormFiller):
    """Form filler for Green Japan (green-japan.com)."""

    FIELD_SELECTORS: dict[str, str] = {
        "name": 'input[name="name"]',
        "email": 'input[name="email"]',
        "phone": 'input[name="phone"]',
        "resume": 'input[type="file"]',
    }
    SUBMIT_BUTTON: str = 'button[type="submit"]'

    async def detect(self, page: Page) -> bool:
        """Return *True* if the page URL contains green-japan.com."""
        return "green-japan.com" in page.url

    async def fill(self, page: Page, job: Job, profile: dict) -> FillResult:
        """Fill visible text fields by selector."""
        filled = 0
        skipped = 0

        field_values: dict[str, str] = {
            "name": profile.get("name", ""),
            "email": profile.get("email", ""),
            "phone": profile.get("phone", ""),
        }

        for key, selector in self.FIELD_SELECTORS.items():
            if key == "resume":
                continue
            value = field_values.get(key, "")
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
            except Exception:  # noqa: BLE001
                skipped += 1

        return FillResult(success=filled > 0, fields_filled=filled, fields_skipped=skipped)

    async def upload_files(self, page: Page, job: Job) -> bool:
        """Upload resume via file input."""
        selector = self.FIELD_SELECTORS.get("resume", 'input[type="file"]')
        if not job.resume_path:
            return False
        path = Path(job.resume_path)
        if not path.exists():
            return False
        try:
            el = await page.query_selector(selector)
            if el:
                await el.set_input_files(str(path))
                logger.info("Uploaded resume: %s", path.name)
                return True
        except Exception:  # noqa: BLE001
            logger.exception("Failed to upload resume on Green")
        return False

    async def submit(self, page: Page) -> bool:
        """Click the submit button."""
        try:
            btn = await page.query_selector(self.SUBMIT_BUTTON)
            if btn and await btn.is_visible():
                await btn.click()
                logger.info("Clicked submit on Green")
                return True
        except Exception:  # noqa: BLE001
            logger.exception("Failed to submit on Green")
        return False


class CareerCrossFormFiller(BaseFormFiller):
    """Form filler for CareerCross (careercross.com)."""

    FIELD_SELECTORS: dict[str, str] = {
        "name": "#name",
        "email": "#email",
        "phone": "#phone",
        "resume": 'input[type="file"]',
    }
    SUBMIT_BUTTON: str = 'button[type="submit"]'

    async def detect(self, page: Page) -> bool:
        """Return *True* if the page URL contains careercross.com."""
        return "careercross.com" in page.url

    async def fill(self, page: Page, job: Job, profile: dict) -> FillResult:
        """Fill visible text fields by selector."""
        filled = 0
        skipped = 0

        field_values: dict[str, str] = {
            "name": profile.get("name", ""),
            "email": profile.get("email", ""),
            "phone": profile.get("phone", ""),
        }

        for key, selector in self.FIELD_SELECTORS.items():
            if key == "resume":
                continue
            value = field_values.get(key, "")
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
            except Exception:  # noqa: BLE001
                skipped += 1

        return FillResult(success=filled > 0, fields_filled=filled, fields_skipped=skipped)

    async def upload_files(self, page: Page, job: Job) -> bool:
        """Upload resume via file input."""
        selector = self.FIELD_SELECTORS.get("resume", 'input[type="file"]')
        if not job.resume_path:
            return False
        path = Path(job.resume_path)
        if not path.exists():
            return False
        try:
            el = await page.query_selector(selector)
            if el:
                await el.set_input_files(str(path))
                logger.info("Uploaded resume: %s", path.name)
                return True
        except Exception:  # noqa: BLE001
            logger.exception("Failed to upload resume on CareerCross")
        return False

    async def submit(self, page: Page) -> bool:
        """Click the submit button."""
        try:
            btn = await page.query_selector(self.SUBMIT_BUTTON)
            if btn and await btn.is_visible():
                await btn.click()
                logger.info("Clicked submit on CareerCross")
                return True
        except Exception:  # noqa: BLE001
            logger.exception("Failed to submit on CareerCross")
        return False
