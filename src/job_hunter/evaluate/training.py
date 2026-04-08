"""Course/certification evaluator.

Evaluates training opportunities on 6 dimensions and provides a
DO/SKIP/DO_WITH_TIMEBOX verdict with a study plan.
"""

from __future__ import annotations

import json
import logging
import re

logger = logging.getLogger(__name__)

# Dimension definitions
TRAINING_DIMENSIONS = {
    "north_star_alignment": "Does this move you closer to your target roles?",
    "recruiter_signal": "What do hiring managers think of this credential?",
    "time_investment": "Weeks x hours/week -- is the ROI worth it?",
    "opportunity_cost": "What can't you do during that time (projects, applying, networking)?",
    "risks": "Outdated content? Weak brand? Too basic? Too advanced?",
    "portfolio_deliverable": "Does it produce a demonstrable artifact (project, paper, demo)?",
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


_TRAINING_EVAL_PROMPT = """You are an expert career strategist evaluating whether a job seeker should invest time in a course or certification.

## Course/Certification
{course}

## Candidate Profile
- Target roles: {target_roles}
- Current skills: {skills}
- Years of experience: {yoe}
- Current gaps or focus areas: {gaps}

## Evaluation Dimensions
Score each dimension 1-5 with reasoning:

1. **north_star_alignment**: Does completing this move the candidate measurably closer to their target roles? 5=directly qualifies for target roles, 1=irrelevant tangent.
2. **recruiter_signal**: How do hiring managers and recruiters view this credential? 5=strong positive signal (e.g., AWS SA Pro, GCP ML Engineer), 3=nice-to-have, 1=ignored or negative signal.
3. **time_investment**: Consider weeks x hours/week. Is the ROI justified? 5=high ROI (short time, big impact), 1=months of effort for minimal return.
4. **opportunity_cost**: What could the candidate do instead (build projects, apply to jobs, network)? 5=low opportunity cost (can do alongside other things), 1=full-time commitment that blocks everything else.
5. **risks**: Content outdated? Provider has weak brand? Level mismatch (too basic/advanced)? 5=no significant risks, 1=multiple serious risks.
6. **portfolio_deliverable**: Does it produce something demonstrable (capstone project, published paper, deployed system)? 5=strong portfolio piece, 1=just a certificate PDF.

## Verdict Rules
- **DO**: Most dimensions score 3+, strong north_star_alignment (4-5). Include a 4-12 week study plan.
- **DO_WITH_TIMEBOX**: Mixed scores but some value. Specify max weeks to invest before cutting losses.
- **SKIP**: Low scores on north_star_alignment or recruiter_signal. Suggest a better alternative.

Return JSON:
{{
  "scores": {{
    "north_star_alignment": {{"score": 1-5, "reasoning": "..."}},
    "recruiter_signal": {{"score": 1-5, "reasoning": "..."}},
    "time_investment": {{"score": 1-5, "reasoning": "..."}},
    "opportunity_cost": {{"score": 1-5, "reasoning": "..."}},
    "risks": {{"score": 1-5, "reasoning": "..."}},
    "portfolio_deliverable": {{"score": 1-5, "reasoning": "..."}}
  }},
  "verdict": "DO/SKIP/DO_WITH_TIMEBOX",
  "plan": ["Week 1: ...", "Week 2: ...", ...],
  "timebox_weeks": null or number (only for DO_WITH_TIMEBOX),
  "alternative": null or "Better course/cert suggestion if SKIP or DO_WITH_TIMEBOX"
}}"""


async def evaluate_training(course: str, profile: dict, llm) -> dict:
    """Evaluate a course or certification for career value.

    Args:
        course: Description of the course or certification.
        profile: Candidate profile dict.
        llm: LLM provider instance.

    Returns:
        Dict with scores, verdict, plan, and alternative.
    """
    # Truncate long inputs
    course_truncated = course[:2000]

    # Extract gaps from profile if available
    gaps = ""
    if profile.get("gaps"):
        gaps = ", ".join(profile["gaps"])[:300] if isinstance(profile["gaps"], list) else str(profile["gaps"])[:300]
    elif profile.get("target_roles"):
        gaps = "Focused on landing target roles"

    prompt = _TRAINING_EVAL_PROMPT.format(
        course=course_truncated,
        target_roles=", ".join(profile.get("target_roles", []))[:200],
        skills=", ".join(profile.get("skills", []))[:300],
        yoe=profile.get("years_of_experience", "Not specified"),
        gaps=gaps or "Not specified",
    )

    try:
        response = await llm.generate(prompt, json_mode=True, max_tokens=4096)
        result = _repair_json(response)

        # Validate scores
        scores = result.get("scores", {})
        for dim_name in TRAINING_DIMENSIONS:
            dim_score = scores.get(dim_name, {})
            if isinstance(dim_score, dict) and "score" in dim_score:
                dim_score["score"] = max(1, min(5, int(dim_score["score"])))
            elif not isinstance(dim_score, dict):
                scores[dim_name] = {"score": 0, "reasoning": "Not evaluated"}

        # Ensure verdict consistency
        if result.get("verdict") not in ("DO", "SKIP", "DO_WITH_TIMEBOX"):
            north_star = scores.get("north_star_alignment", {}).get("score", 0)
            recruiter = scores.get("recruiter_signal", {}).get("score", 0)
            if north_star >= 4 and recruiter >= 3:
                result["verdict"] = "DO"
            elif north_star <= 2 or recruiter <= 2:
                result["verdict"] = "SKIP"
            else:
                result["verdict"] = "DO_WITH_TIMEBOX"

        # Ensure required fields exist
        result.setdefault("plan", [])
        result.setdefault("timebox_weeks", None)
        result.setdefault("alternative", None)

        logger.info(f"Training evaluation: {result['verdict']}")
        return result

    except Exception as e:
        logger.error(f"Training evaluation failed: {e}")
        return {
            "error": str(e),
            "scores": {
                dim: {"score": 0, "reasoning": "Evaluation failed"}
                for dim in TRAINING_DIMENSIONS
            },
            "verdict": "SKIP",
            "plan": [],
            "timebox_weeks": None,
            "alternative": "Evaluation failed. Please retry.",
        }
