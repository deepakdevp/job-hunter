"""Negotiation intelligence module.

Generates market-calibrated compensation data, word-for-word negotiation
scripts, contractor rate guidance, and geographic arbitrage notes.
"""

from __future__ import annotations

import json
import logging
import re

from job_hunter.database import Job, JobDB

logger = logging.getLogger(__name__)


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

    # Remove trailing commas before } or ]
    cleaned = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    # Find first JSON object
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


_NEGOTIATION_PROMPT = """You are an expert compensation negotiation coach. Generate negotiation intelligence for a job candidate.

## Job Details
- Title: {title}
- Company: {company}
- Location: {location}
- Remote Policy: {remote_policy}
- Contract Type: {contract_type}
- Salary (from JD): {salary_raw}

## Evaluation Comp Data (if available)
{eval_comp_data}

## Candidate Profile
- Target roles: {target_roles}
- Years of experience: {yoe}
- Current location: {candidate_location}
- Skills: {skills}

## Instructions
Generate comprehensive negotiation intelligence:

1. **Market Data**: Estimate salary range for this role, location, and seniority. Include sources/methodology.
2. **Negotiation Scripts**: Word-for-word scripts for common scenarios:
   - salary_expectations: How to state your target range professionally
   - geographic_discount_pushback: How to counter location-based pay cuts for remote roles
   - below_target_counter: How to counter when an offer is below your range
   - competing_offers: How to leverage other opportunities
   - benefits_negotiation: How to negotiate non-salary components
3. **Contractor Rate**: If this could be contract work, calculate contractor rate (30-50% premium over employee base to cover benefits, taxes, instability).
4. **Geographic Arbitrage**: Notes on cost-of-living differences if the role is remote and candidate is in a different location than the company HQ.

Return JSON:
{{
  "market_data": {{
    "salary_range": {{
      "low": "amount with currency",
      "mid": "amount with currency",
      "high": "amount with currency",
      "currency": "USD/JPY/EUR/etc"
    }},
    "sources": ["methodology or data source descriptions"],
    "confidence": "HIGH/MEDIUM/LOW",
    "factors": "what drives this range (seniority, location, demand)"
  }},
  "scripts": [
    {{
      "scenario": "salary_expectations",
      "script": "Based on market data for this role, I'm targeting [range]. I'm flexible on structure -- what matters is total package and opportunity."
    }},
    {{
      "scenario": "geographic_discount_pushback",
      "script": "The roles I'm competitive for are output-based, not location-based. My track record doesn't change based on postal code."
    }},
    {{
      "scenario": "below_target_counter",
      "script": "I'm comparing with opportunities in [higher range]. I'm drawn to [company] because of [reason]. Can we explore [target]?"
    }},
    {{
      "scenario": "competing_offers",
      "script": "..."
    }},
    {{
      "scenario": "benefits_negotiation",
      "script": "..."
    }}
  ],
  "contractor_rate": "Estimated contractor/freelance rate with calculation basis",
  "notes": "Geographic arbitrage observations, timing advice, red flags, etc."
}}"""


async def generate_negotiation(job: Job, profile: dict, llm) -> dict:
    """Generate negotiation intelligence for a job.

    Pulls comp data from evaluation Block D if available, otherwise
    relies on LLM knowledge. Returns structured negotiation data.
    """
    # Extract evaluation comp data if available
    eval_comp_data = "No evaluation data available."
    if job.evaluation:
        try:
            evaluation = json.loads(job.evaluation)
            comp = evaluation.get("blocks", {}).get("comp_intelligence", {})
            if comp and "error" not in comp:
                eval_comp_data = json.dumps(comp, indent=2)[:1500]
        except (json.JSONDecodeError, TypeError):
            pass

    prompt = _NEGOTIATION_PROMPT.format(
        title=job.title,
        company=job.company,
        location=job.location or "Not specified",
        remote_policy=job.remote_policy or "Not specified",
        contract_type=job.contract_type or "Not specified",
        salary_raw=job.salary_raw or "Not listed",
        eval_comp_data=eval_comp_data,
        target_roles=", ".join(profile.get("target_roles", []))[:200],
        yoe=profile.get("years_of_experience", "Not specified"),
        candidate_location=profile.get("location", "Not specified"),
        skills=", ".join(profile.get("skills", []))[:300],
    )

    try:
        response = await llm.generate(prompt, json_mode=True, max_tokens=4096)
        result = _repair_json(response)
        logger.info(
            f"Generated negotiation intelligence for {job.title} at {job.company}"
        )
        return result
    except Exception as e:
        logger.error(f"Negotiation generation failed for {job.url}: {e}")
        return {
            "error": str(e),
            "market_data": {"salary_range": {}, "sources": [], "confidence": "LOW"},
            "scripts": [],
            "contractor_rate": "Unable to generate",
            "notes": "Negotiation generation failed. Retry or generate manually.",
        }


async def run_negotiation(
    db: JobDB, profile: dict, llm, job_url: str
) -> dict:
    """Generate negotiation data for a specific job and store it.

    Args:
        db: Job database.
        profile: Candidate profile dict.
        llm: LLM provider instance.
        job_url: URL of the job to generate negotiation for.

    Returns:
        The negotiation dict, or an error dict if the job is not found.
    """
    job = db.get_job(job_url)
    if job is None:
        logger.error(f"Job not found: {job_url}")
        return {"error": f"Job not found: {job_url}"}

    result = await generate_negotiation(job, profile, llm)

    # Store in database
    job.negotiation = json.dumps(result)
    db.upsert_job(job)
    logger.info(f"Stored negotiation data for {job.title} at {job.company}")

    return result
