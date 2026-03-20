from __future__ import annotations

import logging
import re

from job_hunter.database import Job
from job_hunter.tailor.parser import ParsedResume
from job_hunter.tailor.validator import validate_resume, ValidationMode

logger = logging.getLogger(__name__)

_TAILOR_PROMPT = """You are an expert resume writer. Tailor this resume for the specific job description.

## Rules
- MODERATE tailoring: reorder sections/bullets + rephrase to match JD language (~60-70% original wording)
- Inject relevant keywords from the JD into existing bullets where truthful
- NEVER fabricate companies, titles, degrees, certifications, or metrics
- NEVER add experience or skills the candidate doesn't have
- Keep ALL dates, company names, and education exactly as-is
- Do NOT use these filler words: passionate, spearheaded, robust, synergy, proven track record, leveraged, utilized, orchestrated, championed
- Do NOT include any meta-commentary like "here is your resume" or "I have tailored"
- Output ONLY the LaTeX content between \\begin{{document}} and \\end{{document}} (inclusive)

## Candidate's Current Resume (LaTeX)
{resume_latex}

## Candidate's Profile
- Target roles: {target_roles}
- Key skills: {skills}

## Job Description
- Title: {job_title}
- Company: {job_company}
- Location: {job_location}
- Tech stack: {job_tech_stack}
- Description:
{job_description}

## Output
Return ONLY the LaTeX body content. Start with \\begin{{document}} and end with \\end{{document}}.
Preserve the exact LaTeX template structure, commands, and formatting.
Only modify text content within the template."""

MAX_RETRIES = 2


async def tailor_resume(
    job: Job,
    resume: ParsedResume,
    profile: dict,
    llm,
    mode: ValidationMode = ValidationMode.STRICT,
) -> str | None:
    """Generate a tailored resume for a specific job.

    Returns the tailored LaTeX source, or None if all retries fail validation.
    """
    target_roles = ", ".join(profile.get("target_roles", []))
    skills = ", ".join(profile.get("skills", []))
    desc = (job.description or "No description")[:4000]

    prompt = _TAILOR_PROMPT.format(
        resume_latex=resume.full_text[:8000],
        target_roles=target_roles,
        skills=skills,
        job_title=job.title,
        job_company=job.company,
        job_location=job.location,
        job_tech_stack=job.tech_stack or "Not specified",
        job_description=desc,
    )

    # Extract source facts for fabrication detection
    source_companies = _extract_companies_from_profile(profile)

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = await llm.generate(prompt, max_tokens=8192)
            tailored_latex = _clean_llm_response(response)

            if not tailored_latex:
                logger.warning(f"Empty response from LLM on attempt {attempt + 1}")
                continue

            # Validate
            result = validate_resume(
                tailored_latex,
                source_companies=source_companies,
                mode=mode,
            )

            if result.passed:
                if result.warnings:
                    logger.info(f"Resume passed with {result.warning_count} warnings")
                return tailored_latex

            # Failed validation
            error_msgs = [i.message for i in result.errors]
            logger.warning(
                f"Validation failed (attempt {attempt + 1}/{MAX_RETRIES + 1}): "
                f"{'; '.join(error_msgs[:5])}"
            )

            if attempt < MAX_RETRIES:
                # Retry with feedback
                prompt = (
                    prompt
                    + "\n\n## VALIDATION ERRORS (fix these):\n"
                    + "\n".join(f"- {m}" for m in error_msgs)
                    + "\n\nRegenerate the resume fixing ALL the above issues."
                )

        except Exception as e:
            logger.warning(f"Tailoring failed on attempt {attempt + 1}: {e}")

    logger.error(f"All {MAX_RETRIES + 1} attempts failed for {job.url}")
    return None


def _clean_llm_response(response: str) -> str:
    """Extract LaTeX content from LLM response."""
    # Remove markdown code fences if present
    response = re.sub(r"```(?:latex|tex)?\s*\n?", "", response)
    response = re.sub(r"```\s*$", "", response)

    # Try to extract \begin{document}...\end{document}
    match = re.search(
        r"(\\begin\{document\}.*?\\end\{document\})",
        response,
        re.DOTALL,
    )
    if match:
        return match.group(1).strip()

    # If no document environment, return cleaned response
    return response.strip()


def _extract_companies_from_profile(profile: dict) -> list[str]:
    """Extract company names from profile for fabrication detection."""
    companies = []
    for exp in profile.get("experience", []):
        company = exp.get("company", "")
        if company:
            companies.append(company)
    for edu in profile.get("education", []):
        institution = edu.get("institution", "") or edu.get("school", "")
        if institution:
            companies.append(institution)
    return companies
