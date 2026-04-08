from __future__ import annotations

import json
import logging

from job_hunter.database import Job
from job_hunter.evaluate.archetype import ARCHETYPES

logger = logging.getLogger(__name__)


def _truncate_jd(job: Job) -> str:
    """Truncate job description to 4000 chars for LLM prompts."""
    return (job.description or "No description available.")[:4000]


def _profile_summary(profile: dict) -> str:
    """Build a concise profile summary for LLM prompts."""
    lines = []
    lines.append(f"Name: {profile.get('name', 'Candidate')}")
    lines.append(f"Target roles: {', '.join(profile.get('target_roles', []))}")
    lines.append(f"Skills: {', '.join(profile.get('skills', []))}")

    education = profile.get("education", [])
    if education:
        edu_lines = []
        for edu in education[:2]:
            degree = edu.get("degree", "")
            school = edu.get("school", "")
            edu_lines.append(f"{degree} from {school}")
        lines.append(f"Education: {'; '.join(edu_lines)}")

    experience = profile.get("experience", [])
    for exp in experience[:4]:
        title = exp.get("title", "")
        company = exp.get("company", "")
        highlights = exp.get("highlights", [])[:3]
        hl_str = "; ".join(highlights) if highlights else "N/A"
        lines.append(f"Experience: {title} at {company} — {hl_str}")

    return "\n".join(lines)


def _archetype_context(archetype: dict) -> str:
    """Build archetype context string for prompts."""
    primary_key = archetype.get("primary", "full_stack")
    primary = ARCHETYPES.get(primary_key, ARCHETYPES["full_stack"])
    ctx = f"Primary archetype: {primary['name']}\n"
    ctx += f"Proof priorities: {', '.join(primary['proof_priorities'])}\n"
    ctx += f"Framing: {primary['framing']}"

    secondary_key = archetype.get("secondary")
    if secondary_key and secondary_key in ARCHETYPES:
        sec = ARCHETYPES[secondary_key]
        ctx += f"\nSecondary archetype: {sec['name']}"
        ctx += f"\nSecondary proof priorities: {', '.join(sec['proof_priorities'])}"

    return ctx


async def _llm_json(llm, prompt: str, max_tokens: int = 4096) -> dict:
    """Call LLM with json_mode and parse the response."""
    response = await llm.generate(prompt, json_mode=True, max_tokens=max_tokens)
    return json.loads(response)


# ---------------------------------------------------------------------------
# Block A: Role Summary
# ---------------------------------------------------------------------------

_BLOCK_A_PROMPT = """You are a job analysis expert. Extract structured role information from this job description.

## Job Details
- Title: {title}
- Company: {company}
- Location: {location}

## Archetype Context
{archetype_context}

## Job Description
{jd}

Return JSON only:
{{
  "archetype": "{primary_archetype}",
  "domain": "<industry/domain, e.g. fintech, healthcare, e-commerce>",
  "function": "<primary function, e.g. product development, platform engineering>",
  "seniority": "<junior/mid/senior/staff/principal/lead/manager>",
  "remote": "<remote/hybrid/onsite/unknown>",
  "team_size": "<team size if mentioned, otherwise 'unknown'>",
  "tldr": "<1-2 sentence plain-English summary of what this person will actually do day-to-day>"
}}

IMPORTANT: Base every field strictly on the JD text. If information is not present, use 'unknown'. NEVER invent details."""


async def block_a_role_summary(
    job: Job, profile: dict, llm, archetype: dict
) -> dict:
    """Extract structured role summary from the job description."""
    prompt = _BLOCK_A_PROMPT.format(
        title=job.title,
        company=job.company,
        location=job.location or "Unknown",
        archetype_context=_archetype_context(archetype),
        jd=_truncate_jd(job),
        primary_archetype=archetype.get("primary", "full_stack"),
    )
    try:
        return await _llm_json(llm, prompt)
    except Exception as e:
        logger.warning(f"Block A failed for {job.url}: {e}")
        return {
            "archetype": archetype.get("primary", "full_stack"),
            "domain": "unknown",
            "function": "unknown",
            "seniority": job.seniority or "unknown",
            "remote": job.remote_policy or "unknown",
            "team_size": job.team_size or "unknown",
            "tldr": f"{job.title} at {job.company}",
        }


# ---------------------------------------------------------------------------
# Block B: CV Match Analysis
# ---------------------------------------------------------------------------

_BLOCK_B_PROMPT = """You are a resume-matching expert. Map every requirement in the JD to the candidate's profile.

## Candidate Profile
{profile_summary}

## Archetype Context
{archetype_context}

## Job Description
{jd}

For EACH requirement in the JD:
1. If the candidate has matching experience, list it as a match with strength (strong/moderate/weak).
2. If not, list it as a gap — note if it is a blocker (hard requirement) or nice-to-have, and suggest adjacent experience that partially covers it plus a mitigation strategy.

Prioritize requirements aligned with the archetype's proof_priorities.

Return JSON only:
{{
  "matches": [
    {{"requirement": "<JD requirement>", "cv_line": "<specific experience from profile>", "strength": "strong|moderate|weak"}}
  ],
  "gaps": [
    {{"requirement": "<JD requirement>", "is_blocker": true|false, "adjacent_experience": "<closest relevant experience or null>", "mitigation": "<how to address this gap>"}}
  ],
  "match_percentage": <0.0-100.0>
}}

IMPORTANT: NEVER invent experience or skills the candidate does not have. Only reference what is in the profile. If the candidate lacks something, say so honestly."""


async def block_b_cv_match(
    job: Job, profile: dict, llm, archetype: dict
) -> dict:
    """Map JD requirements to candidate profile."""
    prompt = _BLOCK_B_PROMPT.format(
        profile_summary=_profile_summary(profile),
        archetype_context=_archetype_context(archetype),
        jd=_truncate_jd(job),
    )
    try:
        return await _llm_json(llm, prompt, max_tokens=8192)
    except Exception as e:
        logger.warning(f"Block B failed for {job.url}: {e}")
        return {"matches": [], "gaps": [], "match_percentage": 0.0}


# ---------------------------------------------------------------------------
# Block C: Level Strategy
# ---------------------------------------------------------------------------

_BLOCK_C_PROMPT = """You are a career-level strategist. Analyze the seniority match between this candidate and the job.

## Candidate Profile
{profile_summary}

## Job Description
{jd}

Determine:
1. The JD's expected seniority level
2. The candidate's actual seniority level based on their experience
3. Whether there is a mismatch and what strategy to use

If the candidate is MORE senior than the role requires, provide a "sell senior" strategy — how to frame their experience as an asset without seeming overqualified.
If the candidate is LESS senior, provide an "upleveling" strategy — how to frame adjacent experience.
If levels match, strategy should be "aligned".

Return JSON only:
{{
  "jd_level": "<junior/mid/senior/staff/principal/lead/manager>",
  "candidate_level": "<junior/mid/senior/staff/principal/lead/manager>",
  "strategy": "aligned|sell_senior|uplevel",
  "downlevel_plan": "<1-3 sentences: specific advice for how to frame the application given the level relationship. If aligned, say 'Levels are aligned — no repositioning needed.'>"
}}

IMPORTANT: NEVER invent experience or metrics. Base analysis strictly on the provided profile and JD."""


async def block_c_level_strategy(
    job: Job, profile: dict, llm, archetype: dict
) -> dict:
    """Detect seniority mismatch and generate positioning strategy."""
    prompt = _BLOCK_C_PROMPT.format(
        profile_summary=_profile_summary(profile),
        jd=_truncate_jd(job),
    )
    try:
        return await _llm_json(llm, prompt)
    except Exception as e:
        logger.warning(f"Block C failed for {job.url}: {e}")
        return {
            "jd_level": "unknown",
            "candidate_level": "unknown",
            "strategy": "aligned",
            "downlevel_plan": "Unable to determine level strategy.",
        }


# ---------------------------------------------------------------------------
# Block D: Compensation Intelligence
# ---------------------------------------------------------------------------

_BLOCK_D_PROMPT = """You are a compensation research analyst. Provide salary intelligence for this role.

## Job Details
- Title: {title}
- Company: {company}
- Location: {location}
- Seniority: {seniority}
- Salary info from JD: {salary_raw}

## Job Description
{jd}

Research this role and provide compensation estimates. Use your knowledge of market rates for similar roles at similar companies in the same location.

Return JSON only:
{{
  "salary_range": {{
    "low": <number or null>,
    "mid": <number or null>,
    "high": <number or null>,
    "currency": "<USD/EUR/JPY/GBP or null>"
  }},
  "company_comp_reputation": "<known for high/average/below-average comp, or 'unknown'>",
  "demand_trend": "<high demand/moderate demand/low demand/unknown>",
  "sources": ["<list of reasoning sources, e.g. 'Glassdoor estimates for similar roles', 'known market rates for this location'>"],
  "data_available": <true if you have reasonable confidence in the estimates, false if you are guessing>
}}

CRITICAL: If you do not have reliable data for this company or role, set salary values to null and data_available to false. NEVER invent specific numbers without basis. It is far better to say 'unknown' than to fabricate data."""


async def block_d_comp_intelligence(
    job: Job, profile: dict, llm, archetype: dict
) -> dict:
    """Estimate compensation and market positioning."""
    prompt = _BLOCK_D_PROMPT.format(
        title=job.title,
        company=job.company,
        location=job.location or "Unknown",
        seniority=job.seniority or "unknown",
        salary_raw=job.salary_raw or "Not mentioned in JD",
        jd=_truncate_jd(job),
    )
    try:
        return await _llm_json(llm, prompt)
    except Exception as e:
        logger.warning(f"Block D failed for {job.url}: {e}")
        return {
            "salary_range": {
                "low": None, "mid": None, "high": None, "currency": None,
            },
            "company_comp_reputation": "unknown",
            "demand_trend": "unknown",
            "sources": [],
            "data_available": False,
        }


# ---------------------------------------------------------------------------
# Block E: Personalization Recommendations
# ---------------------------------------------------------------------------

_BLOCK_E_PROMPT = """You are a resume and LinkedIn optimization expert. Suggest specific changes to tailor the candidate's materials for this role.

## Candidate Profile
{profile_summary}

## Archetype Context
{archetype_context}

## Job Description
{jd}

Suggest the top 5 most impactful resume changes and top 5 LinkedIn profile changes. Each change should be specific — reference a real section/bullet from the profile and propose a concrete revision.

Return JSON only:
{{
  "resume_changes": [
    {{"section": "<e.g. experience bullet 2, skills section>", "current": "<what it says now, or 'missing'>", "proposed": "<what it should say>", "why": "<1 sentence reason>"}}
  ],
  "linkedin_changes": [
    {{"section": "<e.g. headline, about, experience>", "current": "<what it likely says now>", "proposed": "<what it should say>", "why": "<1 sentence reason>"}}
  ]
}}

IMPORTANT:
- NEVER invent experience, metrics, or accomplishments the candidate does not have.
- Only reframe, reorder, or emphasize existing experience.
- Changes should be targeted at this specific role and archetype."""


async def block_e_personalization(
    job: Job, profile: dict, llm, archetype: dict
) -> dict:
    """Generate resume and LinkedIn personalization recommendations."""
    prompt = _BLOCK_E_PROMPT.format(
        profile_summary=_profile_summary(profile),
        archetype_context=_archetype_context(archetype),
        jd=_truncate_jd(job),
    )
    try:
        return await _llm_json(llm, prompt, max_tokens=8192)
    except Exception as e:
        logger.warning(f"Block E failed for {job.url}: {e}")
        return {"resume_changes": [], "linkedin_changes": []}


# ---------------------------------------------------------------------------
# Block F: Interview Preparation
# ---------------------------------------------------------------------------

_BLOCK_F_PROMPT = """You are an interview preparation coach. Create STAR+R stories and preparation materials for this role.

## Candidate Profile
{profile_summary}

## Archetype Context
{archetype_context}

## Job Description
{jd}

Create:
1. 6-10 STAR+R stories that map to key JD requirements. Each story should use the candidate's REAL experience from the profile. Frame them through the lens of the archetype.
2. A case study / portfolio demo plan using the candidate's actual projects.
3. Red-flag questions the interviewer might ask (gaps, concerns) with prepared responses.

Return JSON only:
{{
  "stories": [
    {{
      "requirement": "<JD requirement this addresses>",
      "title": "<short story title>",
      "situation": "<STAR situation — specific context from candidate's real experience>",
      "task": "<STAR task — what needed to be done>",
      "action": "<STAR action — what the candidate specifically did>",
      "result": "<STAR result — measurable outcome>",
      "reflection": "<STAR+R reflection — what was learned, how it applies to this role>"
    }}
  ],
  "case_study": {{
    "project": "<real project from candidate's profile to demo>",
    "demo_plan": "<how to present this project in an interview context>"
  }},
  "red_flag_questions": [
    {{
      "question": "<potential concern the interviewer might raise>",
      "response": "<prepared response that addresses the concern honestly>"
    }}
  ]
}}

CRITICAL:
- NEVER invent experience, projects, or metrics the candidate does not have.
- Every story MUST reference real experience from the profile.
- If the candidate does not have enough experience for 6 stories, create fewer — quality over quantity.
- Results should use real metrics from the profile where available, or honest qualitative outcomes otherwise."""


async def block_f_interview_prep(
    job: Job, profile: dict, llm, archetype: dict
) -> dict:
    """Generate STAR+R stories and interview preparation materials."""
    prompt = _BLOCK_F_PROMPT.format(
        profile_summary=_profile_summary(profile),
        archetype_context=_archetype_context(archetype),
        jd=_truncate_jd(job),
    )
    try:
        return await _llm_json(llm, prompt, max_tokens=8192)
    except Exception as e:
        logger.warning(f"Block F failed for {job.url}: {e}")
        return {"stories": [], "case_study": {}, "red_flag_questions": []}


# ---------------------------------------------------------------------------
# Block G: Draft Application Answers
# ---------------------------------------------------------------------------

_BLOCK_G_PROMPT = """You are an application-answer writer. Draft answers to common application questions for this role.

## Candidate Profile
{profile_summary}

## Archetype Context
{archetype_context}

## Job Details
- Title: {title}
- Company: {company}

## Job Description
{jd}

Write answers for these question types:
1. why_role — "Why are you interested in this role?"
2. why_company — "Why do you want to work at this company?"
3. relevant_experience — "Describe your most relevant experience."
4. good_fit — "Why are you a good fit?"
5. how_heard — "How did you hear about this role?"

## Tone Rules — FOLLOW STRICTLY:
- Confident without arrogance
- Selective without snobbery
- Specific + concrete: reference something REAL from the JD and REAL from the candidate's resume
- Direct, no fluff: 2-4 sentences per answer
- NO "I'm passionate..." or "I would love..." or "I'm excited..." — these are banned phrases
- Proof is the hook, not assertion — lead with what you built/did, not what you feel

Return JSON only:
{{
  "answers": [
    {{"question_type": "why_role", "question": "Why are you interested in this role?", "answer": "<2-4 sentences>"}},
    {{"question_type": "why_company", "question": "Why do you want to work at this company?", "answer": "<2-4 sentences>"}},
    {{"question_type": "relevant_experience", "question": "Describe your most relevant experience.", "answer": "<2-4 sentences>"}},
    {{"question_type": "good_fit", "question": "Why are you a good fit?", "answer": "<2-4 sentences>"}},
    {{"question_type": "how_heard", "question": "How did you hear about this role?", "answer": "<1-2 sentences>"}}
  ]
}}

CRITICAL:
- NEVER invent experience or accomplishments.
- Every answer must reference something specific from the JD AND something specific from the candidate's real profile.
- Keep each answer to 2-4 sentences maximum. Brevity is power."""


async def block_g_draft_answers(
    job: Job, profile: dict, llm, archetype: dict
) -> dict:
    """Draft application answers with 'I'm Choosing You' tone."""
    prompt = _BLOCK_G_PROMPT.format(
        profile_summary=_profile_summary(profile),
        archetype_context=_archetype_context(archetype),
        title=job.title,
        company=job.company,
        jd=_truncate_jd(job),
    )
    try:
        return await _llm_json(llm, prompt)
    except Exception as e:
        logger.warning(f"Block G failed for {job.url}: {e}")
        return {"answers": []}
