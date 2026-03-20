# Phase 7: Apply — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Automate job applications using Playwright with platform-specific ATS strategies, LLM-powered field mapping, and session persistence.

**Architecture:** Strategy pattern with a base `FormFiller` interface. Platform detection by URL domain delegates to specific handlers (Workday, Greenhouse, Lever, Ashby, Japan boards) or a generic fallback. An orchestrator (`Applicant`) manages browser lifecycle, session loading, and logging.

**Tech Stack:** Playwright (async API), Gemini LLM (field mapping), asyncio, Click CLI

---

### Task 1: Base Form Filler Interface + Platform Detection

**Files:**
- Create: `src/job_hunter/apply/__init__.py`
- Create: `src/job_hunter/apply/strategies/__init__.py`
- Create: `src/job_hunter/apply/strategies/base.py`
- Test: `tests/test_apply_base.py`

**Step 1: Write the failing test**

```python
"""Tests for apply strategy base + platform detection."""

from __future__ import annotations

import pytest

from job_hunter.apply.strategies.base import BaseFormFiller, detect_platform


def test_detect_workday():
    assert detect_platform("https://company.myworkdayjobs.com/en-US/jobs/1234") == "workday"


def test_detect_greenhouse():
    assert detect_platform("https://boards.greenhouse.io/company/jobs/1234") == "greenhouse"


def test_detect_lever():
    assert detect_platform("https://jobs.lever.co/company/1234") == "lever"


def test_detect_ashby():
    assert detect_platform("https://jobs.ashbyhq.com/company/1234") == "ashby"


def test_detect_wantedly():
    assert detect_platform("https://www.wantedly.com/projects/1234") == "wantedly"


def test_detect_green_japan():
    assert detect_platform("https://www.green-japan.com/job/1234") == "green"


def test_detect_careercross():
    assert detect_platform("https://www.careercross.com/en/job/detail-1234") == "careercross"


def test_detect_generic_fallback():
    assert detect_platform("https://randomcompany.com/careers/apply") == "generic"


def test_base_form_filler_is_abstract():
    with pytest.raises(TypeError):
        BaseFormFiller()
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_apply_base.py -v`
Expected: FAIL — ModuleNotFoundError

**Step 3: Write minimal implementation**

`src/job_hunter/apply/__init__.py`:
```python
from job_hunter.apply.strategies.base import BaseFormFiller, detect_platform

__all__ = ["BaseFormFiller", "detect_platform"]
```

`src/job_hunter/apply/strategies/__init__.py`:
```python
```

`src/job_hunter/apply/strategies/base.py`:
```python
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Any

from playwright.async_api import Page

from job_hunter.database import Job


@dataclass
class FillResult:
    """Result of a form fill attempt."""
    success: bool
    fields_filled: int = 0
    fields_skipped: int = 0
    error: str | None = None


PLATFORM_PATTERNS: list[tuple[str, str]] = [
    (r"myworkdayjobs\.com", "workday"),
    (r"boards\.greenhouse\.io", "greenhouse"),
    (r"jobs\.lever\.co", "lever"),
    (r"jobs\.ashbyhq\.com", "ashby"),
    (r"wantedly\.com", "wantedly"),
    (r"green-japan\.com", "green"),
    (r"careercross\.com", "careercross"),
]


def detect_platform(url: str) -> str:
    """Detect ATS platform from URL. Returns platform name or 'generic'."""
    for pattern, name in PLATFORM_PATTERNS:
        if re.search(pattern, url):
            return name
    return "generic"


class BaseFormFiller(ABC):
    """Base interface for platform-specific form fillers."""

    @abstractmethod
    async def detect(self, page: Page) -> bool:
        """Check if this strategy can handle the current page."""
        ...

    @abstractmethod
    async def fill(self, page: Page, job: Job, profile: dict) -> FillResult:
        """Fill all form fields."""
        ...

    @abstractmethod
    async def upload_files(self, page: Page, job: Job) -> bool:
        """Upload resume and cover letter."""
        ...

    @abstractmethod
    async def submit(self, page: Page) -> bool:
        """Click submit button."""
        ...

    async def handle_wizard(self, page: Page) -> bool:
        """Navigate multi-step forms. Override for multi-step ATS."""
        return True
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_apply_base.py -v`
Expected: 9 PASS

**Step 5: Commit**

```bash
git add src/job_hunter/apply/ tests/test_apply_base.py
git commit -m "feat(apply): base form filler interface + platform detection"
```

---

### Task 2: Session Manager

**Files:**
- Create: `src/job_hunter/apply/session.py`
- Test: `tests/test_apply_session.py`

**Step 1: Write the failing test**

```python
"""Tests for apply session manager."""

from __future__ import annotations

import json

import pytest

from job_hunter.apply.session import SessionManager


@pytest.fixture
def session_dir(tmp_path):
    return tmp_path / "sessions"


@pytest.fixture
def manager(session_dir):
    return SessionManager(session_dir)


def test_session_dir_created(session_dir):
    SessionManager(session_dir)
    assert session_dir.exists()


def test_get_session_path(manager, session_dir):
    path = manager.get_session_path("workday")
    assert path == session_dir / "workday.json"


def test_has_session_false(manager):
    assert manager.has_session("workday") is False


def test_has_session_true(manager, session_dir):
    (session_dir / "workday.json").write_text("{}")
    assert manager.has_session("workday") is True


def test_save_session(manager, session_dir):
    state = {"cookies": [{"name": "sid", "value": "abc"}]}
    manager.save_session("greenhouse", state)
    saved = json.loads((session_dir / "greenhouse.json").read_text())
    assert saved == state


def test_load_session(manager, session_dir):
    state = {"cookies": [{"name": "sid", "value": "xyz"}]}
    (session_dir / "lever.json").write_text(json.dumps(state))
    loaded = manager.load_session("lever")
    assert loaded == state


def test_load_session_missing(manager):
    assert manager.load_session("nonexistent") is None


def test_domain_from_url(manager):
    assert manager.domain_from_url("https://company.myworkdayjobs.com/en/jobs/1") == "myworkdayjobs.com"
    assert manager.domain_from_url("https://boards.greenhouse.io/acme/1") == "greenhouse.io"
    assert manager.domain_from_url("https://jobs.lever.co/acme") == "lever.co"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_apply_session.py -v`
Expected: FAIL — ModuleNotFoundError

**Step 3: Write minimal implementation**

```python
from __future__ import annotations

import json
import logging
from pathlib import Path
from urllib.parse import urlparse

logger = logging.getLogger(__name__)


class SessionManager:
    """Manage browser session state per domain."""

    def __init__(self, session_dir: Path):
        self.session_dir = session_dir
        self.session_dir.mkdir(parents=True, exist_ok=True)

    def get_session_path(self, domain: str) -> Path:
        return self.session_dir / f"{domain}.json"

    def has_session(self, domain: str) -> bool:
        return self.get_session_path(domain).exists()

    def save_session(self, domain: str, state: dict) -> None:
        path = self.get_session_path(domain)
        path.write_text(json.dumps(state, indent=2))
        logger.info(f"Session saved for {domain}")

    def load_session(self, domain: str) -> dict | None:
        path = self.get_session_path(domain)
        if not path.exists():
            return None
        return json.loads(path.read_text())

    @staticmethod
    def domain_from_url(url: str) -> str:
        """Extract registrable domain from URL (e.g., 'myworkdayjobs.com')."""
        hostname = urlparse(url).hostname or ""
        parts = hostname.split(".")
        if len(parts) >= 2:
            return ".".join(parts[-2:])
        return hostname
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_apply_session.py -v`
Expected: 8 PASS

**Step 5: Commit**

```bash
git add src/job_hunter/apply/session.py tests/test_apply_session.py
git commit -m "feat(apply): session manager for browser state persistence"
```

---

### Task 3: Generic Form Strategy

**Files:**
- Create: `src/job_hunter/apply/strategies/generic.py`
- Test: `tests/test_apply_generic.py`

**Step 1: Write the failing test**

```python
"""Tests for generic form strategy."""

from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from job_hunter.apply.strategies.generic import GenericFormFiller
from job_hunter.database import Job


@pytest.fixture
def filler():
    return GenericFormFiller()


@pytest.fixture
def sample_job():
    return Job(
        url="https://company.com/apply",
        title="Software Engineer",
        company="Acme Corp",
        location="Tokyo",
        source="indeed",
        status="tailored",
        resume_path="/tmp/resume.pdf",
        cover_letter_path="/tmp/cover.txt",
        apply_url="https://company.com/apply",
    )


@pytest.fixture
def sample_profile():
    return {
        "name": "Test User",
        "email": "test@example.com",
        "phone": "+1234567890",
        "linkedin_url": "https://linkedin.com/in/testuser",
        "website": "https://testuser.dev",
    }


def test_detect_always_true(filler):
    """Generic filler is the fallback — always returns True."""
    page = AsyncMock()
    import asyncio
    assert asyncio.run(filler.detect(page)) is True


def test_field_mapping_name(filler, sample_profile):
    mappings = filler._build_field_map(sample_profile)
    assert mappings["name"] == "Test User"
    assert mappings["email"] == "test@example.com"
    assert mappings["phone"] == "+1234567890"


def test_field_mapping_linkedin(filler, sample_profile):
    mappings = filler._build_field_map(sample_profile)
    assert mappings["linkedin"] == "https://linkedin.com/in/testuser"


def test_match_field_label_exact(filler):
    assert filler._match_label_to_key("Email Address") == "email"


def test_match_field_label_partial(filler):
    assert filler._match_label_to_key("Your Full Name") == "name"


def test_match_field_label_phone(filler):
    assert filler._match_label_to_key("Phone Number") == "phone"


def test_match_field_label_unknown(filler):
    assert filler._match_label_to_key("Favorite Color") is None


def test_submit_selector_candidates(filler):
    """Verify submit button selectors exist."""
    assert len(filler.SUBMIT_SELECTORS) > 0
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_apply_generic.py -v`
Expected: FAIL — ModuleNotFoundError

**Step 3: Write minimal implementation**

```python
from __future__ import annotations

import logging
import re
from pathlib import Path

from playwright.async_api import Page

from job_hunter.apply.strategies.base import BaseFormFiller, FillResult
from job_hunter.database import Job

logger = logging.getLogger(__name__)

# Common label → field key patterns
LABEL_PATTERNS: list[tuple[str, str]] = [
    (r"(?i)\b(full\s*)?name\b", "name"),
    (r"(?i)\bemail\b", "email"),
    (r"(?i)\bphone\b|mobile|telephone", "phone"),
    (r"(?i)\blinkedin\b", "linkedin"),
    (r"(?i)\bwebsite\b|portfolio|url|github", "website"),
    (r"(?i)\bcity\b|location", "location"),
    (r"(?i)\bcurrent\s*(company|employer)", "current_company"),
    (r"(?i)\bresume\b|cv\b", "resume"),
    (r"(?i)\bcover\s*letter\b", "cover_letter"),
]


class GenericFormFiller(BaseFormFiller):
    """Generic form filler using CSS heuristics for unknown ATS platforms."""

    SUBMIT_SELECTORS = [
        'button[type="submit"]',
        'input[type="submit"]',
        'button:has-text("Submit")',
        'button:has-text("Apply")',
        'button:has-text("Send")',
        'a:has-text("Submit Application")',
    ]

    async def detect(self, page: Page) -> bool:
        """Generic filler is the fallback — always True."""
        return True

    def _build_field_map(self, profile: dict) -> dict[str, str]:
        """Map field keys to profile values."""
        return {
            "name": profile.get("name", ""),
            "email": profile.get("email", ""),
            "phone": profile.get("phone", ""),
            "linkedin": profile.get("linkedin_url", ""),
            "website": profile.get("website", "") or profile.get("github_url", ""),
            "location": profile.get("location", ""),
            "current_company": "",
        }

    def _match_label_to_key(self, label: str) -> str | None:
        """Match a form field label to a profile key."""
        for pattern, key in LABEL_PATTERNS:
            if re.search(pattern, label):
                return key
        return None

    async def fill(self, page: Page, job: Job, profile: dict) -> FillResult:
        """Fill form fields by matching labels to profile data."""
        field_map = self._build_field_map(profile)
        filled = 0
        skipped = 0

        # Find all visible input/textarea/select fields
        inputs = await page.query_selector_all(
            "input:visible, textarea:visible, select:visible"
        )

        for inp in inputs:
            input_type = await inp.get_attribute("type") or "text"
            if input_type in ("hidden", "submit", "button", "file"):
                continue

            # Try to find label text
            label_text = ""
            inp_id = await inp.get_attribute("id")
            if inp_id:
                label_el = await page.query_selector(f'label[for="{inp_id}"]')
                if label_el:
                    label_text = (await label_el.inner_text()).strip()

            if not label_text:
                label_text = await inp.get_attribute("placeholder") or ""
            if not label_text:
                label_text = await inp.get_attribute("name") or ""
            if not label_text:
                label_text = await inp.get_attribute("aria-label") or ""

            key = self._match_label_to_key(label_text)
            if key and key in field_map and field_map[key]:
                try:
                    await inp.fill(field_map[key])
                    filled += 1
                    logger.debug(f"Filled '{label_text}' → {key}")
                except Exception as e:
                    logger.warning(f"Failed to fill '{label_text}': {e}")
                    skipped += 1
            else:
                skipped += 1

        return FillResult(success=filled > 0, fields_filled=filled, fields_skipped=skipped)

    async def upload_files(self, page: Page, job: Job) -> bool:
        """Upload resume and cover letter via file inputs."""
        uploaded = False

        file_inputs = await page.query_selector_all('input[type="file"]')
        for fi in file_inputs:
            label_text = ""
            fi_id = await fi.get_attribute("id")
            if fi_id:
                label_el = await page.query_selector(f'label[for="{fi_id}"]')
                if label_el:
                    label_text = (await label_el.inner_text()).strip()
            if not label_text:
                label_text = await fi.get_attribute("name") or ""
            if not label_text:
                label_text = await fi.get_attribute("accept") or ""

            key = self._match_label_to_key(label_text)

            if key == "cover_letter" and job.cover_letter_path and Path(job.cover_letter_path).exists():
                await fi.set_input_files(job.cover_letter_path)
                uploaded = True
                logger.info(f"Uploaded cover letter: {job.cover_letter_path}")
            elif job.resume_path and Path(job.resume_path).exists():
                # Default: upload resume for any file input
                await fi.set_input_files(job.resume_path)
                uploaded = True
                logger.info(f"Uploaded resume: {job.resume_path}")

        return uploaded

    async def submit(self, page: Page) -> bool:
        """Click submit button."""
        for selector in self.SUBMIT_SELECTORS:
            try:
                btn = await page.query_selector(selector)
                if btn and await btn.is_visible():
                    await btn.click()
                    logger.info(f"Clicked submit: {selector}")
                    await page.wait_for_load_state("networkidle", timeout=10000)
                    return True
            except Exception:
                continue
        return False
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_apply_generic.py -v`
Expected: 8 PASS

**Step 5: Commit**

```bash
git add src/job_hunter/apply/strategies/generic.py tests/test_apply_generic.py
git commit -m "feat(apply): generic form filler with CSS heuristic field matching"
```

---

### Task 4: LLM Field Mapper

**Files:**
- Create: `src/job_hunter/apply/field_mapper.py`
- Test: `tests/test_field_mapper.py`

**Step 1: Write the failing test**

```python
"""Tests for LLM-powered field mapper."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock

import pytest

from job_hunter.apply.field_mapper import FieldMapper, FieldSuggestion


@pytest.fixture
def sample_profile():
    return {
        "name": "Test User",
        "skills": ["Python", "React"],
        "target_role": "Software Engineer",
        "work_authorization": "visa_required",
        "resume_facts": {
            "companies": [{"name": "Acme", "title": "SDE 2"}],
        },
    }


@pytest.fixture
def mock_llm():
    return AsyncMock()


@pytest.mark.asyncio
async def test_map_known_field(mock_llm, sample_profile):
    mock_llm.generate.return_value = json.dumps({
        "answer": "Yes",
        "confidence": 0.95,
    })
    mapper = FieldMapper(mock_llm, sample_profile)
    result = await mapper.suggest("Are you authorized to work in Japan?")

    assert result.answer == "Yes"
    assert result.confidence >= 0.9


@pytest.mark.asyncio
async def test_map_low_confidence(mock_llm, sample_profile):
    mock_llm.generate.return_value = json.dumps({
        "answer": "Maybe",
        "confidence": 0.3,
    })
    mapper = FieldMapper(mock_llm, sample_profile)
    result = await mapper.suggest("What is your expected salary?")

    assert result.confidence < 0.5
    assert result.needs_human is True


@pytest.mark.asyncio
async def test_map_llm_error_returns_empty(mock_llm, sample_profile):
    mock_llm.generate.side_effect = Exception("LLM unavailable")
    mapper = FieldMapper(mock_llm, sample_profile)
    result = await mapper.suggest("Some question")

    assert result.answer == ""
    assert result.needs_human is True


def test_field_suggestion_needs_human_threshold():
    high = FieldSuggestion(answer="Yes", confidence=0.9)
    assert high.needs_human is False

    low = FieldSuggestion(answer="Maybe", confidence=0.4)
    assert low.needs_human is True


@pytest.mark.asyncio
async def test_prompt_includes_profile_context(mock_llm, sample_profile):
    mock_llm.generate.return_value = json.dumps({"answer": "test", "confidence": 0.8})
    mapper = FieldMapper(mock_llm, sample_profile)
    await mapper.suggest("Why do you want this job?")

    prompt = mock_llm.generate.call_args[0][0]
    assert "Test User" in prompt
    assert "Python" in prompt
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_field_mapper.py -v`
Expected: FAIL — ModuleNotFoundError

**Step 3: Write minimal implementation**

```python
from __future__ import annotations

import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.7

_FIELD_MAPPER_PROMPT = """You are filling out a job application form. Answer the following form field question
based on the candidate's profile.

## Candidate Profile
Name: {name}
Target Role: {target_role}
Skills: {skills}
Work Authorization: {work_authorization}
Current Role: {current_role} at {current_company}

## Form Field Question
"{question}"

## Instructions
- Answer concisely and appropriately for a job application form
- If it's a yes/no or selection question, give the most appropriate single answer
- If you're unsure or the question requires personal information not in the profile, set confidence low

Respond in JSON: {{"answer": "your answer", "confidence": 0.0-1.0}}
"""


@dataclass
class FieldSuggestion:
    """LLM suggestion for a form field."""
    answer: str
    confidence: float

    @property
    def needs_human(self) -> bool:
        return self.confidence < CONFIDENCE_THRESHOLD


class FieldMapper:
    """Use LLM to fill unknown form fields from profile context."""

    def __init__(self, llm, profile: dict):
        self.llm = llm
        self.profile = profile

    def _build_prompt(self, question: str) -> str:
        companies = self.profile.get("resume_facts", {}).get("companies", [])
        current = companies[0] if companies else {}

        return _FIELD_MAPPER_PROMPT.format(
            name=self.profile.get("name", ""),
            target_role=self.profile.get("target_role", ""),
            skills=", ".join(self.profile.get("skills", [])[:10]),
            work_authorization=self.profile.get("work_authorization", ""),
            current_role=current.get("title", ""),
            current_company=current.get("name", ""),
            question=question,
        )

    async def suggest(self, question: str) -> FieldSuggestion:
        """Get LLM suggestion for a form field."""
        try:
            prompt = self._build_prompt(question)
            response = await self.llm.generate(prompt, json_mode=True)
            data = json.loads(response)
            return FieldSuggestion(
                answer=str(data.get("answer", "")),
                confidence=float(data.get("confidence", 0.0)),
            )
        except Exception as e:
            logger.warning(f"Field mapper failed for '{question}': {e}")
            return FieldSuggestion(answer="", confidence=0.0)
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_field_mapper.py -v`
Expected: 5 PASS

**Step 5: Commit**

```bash
git add src/job_hunter/apply/field_mapper.py tests/test_field_mapper.py
git commit -m "feat(apply): LLM field mapper for unknown form fields"
```

---

### Task 5: Workday Strategy (Multi-Step Wizard)

**Files:**
- Create: `src/job_hunter/apply/strategies/workday.py`
- Test: `tests/test_apply_workday.py`

**Step 1: Write the failing test**

```python
"""Tests for Workday form strategy."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, PropertyMock

import pytest

from job_hunter.apply.strategies.workday import WorkdayFormFiller


@pytest.fixture
def filler():
    return WorkdayFormFiller()


def test_detect_workday_url(filler):
    page = AsyncMock()
    page.url = "https://acme.myworkdayjobs.com/en-US/External/job/1234"
    assert asyncio.run(filler.detect(page)) is True


def test_detect_non_workday(filler):
    page = AsyncMock()
    page.url = "https://greenhouse.io/jobs/1234"
    assert asyncio.run(filler.detect(page)) is False


def test_wizard_step_selectors_defined(filler):
    assert len(filler.STEP_SELECTORS) > 0


def test_next_button_selector(filler):
    assert filler.NEXT_BUTTON is not None


def test_personal_info_selectors(filler):
    """Workday has known field selectors for personal info."""
    selectors = filler.FIELD_SELECTORS
    assert "name" in selectors or "first_name" in selectors
    assert "email" in selectors
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_apply_workday.py -v`
Expected: FAIL — ModuleNotFoundError

**Step 3: Write minimal implementation**

```python
from __future__ import annotations

import logging
from pathlib import Path

from playwright.async_api import Page

from job_hunter.apply.strategies.base import BaseFormFiller, FillResult
from job_hunter.database import Job

logger = logging.getLogger(__name__)


class WorkdayFormFiller(BaseFormFiller):
    """Workday ATS multi-step wizard handler."""

    NEXT_BUTTON = 'button[data-automation-id="bottom-navigation-next-button"]'

    STEP_SELECTORS = [
        '[data-automation-id="myExperience"]',
        '[data-automation-id="voluntaryDisclosures"]',
        '[data-automation-id="selfIdentification"]',
    ]

    FIELD_SELECTORS = {
        "first_name": 'input[data-automation-id="legalNameSection_firstName"]',
        "last_name": 'input[data-automation-id="legalNameSection_lastName"]',
        "email": 'input[data-automation-id="email"]',
        "phone": 'input[data-automation-id="phone-number"]',
        "address_line1": 'input[data-automation-id="addressSection_addressLine1"]',
        "city": 'input[data-automation-id="addressSection_city"]',
        "resume": 'input[data-automation-id="file-upload-input-ref"]',
    }

    SUBMIT_BUTTON = 'button[data-automation-id="bottom-navigation-next-button"]'

    async def detect(self, page: Page) -> bool:
        return "myworkdayjobs.com" in (page.url or "")

    async def fill(self, page: Page, job: Job, profile: dict) -> FillResult:
        filled = 0
        skipped = 0

        name_parts = profile.get("name", "").split(" ", 1)
        first_name = name_parts[0] if name_parts else ""
        last_name = name_parts[1] if len(name_parts) > 1 else ""

        field_values = {
            "first_name": first_name,
            "last_name": last_name,
            "email": profile.get("email", ""),
            "phone": profile.get("phone", ""),
        }

        for key, selector in self.FIELD_SELECTORS.items():
            if key in ("resume",):
                continue
            value = field_values.get(key)
            if not value:
                skipped += 1
                continue
            try:
                el = await page.query_selector(selector)
                if el:
                    await el.fill(value)
                    filled += 1
                else:
                    skipped += 1
            except Exception as e:
                logger.warning(f"Workday fill failed for {key}: {e}")
                skipped += 1

        return FillResult(success=filled > 0, fields_filled=filled, fields_skipped=skipped)

    async def upload_files(self, page: Page, job: Job) -> bool:
        if not job.resume_path or not Path(job.resume_path).exists():
            return False
        try:
            file_input = await page.query_selector(self.FIELD_SELECTORS["resume"])
            if file_input:
                await file_input.set_input_files(job.resume_path)
                logger.info(f"Uploaded resume to Workday: {job.resume_path}")
                return True
        except Exception as e:
            logger.warning(f"Workday file upload failed: {e}")
        return False

    async def submit(self, page: Page) -> bool:
        try:
            btn = await page.query_selector(self.SUBMIT_BUTTON)
            if btn and await btn.is_visible():
                await btn.click()
                await page.wait_for_load_state("networkidle", timeout=15000)
                return True
        except Exception as e:
            logger.warning(f"Workday submit failed: {e}")
        return False

    async def handle_wizard(self, page: Page) -> bool:
        """Navigate through Workday's multi-step application."""
        max_steps = 6
        for step in range(max_steps):
            try:
                next_btn = await page.query_selector(self.NEXT_BUTTON)
                if not next_btn or not await next_btn.is_visible():
                    break
                await next_btn.click()
                await page.wait_for_load_state("networkidle", timeout=10000)
                logger.debug(f"Workday wizard step {step + 1} completed")
            except Exception as e:
                logger.warning(f"Workday wizard step {step + 1} failed: {e}")
                return False
        return True
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_apply_workday.py -v`
Expected: 5 PASS

**Step 5: Commit**

```bash
git add src/job_hunter/apply/strategies/workday.py tests/test_apply_workday.py
git commit -m "feat(apply): Workday multi-step wizard strategy"
```

---

### Task 6: Greenhouse + Lever + Ashby Strategies

**Files:**
- Create: `src/job_hunter/apply/strategies/greenhouse.py`
- Create: `src/job_hunter/apply/strategies/lever.py`
- Create: `src/job_hunter/apply/strategies/ashby.py`
- Test: `tests/test_apply_ats.py`

**Step 1: Write the failing test**

```python
"""Tests for Greenhouse, Lever, and Ashby strategies."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from job_hunter.apply.strategies.greenhouse import GreenhouseFormFiller
from job_hunter.apply.strategies.lever import LeverFormFiller
from job_hunter.apply.strategies.ashby import AshbyFormFiller


# --- Greenhouse ---

@pytest.fixture
def greenhouse():
    return GreenhouseFormFiller()


def test_greenhouse_detect(greenhouse):
    page = AsyncMock()
    page.url = "https://boards.greenhouse.io/acme/jobs/1234"
    assert asyncio.run(greenhouse.detect(page)) is True


def test_greenhouse_detect_false(greenhouse):
    page = AsyncMock()
    page.url = "https://lever.co/jobs/1234"
    assert asyncio.run(greenhouse.detect(page)) is False


def test_greenhouse_field_selectors(greenhouse):
    assert "first_name" in greenhouse.FIELD_SELECTORS
    assert "email" in greenhouse.FIELD_SELECTORS
    assert "resume" in greenhouse.FIELD_SELECTORS


def test_greenhouse_submit_selector(greenhouse):
    assert greenhouse.SUBMIT_BUTTON is not None


# --- Lever ---

@pytest.fixture
def lever():
    return LeverFormFiller()


def test_lever_detect(lever):
    page = AsyncMock()
    page.url = "https://jobs.lever.co/acme/abc-123"
    assert asyncio.run(lever.detect(page)) is True


def test_lever_detect_false(lever):
    page = AsyncMock()
    page.url = "https://greenhouse.io/jobs/1234"
    assert asyncio.run(lever.detect(page)) is False


def test_lever_field_selectors(lever):
    assert "name" in lever.FIELD_SELECTORS
    assert "email" in lever.FIELD_SELECTORS
    assert "resume" in lever.FIELD_SELECTORS


# --- Ashby ---

@pytest.fixture
def ashby():
    return AshbyFormFiller()


def test_ashby_detect(ashby):
    page = AsyncMock()
    page.url = "https://jobs.ashbyhq.com/acme/1234"
    assert asyncio.run(ashby.detect(page)) is True


def test_ashby_detect_false(ashby):
    page = AsyncMock()
    page.url = "https://lever.co/jobs/1234"
    assert asyncio.run(ashby.detect(page)) is False


def test_ashby_field_selectors(ashby):
    assert "name" in ashby.FIELD_SELECTORS
    assert "email" in ashby.FIELD_SELECTORS
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_apply_ats.py -v`
Expected: FAIL — ModuleNotFoundError

**Step 3: Write implementations**

Each strategy follows the same pattern as Workday but with platform-specific selectors. All three inherit from `BaseFormFiller` and implement `detect`, `fill`, `upload_files`, `submit` with their respective CSS selectors. Code follows the same structure as `workday.py` — detect by URL, fill by known selectors, upload via file input, submit via button selector.

`greenhouse.py`: `boards.greenhouse.io` detection, `#first_name`, `#last_name`, `#email`, `#phone`, `input[type="file"]` for resume, `#submit_app` submit button.

`lever.py`: `jobs.lever.co` detection, `.application-name input`, `.application-email input`, `.application-phone input`, `input[type="file"]` for resume, `.postings-btn-submit` submit.

`ashby.py`: `jobs.ashbyhq.com` detection, `input[name="name"]`, `input[name="email"]`, `input[name="phone"]`, `input[type="file"]` for resume, `button[type="submit"]` submit.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_apply_ats.py -v`
Expected: 10 PASS

**Step 5: Commit**

```bash
git add src/job_hunter/apply/strategies/greenhouse.py src/job_hunter/apply/strategies/lever.py src/job_hunter/apply/strategies/ashby.py tests/test_apply_ats.py
git commit -m "feat(apply): Greenhouse, Lever, and Ashby ATS strategies"
```

---

### Task 7: Japan Strategies (Wantedly, Green, CareerCross)

**Files:**
- Create: `src/job_hunter/apply/strategies/japan.py`
- Test: `tests/test_apply_japan.py`

**Step 1: Write the failing test**

```python
"""Tests for Japan-specific form strategies."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock

import pytest

from job_hunter.apply.strategies.japan import (
    WantedlyFormFiller,
    GreenFormFiller,
    CareerCrossFormFiller,
)


# --- Wantedly ---

def test_wantedly_detect():
    filler = WantedlyFormFiller()
    page = AsyncMock()
    page.url = "https://www.wantedly.com/projects/1234"
    assert asyncio.run(filler.detect(page)) is True


def test_wantedly_detect_false():
    filler = WantedlyFormFiller()
    page = AsyncMock()
    page.url = "https://lever.co/jobs/1"
    assert asyncio.run(filler.detect(page)) is False


def test_wantedly_field_selectors():
    filler = WantedlyFormFiller()
    assert "name" in filler.FIELD_SELECTORS or "email" in filler.FIELD_SELECTORS


# --- Green ---

def test_green_detect():
    filler = GreenFormFiller()
    page = AsyncMock()
    page.url = "https://www.green-japan.com/job/1234"
    assert asyncio.run(filler.detect(page)) is True


def test_green_detect_false():
    filler = GreenFormFiller()
    page = AsyncMock()
    page.url = "https://wantedly.com/projects/1"
    assert asyncio.run(filler.detect(page)) is False


# --- CareerCross ---

def test_careercross_detect():
    filler = CareerCrossFormFiller()
    page = AsyncMock()
    page.url = "https://www.careercross.com/en/job/detail-1234"
    assert asyncio.run(filler.detect(page)) is True


def test_careercross_detect_false():
    filler = CareerCrossFormFiller()
    page = AsyncMock()
    page.url = "https://green-japan.com/job/1"
    assert asyncio.run(filler.detect(page)) is False
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_apply_japan.py -v`
Expected: FAIL — ModuleNotFoundError

**Step 3: Write implementation**

All three Japan strategies follow the same pattern: detect by URL domain, fill using platform-specific CSS selectors, upload files, submit. Wantedly uses a "talk to us" flow rather than traditional apply. Green and CareerCross have standard form layouts with Japanese field labels mapped to profile keys.

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_apply_japan.py -v`
Expected: 6 PASS

**Step 5: Commit**

```bash
git add src/job_hunter/apply/strategies/japan.py tests/test_apply_japan.py
git commit -m "feat(apply): Japan ATS strategies (Wantedly, Green, CareerCross)"
```

---

### Task 8: Applicant Orchestrator

**Files:**
- Create: `src/job_hunter/apply/applicant.py`
- Test: `tests/test_applicant.py`

**Step 1: Write the failing test**

```python
"""Tests for the Applicant orchestrator."""

from __future__ import annotations

import json
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from job_hunter.apply.applicant import Applicant, ApplyResult
from job_hunter.apply.strategies.base import FillResult
from job_hunter.database import Job


@pytest.fixture
def sample_job():
    return Job(
        url="https://example.com/job/1",
        title="Software Engineer",
        company="Acme Corp",
        location="Tokyo",
        source="indeed",
        status="tailored",
        apply_url="https://boards.greenhouse.io/acme/jobs/1234",
        resume_path="/tmp/resume.pdf",
        cover_letter_path="/tmp/cover.txt",
    )


@pytest.fixture
def sample_profile():
    return {
        "name": "Test User",
        "email": "test@example.com",
        "phone": "+1234567890",
    }


def test_apply_result_dataclass():
    r = ApplyResult(
        job_url="https://example.com",
        company="Acme",
        platform="greenhouse",
        status="applied",
    )
    assert r.error is None


def test_apply_result_to_dict():
    r = ApplyResult(
        job_url="https://example.com",
        company="Acme",
        platform="greenhouse",
        status="applied",
    )
    d = r.to_dict()
    assert d["company"] == "Acme"
    assert "timestamp" in d


def test_select_strategy_greenhouse(sample_profile):
    applicant = Applicant(
        profile=sample_profile, session_dir="/tmp/sessions", llm=None
    )
    strategy = applicant._select_strategy("https://boards.greenhouse.io/acme/1")
    assert strategy.__class__.__name__ == "GreenhouseFormFiller"


def test_select_strategy_workday(sample_profile):
    applicant = Applicant(
        profile=sample_profile, session_dir="/tmp/sessions", llm=None
    )
    strategy = applicant._select_strategy("https://acme.myworkdayjobs.com/1")
    assert strategy.__class__.__name__ == "WorkdayFormFiller"


def test_select_strategy_generic_fallback(sample_profile):
    applicant = Applicant(
        profile=sample_profile, session_dir="/tmp/sessions", llm=None
    )
    strategy = applicant._select_strategy("https://randomsite.com/apply")
    assert strategy.__class__.__name__ == "GenericFormFiller"


def test_job_eligible_true(sample_job, sample_profile):
    applicant = Applicant(profile=sample_profile, session_dir="/tmp/sessions", llm=None)
    assert applicant.is_eligible(sample_job) is True


def test_job_eligible_no_resume(sample_job, sample_profile):
    sample_job.resume_path = None
    applicant = Applicant(profile=sample_profile, session_dir="/tmp/sessions", llm=None)
    assert applicant.is_eligible(sample_job) is False


def test_job_eligible_wrong_status(sample_job, sample_profile):
    sample_job.status = "scored"
    applicant = Applicant(profile=sample_profile, session_dir="/tmp/sessions", llm=None)
    assert applicant.is_eligible(sample_job) is False


def test_log_result(sample_profile, tmp_path):
    applicant = Applicant(
        profile=sample_profile, session_dir="/tmp/sessions", llm=None,
        log_path=tmp_path / "apply_log.json",
    )
    result = ApplyResult(
        job_url="https://example.com",
        company="Acme",
        platform="generic",
        status="applied",
    )
    applicant._log_result(result)

    log = json.loads((tmp_path / "apply_log.json").read_text())
    assert len(log) == 1
    assert log[0]["status"] == "applied"
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_applicant.py -v`
Expected: FAIL — ModuleNotFoundError

**Step 3: Write minimal implementation**

```python
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any

from playwright.async_api import async_playwright

from job_hunter.apply.session import SessionManager
from job_hunter.apply.strategies.base import BaseFormFiller, FillResult, detect_platform
from job_hunter.apply.strategies.generic import GenericFormFiller
from job_hunter.apply.strategies.workday import WorkdayFormFiller
from job_hunter.apply.strategies.greenhouse import GreenhouseFormFiller
from job_hunter.apply.strategies.lever import LeverFormFiller
from job_hunter.apply.strategies.ashby import AshbyFormFiller
from job_hunter.apply.strategies.japan import (
    WantedlyFormFiller, GreenFormFiller, CareerCrossFormFiller,
)
from job_hunter.database import Job

logger = logging.getLogger(__name__)

STRATEGY_MAP: dict[str, type[BaseFormFiller]] = {
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


@dataclass
class ApplyResult:
    job_url: str
    company: str
    platform: str
    status: str  # "applied", "apply_failed", "skipped"
    error: str | None = None
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())

    def to_dict(self) -> dict:
        return {
            "timestamp": self.timestamp,
            "url": self.job_url,
            "company": self.company,
            "platform": self.platform,
            "status": self.status,
            "error": self.error,
        }


class Applicant:
    """Orchestrator for job applications."""

    def __init__(
        self,
        profile: dict,
        session_dir: str | Path,
        llm=None,
        log_path: Path | None = None,
        dry_run: bool = False,
    ):
        self.profile = profile
        self.session_mgr = SessionManager(Path(session_dir))
        self.llm = llm
        self.log_path = log_path or Path("output/apply_log.json")
        self.dry_run = dry_run

    def _select_strategy(self, url: str) -> BaseFormFiller:
        platform = detect_platform(url)
        cls = STRATEGY_MAP.get(platform, GenericFormFiller)
        return cls()

    def is_eligible(self, job: Job) -> bool:
        if job.status not in ELIGIBLE_STATUSES:
            return False
        if not job.resume_path or not Path(job.resume_path).exists():
            return False
        if not job.cover_letter_path or not Path(job.cover_letter_path).exists():
            return False
        return True

    async def apply_to_job(self, job: Job) -> ApplyResult:
        """Apply to a single job using browser automation."""
        apply_url = job.apply_url or job.url
        platform = detect_platform(apply_url)
        strategy = self._select_strategy(apply_url)

        try:
            async with async_playwright() as p:
                domain = self.session_mgr.domain_from_url(apply_url)
                storage = self.session_mgr.load_session(domain)

                browser = await p.chromium.launch(headless=False)
                context_kwargs: dict[str, Any] = {}
                if storage:
                    context_kwargs["storage_state"] = storage

                context = await browser.new_context(**context_kwargs)
                page = await context.new_page()

                await page.goto(apply_url, wait_until="networkidle", timeout=30000)

                # Fill form
                result = await strategy.fill(page, job, self.profile)
                logger.info(f"Filled {result.fields_filled} fields for {job.company}")

                # Upload files
                await strategy.upload_files(page, job)

                # Handle multi-step wizard
                await strategy.handle_wizard(page)

                # Submit (unless dry run)
                if not self.dry_run:
                    submitted = await strategy.submit(page)
                    if not submitted:
                        await browser.close()
                        return ApplyResult(
                            job_url=job.url, company=job.company,
                            platform=platform, status="apply_failed",
                            error="Submit button not found",
                        )

                # Save session state
                state = await context.storage_state()
                self.session_mgr.save_session(domain, state)

                await browser.close()

                status = "applied" if not self.dry_run else "dry_run"
                return ApplyResult(
                    job_url=job.url, company=job.company,
                    platform=platform, status=status,
                )

        except Exception as e:
            logger.error(f"Apply failed for {job.url}: {e}")
            return ApplyResult(
                job_url=job.url, company=job.company,
                platform=platform, status="apply_failed", error=str(e),
            )

    def _log_result(self, result: ApplyResult) -> None:
        """Append result to the apply log file."""
        self.log_path.parent.mkdir(parents=True, exist_ok=True)
        log: list[dict] = []
        if self.log_path.exists():
            log = json.loads(self.log_path.read_text())
        log.append(result.to_dict())
        self.log_path.write_text(json.dumps(log, indent=2))

    async def login_and_save(self, domain: str) -> None:
        """Open browser for manual login, save session on close."""
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=False)
            context = await browser.new_context()
            page = await context.new_page()
            await page.goto(f"https://{domain}", wait_until="networkidle")

            logger.info(f"Log in to {domain}, then close the browser window.")
            await page.wait_for_event("close", timeout=300000)

            state = await context.storage_state()
            self.session_mgr.save_session(domain, state)
            logger.info(f"Session saved for {domain}")
            await browser.close()
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_applicant.py -v`
Expected: 10 PASS

**Step 5: Commit**

```bash
git add src/job_hunter/apply/applicant.py tests/test_applicant.py
git commit -m "feat(apply): applicant orchestrator with strategy selection and logging"
```

---

### Task 9: `hunt apply` CLI Command

**Files:**
- Modify: `src/job_hunter/cli.py` (add apply command group after sync)
- Modify: `src/job_hunter/apply/__init__.py` (update exports)
- Test: verify CLI runs with `hunt apply --help`

**Step 1: Add CLI commands to `cli.py`**

Add after the `sync` command group:

```python
@cli.command()
@click.option("--job-url", default=None, help="Apply to a single job by URL")
@click.option("--all", "apply_all", is_flag=True, help="Apply to all eligible jobs")
@click.option("--limit", default=None, type=int, help="Max applications in batch mode")
@click.option("--login", "login_domain", default=None, help="Open browser to save session for a domain")
@click.option("--dry-run", is_flag=True, help="Fill forms without submitting")
@click.pass_context
def apply(ctx, job_url, apply_all, limit, login_domain, dry_run):
    """Apply to jobs using browser automation."""
    import os
    from job_hunter.config import load_config
    from job_hunter.database import JobDB
    from job_hunter.apply.applicant import Applicant

    config = load_config(ctx.obj["config_dir"])
    config_dir = ctx.obj["config_dir"]

    profile_path = config_dir / "profile.json"
    if not profile_path.exists():
        console.print("[red]profile.json not found[/]")
        raise SystemExit(1)

    import json
    profile = json.loads(profile_path.read_text())

    llm = None
    try:
        from job_hunter.llm.base import get_provider
        llm = get_provider(config.llm_provider, api_key=config.gemini_api_key, model=config.llm_model)
    except Exception:
        pass

    applicant = Applicant(
        profile=profile,
        session_dir=config_dir / "sessions",
        llm=llm,
        log_path=config_dir / "output" / "apply_log.json",
        dry_run=dry_run,
    )

    # Login mode
    if login_domain:
        console.print(f"[bold]Opening browser for {login_domain} — log in then close the window[/]")
        asyncio.run(applicant.login_and_save(login_domain))
        console.print(f"[green]Session saved for {login_domain}[/]")
        return

    db = JobDB(config_dir / "jobs.db")

    # Single job mode
    if job_url:
        job = db.get_job(job_url)
        if not job:
            console.print(f"[red]Job not found: {job_url}[/]")
            db.close()
            raise SystemExit(1)

        console.print(f"[bold]Applying: {job.title} @ {job.company}[/]")
        result = asyncio.run(applicant.apply_to_job(job))
        applicant._log_result(result)

        if result.status == "applied":
            job.status = "applied"
            db.upsert_job(job)
            console.print(f"[green bold]✓ Applied successfully[/]")
        elif result.status == "dry_run":
            console.print(f"[yellow]Dry run — form filled but not submitted[/]")
        else:
            job.status = "apply_failed"
            db.upsert_job(job)
            console.print(f"[red]✗ Failed: {result.error}[/]")

        db.close()
        return

    # Batch mode
    if not apply_all:
        console.print("[yellow]Use --job-url or --all[/]")
        db.close()
        return

    jobs = []
    for status in ("tailored", "synced"):
        jobs.extend(db.get_jobs_by_status(status))
    jobs = [j for j in jobs if applicant.is_eligible(j)]

    if limit:
        jobs = jobs[:limit]

    if not jobs:
        console.print("[yellow]No eligible jobs to apply to[/]")
        db.close()
        return

    console.print(f"[bold]Applying to {len(jobs)} jobs{' (dry run)' if dry_run else ''}[/]\n")

    import time
    for i, job in enumerate(jobs, 1):
        console.print(f"[bold][{i}/{len(jobs)}] {job.title} @ {job.company}[/]")
        platform = detect_platform(job.apply_url or job.url)
        console.print(f"      Platform: {platform}")

        result = asyncio.run(applicant.apply_to_job(job))
        applicant._log_result(result)

        if result.status == "applied":
            job.status = "applied"
            db.upsert_job(job)
            console.print(f"      [green]✓ Applied[/]")
        elif result.status == "dry_run":
            console.print(f"      [yellow]○ Dry run[/]")
        else:
            job.status = "apply_failed"
            db.upsert_job(job)
            console.print(f"      [red]✗ Failed: {result.error}[/]")

        if i < len(jobs):
            time.sleep(2)  # Rate limit between applications

    db.close()
    applied = sum(1 for j in jobs if j.status == "applied")
    console.print(f"\n[green bold]Done: {applied}/{len(jobs)} applied[/]")
```

Add import at top of CLI section:
```python
from job_hunter.apply.strategies.base import detect_platform
```

**Step 2: Verify CLI help works**

Run: `hunt apply --help`
Expected: Shows help with --job-url, --all, --limit, --login, --dry-run options

**Step 3: Commit**

```bash
git add src/job_hunter/cli.py src/job_hunter/apply/__init__.py
git commit -m "feat(apply): hunt apply CLI command (single, batch, login, dry-run)"
```
