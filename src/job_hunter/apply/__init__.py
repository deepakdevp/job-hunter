"""Job application automation — form filling and submission."""
from __future__ import annotations

from job_hunter.apply.applicant import Applicant, ApplyResult
from job_hunter.apply.session import SessionManager
from job_hunter.apply.strategies.base import BaseFormFiller, FillResult, detect_platform

__all__ = [
    "Applicant",
    "ApplyResult",
    "SessionManager",
    "BaseFormFiller",
    "FillResult",
    "detect_platform",
]
