from __future__ import annotations

import json
import logging
import re

from job_hunter.database import Job
from job_hunter.tailor.validator import (
    validate_resume,
    ValidationMode,
    ValidationResult,
    ValidationIssue,
)

logger = logging.getLogger(__name__)

_COVER_LETTER_PROMPT = """Write a cover letter for this job application. You are the candidate — write in first person.

## CRITICAL RULES — READ CAREFULLY
- Write like a real human. Professional but warm. NOT robotic, NOT corporate-speak.
- Use contractions naturally (I'm, I've, it's, don't).
- Vary sentence length — mix short punchy sentences with longer ones.
- Reference SPECIFIC details from the job posting (team name, product, tech stack).
- Reference SPECIFIC personal experience (project names, metrics, technologies used).
- NEVER start 3+ consecutive sentences with "I".
- NO bullet points. Prose paragraphs only.
- NO filler words: passionate, spearheaded, robust, synergy, proven track record, leveraged, utilized, orchestrated, cutting-edge, innovative solutions, results-driven, dynamic environment.
- NO meta-commentary: "here is", "I hope this helps", "as requested", "I am writing to apply".
- Add one natural touch — a parenthetical aside, an em-dash, or a casual observation.
- Keep it under 250 words. 3-4 short paragraphs max.
- Mention the company name at least once.
- Mention at least one specific technology or skill from the JD.
- End with a simple, confident closing — not "I look forward to the opportunity to discuss..."
- Use the "I'm Choosing You" tone: confident without arrogance, proof-first, 2-4 sentences per paragraph.
- Map specific JD quotes/requirements to candidate proof points — show evidence, not claims.
- If evaluation data is provided below, use Block B match data for concrete proof points.
- Include links to relevant case studies or portfolio if available in the profile.
- Match the JD's language (English by default; if JD is in another language, write in that language).

{evaluation_block}
{portfolio_block}

## Candidate Profile
- Name: {name}
- Target roles: {target_roles}
- Key skills: {skills}
- Recent experience: {experience_summary}

## Job Details
- Title: {job_title}
- Company: {job_company}
- Location: {job_location}
- Tech stack: {job_tech_stack}
- Description:
{job_description}

## Output
Write ONLY the cover letter body text. No salutation header, no "Dear Hiring Manager", no signature block — just the 3-4 paragraphs. Plain text, no formatting."""

MAX_RETRIES = 2

# Word limits by validation mode
WORD_LIMITS = {
    ValidationMode.STRICT: 275,
    ValidationMode.NORMAL: 300,
    ValidationMode.LENIENT: None,
}


def validate_cover_letter(
    text: str,
    company_name: str,
    mode: ValidationMode = ValidationMode.STRICT,
) -> ValidationResult:
    """Validate a cover letter with additional cover-letter-specific checks."""
    # Run standard resume validation (filler + leaks)
    result = validate_resume(text, mode=mode)

    # Additional checks for cover letters
    extra_issues: list[ValidationIssue] = []

    # Word count
    word_count = len(text.split())
    word_limit = WORD_LIMITS.get(mode)
    if word_limit and word_count > word_limit:
        extra_issues.append(
            ValidationIssue(
                severity="error" if mode == ValidationMode.STRICT else "warning",
                category="structure",
                message=f"Cover letter too long: {word_count} words (max {word_limit})",
            )
        )

    # Must mention company (skip for unknown companies)
    if (
        company_name
        and company_name.lower() not in ("unknown", "")
        and company_name.lower() not in text.lower()
    ):
        extra_issues.append(
            ValidationIssue(
                severity="error",
                category="structure",
                message=f"Cover letter doesn't mention the company: '{company_name}'",
            )
        )

    # Check for overly formal openings
    formal_openers = [
        "I am writing to apply",
        "I am writing to express",
        "I wish to apply",
        "Please accept this letter",
        "To whom it may concern",
        "Dear Sir or Madam",
    ]
    text_lower = text.lower()
    for opener in formal_openers:
        if opener.lower() in text_lower:
            extra_issues.append(
                ValidationIssue(
                    severity="error" if mode == ValidationMode.STRICT else "warning",
                    category="structure",
                    message=f"Overly formal opener detected: '{opener}'",
                )
            )

    all_issues = result.issues + extra_issues
    errors = [i for i in all_issues if i.severity == "error"]
    warnings = [i for i in all_issues if i.severity == "warning"]

    return ValidationResult(
        passed=len(errors) == 0,
        issues=all_issues,
        errors=errors,
        warnings=warnings,
    )


def _build_cover_letter_evaluation_block(job: Job, evaluation_data: dict | None = None) -> str:
    """Format evaluation data for the cover letter prompt."""
    eval_data = evaluation_data
    if eval_data is None and job.evaluation:
        try:
            eval_data = json.loads(job.evaluation)
        except (json.JSONDecodeError, TypeError):
            return ""
    if not eval_data:
        return ""

    parts = ["## Evaluation Match Data"]
    for key in ("block_b", "cv_match", "match_data", "proof_points"):
        if key in eval_data:
            parts.append(f"### {key}")
            val = eval_data[key]
            if isinstance(val, dict):
                parts.append(json.dumps(val, indent=2))
            elif isinstance(val, list):
                for item in val:
                    parts.append(f"- {item}")
            else:
                parts.append(str(val))

    # Block F STAR stories for behavioral proof
    for key in ("block_f", "star_stories"):
        if key in eval_data:
            parts.append(f"### STAR Stories ({key})")
            val = eval_data[key]
            if isinstance(val, (dict, list)):
                parts.append(json.dumps(val, indent=2))
            else:
                parts.append(str(val))

    return "\n".join(parts) if len(parts) > 1 else ""


def _build_portfolio_block(profile: dict) -> str:
    """Include portfolio/case study URLs from the profile if available."""
    urls = []
    for key in ("portfolio_url", "portfolio", "case_studies", "github", "website"):
        val = profile.get(key)
        if val:
            if isinstance(val, list):
                urls.extend(val)
            else:
                urls.append(str(val))
    if not urls:
        return ""
    lines = ["## Portfolio / Case Studies (include if relevant)"]
    for url in urls:
        lines.append(f"- {url}")
    return "\n".join(lines)


async def generate_cover_letter(
    job: Job,
    profile: dict,
    llm,
    mode: ValidationMode = ValidationMode.STRICT,
    evaluation_data: dict | None = None,
) -> str | None:
    """Generate a humanized cover letter for a specific job.

    Parameters
    ----------
    evaluation_data:
        Optional pre-parsed evaluation dict. If *None*, falls back to ``job.evaluation``.

    Returns plain text cover letter body, or None if all retries fail.
    """
    name = profile.get("name", "Candidate")
    target_roles = ", ".join(profile.get("target_roles", [])[:5])
    skills = ", ".join(profile.get("skills", [])[:10])

    experience = profile.get("experience", [])
    exp_lines = []
    for exp in experience[:2]:
        company = exp.get("company", "")
        role = exp.get("title", "")
        highlights = exp.get("highlights", [])[:2]
        exp_lines.append(f"{role} at {company}: {'; '.join(highlights)}")
    experience_summary = " | ".join(exp_lines) if exp_lines else "2+ years software development"

    desc = (job.description or "No description")[:3000]

    evaluation_block = _build_cover_letter_evaluation_block(job, evaluation_data)
    portfolio_block = _build_portfolio_block(profile)

    prompt = _COVER_LETTER_PROMPT.format(
        name=name,
        target_roles=target_roles,
        skills=skills,
        experience_summary=experience_summary,
        job_title=job.title,
        job_company=job.company,
        job_location=job.location,
        job_tech_stack=job.tech_stack or "Not specified",
        job_description=desc,
        evaluation_block=evaluation_block,
        portfolio_block=portfolio_block,
    )

    for attempt in range(MAX_RETRIES + 1):
        try:
            response = await llm.generate(prompt)
            text = _clean_response(response)

            if not text or len(text) < 50:
                logger.warning(f"Cover letter too short on attempt {attempt + 1}")
                continue

            result = validate_cover_letter(text, job.company, mode=mode)

            if result.passed:
                if result.warnings:
                    logger.info(f"Cover letter passed with {result.warning_count} warnings")
                return text

            error_msgs = [i.message for i in result.errors]
            logger.warning(
                f"Cover letter validation failed (attempt {attempt + 1}): "
                f"{'; '.join(error_msgs[:5])}"
            )

            if attempt < MAX_RETRIES:
                prompt = (
                    prompt
                    + "\n\n## VALIDATION ERRORS (fix these):\n"
                    + "\n".join(f"- {m}" for m in error_msgs)
                    + "\n\nRewrite the cover letter fixing ALL the above issues."
                )

        except Exception as e:
            logger.warning(f"Cover letter generation failed on attempt {attempt + 1}: {e}")

    logger.error(f"All {MAX_RETRIES + 1} cover letter attempts failed for {job.url}")
    return None


def _clean_response(response: str) -> str:
    """Clean LLM response — remove code fences, extra whitespace."""
    response = re.sub(r"```\w*\s*\n?", "", response)
    response = re.sub(r"```\s*$", "", response)
    # Remove any "Dear..." or "Sincerely..." the LLM might add
    response = re.sub(r"^Dear\s+.*?,?\s*\n+", "", response, flags=re.IGNORECASE)
    response = re.sub(
        r"\n+(?:Sincerely|Best regards|Kind regards|Regards|Yours truly),?\s*\n.*$",
        "",
        response,
        flags=re.IGNORECASE | re.DOTALL,
    )
    return response.strip()
