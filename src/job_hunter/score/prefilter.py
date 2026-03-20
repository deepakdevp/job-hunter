from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta

from job_hunter.database import Job

# Minimum salary in JPY
SALARY_FLOOR_JPY = 5_000_000

# Max job age in days
MAX_JOB_AGE_DAYS = 14

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
    # Management roles
    re.compile(r"\bengineering\s+manager\b", re.IGNORECASE),
    re.compile(r"\beng\.?\s+manager\b", re.IGNORECASE),
    re.compile(r"\bteam\s+lead\b", re.IGNORECASE),
    re.compile(r"\bstaff\s+manager\b", re.IGNORECASE),
    re.compile(r"\bpeople\s+manager\b", re.IGNORECASE),
    re.compile(r"\bmanager\s*,\s*engineering\b", re.IGNORECASE),
    # Infrastructure/Platform/DevOps roles
    re.compile(r"\binfrastructure\s+engineer\b", re.IGNORECASE),
    re.compile(r"\bplatform\s+engineer\b", re.IGNORECASE),
    re.compile(r"\bsre\b", re.IGNORECASE),
    re.compile(r"\bsite\s+reliability\b", re.IGNORECASE),
    re.compile(r"\bdevops\s+engineer\b", re.IGNORECASE),
    # Data Engineering roles
    re.compile(r"\bdata\s+engineer\b", re.IGNORECASE),
    re.compile(r"\bdata\s+pipeline\b", re.IGNORECASE),
    re.compile(r"\betl\s+engineer\b", re.IGNORECASE),
    re.compile(r"\bdata\s+platform\b", re.IGNORECASE),
    # Core ML/AI Research roles
    re.compile(r"\bmachine\s+learning\s+engineer\b", re.IGNORECASE),
    re.compile(r"\bml\s+engineer\b", re.IGNORECASE),
    re.compile(r"\bai\s+research\s+scientist\b", re.IGNORECASE),
    re.compile(r"\bresearch\s+scientist\b", re.IGNORECASE),
    re.compile(r"\bcomputer\s+vision\s+engineer\b", re.IGNORECASE),
    re.compile(r"\bnlp\s+engineer\b", re.IGNORECASE),
]

BLOCKED_DESCRIPTION_PATTERNS = [
    re.compile(r"\b1[0-9]\+?\s+years\b", re.IGNORECASE),  # 10+ years, 15+ years
    re.compile(r"\bsecurity\s+clearance\s+required\b", re.IGNORECASE),
    re.compile(r"\bUS\s+citizens?\s+only\b", re.IGNORECASE),
    re.compile(r"\bEU\s+citizens?\s+only\b", re.IGNORECASE),
    # Core ML framework requirements (as primary skill, not just "nice to have")
    re.compile(
        r"\b(?:extensive|deep|strong)\s+(?:experience|expertise)\s+(?:in|with)\s+(?:PyTorch|TensorFlow)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\bmanag(?:e|ing)\s+(?:a\s+)?team\s+of\s+(?:[5-9]|[1-9][0-9])\+?\s+engineers\b",
        re.IGNORECASE,
    ),
]

# Tokyo location patterns
TOKYO_PATTERNS = [
    re.compile(r"\btokyo\b", re.IGNORECASE),
    re.compile(r"東京"),
    re.compile(
        r"渋谷|新宿|港区|千代田|品川|目黒|世田谷|中央区|文京|台東|墨田|江東|大田|中野|杉並|豊島|北区|板橋|練馬|足立|荒川|葛飾|江戸川"
    ),
    re.compile(r"\bshibuya\b", re.IGNORECASE),
    re.compile(r"\bshinjuku\b", re.IGNORECASE),
    re.compile(r"\bminato\b", re.IGNORECASE),
    re.compile(r"\bmeguro\b", re.IGNORECASE),
    re.compile(r"\bchiyoda\b", re.IGNORECASE),
    re.compile(r"\bshinagawa\b", re.IGNORECASE),
    re.compile(r"\broppongi\b", re.IGNORECASE),
    re.compile(r"\bsumida\b", re.IGNORECASE),
    re.compile(r"\b千駄[ヶが]谷\b"),
    re.compile(r"\b大手町\b"),
    re.compile(r"\b高輪\b"),
    re.compile(r"\bremote\b", re.IGNORECASE),  # Remote jobs are OK
]


@dataclass
class PreFilterResult:
    passed: bool
    reason: str | None = None


def _normalize(text: str) -> str:
    """Lowercase and collapse whitespace for fuzzy matching."""
    return re.sub(r"\s+", " ", text.lower().strip())


def _is_tokyo_or_remote(location: str) -> bool:
    """Check if location is Tokyo, a Tokyo ward, or remote."""
    if not location:
        return True  # null location → keep
    for pattern in TOKYO_PATTERNS:
        if pattern.search(location):
            return True
    return False


def _is_too_old(posted_date: str | None) -> bool:
    """Check if job was posted more than MAX_JOB_AGE_DAYS ago."""
    if not posted_date:
        return False  # null → keep

    try:
        # Try ISO format first
        dt = datetime.fromisoformat(posted_date.replace("Z", "+00:00"))
        cutoff = datetime.now(dt.tzinfo) - timedelta(days=MAX_JOB_AGE_DAYS)
        return dt < cutoff
    except (ValueError, TypeError):
        pass

    # Try common date formats
    for fmt in ("%Y-%m-%d", "%m/%d/%Y", "%d-%m-%Y", "%B %d, %Y"):
        try:
            dt = datetime.strptime(posted_date[:10], fmt)
            cutoff = datetime.now() - timedelta(days=MAX_JOB_AGE_DAYS)
            return dt < cutoff
        except (ValueError, TypeError):
            continue

    return False  # unparseable → keep


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

    # Also match common generic patterns (excluding blocked roles)
    generic_patterns = [
        r"software",
        r"developer",
        r"frontend",
        r"front[\s-]?end",
        r"backend",
        r"back[\s-]?end",
        r"full[\s-]?stack",
        r"fullstack",
        r"\bai\b",
        r"python",
        r"react",
        r"node",
        r"typescript",
        r"agentic",
        r"llm",
        r"genai",
        r"gen[\s-]?ai",
        r"mcp",
        r"rag\b",
        r"vector\s+database",
        r"fine[\s-]?tun",
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
            return PreFilterResult(passed=False, reason=f"Blocked title: {pattern.pattern}")

    # 2. Title match against target roles
    if not _title_matches_roles(job.title, target_roles):
        return PreFilterResult(
            passed=False, reason=f"Title '{job.title}' doesn't match target roles"
        )

    # 3. Location must be Tokyo or Remote
    if not _is_tokyo_or_remote(job.location):
        return PreFilterResult(
            passed=False, reason=f"Location '{job.location}' is not Tokyo/Remote"
        )

    # 4. Job must not be older than 2 weeks
    if _is_too_old(job.posted_date):
        return PreFilterResult(passed=False, reason=f"Job posted too long ago: {job.posted_date}")

    # 5. Salary floor (only reject if salary is parseable and below floor)
    if job.salary_min is not None and job.salary_min > 0:
        if job.salary_min < SALARY_FLOOR_JPY:
            return PreFilterResult(
                passed=False,
                reason=f"Salary {job.salary_min} below {SALARY_FLOOR_JPY} JPY floor",
            )

    # 6. Description blocklist
    desc = job.description or ""
    for pattern in BLOCKED_DESCRIPTION_PATTERNS:
        if pattern.search(desc):
            return PreFilterResult(passed=False, reason=f"Blocked description: {pattern.pattern}")

    return PreFilterResult(passed=True)
