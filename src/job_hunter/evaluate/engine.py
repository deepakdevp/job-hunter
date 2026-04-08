from __future__ import annotations

import json
import logging
import re
from datetime import datetime
from pathlib import Path

from job_hunter.database import Job, JobDB
from job_hunter.evaluate.archetype import ARCHETYPES, detect_archetype
from job_hunter.evaluate.blocks import (
    block_a_role_summary,
    block_b_cv_match,
    block_c_level_strategy,
    block_d_comp_intelligence,
    block_e_personalization,
    block_f_interview_prep,
    block_g_draft_answers,
)

logger = logging.getLogger(__name__)


def _slugify(text: str) -> str:
    """Convert text to a filesystem-safe slug."""
    text = text.lower().strip()
    text = re.sub(r"[^\w\s-]", "", text)
    text = re.sub(r"[\s_]+", "-", text)
    text = re.sub(r"-+", "-", text)
    return text[:60].strip("-")


async def evaluate_job(
    job: Job,
    profile: dict,
    llm,
    score_threshold: int = 5,
) -> dict | None:
    """Run the full evaluation engine on a single job.

    Returns the complete evaluation dict, or None if the job has no description.
    """
    if not job.description:
        logger.warning(f"Skipping {job.url}: no job description available")
        return None

    evaluation: dict = {
        "version": "1.0",
        "evaluated_at": datetime.now().isoformat(),
        "job_url": job.url,
        "job_title": job.title,
        "company": job.company,
    }

    # Step 1: Detect archetype
    archetype = await detect_archetype(job.description, job.title, llm)
    evaluation["archetype"] = archetype

    # Step 2: Run blocks A-F (always)
    block_results = {}

    # Block A
    try:
        block_results["role_summary"] = await block_a_role_summary(
            job, profile, llm, archetype
        )
    except Exception as e:
        logger.error(f"Block A error for {job.url}: {e}")
        block_results["role_summary"] = {"error": str(e)}

    # Block B
    try:
        block_results["cv_match"] = await block_b_cv_match(
            job, profile, llm, archetype
        )
    except Exception as e:
        logger.error(f"Block B error for {job.url}: {e}")
        block_results["cv_match"] = {"error": str(e)}

    # Block C
    try:
        block_results["level_strategy"] = await block_c_level_strategy(
            job, profile, llm, archetype
        )
    except Exception as e:
        logger.error(f"Block C error for {job.url}: {e}")
        block_results["level_strategy"] = {"error": str(e)}

    # Block D
    try:
        block_results["comp_intelligence"] = await block_d_comp_intelligence(
            job, profile, llm, archetype
        )
    except Exception as e:
        logger.error(f"Block D error for {job.url}: {e}")
        block_results["comp_intelligence"] = {"error": str(e)}

    # Block E
    try:
        block_results["personalization"] = await block_e_personalization(
            job, profile, llm, archetype
        )
    except Exception as e:
        logger.error(f"Block E error for {job.url}: {e}")
        block_results["personalization"] = {"error": str(e)}

    # Block F
    try:
        block_results["interview_prep"] = await block_f_interview_prep(
            job, profile, llm, archetype
        )
    except Exception as e:
        logger.error(f"Block F error for {job.url}: {e}")
        block_results["interview_prep"] = {"error": str(e)}

    # Step 3: Block G only if score >= threshold
    job_score = job.score or 0
    if job_score >= score_threshold:
        try:
            block_results["draft_answers"] = await block_g_draft_answers(
                job, profile, llm, archetype
            )
        except Exception as e:
            logger.error(f"Block G error for {job.url}: {e}")
            block_results["draft_answers"] = {"error": str(e)}
    else:
        block_results["draft_answers"] = {
            "skipped": True,
            "reason": f"Job score ({job_score}) below threshold ({score_threshold})",
        }

    evaluation["blocks"] = block_results
    return evaluation


def format_evaluation_markdown(job: Job, evaluation: dict) -> str:
    """Format an evaluation dict as a readable markdown report."""
    lines: list[str] = []

    lines.append(f"# Evaluation: {job.title} at {job.company}")
    lines.append("")
    lines.append(f"- **URL:** {job.url}")
    lines.append(f"- **Score:** {job.score or 'N/A'}")
    lines.append(f"- **Evaluated:** {evaluation.get('evaluated_at', 'Unknown')}")
    lines.append("")

    # Archetype
    arch = evaluation.get("archetype", {})
    primary_key = arch.get("primary", "unknown")
    primary_info = ARCHETYPES.get(primary_key, {})
    lines.append("## Archetype")
    lines.append(
        f"- **Primary:** {primary_info.get('name', primary_key)} "
        f"(confidence: {arch.get('confidence', 0):.0%})"
    )
    if arch.get("secondary"):
        sec_info = ARCHETYPES.get(arch["secondary"], {})
        lines.append(f"- **Secondary:** {sec_info.get('name', arch['secondary'])}")
    lines.append("")

    blocks = evaluation.get("blocks", {})

    # Block A: Role Summary
    role = blocks.get("role_summary", {})
    if "error" not in role:
        lines.append("## Role Summary")
        lines.append(f"- **Domain:** {role.get('domain', 'unknown')}")
        lines.append(f"- **Function:** {role.get('function', 'unknown')}")
        lines.append(f"- **Seniority:** {role.get('seniority', 'unknown')}")
        lines.append(f"- **Remote:** {role.get('remote', 'unknown')}")
        lines.append(f"- **Team Size:** {role.get('team_size', 'unknown')}")
        lines.append(f"- **TL;DR:** {role.get('tldr', 'N/A')}")
        lines.append("")

    # Block B: CV Match
    cv = blocks.get("cv_match", {})
    if "error" not in cv:
        lines.append("## CV Match Analysis")
        match_pct = cv.get("match_percentage", 0)
        lines.append(f"**Overall Match: {match_pct:.0f}%**")
        lines.append("")

        matches = cv.get("matches", [])
        if matches:
            lines.append("### Matches")
            for m in matches:
                strength = m.get("strength", "unknown")
                icon = {"strong": "+", "moderate": "~", "weak": "-"}.get(
                    strength, "?"
                )
                lines.append(
                    f"- [{icon}] **{m.get('requirement', '')}** "
                    f"-> {m.get('cv_line', '')} ({strength})"
                )
            lines.append("")

        gaps = cv.get("gaps", [])
        if gaps:
            lines.append("### Gaps")
            for g in gaps:
                blocker = "BLOCKER" if g.get("is_blocker") else "nice-to-have"
                lines.append(f"- [{blocker}] **{g.get('requirement', '')}**")
                if g.get("adjacent_experience"):
                    lines.append(
                        f"  - Adjacent: {g['adjacent_experience']}"
                    )
                if g.get("mitigation"):
                    lines.append(f"  - Mitigation: {g['mitigation']}")
            lines.append("")

    # Block C: Level Strategy
    level = blocks.get("level_strategy", {})
    if "error" not in level:
        lines.append("## Level Strategy")
        lines.append(f"- **JD Level:** {level.get('jd_level', 'unknown')}")
        lines.append(
            f"- **Candidate Level:** {level.get('candidate_level', 'unknown')}"
        )
        lines.append(f"- **Strategy:** {level.get('strategy', 'unknown')}")
        lines.append(f"- **Plan:** {level.get('downlevel_plan', 'N/A')}")
        lines.append("")

    # Block D: Compensation Intelligence
    comp = blocks.get("comp_intelligence", {})
    if "error" not in comp:
        lines.append("## Compensation Intelligence")
        salary = comp.get("salary_range", {})
        data_avail = comp.get("data_available", False)
        if data_avail and salary.get("mid"):
            currency = salary.get("currency", "")
            lines.append(
                f"- **Range:** {currency} {salary.get('low', '?')} - "
                f"{salary.get('high', '?')} (mid: {salary.get('mid', '?')})"
            )
        else:
            lines.append("- **Range:** Insufficient data for reliable estimate")
        lines.append(
            f"- **Company Reputation:** "
            f"{comp.get('company_comp_reputation', 'unknown')}"
        )
        lines.append(
            f"- **Demand Trend:** {comp.get('demand_trend', 'unknown')}"
        )
        sources = comp.get("sources", [])
        if sources:
            lines.append(f"- **Sources:** {', '.join(sources)}")
        lines.append("")

    # Block E: Personalization
    pers = blocks.get("personalization", {})
    if "error" not in pers:
        lines.append("## Personalization Recommendations")

        resume_changes = pers.get("resume_changes", [])
        if resume_changes:
            lines.append("### Resume Changes")
            for i, ch in enumerate(resume_changes, 1):
                lines.append(f"**{i}. {ch.get('section', 'Unknown section')}**")
                lines.append(f"- Current: {ch.get('current', 'N/A')}")
                lines.append(f"- Proposed: {ch.get('proposed', 'N/A')}")
                lines.append(f"- Why: {ch.get('why', 'N/A')}")
                lines.append("")

        linkedin_changes = pers.get("linkedin_changes", [])
        if linkedin_changes:
            lines.append("### LinkedIn Changes")
            for i, ch in enumerate(linkedin_changes, 1):
                lines.append(f"**{i}. {ch.get('section', 'Unknown section')}**")
                lines.append(f"- Current: {ch.get('current', 'N/A')}")
                lines.append(f"- Proposed: {ch.get('proposed', 'N/A')}")
                lines.append(f"- Why: {ch.get('why', 'N/A')}")
                lines.append("")

    # Block F: Interview Prep
    prep = blocks.get("interview_prep", {})
    if "error" not in prep:
        lines.append("## Interview Preparation")

        stories = prep.get("stories", [])
        if stories:
            lines.append("### STAR+R Stories")
            for i, s in enumerate(stories, 1):
                lines.append(f"#### Story {i}: {s.get('title', 'Untitled')}")
                lines.append(
                    f"*Addresses: {s.get('requirement', 'general')}*"
                )
                lines.append(f"- **Situation:** {s.get('situation', 'N/A')}")
                lines.append(f"- **Task:** {s.get('task', 'N/A')}")
                lines.append(f"- **Action:** {s.get('action', 'N/A')}")
                lines.append(f"- **Result:** {s.get('result', 'N/A')}")
                lines.append(
                    f"- **Reflection:** {s.get('reflection', 'N/A')}"
                )
                lines.append("")

        case_study = prep.get("case_study", {})
        if case_study.get("project"):
            lines.append("### Case Study / Demo")
            lines.append(f"- **Project:** {case_study['project']}")
            lines.append(
                f"- **Demo Plan:** {case_study.get('demo_plan', 'N/A')}"
            )
            lines.append("")

        red_flags = prep.get("red_flag_questions", [])
        if red_flags:
            lines.append("### Red-Flag Questions")
            for rf in red_flags:
                lines.append(f"**Q:** {rf.get('question', 'N/A')}")
                lines.append(f"**A:** {rf.get('response', 'N/A')}")
                lines.append("")

    # Block G: Draft Answers
    answers = blocks.get("draft_answers", {})
    if answers.get("skipped"):
        lines.append("## Draft Application Answers")
        lines.append(f"*Skipped: {answers.get('reason', 'below threshold')}*")
        lines.append("")
    elif "error" not in answers:
        answer_list = answers.get("answers", [])
        if answer_list:
            lines.append("## Draft Application Answers")
            for a in answer_list:
                lines.append(f"### {a.get('question', 'Unknown question')}")
                lines.append(a.get("answer", "N/A"))
                lines.append("")

    lines.append("---")
    lines.append("*Generated by job-hunter evaluation engine v1.0*")

    return "\n".join(lines)


async def run_evaluation(
    db: JobDB,
    profile: dict,
    llm,
    min_score: int = 5,
    job_url: str | None = None,
    on_progress=None,
) -> tuple[int, int]:
    """Run evaluation on jobs.

    If job_url is specified, evaluate just that job.
    Otherwise, evaluate all unevaluated jobs above min_score.

    Returns (evaluated_count, total_count).
    """
    if job_url:
        job = db.get_job(job_url)
        if job is None:
            logger.error(f"Job not found: {job_url}")
            return 0, 0
        jobs = [job]
    else:
        jobs = db.get_unevaluated_jobs(min_score=min_score)

    total = len(jobs)
    if total == 0:
        return 0, 0

    evaluated = 0
    output_dir = Path("output")
    output_dir.mkdir(exist_ok=True)

    for i, job in enumerate(jobs):
        try:
            result = await evaluate_job(
                job, profile, llm, score_threshold=min_score
            )
            if result is None:
                logger.warning(
                    f"Skipped {job.url}: evaluation returned None"
                )
                if on_progress:
                    on_progress(i + 1, total)
                continue

            # Store JSON in database
            job.evaluation = json.dumps(result)
            db.upsert_job(job)

            # Save markdown report
            company_slug = _slugify(job.company)
            role_slug = _slugify(job.title)
            md_filename = f"{company_slug}-{role_slug}-evaluation.md"
            md_path = output_dir / md_filename

            markdown = format_evaluation_markdown(job, result)
            md_path.write_text(markdown, encoding="utf-8")
            logger.info(f"Saved evaluation: {md_path}")

            evaluated += 1
        except Exception as e:
            logger.error(f"Evaluation failed for {job.url}: {e}")

        if on_progress:
            on_progress(i + 1, total)

    return evaluated, total
