"""Portfolio project evaluator.

Scores project ideas on 6 weighted dimensions and provides a BUILD/SKIP/PIVOT
verdict with weekly milestones and interview prep materials.
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

# Dimension definitions with weights
DIMENSIONS = {
    "signal_for_target_roles": {
        "weight": 0.25,
        "criteria": "5=directly demonstrates JD skill, 1=irrelevant to target roles",
    },
    "uniqueness": {
        "weight": 0.20,
        "criteria": "5=nobody has done this, 1=thousands of identical tutorials",
    },
    "demo_ability": {
        "weight": 0.20,
        "criteria": "5=live demo in 2 min, 1=requires complex setup or no visual output",
    },
    "metrics_potential": {
        "weight": 0.15,
        "criteria": "5=clear latency/cost/accuracy metrics, 1=no measurable outcomes",
    },
    "time_to_mvp": {
        "weight": 0.10,
        "criteria": "5=1 week MVP, 4=2 weeks, 3=1 month, 2=2 months, 1=3+ months",
    },
    "star_story_potential": {
        "weight": 0.10,
        "criteria": "5=rich story with trade-offs and lessons, 1=trivial with no depth",
    },
}


def _repair_json(text: str) -> dict:
    """Attempt to parse JSON from LLM response with repair heuristics."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    cleaned = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    if start >= 0:
        content = text[start:]
        open_braces = content.count("{") - content.count("}")
        open_brackets = content.count("[") - content.count("]")
        content = content.rstrip().rstrip(",")
        content += "]" * max(0, open_brackets) + "}" * max(0, open_braces)
        try:
            return json.loads(content)
        except json.JSONDecodeError:
            pass

    raise ValueError(f"Could not parse JSON from LLM response: {text[:200]}")


_PROJECT_EVAL_PROMPT = """You are an expert career strategist evaluating a portfolio project idea for a job seeker.

## Project Idea
{idea}

## Candidate Profile
- Target roles: {target_roles}
- Skills: {skills}
- Years of experience: {yoe}
- Current projects/experience highlights: {experience_highlights}

## Evaluation Dimensions
Score each dimension 1-5:

1. **signal_for_target_roles** (weight 0.25): Does this project directly demonstrate skills from target JDs? 5=directly demonstrates JD skill, 1=irrelevant.
2. **uniqueness** (weight 0.20): How original is this? 5=nobody has done this, 1=thousands of identical tutorials.
3. **demo_ability** (weight 0.20): Can you show a compelling live demo in 2 minutes? 5=yes easily, 1=no visual output.
4. **metrics_potential** (weight 0.15): Will you get clear, quantifiable metrics (latency, cost, accuracy)? 5=yes, 1=no.
5. **time_to_mvp** (weight 0.10): How long to a working MVP? 5=1 week, 4=2 weeks, 3=1 month, 2=2 months, 1=3+ months.
6. **star_story_potential** (weight 0.10): Will this produce a rich STAR interview story with trade-offs? 5=yes, 1=trivial.

## Verdict Rules
- **BUILD**: weighted_total >= 3.5. Include 4-6 weekly milestones and an interview_pack.
- **PIVOT**: weighted_total >= 2.5 but < 3.5 AND a better variant exists. Describe the better variant.
- **SKIP**: weighted_total < 2.5 OR a fundamentally better alternative exists. Suggest the alternative.

## Interview Pack (only if BUILD)
- one_pager: Key architecture decisions, metrics, and lessons (bullet points)
- demo_script: 2-minute demo walkthrough script
- postmortem_outline: What went wrong, what you learned, what you'd do differently

Return JSON:
{{
  "scores": {{
    "signal_for_target_roles": {{"score": 1-5, "reasoning": "..."}},
    "uniqueness": {{"score": 1-5, "reasoning": "..."}},
    "demo_ability": {{"score": 1-5, "reasoning": "..."}},
    "metrics_potential": {{"score": 1-5, "reasoning": "..."}},
    "time_to_mvp": {{"score": 1-5, "reasoning": "..."}},
    "star_story_potential": {{"score": 1-5, "reasoning": "..."}}
  }},
  "weighted_total": 0.0,
  "verdict": "BUILD/SKIP/PIVOT",
  "milestones": ["Week 1: ...", "Week 2: ...", ...],
  "interview_pack": {{
    "one_pager": "...",
    "demo_script": "...",
    "postmortem_outline": "..."
  }},
  "alternative": null or "Better project idea description if SKIP/PIVOT"
}}"""


async def evaluate_project(idea: str, profile: dict, llm) -> dict:
    """Score a portfolio project idea on 6 dimensions.

    Args:
        idea: Description of the project idea.
        profile: Candidate profile dict.
        llm: LLM provider instance.

    Returns:
        Dict with scores, weighted_total, verdict, milestones,
        interview_pack, and alternative.
    """
    # Truncate long inputs
    idea_truncated = idea[:2000]

    experience_highlights = ""
    if profile.get("experience"):
        highlights = profile["experience"]
        if isinstance(highlights, list):
            highlights = "; ".join(
                str(e.get("title", "") + " at " + str(e.get("company", "")))
                if isinstance(e, dict)
                else str(e)
                for e in highlights[:5]
            )
        experience_highlights = str(highlights)[:500]

    prompt = _PROJECT_EVAL_PROMPT.format(
        idea=idea_truncated,
        target_roles=", ".join(profile.get("target_roles", []))[:200],
        skills=", ".join(profile.get("skills", []))[:300],
        yoe=profile.get("years_of_experience", "Not specified"),
        experience_highlights=experience_highlights or "Not provided",
    )

    try:
        response = await llm.generate(prompt, json_mode=True, max_tokens=4096)
        result = _repair_json(response)

        # Validate and recompute weighted total for consistency
        scores = result.get("scores", {})
        computed_total = 0.0
        for dim_name, dim_info in DIMENSIONS.items():
            dim_score = scores.get(dim_name, {})
            score_val = dim_score.get("score", 0) if isinstance(dim_score, dict) else 0
            score_val = max(1, min(5, int(score_val)))
            computed_total += score_val * dim_info["weight"]

        result["weighted_total"] = round(computed_total, 2)

        # Ensure verdict consistency
        if result.get("verdict") not in ("BUILD", "SKIP", "PIVOT"):
            if computed_total >= 3.5:
                result["verdict"] = "BUILD"
            elif computed_total >= 2.5:
                result["verdict"] = "PIVOT"
            else:
                result["verdict"] = "SKIP"

        # Ensure required fields exist
        result.setdefault("milestones", [])
        result.setdefault("interview_pack", {})
        result.setdefault("alternative", None)

        logger.info(
            f"Project evaluation: {result['verdict']} "
            f"(weighted_total={result['weighted_total']})"
        )
        return result

    except Exception as e:
        logger.error(f"Project evaluation failed: {e}")
        return {
            "error": str(e),
            "scores": {dim: {"score": 0, "reasoning": "Evaluation failed"} for dim in DIMENSIONS},
            "weighted_total": 0.0,
            "verdict": "SKIP",
            "milestones": [],
            "interview_pack": {},
            "alternative": "Evaluation failed. Please retry.",
        }
