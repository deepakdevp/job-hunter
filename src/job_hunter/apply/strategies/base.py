"""Base form filler interface and platform detection utilities."""
from __future__ import annotations

import re
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from playwright.async_api import Page

    from job_hunter.database import Job


@dataclass
class FillResult:
    """Result of a form-filling attempt."""

    success: bool
    fields_filled: int = 0
    fields_skipped: int = 0
    error: str | None = None


# Each tuple is (compiled regex pattern, platform name).
PLATFORM_PATTERNS: list[tuple[re.Pattern[str], str]] = [
    (re.compile(r"myworkdayjobs\.com"), "workday"),
    (re.compile(r"boards\.greenhouse\.io"), "greenhouse"),
    (re.compile(r"jobs\.lever\.co"), "lever"),
    (re.compile(r"jobs\.ashbyhq\.com"), "ashby"),
    (re.compile(r"wantedly\.com"), "wantedly"),
    (re.compile(r"green-japan\.com"), "green"),
    (re.compile(r"careercross\.com"), "careercross"),
]


def detect_platform(url: str) -> str:
    """Match *url* against known ATS patterns and return the platform name.

    Returns ``"generic"`` when no pattern matches.
    """
    for pattern, name in PLATFORM_PATTERNS:
        if pattern.search(url):
            return name
    return "generic"


class BaseFormFiller(ABC):
    """Abstract base for platform-specific form fillers.

    Every concrete strategy must implement :meth:`detect`, :meth:`fill`,
    :meth:`upload_files`, and :meth:`submit`.  The :meth:`handle_wizard`
    hook is optional and defaults to ``True`` (no-op success).
    """

    @abstractmethod
    async def detect(self, page: Page) -> bool:
        """Return *True* if this strategy can handle the current page."""
        ...

    @abstractmethod
    async def fill(self, page: Page, job: Job, profile: dict) -> FillResult:
        """Fill the application form and return a :class:`FillResult`."""
        ...

    @abstractmethod
    async def upload_files(self, page: Page, job: Job) -> bool:
        """Attach résumé / cover-letter files.  Return *True* on success."""
        ...

    @abstractmethod
    async def submit(self, page: Page) -> bool:
        """Click the final submit button.  Return *True* on success."""
        ...

    async def handle_wizard(self, page: Page) -> bool:
        """Navigate multi-step wizards.  Default is a successful no-op."""
        return True
