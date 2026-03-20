"""Indeed form filler — handles Indeed's apply flow."""

from __future__ import annotations

import logging
from pathlib import Path
from typing import TYPE_CHECKING

from job_hunter.apply.strategies.base import BaseFormFiller, FillResult

if TYPE_CHECKING:
    from playwright.async_api import Page

    from job_hunter.database import Job

logger = logging.getLogger(__name__)


class IndeedFormFiller(BaseFormFiller):
    """Strategy for Indeed job applications.

    Indeed has two apply flows:
    1. "Indeed Apply" — a multi-step form hosted on Indeed
    2. "Apply on company site" — redirects to external ATS

    This strategy handles the Indeed Apply flow. For external redirects,
    it navigates there and falls back to generic filling.
    """

    async def detect(self, page: Page) -> bool:
        """Return True if on an Indeed job page."""
        return "indeed.com" in page.url

    async def fill(self, page: Page, job: Job, profile: dict) -> FillResult:
        """Click apply, then fill the Indeed application form."""
        # Step 1: Find and click the Apply button on the job listing page
        apply_clicked = await self._click_apply_button(page)
        if not apply_clicked:
            return FillResult(success=False, error="Could not find Apply button on Indeed page")

        # Wait for navigation / modal
        await page.wait_for_timeout(3000)

        # Step 2: Check if we got redirected to an external site
        if "indeed.com" not in page.url:
            logger.info("Redirected to external site: %s", page.url)
            # Fall back to generic filling on external site
            from job_hunter.apply.strategies.generic import GenericFormFiller

            generic = GenericFormFiller()
            return await generic.fill(page, job, profile)

        # Step 3: Handle Indeed's own apply flow
        return await self._fill_indeed_form(page, job, profile)

    async def _click_apply_button(self, page: Page) -> bool:
        """Find and click the Apply/応募 button on the Indeed job page."""
        # Indeed Japan and international have various apply button patterns
        selectors = [
            # Indeed Apply button (various forms)
            "button:has-text('Apply now')",
            "button:has-text('Apply on company site')",
            "button:has-text('応募する')",
            "button:has-text('応募画面へ進む')",
            "button:has-text('今すぐ応募')",
            "a:has-text('Apply now')",
            "a:has-text('Apply on company site')",
            "a:has-text('応募する')",
            "a:has-text('応募画面へ進む')",
            "a:has-text('今すぐ応募')",
            # Indeed's specific button IDs/classes
            "#indeedApplyButton",
            "[data-testid='indeedApplyButton']",
            ".jobsearch-IndeedApplyButton-newDesign",
            ".ia-IndeedApplyButton",
            # Generic apply patterns
            "button:has-text('Apply')",
            "a:has-text('Apply')",
        ]

        for selector in selectors:
            try:
                btn = await page.query_selector(selector)
                if btn and await btn.is_visible():
                    await btn.click()
                    logger.info("Clicked apply button: %s", selector)
                    return True
            except Exception:
                continue

        # Try clicking any element with apply-related text
        try:
            apply_el = page.locator("text=/[Aa]pply|応募/").first
            if await apply_el.is_visible():
                await apply_el.click()
                logger.info("Clicked apply via text match")
                return True
        except Exception:
            pass

        logger.warning("No apply button found on Indeed page")
        return False

    async def _fill_indeed_form(self, page: Page, job: Job, profile: dict) -> FillResult:
        """Fill Indeed's multi-step application form."""
        filled = 0

        # Indeed's apply form fields
        field_mapping = {
            "name": profile.get("name", ""),
            "email": profile.get("email", ""),
            "phone": profile.get("phone", ""),
        }

        # Try filling visible inputs
        inputs = await page.query_selector_all("input:visible, textarea:visible")
        for inp in inputs:
            input_type = (await inp.get_attribute("type") or "text").lower()
            if input_type in {"hidden", "file", "submit", "button", "checkbox", "radio"}:
                continue

            label_text = await self._get_label(page, inp)
            if not label_text:
                continue

            label_lower = label_text.lower()
            value = None

            if any(w in label_lower for w in ("name", "名前", "氏名")):
                value = field_mapping["name"]
            elif any(w in label_lower for w in ("email", "メール", "eメール")):
                value = field_mapping["email"]
            elif any(w in label_lower for w in ("phone", "電話", "携帯")):
                value = field_mapping["phone"]
            elif any(
                w in label_lower for w in ("cover letter", "カバーレター", "志望動機", "message")
            ):
                if job.cover_letter_path:
                    cl_path = Path(job.cover_letter_path)
                    if cl_path.exists() and cl_path.suffix == ".txt":
                        value = cl_path.read_text()

            if value:
                await inp.fill(value)
                filled += 1
                logger.info("Filled field '%s'", label_text)

        # Handle multi-step: click Continue/Next buttons
        await self._handle_steps(page, job, profile)

        return FillResult(success=True, fields_filled=filled)

    async def _handle_steps(self, page: Page, job: Job, profile: dict) -> None:
        """Navigate through Indeed's multi-step form."""
        for step in range(5):  # max 5 steps
            # Look for Continue/Next button
            next_selectors = [
                "button:has-text('Continue')",
                "button:has-text('次へ')",
                "button:has-text('Next')",
                "button:has-text('続ける')",
            ]
            clicked = False
            for sel in next_selectors:
                try:
                    btn = await page.query_selector(sel)
                    if btn and await btn.is_visible():
                        await btn.click()
                        await page.wait_for_timeout(2000)
                        clicked = True
                        logger.info("Clicked next button (step %d)", step + 1)
                        break
                except Exception:
                    continue

            if not clicked:
                break

            # Try filling any new fields on the new step
            await self._fill_indeed_form(page, job, profile)

    async def upload_files(self, page: Page, job: Job) -> bool:
        """Upload resume file."""
        file_inputs = await page.query_selector_all("input[type='file']")
        uploaded = False

        for fi in file_inputs:
            if job.resume_path and Path(job.resume_path).exists():
                try:
                    await fi.set_input_files(job.resume_path)
                    uploaded = True
                    logger.info("Uploaded resume: %s", job.resume_path)
                    break
                except Exception as e:
                    logger.warning("Failed to upload file: %s", e)

        return uploaded

    async def submit(self, page: Page) -> bool:
        """Click the final submit button."""
        submit_selectors = [
            "button:has-text('Submit your application')",
            "button:has-text('Submit')",
            "button:has-text('応募を送信')",
            "button:has-text('送信')",
            "button:has-text('Apply')",
            "button[type='submit']",
        ]

        for sel in submit_selectors:
            try:
                btn = await page.query_selector(sel)
                if btn and await btn.is_visible():
                    await btn.click()
                    logger.info("Submitted via: %s", sel)
                    return True
            except Exception:
                continue

        logger.warning("No submit button found")
        return False

    @staticmethod
    async def _get_label(page: Page, element) -> str | None:
        """Extract label for a form element."""
        el_id = await element.get_attribute("id")
        if el_id:
            label_el = await page.query_selector(f"label[for='{el_id}']")
            if label_el:
                text = (await label_el.inner_text() or "").strip()
                if text:
                    return text

        for attr in ("placeholder", "name", "aria-label"):
            val = await element.get_attribute(attr)
            if val:
                return val.strip()

        return None
