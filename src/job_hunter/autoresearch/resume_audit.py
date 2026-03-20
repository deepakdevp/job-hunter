"""Pipeline 4: Resume Audit — validate generated resumes against job descriptions."""
from __future__ import annotations

import json
import logging
import subprocess
from pathlib import Path

from job_hunter.database import Job, JobDB
from job_hunter.tailor.validator import validate_resume, ValidationMode

logger = logging.getLogger(__name__)

_RESUME_AUDIT_PROMPT = """You are a resume quality auditor. Compare this tailored resume against the job description and candidate profile.

## Job Description
- Title: {title}
- Company: {company}
- Key requirements from JD: {description}

## Candidate Profile Skills
{skills}

## Generated Resume Text
{resume_text}

## Audit Checks
1. **Hallucination**: Does the resume claim skills, companies, or achievements NOT in the candidate's profile?
2. **Relevance**: Does the resume actually address the key job requirements?
3. **Completeness**: Are contact details present? Are there template placeholders like [NAME] or {{COMPANY}}?
4. **Quality**: Any copy-paste artifacts, broken formatting, or nonsensical text?
5. **Match score**: How well does this resume match the job (0-100%)?

Return JSON:
{{
  "passed": <true/false>,
  "match_percentage": <0-100>,
  "issues": ["list of issues"],
  "hallucinations": ["any fabricated claims"],
  "missing_requirements": ["key job requirements not addressed in resume"]
}}"""


def extract_text_from_pdf(pdf_path: str) -> str | None:
    """Extract text from a PDF file using pdftotext."""
    try:
        result = subprocess.run(
            ["pdftotext", "-layout", pdf_path, "-"],
            capture_output=True, text=True, timeout=10,
        )
        if result.returncode == 0:
            return result.stdout
    except (FileNotFoundError, subprocess.TimeoutExpired):
        pass

    # Fallback: try python-based extraction
    try:
        import fitz  # PyMuPDF
        doc = fitz.open(pdf_path)
        text = ""
        for page in doc:
            text += page.get_text()
        doc.close()
        return text
    except ImportError:
        pass

    return None


def quick_resume_audit(resume_text: str, job: Job) -> list[str]:
    """Fast rule-based resume audit (no LLM)."""
    issues = []

    if not resume_text or len(resume_text.strip()) < 100:
        issues.append("Resume text too short or empty")
        return issues

    # Check for template placeholders
    import re
    placeholders = re.findall(r'\[([A-Z_\s]+)\]|\{\{([A-Z_\s]+)\}\}', resume_text)
    if placeholders:
        issues.append(f"Template placeholders found: {placeholders[:3]}")

    # Run existing validator
    validation = validate_resume(resume_text, mode=ValidationMode.NORMAL)
    for error in validation.errors:
        issues.append(f"{error.category}: {error.message}")

    # Check resume mentions the target company
    if job.company and job.company != "Unknown":
        # It's OK if the resume doesn't mention the company explicitly
        pass

    # Check resume isn't just the job description copy-pasted
    if job.description:
        desc_words = set(job.description.lower().split()[:50])
        resume_words = set(resume_text.lower().split()[:50])
        overlap = len(desc_words & resume_words) / max(len(desc_words), 1)
        if overlap > 0.7:
            issues.append("Resume appears to be copy of job description")

    return issues


async def llm_audit_resume(
    resume_text: str,
    job: Job,
    profile: dict,
    llm,
) -> dict | None:
    """LLM-powered resume audit."""
    prompt = _RESUME_AUDIT_PROMPT.format(
        title=job.title,
        company=job.company,
        description=(job.description or "")[:1500],
        skills=", ".join(profile.get("skills", [])),
        resume_text=resume_text[:3000],
    )

    try:
        response = await llm.generate(prompt, json_mode=True)
        return json.loads(response)
    except Exception as e:
        logger.warning(f"LLM resume audit failed for {job.url}: {e}")
        return None


async def run_resume_audit(
    db: JobDB,
    profile: dict,
    llm=None,
    on_progress=None,
) -> dict:
    """Audit all tailored resumes for quality.

    Returns summary with flagged/regeneration counts.
    """
    tailored = db.get_jobs_by_status("tailored") + db.get_jobs_by_status("synced")
    jobs_with_resumes = [j for j in tailored if j.resume_path and Path(j.resume_path).exists()]

    results = {
        "total_audited": len(jobs_with_resumes),
        "quick_flagged": 0,
        "llm_flagged": 0,
        "needs_regeneration": 0,
        "avg_match_percentage": 0,
    }

    done = 0
    total = len(jobs_with_resumes)
    match_scores = []

    for job in jobs_with_resumes:
        resume_text = extract_text_from_pdf(job.resume_path)
        if not resume_text:
            logger.warning(f"Could not extract text from {job.resume_path}")
            done += 1
            if on_progress:
                on_progress(done, total)
            continue

        # Quick rule-based audit
        issues = quick_resume_audit(resume_text, job)
        if issues:
            results["quick_flagged"] += 1
            logger.info(f"Resume audit ({job.title[:40]}): {issues}")

            # If critical issues, mark for regeneration
            if any("leak" in i.lower() or "placeholder" in i.lower() for i in issues):
                results["needs_regeneration"] += 1
                job.resume_path = None
                job.status = "scored"  # Reset to scored so it gets re-tailored
                db.upsert_job(job)

        # LLM audit for high-score jobs
        if llm and (job.score or 0) >= 7 and not issues:
            audit_result = await llm_audit_resume(resume_text, job, profile, llm)
            if audit_result:
                match_pct = audit_result.get("match_percentage", 0)
                match_scores.append(match_pct)

                if not audit_result.get("passed", True):
                    results["llm_flagged"] += 1
                    hallucinations = audit_result.get("hallucinations", [])
                    if hallucinations:
                        logger.warning(f"Resume hallucinations ({job.title[:30]}): {hallucinations}")
                        results["needs_regeneration"] += 1
                        job.resume_path = None
                        job.status = "scored"
                        db.upsert_job(job)

        done += 1
        if on_progress:
            on_progress(done, total)

    if match_scores:
        results["avg_match_percentage"] = round(sum(match_scores) / len(match_scores), 1)

    return results
