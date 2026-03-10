from __future__ import annotations

import asyncio
import json
import logging
from dataclasses import dataclass

from job_hunter.database import Job, JobDB
from job_hunter.score.prefilter import pre_filter_job

logger = logging.getLogger(__name__)

SCORING_WEIGHTS = {
    "skills_match": 0.30,
    "role_fit": 0.20,
    "location_remote": 0.15,
    "visa_sponsorship": 0.25,
    "salary_fit": 0.10,
}

_SCORING_PROMPT = """You are a job-matching expert. Score this job for the candidate on 5 dimensions (1-10 each).

## Candidate Profile
- Target roles: {target_roles}
- Skills: {skills}
- Location preference: Japan (highest), Europe, Canada, worldwide
- Visa: Needs sponsorship
- Min salary: 5,000,000 JPY
- Experience: {experience_summary}

## Job Details
- Title: {title}
- Company: {company}
- Location: {location}
- Salary: {salary}
- Visa sponsorship: {visa}
- Remote policy: {remote}
- Tech stack: {tech_stack}
- Description: {description}

## Scoring Dimensions
1. skills_match (weight 30%): How well do the candidate's skills match the job requirements?
2. role_fit (weight 20%): How well does the title/responsibilities align with target roles?
3. location_remote (weight 15%): Japan=10, Europe=7, Remote=6, Canada=5, Other=3
4. visa_sponsorship (weight 25%): Sponsored=10, Not mentioned=5, Explicitly denied=1
5. salary_fit (weight 10%): Above 8M=10, 6-8M=8, 5-6M=6, Unknown=5, Below 5M=2

Return JSON only:
{{
  "skills_match": <1-10>,
  "role_fit": <1-10>,
  "location_remote": <1-10>,
  "visa_sponsorship": <1-10>,
  "salary_fit": <1-10>,
  "reason": "<2 analytical sentences explaining the match, referencing specific skills and priorities>"
}}"""


@dataclass
class ScoreResult:
    score: int
    reason: str
    dimensions: dict[str, int]


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
        if not isinstance(val, (int, float)) or val < 1 or val > 10:
            logger.warning(f"Invalid dimension score for {dim}: {val}")
            return None
        dimensions[dim] = int(val)

    # Weighted average
    weighted = sum(dimensions[d] * SCORING_WEIGHTS[d] for d in SCORING_WEIGHTS)
    final_score = round(weighted)
    final_score = max(1, min(10, final_score))

    reason = data.get("reason", "")
    if not reason:
        reason = "No reason provided."

    return ScoreResult(score=final_score, reason=reason, dimensions=dimensions)


def _build_scoring_prompt(job: Job, profile: dict) -> str:
    """Build the scoring prompt from job and profile data."""
    target_roles = ", ".join(profile.get("target_roles", []))
    skills = ", ".join(profile.get("skills", []))

    # Build experience summary from profile
    experience = profile.get("experience", [])
    exp_lines = []
    for exp in experience[:3]:
        company = exp.get("company", "")
        role = exp.get("title", "")
        highlights = exp.get("highlights", [])[:2]
        exp_lines.append(f"{role} at {company}: {'; '.join(highlights)}")
    experience_summary = " | ".join(exp_lines) if exp_lines else "2+ years full-stack development"

    salary = job.salary_raw or "Unknown"
    if job.salary_min:
        salary = f"{job.salary_min:,}"
        if job.salary_max:
            salary += f" - {job.salary_max:,}"

    visa = "Unknown"
    if job.visa_sponsorship is True:
        visa = "Yes, sponsored"
    elif job.visa_sponsorship is False:
        visa = "No, not sponsored"

    desc = (job.description or "No description available")[:3000]

    return _SCORING_PROMPT.format(
        target_roles=target_roles,
        skills=skills,
        experience_summary=experience_summary,
        title=job.title,
        company=job.company,
        location=job.location,
        salary=salary,
        visa=visa,
        remote=job.remote_policy or "Unknown",
        tech_stack=job.tech_stack or "Unknown",
        description=desc,
    )


async def score_job(job: Job, profile: dict, llm) -> ScoreResult | None:
    """Score a single job using LLM."""
    prompt = _build_scoring_prompt(job, profile)
    try:
        response = await llm.generate(prompt, json_mode=True)
        return parse_score_response(response)
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
            job.status = "scored"
            db.upsert_job(job)
            scored += 1
        done += 1
        if on_progress:
            on_progress(done, total)

    return scored, filtered, total
