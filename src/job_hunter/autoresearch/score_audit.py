"""Pipeline 3: Score Audit — validate scoring accuracy and detect inflation."""

from __future__ import annotations

import json
import logging

from job_hunter.database import Job, JobDB
from job_hunter.score.scorer import detect_jd_language

logger = logging.getLogger(__name__)

_AUDIT_PROMPT = """You are a strict quality auditor for job scoring. Review this job and its assigned score.

## Job
- Title: {title}
- Company: {company}
- Location: {location}
- Tech stack: {tech_stack}
- Score: {score}/10
- Score reason: {score_reason}
- Visa mentioned: {visa_mentioned}
- JD language: {jd_language}
- Description (first 2000 chars): {description}

## Candidate
- Target roles: {target_roles}
- Skills: {skills}

## Audit Rules
1. If score >= 8 but visa NOT explicitly mentioned in JD → FLAG as inflated
2. If score >= 7 but JD is fully Japanese → FLAG as inflated (unlikely to sponsor)
3. If score_reason mentions visa but description doesn't → FLAG as hallucinated
4. If title doesn't match target roles at all → FLAG if score > 5
5. If job is clearly management/data/ML-only and score > 5 → FLAG as wrong category

Return JSON:
{{
  "audit_passed": <true/false>,
  "issues": ["list of issues found"],
  "suggested_score": <1-10 or null if no change>,
  "confidence": <0.0-1.0 how confident you are in the audit>
}}"""


def rule_based_audit(job: Job) -> list[str]:
    """Run fast rule-based score audit checks (no LLM needed)."""
    issues = []
    score = job.score or 0
    desc = job.description or ""
    jd_lang = detect_jd_language(desc)

    # Rule 1: High score + no visa mention
    if score >= 8 and not job.visa_sponsorship:
        issues.append(f"Score {score} but visa not mentioned — likely inflated")

    # Rule 2: High score + Japanese JD
    if score >= 7 and jd_lang == "japanese":
        issues.append(f"Score {score} but JD is fully Japanese — unlikely to sponsor")

    # Rule 3: Score reason mentions visa but JD doesn't
    if job.score_reason and "visa" in job.score_reason.lower():
        desc_lower = desc.lower()
        if not any(kw in desc_lower for kw in ("visa", "sponsorship", "relocation", "work permit")):
            issues.append("Score reason mentions visa but JD doesn't — hallucinated")

    # Rule 4: No description at all but high score
    if score >= 7 and (not desc or len(desc.strip()) < 50):
        issues.append(f"Score {score} with no/minimal description — unreliable")

    # Rule 5: Score reason is generic/empty
    if score >= 7 and job.score_reason and len(job.score_reason.strip()) < 20:
        issues.append("Score reason too short — may be unreliable")

    return issues


async def llm_audit_job(job: Job, profile: dict, llm) -> dict | None:
    """Use LLM to audit a single job's score."""
    desc = (job.description or "")[:2000]
    jd_lang = detect_jd_language(desc)

    prompt = _AUDIT_PROMPT.format(
        title=job.title,
        company=job.company,
        location=job.location,
        tech_stack=job.tech_stack or "Unknown",
        score=job.score,
        score_reason=job.score_reason or "None",
        visa_mentioned=job.visa_sponsorship,
        jd_language=jd_lang,
        description=desc,
        target_roles=", ".join(profile.get("target_roles", [])),
        skills=", ".join(profile.get("skills", [])),
    )

    try:
        response = await llm.generate(prompt, json_mode=True)
        return json.loads(response)
    except Exception as e:
        logger.warning(f"LLM audit failed for {job.url}: {e}")
        return None


async def run_score_audit(
    db: JobDB,
    profile: dict,
    llm=None,
    on_progress=None,
) -> dict:
    """Audit all scored jobs for accuracy.

    Returns summary with flagged/adjusted counts.
    """
    scored_jobs = (
        db.get_jobs_by_status("scored")
        + db.get_jobs_by_status("tailored")
        + db.get_jobs_by_status("synced")
    )
    # Only audit jobs with score >= 5 (low scores don't need auditing)
    audit_jobs = [j for j in scored_jobs if (j.score or 0) >= 5]

    results = {
        "total_audited": len(audit_jobs),
        "rule_flagged": 0,
        "llm_flagged": 0,
        "scores_adjusted": 0,
    }

    done = 0
    total = len(audit_jobs)

    for job in audit_jobs:
        # Rule-based audit (always runs)
        issues = rule_based_audit(job)
        if issues:
            results["rule_flagged"] += 1
            logger.info(f"Score audit ({job.title[:40]}): {issues}")

            # Auto-adjust for clear inflation cases
            if any("fully Japanese" in i for i in issues):
                old_score = job.score
                job.score = min(job.score or 0, 4)
                job.score_reason = (
                    f"[AUDIT: adjusted {old_score}→{job.score}] {job.score_reason or ''}"
                )
                db.upsert_job(job)
                results["scores_adjusted"] += 1

            elif any("hallucinated" in i for i in issues):
                old_score = job.score
                job.score = max(1, (job.score or 0) - 2)
                job.score_reason = (
                    f"[AUDIT: adjusted {old_score}→{job.score}] {job.score_reason or ''}"
                )
                db.upsert_job(job)
                results["scores_adjusted"] += 1

        # LLM audit for high-value jobs (score >= 7)
        if llm and (job.score or 0) >= 7 and not issues:
            audit_result = await llm_audit_job(job, profile, llm)
            if audit_result and not audit_result.get("audit_passed", True):
                results["llm_flagged"] += 1
                suggested = audit_result.get("suggested_score")
                if suggested and isinstance(suggested, (int, float)):
                    old_score = job.score
                    job.score = int(suggested)
                    audit_issues = "; ".join(audit_result.get("issues", []))
                    job.score_reason = f"[AUDIT: {old_score}→{job.score}] {audit_issues}"
                    db.upsert_job(job)
                    results["scores_adjusted"] += 1

        done += 1
        if on_progress:
            on_progress(done, total)

    return results
