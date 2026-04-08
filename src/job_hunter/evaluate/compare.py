from __future__ import annotations

import json
import logging
from typing import Any

from job_hunter.database import Job

logger = logging.getLogger(__name__)

DIMENSIONS: dict[str, dict[str, Any]] = {
    "north_star_alignment": {
        "weight": 0.25,
        "description": (
            "How well does this role align with the candidate's long-term career "
            "goals, values, and the type of work they find most meaningful?"
        ),
    },
    "cv_match": {
        "weight": 0.15,
        "description": (
            "How closely do the job requirements match the candidate's existing "
            "skills, experience, and qualifications?"
        ),
    },
    "seniority_level": {
        "weight": 0.15,
        "description": (
            "Is the seniority level appropriate? A role at the right level or one "
            "step up is ideal. Significantly under- or over-leveled roles score lower."
        ),
    },
    "estimated_comp": {
        "weight": 0.10,
        "description": (
            "How competitive is the estimated total compensation (base + equity + "
            "bonus) compared to market rate for this role and location?"
        ),
    },
    "growth_trajectory": {
        "weight": 0.10,
        "description": (
            "What is the potential for skill development, career advancement, and "
            "learning new technologies or domains in this role?"
        ),
    },
    "remote_quality": {
        "weight": 0.05,
        "description": (
            "How well does the remote/hybrid/onsite policy match the candidate's "
            "preferences and life situation?"
        ),
    },
    "company_reputation": {
        "weight": 0.05,
        "description": (
            "How strong is the company's brand, market position, and reputation "
            "as an employer in the industry?"
        ),
    },
    "tech_stack_modernity": {
        "weight": 0.05,
        "description": (
            "How modern, well-maintained, and career-enhancing is the technology "
            "stack used in this role?"
        ),
    },
    "speed_to_offer": {
        "weight": 0.05,
        "description": (
            "How quickly is the company likely to move through the interview process "
            "and extend an offer? Faster pipelines score higher."
        ),
    },
    "cultural_signals": {
        "weight": 0.05,
        "description": (
            "What cultural signals are present in the JD and company info? "
            "Work-life balance, team autonomy, bureaucracy level, and values fit."
        ),
    },
}

_COMPARE_PROMPT = """You are a career decision analyst. Score the following job on 10
weighted dimensions using a 1-5 scale.

## Candidate Profile
{profile_summary}

## Job Details
- Title: {job_title}
- Company: {company}
- Location: {location}
- Score: {job_score}
- Description excerpt: {jd_excerpt}

## Evaluation Data (if available)
{evaluation_summary}

## Dimensions to Score (1 = poor, 5 = excellent)
{dimensions_text}

Return JSON only:
{{
  "scores": {{
    "north_star_alignment": <1-5>,
    "cv_match": <1-5>,
    "seniority_level": <1-5>,
    "estimated_comp": <1-5>,
    "growth_trajectory": <1-5>,
    "remote_quality": <1-5>,
    "company_reputation": <1-5>,
    "tech_stack_modernity": <1-5>,
    "speed_to_offer": <1-5>,
    "cultural_signals": <1-5>
  }},
  "notes": "<1-2 sentence summary of this job's strongest and weakest points>"
}}

CRITICAL:
- Base scores on concrete evidence from the JD and evaluation data.
- If information is missing for a dimension, score it 3 (neutral) and note the gap.
- Be calibrated: reserve 5 for truly exceptional matches and 1 for clear mismatches.
- Do NOT inflate scores. A realistic assessment helps the candidate make better decisions."""


def _build_profile_summary(profile: dict) -> str:
    """Build a compact profile summary for the prompt."""
    parts: list[str] = []
    if profile.get("name"):
        parts.append(f"Name: {profile['name']}")
    if profile.get("title"):
        parts.append(f"Current title: {profile['title']}")
    if profile.get("summary"):
        parts.append(f"Summary: {profile['summary']}")
    if profile.get("north_star"):
        parts.append(f"Career north star: {profile['north_star']}")

    experience = profile.get("experience", [])
    if experience:
        parts.append("Recent experience:")
        for exp in experience[:3]:
            role = exp.get("title", "")
            company = exp.get("company", "")
            parts.append(f"  - {role} at {company}")

    skills = profile.get("skills", [])
    if skills:
        parts.append(f"Skills: {', '.join(skills[:15])}")

    preferences = profile.get("preferences", {})
    if preferences:
        if preferences.get("remote"):
            parts.append(f"Remote preference: {preferences['remote']}")
        if preferences.get("location"):
            parts.append(f"Location preference: {preferences['location']}")

    return "\n".join(parts)


def _build_evaluation_summary(job: Job) -> str:
    """Extract key evaluation data if available."""
    if not job.evaluation:
        return "No evaluation data available."

    try:
        evaluation = json.loads(job.evaluation)
    except (json.JSONDecodeError, TypeError):
        return "Evaluation data could not be parsed."

    parts: list[str] = []
    blocks = evaluation.get("blocks", {})

    # Role summary
    role = blocks.get("role_summary", {})
    if "error" not in role:
        parts.append(f"Domain: {role.get('domain', 'unknown')}")
        parts.append(f"Seniority: {role.get('seniority', 'unknown')}")
        parts.append(f"Remote: {role.get('remote', 'unknown')}")
        if role.get("tldr"):
            parts.append(f"TL;DR: {role['tldr']}")

    # CV match
    cv = blocks.get("cv_match", {})
    if "error" not in cv:
        match_pct = cv.get("match_percentage", 0)
        parts.append(f"CV match: {match_pct:.0f}%")
        gaps = cv.get("gaps", [])
        blockers = [g for g in gaps if g.get("is_blocker")]
        if blockers:
            parts.append(f"Blockers: {', '.join(g.get('requirement', '') for g in blockers)}")

    # Level strategy
    level = blocks.get("level_strategy", {})
    if "error" not in level:
        parts.append(f"JD level: {level.get('jd_level', 'unknown')}")
        parts.append(f"Strategy: {level.get('strategy', 'unknown')}")

    # Comp intelligence
    comp = blocks.get("comp_intelligence", {})
    if "error" not in comp:
        salary = comp.get("salary_range", {})
        if salary.get("mid"):
            currency = salary.get("currency", "")
            parts.append(
                f"Comp range: {currency} {salary.get('low', '?')}-{salary.get('high', '?')}"
            )
        parts.append(f"Comp reputation: {comp.get('company_comp_reputation', 'unknown')}")

    return "\n".join(parts) if parts else "No structured evaluation data."


def _build_dimensions_text() -> str:
    """Format dimensions for the LLM prompt."""
    lines: list[str] = []
    for name, dim in DIMENSIONS.items():
        lines.append(f"- {name} (weight: {dim['weight']:.2f}): {dim['description']}")
    return "\n".join(lines)


def _truncate_jd(description: str | None, max_chars: int = 2000) -> str:
    """Truncate job description to fit prompt limits."""
    if not description:
        return "No description available."
    if len(description) <= max_chars:
        return description
    return description[:max_chars] + "..."


async def compare_jobs(jobs: list[Job], profile: dict, llm) -> list[dict]:
    """Score and rank multiple jobs across weighted dimensions.

    Args:
        jobs: List of Job objects to compare.
        profile: Candidate profile dict.
        llm: An LLMProvider instance.

    Returns:
        Sorted list of comparison results (best first), each containing:
        job_url, company, title, scores, weighted_total, rank, notes.
    """
    if not jobs:
        return []

    profile_summary = _build_profile_summary(profile)
    dimensions_text = _build_dimensions_text()
    results: list[dict] = []

    for job in jobs:
        try:
            prompt = _COMPARE_PROMPT.format(
                profile_summary=profile_summary,
                job_title=job.title,
                company=job.company,
                location=job.location or "Not specified",
                job_score=job.score or "N/A",
                jd_excerpt=_truncate_jd(job.description),
                evaluation_summary=_build_evaluation_summary(job),
                dimensions_text=dimensions_text,
            )

            response = await llm.generate(prompt, json_mode=True, max_tokens=1024)
            parsed = json.loads(response)
            scores = parsed.get("scores", {})

            # Validate and clamp scores to 1-5
            validated_scores: dict[str, int] = {}
            for dim_name in DIMENSIONS:
                raw_score = scores.get(dim_name, 3)
                try:
                    score = int(raw_score)
                except (ValueError, TypeError):
                    score = 3
                validated_scores[dim_name] = max(1, min(5, score))

            # Calculate weighted total
            weighted_total = sum(
                validated_scores[dim] * DIMENSIONS[dim]["weight"] for dim in DIMENSIONS
            )

            results.append(
                {
                    "job_url": job.url,
                    "company": job.company,
                    "title": job.title,
                    "scores": validated_scores,
                    "weighted_total": round(weighted_total, 2),
                    "rank": 0,  # assigned after sorting
                    "notes": parsed.get("notes", ""),
                }
            )
        except json.JSONDecodeError as e:
            logger.error(f"Failed to parse comparison JSON for {job.url}: {e}")
            results.append(_fallback_result(job, f"JSON parse error: {e}"))
        except Exception as e:
            logger.error(f"Comparison failed for {job.url}: {e}")
            results.append(_fallback_result(job, str(e)))

    # Sort by weighted total descending and assign ranks
    results.sort(key=lambda r: r["weighted_total"], reverse=True)
    for i, result in enumerate(results):
        result["rank"] = i + 1

    return results


def _fallback_result(job: Job, error_msg: str) -> dict:
    """Create a fallback result when scoring fails."""
    return {
        "job_url": job.url,
        "company": job.company,
        "title": job.title,
        "scores": {dim: 0 for dim in DIMENSIONS},
        "weighted_total": 0.0,
        "rank": 0,
        "notes": f"Scoring failed: {error_msg}",
    }


def format_comparison_table(results: list[dict]) -> str:
    """Format comparison results as a Rich-compatible table string.

    Args:
        results: Sorted list of comparison result dicts.

    Returns:
        A string formatted for display with Rich or plain terminal output.
    """
    if not results:
        return "No jobs to compare."

    # Column headers: short dimension labels
    dim_labels = {
        "north_star_alignment": "North*",
        "cv_match": "CV",
        "seniority_level": "Level",
        "estimated_comp": "Comp",
        "growth_trajectory": "Growth",
        "remote_quality": "Remote",
        "company_reputation": "Reptn",
        "tech_stack_modernity": "Tech",
        "speed_to_offer": "Speed",
        "cultural_signals": "Cultr",
    }

    # Build header
    header_parts = [
        f"{'#':>2}",
        f"{'Company':<20}",
        f"{'Title':<25}",
    ]
    for dim_name in DIMENSIONS:
        label = dim_labels.get(dim_name, dim_name[:5])
        header_parts.append(f"{label:>6}")
    header_parts.append(f"{'Total':>6}")
    header = " | ".join(header_parts)

    separator = "-" * len(header)

    # Build rows
    rows: list[str] = []
    for result in results:
        row_parts = [
            f"{result['rank']:>2}",
            f"{result['company'][:20]:<20}",
            f"{result['title'][:25]:<25}",
        ]
        scores = result.get("scores", {})
        for dim_name in DIMENSIONS:
            score = scores.get(dim_name, 0)
            row_parts.append(f"{score:>6}")
        row_parts.append(f"{result['weighted_total']:>6.2f}")
        rows.append(" | ".join(row_parts))

    # Build weight reference row
    weight_parts = [
        f"{'':>2}",
        f"{'(weights)':20}",
        f"{'':25}",
    ]
    for dim_name in DIMENSIONS:
        weight = DIMENSIONS[dim_name]["weight"]
        weight_parts.append(f"{weight:>6.2f}")
    weight_parts.append(f"{'1.00':>6}")
    weight_row = " | ".join(weight_parts)

    # Assemble table
    lines = [
        "",
        "Job Comparison Matrix",
        "=" * len(header),
        header,
        separator,
        *rows,
        separator,
        weight_row,
        "",
    ]

    # Add notes section
    notes_with_content = [
        r for r in results if r.get("notes") and "Scoring failed" not in r.get("notes", "")
    ]
    if notes_with_content:
        lines.append("Notes:")
        for r in notes_with_content:
            lines.append(f"  #{r['rank']} {r['company']}: {r['notes']}")
        lines.append("")

    return "\n".join(lines)
