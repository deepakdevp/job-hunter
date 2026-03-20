from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass
from datetime import datetime

from job_hunter.database import Job, JobDB
from job_hunter.score.prefilter import pre_filter_job

logger = logging.getLogger(__name__)

SCORING_WEIGHTS = {
    "visa_sponsorship": 0.50,
    "role_fit": 0.30,
    "skills_match": 0.20,
}

_SCORING_PROMPT = """You are a job-matching expert. Score this job for the candidate on 3 dimensions (1-10 each).

## Candidate Profile
- Target roles: {target_roles}
- Skills: {skills}
- Visa: Needs sponsorship (CRITICAL — this is the #1 factor)
- Experience: {experience_summary}

## Job Details
- Title: {title}
- Company: {company}
- Location: {location}
- Tech stack: {tech_stack}
- Visa sponsorship: {visa}
- JD language: {jd_language}
- Description: {description}

## Scoring Dimensions
1. visa_sponsorship (weight 50%): MOST IMPORTANT.
   - Explicitly mentions visa sponsorship/relocation support = 10
   - Full English JD (no Japanese) = 8 (likely international-friendly)
   - Mixed English/Japanese JD = 6 (possibly sponsors)
   - Full Japanese JD = 0 (unlikely to sponsor)
   - Explicitly says no sponsorship / Japanese only / citizens only = 0
2. role_fit (weight 30%): How well does the title/responsibilities align with target roles?
   - Bonus for: RAG, MCP, LLM fine-tuning, vector databases, AI tooling, agentic workflows
   - Penalty for: pure ML/research, infrastructure-only, data pipelines, management-heavy
3. skills_match (weight 20%): How well do the candidate's skills match requirements?
   - Focus on: React, Python/Django, TypeScript, LangChain, LlamaIndex, AWS, PostgreSQL

Return JSON only:
{{
  "visa_sponsorship": <0-10>,
  "role_fit": <1-10>,
  "skills_match": <1-10>,
  "visa_mentioned": <true if JD explicitly mentions visa sponsorship or relocation support, false otherwise>,
  "reason": "<2 analytical sentences explaining the match>"
}}"""


@dataclass
class ScoreResult:
    score: int
    reason: str
    dimensions: dict[str, int]
    visa_mentioned: bool = False


def detect_jd_language(description: str) -> str:
    """Detect whether JD is English, Japanese, or mixed.

    Returns: 'english', 'japanese', or 'mixed'.
    """
    if not description:
        return "english"

    # Count Japanese characters (hiragana, katakana, kanji)
    jp_chars = len(re.findall(r"[\u3040-\u309F\u30A0-\u30FF\u4E00-\u9FFF]", description))
    # Count ASCII letters
    en_chars = len(re.findall(r"[a-zA-Z]", description))

    total = jp_chars + en_chars
    if total == 0:
        return "english"

    jp_ratio = jp_chars / total

    if jp_ratio < 0.1:
        return "english"
    elif jp_ratio > 0.6:
        return "japanese"
    else:
        return "mixed"


def _recency_bonus(posted_date: str | None) -> float:
    """Return a bonus score based on how recently the job was posted."""
    if not posted_date:
        return 0.0

    try:
        dt = datetime.fromisoformat(posted_date.replace("Z", "+00:00"))
        age = datetime.now(dt.tzinfo) - dt
    except (ValueError, TypeError):
        for fmt in ("%Y-%m-%d", "%m/%d/%Y"):
            try:
                dt = datetime.strptime(posted_date[:10], fmt)
                age = datetime.now() - dt
                break
            except (ValueError, TypeError):
                continue
        else:
            return 0.0

    if age.days <= 1:
        return 1.0
    elif age.days <= 7:
        return 0.5
    return 0.0


def parse_score_response(response_text: str) -> ScoreResult | None:
    """Parse LLM scoring response JSON into ScoreResult."""
    try:
        data = json.loads(response_text)
    except json.JSONDecodeError:
        logger.warning("Failed to parse score response as JSON")
        return None

    dimensions = {}
    for dim in SCORING_WEIGHTS:
        val = data.get(dim)
        if not isinstance(val, (int, float)) or val < 0 or val > 10:
            logger.warning(f"Invalid dimension score for {dim}: {val}")
            return None
        dimensions[dim] = int(val)

    # Weighted average
    weighted = sum(dimensions[d] * SCORING_WEIGHTS[d] for d in SCORING_WEIGHTS)
    final_score = round(weighted)
    final_score = max(1, min(10, final_score))

    reason = data.get("reason", "No reason provided.")
    visa_mentioned = bool(data.get("visa_mentioned", False))

    return ScoreResult(
        score=final_score,
        reason=reason,
        dimensions=dimensions,
        visa_mentioned=visa_mentioned,
    )


def _build_scoring_prompt(job: Job, profile: dict) -> str:
    """Build the scoring prompt from job and profile data."""
    target_roles = ", ".join(profile.get("target_roles", []))
    skills = ", ".join(profile.get("skills", []))

    experience = profile.get("experience", [])
    exp_lines = []
    for exp in experience[:3]:
        company = exp.get("company", "")
        role = exp.get("title", "")
        highlights = exp.get("highlights", [])[:2]
        exp_lines.append(f"{role} at {company}: {'; '.join(highlights)}")
    experience_summary = " | ".join(exp_lines) if exp_lines else "2+ years full-stack development"

    visa = "Unknown"
    if job.visa_sponsorship is True:
        visa = "Yes, sponsored"
    elif job.visa_sponsorship is False:
        visa = "No, not sponsored"

    desc = (job.description or "No description available")[:3000]
    jd_language = detect_jd_language(desc)

    return _SCORING_PROMPT.format(
        target_roles=target_roles,
        skills=skills,
        experience_summary=experience_summary,
        title=job.title,
        company=job.company,
        location=job.location,
        visa=visa,
        tech_stack=job.tech_stack or "Unknown",
        jd_language=jd_language,
        description=desc,
    )


async def score_job(job: Job, profile: dict, llm) -> ScoreResult | None:
    """Score a single job using LLM."""
    prompt = _build_scoring_prompt(job, profile)
    try:
        response = await llm.generate(prompt, json_mode=True)
        result = parse_score_response(response)
        if result:
            # Apply recency bonus
            bonus = _recency_bonus(job.posted_date)
            if bonus > 0:
                result.score = min(10, result.score + round(bonus))
        return result
    except Exception as e:
        logger.warning(f"Scoring failed for {job.url}: {e}")
        return None


async def run_scoring(
    db: JobDB,
    profile: dict,
    llm,
    target_roles: list[str] | None = None,
    on_progress=None,
) -> tuple[int, int, int]:
    """Score all unscored enriched jobs.

    Returns (scored_count, filtered_count, total_count).
    """
    jobs = db.get_unscored_jobs()
    total = len(jobs)
    if total == 0:
        return 0, 0, 0

    roles = target_roles or profile.get("target_roles", [])
    scored = 0
    filtered = 0
    done = 0

    for job in jobs:
        # Pass 1: Pre-filter
        pf = pre_filter_job(job, roles)
        if not pf.passed:
            job.score = 0
            job.score_reason = f"Pre-filtered: {pf.reason}"
            job.status = "filtered"
            db.upsert_job(job)
            filtered += 1
            done += 1
            if on_progress:
                on_progress(done, total)
            continue

        # Pass 2: LLM scoring
        result = await score_job(job, profile, llm)
        if result:
            job.score = result.score
            job.score_reason = result.reason
            job.visa_sponsorship = result.visa_mentioned
            job.status = "scored"
            db.upsert_job(job)
            scored += 1
        done += 1
        if on_progress:
            on_progress(done, total)

    return scored, filtered, total
