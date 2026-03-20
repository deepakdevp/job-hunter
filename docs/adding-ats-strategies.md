# Adding ATS Strategies

This tutorial explains how to add a new ATS (Applicant Tracking System) form-filling strategy for `hunt apply`.

## How it works

Job Hunter uses the **strategy pattern** for auto-apply. When a job URL is processed:

1. `detect_platform(url)` matches the URL against regex patterns in `PLATFORM_PATTERNS`
2. The matching `BaseFormFiller` subclass handles the form
3. If no pattern matches, the `GenericFormFiller` fallback is used

## 1. Create the strategy file

Create `src/job_hunter/apply/strategies/my_ats.py`:

```python
from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from job_hunter.apply.strategies.base import BaseFormFiller, FillResult

if TYPE_CHECKING:
    from playwright.async_api import Page
    from job_hunter.database import Job

logger = logging.getLogger(__name__)


class MyATSFormFiller(BaseFormFiller):
    """Form filler for MyATS job application pages."""

    async def detect(self, page: Page) -> bool:
        """Return True if the current page is a MyATS application form."""
        return await page.locator(".my-ats-apply-form").count() > 0

    async def fill(self, page: Page, job: Job, profile: dict) -> FillResult:
        """Fill the application form fields."""
        filled = 0

        # Fill name
        name_input = page.locator("input[name='full_name']")
        if await name_input.count() > 0:
            await name_input.fill(profile.get("name", ""))
            filled += 1

        # Fill email
        email_input = page.locator("input[name='email']")
        if await email_input.count() > 0:
            await email_input.fill(profile.get("email", ""))
            filled += 1

        return FillResult(success=True, fields_filled=filled)

    async def upload_files(self, page: Page, job: Job) -> bool:
        """Upload resume and cover letter."""
        if job.resume_path:
            file_input = page.locator("input[type='file']").first
            if await file_input.count() > 0:
                await file_input.set_input_files(job.resume_path)
                return True
        return False

    async def submit(self, page: Page) -> bool:
        """Click the submit button."""
        submit_btn = page.locator("button[type='submit']")
        if await submit_btn.count() > 0:
            await submit_btn.click()
            return True
        return False

    async def handle_wizard(self, page: Page) -> bool:
        """Navigate multi-step forms. Optional -- defaults to no-op."""
        # Click "Next" buttons if the form has multiple pages
        while True:
            next_btn = page.locator("button.next-step")
            if await next_btn.count() == 0:
                break
            await next_btn.click()
            await page.wait_for_load_state("networkidle")
        return True
```

## 2. Register the URL pattern

In `src/job_hunter/apply/strategies/base.py`, add a pattern to `PLATFORM_PATTERNS`:

```python
PLATFORM_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    # ... existing patterns ...
    (re.compile(r"myats\.com"), "my_ats"),      # add this
]
```

## 3. Register in the applicant

In `src/job_hunter/apply/applicant.py`, import and map your strategy:

```python
from job_hunter.apply.strategies.my_ats import MyATSFormFiller

STRATEGY_MAP = {
    # ... existing strategies ...
    "my_ats": MyATSFormFiller,
}
```

## 4. Test with dry-run

```bash
# Test against a specific job URL
hunt apply --job-url "https://myats.com/jobs/12345" --dry-run
```

The `--dry-run` flag fills the form without clicking submit.

## BaseFormFiller API

```python
class BaseFormFiller(ABC):
    async def detect(self, page: Page) -> bool: ...
    async def fill(self, page: Page, job: Job, profile: dict) -> FillResult: ...
    async def upload_files(self, page: Page, job: Job) -> bool: ...
    async def submit(self, page: Page) -> bool: ...
    async def handle_wizard(self, page: Page) -> bool: ...  # optional
```

## Existing strategies

| File | Platform | URL pattern |
|------|----------|-------------|
| `workday.py` | Workday | `myworkdayjobs.com` |
| `greenhouse.py` | Greenhouse | `boards.greenhouse.io` |
| `lever.py` | Lever | `jobs.lever.co` |
| `ashby.py` | Ashby | `jobs.ashbyhq.com` |
| `indeed.py` | Indeed | `indeed.com` |
| `japan.py` | Japan boards | `wantedly.com`, `green-japan.com`, `careercross.com` |
| `generic.py` | Fallback | any unmatched URL |
