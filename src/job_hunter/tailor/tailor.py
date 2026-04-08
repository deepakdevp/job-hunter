from __future__ import annotations

import json
import logging
import re

from job_hunter.database import Job
from job_hunter.tailor.parser import ParsedResume
from job_hunter.tailor.validator import validate_resume, ValidationMode

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Keyword extraction prompt
# ---------------------------------------------------------------------------

_KEYWORD_EXTRACTION_PROMPT = """\
You are an ATS keyword analyst. Extract the most important keywords from the job description and map them to the candidate's real experience.

## Job Description
{job_description}

## Candidate Skills & Experience
- Skills: {skills}
- Experience summary: {experience_summary}

## Instructions
1. Extract 15-20 ATS-critical keywords/phrases from the JD (technical skills, tools, methodologies, soft skills).
2. For EACH keyword, find the closest matching experience the candidate ACTUALLY has.
3. If the candidate has NO matching experience for a keyword, set source_experience to null.
4. Suggest a reformulation that uses the JD's exact vocabulary while staying truthful.

Example: JD says "RAG pipelines" + candidate has "LLM workflows with retrieval" \
-> reformulation: "RAG pipeline design and LLM orchestration workflows"

Respond with JSON only:
{{
  "keywords": [
    {{"keyword": "...", "source_experience": "..." or null, "reformulation": "..." or null}}
  ],
  "coverage_pct": <0.0-1.0 fraction of keywords the candidate can legitimately claim>
}}
"""

# ---------------------------------------------------------------------------
# Main tailoring prompt
# ---------------------------------------------------------------------------

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

## Archetype Detection
Detect the role archetype from the JD (e.g., Backend Engineer, Full-Stack, ML Engineer, DevOps, \
Engineering Manager) and bias section ordering and keyword density accordingly.

## Keyword Injection Rules
- Reformulate real experience with exact JD vocabulary.
  Example: JD "RAG pipelines" + resume "LLM workflows with retrieval" -> \
  "RAG pipeline design and LLM orchestration workflows".
- NEVER add skills the candidate doesn't have.
- Use the ATS Keywords section below to guide which terms to inject.

## ATS Compliance
- Use single-column layout. No text embedded in images.
- Use standard section headers: Experience, Education, Skills, Projects.
- Add a "Core Competencies" section with 6-8 keyword tags from the JD mapped to real skills.

## Exit Narrative
Bridge past experience to future role in the summary/objective: explain WHY the candidate is \
moving toward THIS role at THIS company.

## Bullet Ordering
Reorder experience bullets by relevance to THIS JD (most relevant first within each role).

{evaluation_block}
{keywords_block}

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


async def extract_keywords(job: Job, llm, profile: dict | None = None) -> dict:
    """Extract ATS keywords from JD and map to candidate experience.

    Returns ``{"keywords": [...], "coverage_pct": float}``.
    """
    profile = profile or {}
    skills = ", ".join(profile.get("skills", []))

    experience = profile.get("experience", [])
    exp_lines = []
    for exp in experience[:3]:
        company = exp.get("company", "")
        role = exp.get("title", "")
        highlights = exp.get("highlights", [])[:3]
        exp_lines.append(f"{role} at {company}: {'; '.join(highlights)}")
    experience_summary = " | ".join(exp_lines) if exp_lines else skills

    desc = (job.description or "")[:4000]
    if not desc:
        return {"keywords": [], "coverage_pct": 0.0}

    prompt = _KEYWORD_EXTRACTION_PROMPT.format(
        job_description=desc,
        skills=skills,
        experience_summary=experience_summary,
    )

    try:
        raw = await llm.generate(prompt, max_tokens=2048)
        # Strip markdown code fences if present
        raw = re.sub(r"```(?:json)?\s*\n?", "", raw)
        raw = re.sub(r"```\s*$", "", raw)
        data = json.loads(raw)
        return {
            "keywords": data.get("keywords", []),
            "coverage_pct": float(data.get("coverage_pct", 0.0)),
        }
    except Exception:
        logger.warning("Keyword extraction failed for %s", job.url, exc_info=True)
        return {"keywords": [], "coverage_pct": 0.0}


def _build_evaluation_block(job: Job) -> str:
    """Format evaluation data for the tailoring prompt (Block E personalization)."""
    if not job.evaluation:
        return ""
    try:
        eval_data = json.loads(job.evaluation)
    except (json.JSONDecodeError, TypeError):
        return ""

    parts = ["## Evaluation Personalization (Block E)"]
    # Extract relevant blocks if they exist
    for key in ("block_e", "personalization_plan", "cv_match", "block_b"):
        if key in eval_data:
            parts.append(f"### {key}")
            val = eval_data[key]
            if isinstance(val, dict):
                parts.append(json.dumps(val, indent=2))
            else:
                parts.append(str(val))

    if len(parts) == 1:
        # No relevant blocks found, dump a summary
        parts.append("Use the following evaluation data to personalize the resume:")
        # Include top-level keys as summary
        for k, v in eval_data.items():
            if isinstance(v, str) and len(v) < 500:
                parts.append(f"- {k}: {v}")

    return "\n".join(parts)


def _build_keywords_block(keywords_data: dict) -> str:
    """Format extracted keywords for the tailoring prompt."""
    keywords = keywords_data.get("keywords", [])
    if not keywords:
        return ""

    coverage = keywords_data.get("coverage_pct", 0.0)
    lines = [
        f"## ATS Keywords (coverage: {coverage:.0%})",
        "Inject these terms where the candidate has matching experience:",
    ]
    for kw in keywords:
        keyword = kw.get("keyword", "")
        source = kw.get("source_experience")
        reformulation = kw.get("reformulation")
        if source:
            lines.append(
                f"- **{keyword}**: source='{source}' -> use '{reformulation or keyword}'"
            )
        else:
            lines.append(f"- **{keyword}**: NO match — do NOT inject")

    return "\n".join(lines)


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

    # --- keyword extraction pipeline ---
    keywords_data = await extract_keywords(job, llm, profile=profile)
    logger.info(
        "Keyword extraction for %s: %d keywords, %.0f%% coverage",
        job.url,
        len(keywords_data.get("keywords", [])),
        keywords_data.get("coverage_pct", 0) * 100,
    )

    # --- evaluation block ---
    evaluation_block = _build_evaluation_block(job)

    # --- keywords block ---
    keywords_block = _build_keywords_block(keywords_data)

    prompt = _TAILOR_PROMPT.format(
        resume_latex=resume.full_text[:8000],
        target_roles=target_roles,
        skills=skills,
        job_title=job.title,
        job_company=job.company,
        job_location=job.location,
        job_tech_stack=job.tech_stack or "Not specified",
        job_description=desc,
        evaluation_block=evaluation_block,
        keywords_block=keywords_block,
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
                # Store extracted keywords on the job object
                if keywords_data.get("keywords"):
                    job.keywords = json.dumps(keywords_data)
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
