from __future__ import annotations

import json
import logging

from job_hunter.database import Job, JobDB

logger = logging.getLogger(__name__)

_OUTREACH_PROMPT = """You are a LinkedIn outreach strategist. Generate hyper-targeted
connection messages for the candidate to send to people at the target company.

## Candidate Profile
{profile_summary}

## Target Job
- Title: {job_title}
- Company: {company}
- Location: {location}
- Description excerpt: {jd_excerpt}

## Instructions

1. Identify 4-5 outreach targets at {company}:
   - 1 likely hiring manager (the person this role reports to)
   - 1 recruiter or talent acquisition person
   - 2-3 peers (people in similar roles who could refer)

2. For EACH target, generate a LinkedIn connection message with EXACTLY 3 sentences:
   - Sentence 1 (Hook): A specific fact about {company}'s challenge, product, or recent news
     that shows you did your homework. NOT generic praise.
   - Sentence 2 (Proof): The candidate's single highest-impact, most relevant achievement.
     Use a concrete metric or outcome.
   - Sentence 3 (Ask): A low-pressure ask — coffee chat, quick question, or insight request.
     NOT "I'd love to pick your brain" or "Can you refer me?"

3. HARD CONSTRAINTS:
   - Each message MUST be 300 characters or fewer (count carefully)
   - NO corporate-speak: banned phrases include "I'm passionate", "synergy", "leverage",
     "I would love to", "excited to", "thrilled", "amazing company"
   - NEVER include phone numbers, email addresses, or personal contact info
   - Messages must feel like they come from a peer, not a supplicant
   - Vary the hook and proof across targets — do not repeat the same message

Return JSON only:
{{
  "targets": [
    {{
      "role": "hiring_manager|recruiter|peer",
      "name_suggestion": "<suggested title, e.g. 'VP of Engineering' or 'Senior SRE'>",
      "message": "<3-sentence message, max 300 chars>",
      "char_count": <integer>
    }}
  ]
}}

CRITICAL:
- Count characters precisely. If a message exceeds 300 characters, shorten it.
- Every hook must reference something specific to {company}, not generic industry trends.
- Every proof must reference real experience from the candidate profile."""


def _build_profile_summary(profile: dict) -> str:
    """Build a compact profile summary for the prompt."""
    parts: list[str] = []
    if profile.get("name"):
        parts.append(f"Name: {profile['name']}")
    if profile.get("title"):
        parts.append(f"Current title: {profile['title']}")
    if profile.get("summary"):
        parts.append(f"Summary: {profile['summary']}")

    experience = profile.get("experience", [])
    if experience:
        parts.append("Key experience:")
        for exp in experience[:3]:
            role = exp.get("title", "")
            company = exp.get("company", "")
            highlights = exp.get("highlights", [])
            parts.append(f"  - {role} at {company}")
            for h in highlights[:2]:
                parts.append(f"    * {h}")

    skills = profile.get("skills", [])
    if skills:
        parts.append(f"Skills: {', '.join(skills[:15])}")

    return "\n".join(parts)


def _truncate_jd(description: str | None, max_chars: int = 2000) -> str:
    """Truncate job description to fit prompt limits."""
    if not description:
        return "No description available."
    if len(description) <= max_chars:
        return description
    return description[:max_chars] + "..."


async def generate_outreach(job: Job, profile: dict, llm) -> dict:
    """Generate LinkedIn outreach messages for a job opportunity.

    Args:
        job: The Job to generate outreach for.
        profile: Candidate profile dict.
        llm: An LLMProvider instance.

    Returns:
        Dict with targets list, each containing role, name_suggestion,
        message, and char_count.
    """
    prompt = _OUTREACH_PROMPT.format(
        profile_summary=_build_profile_summary(profile),
        job_title=job.title,
        company=job.company,
        location=job.location or "Not specified",
        jd_excerpt=_truncate_jd(job.description),
    )

    try:
        response = await llm.generate(prompt, json_mode=True, max_tokens=2048)
        result = json.loads(response)
    except json.JSONDecodeError as e:
        logger.error(f"Failed to parse outreach JSON for {job.url}: {e}")
        return {"targets": [], "error": "LLM returned invalid JSON"}
    except Exception as e:
        logger.error(f"Outreach generation failed for {job.url}: {e}")
        return {"targets": [], "error": str(e)}

    # Validate and enforce char limit
    targets = result.get("targets", [])
    validated_targets: list[dict] = []
    for target in targets:
        message = target.get("message", "")
        char_count = len(message)
        if char_count > 300:
            logger.warning(
                f"Outreach message for {target.get('role', 'unknown')} "
                f"exceeds 300 chars ({char_count}), truncating"
            )
            # Truncate to last complete sentence within 300 chars
            message = _truncate_to_limit(message, 300)
            char_count = len(message)

        validated_targets.append(
            {
                "role": target.get("role", "peer"),
                "name_suggestion": target.get("name_suggestion", ""),
                "message": message,
                "char_count": char_count,
            }
        )

    return {"targets": validated_targets}


def _truncate_to_limit(text: str, limit: int) -> str:
    """Truncate text to limit, preferring sentence boundaries."""
    if len(text) <= limit:
        return text

    truncated = text[:limit]
    # Try to end at last sentence boundary
    for sep in (". ", "! ", "? "):
        last_sep = truncated.rfind(sep)
        if last_sep > limit // 2:
            return truncated[: last_sep + 1]

    # Fall back to word boundary
    last_space = truncated.rfind(" ")
    if last_space > limit // 2:
        return truncated[:last_space]

    return truncated


async def run_outreach(db: JobDB, profile: dict, llm, job_url: str) -> dict:
    """Generate outreach for a job and store it in the database.

    Args:
        db: JobDB instance.
        profile: Candidate profile dict.
        llm: An LLMProvider instance.
        job_url: URL of the job to generate outreach for.

    Returns:
        The outreach dict.
    """
    job = db.get_job(job_url)
    if job is None:
        logger.error(f"Job not found: {job_url}")
        return {"targets": [], "error": f"Job not found: {job_url}"}

    outreach = await generate_outreach(job, profile, llm)

    # Store in database
    job.outreach = json.dumps(outreach)
    db.upsert_job(job)
    logger.info(
        f"Generated outreach for {job.company} — {len(outreach.get('targets', []))} targets"
    )

    return outreach
