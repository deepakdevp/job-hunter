"""Generic form filler — fallback strategy for unknown ATS platforms."""
from __future__ import annotations

import logging
import re
from pathlib import Path
from typing import TYPE_CHECKING

from job_hunter.apply.strategies.base import BaseFormFiller, FillResult

if TYPE_CHECKING:
    from playwright.async_api import Page

    from job_hunter.database import Job

logger = logging.getLogger(__name__)

# (compiled regex, canonical key)
_LABEL_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"(?i)\b(full\s*)?name\b"), "name"),
    (re.compile(r"(?i)\bemail\b"), "email"),
    (re.compile(r"(?i)\bphone\b|mobile|telephone"), "phone"),
    (re.compile(r"(?i)\blinkedin\b"), "linkedin"),
    (re.compile(r"(?i)\bwebsite\b|portfolio|url|github"), "website"),
    (re.compile(r"(?i)\bcity\b|location"), "location"),
    (re.compile(r"(?i)\bresume\b|cv\b"), "resume"),
    (re.compile(r"(?i)\bcover\s*letter\b"), "cover_letter"),
]


class GenericFormFiller(BaseFormFiller):
    """Heuristic form filler that matches labels to profile keys via regex."""

    SUBMIT_SELECTORS: list[str] = [
        "button[type='submit']",
        "input[type='submit']",
        "button:has-text('Submit')",
        "button:has-text('Apply')",
        "button:has-text('Send')",
        "a:has-text('Submit Application')",
    ]

    # ------------------------------------------------------------------
    # Detection
    # ------------------------------------------------------------------

    async def detect(self, page: Page) -> bool:  # noqa: ARG002
        """Always returns True — this is the fallback strategy."""
        return True

    # ------------------------------------------------------------------
    # Field mapping helpers
    # ------------------------------------------------------------------

    @staticmethod
    def _build_field_map(profile: dict) -> dict[str, str]:
        """Map canonical keys to values from *profile*."""
        return {
            "name": profile.get("name", ""),
            "email": profile.get("email", ""),
            "phone": profile.get("phone", ""),
            "linkedin": profile.get("linkedin_url", ""),
            "website": profile.get("website", ""),
            "location": profile.get("location", ""),
        }

    @staticmethod
    def _match_label_to_key(label: str) -> str | None:
        """Return the canonical field key for *label*, or ``None``."""
        for pattern, key in _LABEL_PATTERNS:
            if pattern.search(label):
                return key
        return None

    # ------------------------------------------------------------------
    # Core actions
    # ------------------------------------------------------------------

    async def fill(self, page: Page, job: Job, profile: dict) -> FillResult:
        """Fill visible text inputs by matching labels to profile fields."""
        field_map = self._build_field_map(profile)
        filled = 0
        skipped = 0

        inputs = await page.query_selector_all(
            "input:visible, textarea:visible, select:visible"
        )

        for inp in inputs:
            input_type = (await inp.get_attribute("type") or "text").lower()
            if input_type in {"hidden", "file", "submit", "button", "checkbox", "radio"}:
                continue

            # Try to extract a meaningful label string.
            label_text = await self._extract_label(page, inp)
            if not label_text:
                skipped += 1
                continue

            key = self._match_label_to_key(label_text)
            value = field_map.get(key or "")
            if value:
                await inp.fill(value)
                filled += 1
                logger.debug("Filled '%s' → %s", label_text, key)
            else:
                skipped += 1

        return FillResult(success=filled > 0, fields_filled=filled, fields_skipped=skipped)

    async def upload_files(self, page: Page, job: Job) -> bool:
        """Find file inputs and upload resume / cover letter PDFs."""
        file_inputs = await page.query_selector_all("input[type='file']")
        uploaded = False

        for fi in file_inputs:
            label_text = await self._extract_label(page, fi)
            key = self._match_label_to_key(label_text or "")

            if key == "resume" and job.resume_path:
                path = Path(job.resume_path)
                if path.exists():
                    await fi.set_input_files(str(path))
                    uploaded = True
                    logger.info("Uploaded resume: %s", path.name)

            elif key == "cover_letter" and job.cover_letter_path:
                path = Path(job.cover_letter_path)
                if path.exists():
                    await fi.set_input_files(str(path))
                    uploaded = True
                    logger.info("Uploaded cover letter: %s", path.name)

        return uploaded

    async def submit(self, page: Page) -> bool:
        """Try each submit selector until one succeeds."""
        for selector in self.SUBMIT_SELECTORS:
            try:
                btn = await page.query_selector(selector)
                if btn and await btn.is_visible():
                    await btn.click()
                    logger.info("Clicked submit via selector: %s", selector)
                    return True
            except Exception:  # noqa: BLE001
                continue
        logger.warning("No submit button found")
        return False

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    @staticmethod
    async def _extract_label(page: Page, element) -> str | None:  # noqa: ANN001
        """Best-effort label extraction for a form element."""
        # 1. Associated <label for="id">
        el_id = await element.get_attribute("id")
        if el_id:
            label_el = await page.query_selector(f"label[for='{el_id}']")
            if label_el:
                text = (await label_el.inner_text() or "").strip()
                if text:
                    return text

        # 2. placeholder
        placeholder = await element.get_attribute("placeholder")
        if placeholder:
            return placeholder.strip()

        # 3. name attribute
        name = await element.get_attribute("name")
        if name:
            return name.strip()

        # 4. aria-label
        aria = await element.get_attribute("aria-label")
        if aria:
            return aria.strip()

        return None
