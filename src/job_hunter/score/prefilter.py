from __future__ import annotations

import re
from dataclasses import dataclass

from job_hunter.database import Job

# Minimum salary in JPY
SALARY_FLOOR_JPY = 5_000_000

BLOCKED_TITLE_PATTERNS = [
    re.compile(r"\bintern\b", re.IGNORECASE),
    re.compile(r"\binternship\b", re.IGNORECASE),
    re.compile(r"\bdirector\b", re.IGNORECASE),
    re.compile(r"\bvp\b", re.IGNORECASE),
    re.compile(r"\bvice\s+president\b", re.IGNORECASE),
    re.compile(r"\bchief\b", re.IGNORECASE),
    re.compile(r"\bhead\s+of\b", re.IGNORECASE),
    re.compile(r"\bphd\s+(required|preferred)\b", re.IGNORECASE),
    re.compile(r"\bnative\s+japanese\s+required\b", re.IGNORECASE),
]

BLOCKED_DESCRIPTION_PATTERNS = [
    re.compile(r"\b1[0-9]\+?\s+years\b", re.IGNORECASE),  # 10+ years, 15+ years
    re.compile(r"\bsecurity\s+clearance\s+required\b", re.IGNORECASE),
    re.compile(r"\bUS\s+citizens?\s+only\b", re.IGNORECASE),
    re.compile(r"\bEU\s+citizens?\s+only\b", re.IGNORECASE),
]


@dataclass
class PreFilterResult:
    passed: bool
    reason: str | None = None


def _normalize(text: str) -> str:
    """Lowercase and collapse whitespace for fuzzy matching."""
    return re.sub(r"\s+", " ", text.lower().strip())


def _title_matches_roles(title: str, target_roles: list[str]) -> bool:
    """Check if job title fuzzy-matches any target role."""
    norm_title = _normalize(title)

    for role in target_roles:
        norm_role = _normalize(role)

        # Exact substring match
        if norm_role in norm_title or norm_title in norm_role:
            return True

        # Word-level overlap: if >= 50% of role words appear in title
        role_words = set(norm_role.split())
        title_words = set(norm_title.split())
        overlap = role_words & title_words
        if len(overlap) >= max(1, len(role_words) * 0.5):
            return True

    # Also match common generic patterns
    generic_patterns = [
        r"software", r"developer", r"engineer", r"frontend", r"front[\s-]?end",
        r"backend", r"back[\s-]?end", r"full[\s-]?stack", r"fullstack",
        r"\bai\b", r"machine\s+learning", r"ml\b", r"data\s+engineer",
        r"devops", r"sre", r"platform", r"cloud",
        r"python", r"react", r"node", r"typescript",
        r"agentic", r"llm", r"genai", r"gen[\s-]?ai", r"mcp",
    ]
    for pattern in generic_patterns:
        if re.search(pattern, norm_title):
            return True

    return False


def pre_filter_job(job: Job, target_roles: list[str]) -> PreFilterResult:
    """Pre-filter a job without LLM. Returns pass/fail + reason."""

    # 1. Title blocklist
    for pattern in BLOCKED_TITLE_PATTERNS:
        if pattern.search(job.title):
            return PreFilterResult(passed=False, reason=f"Blocked title keyword: {pattern.pattern}")

    # 2. Title match against target roles
    if not _title_matches_roles(job.title, target_roles):
        return PreFilterResult(passed=False, reason=f"Title '{job.title}' doesn't match target roles")

    # 3. Salary floor (only reject if salary is parseable and below floor)
    if job.salary_min is not None and job.salary_min > 0:
        if job.salary_min < SALARY_FLOOR_JPY:
            return PreFilterResult(
                passed=False,
                reason=f"Salary {job.salary_min} below {SALARY_FLOOR_JPY} JPY floor",
            )

    # 4. Description blocklist
    desc = job.description or ""
    for pattern in BLOCKED_DESCRIPTION_PATTERNS:
        if pattern.search(desc):
            return PreFilterResult(passed=False, reason=f"Blocked description keyword: {pattern.pattern}")

    return PreFilterResult(passed=True)
