"""Pipeline runner — chains all stages with best-effort error handling."""
from __future__ import annotations

import asyncio
import logging
import os
from dataclasses import dataclass
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class StageResult:
    """Result of a single pipeline stage."""

    name: str
    success: bool = True
    detail: str = ""
    error: str | None = None


class PipelineSummary:
    """Collects results from all pipeline stages."""

    def __init__(self) -> None:
        self.stages: list[StageResult] = []

    def add(self, result: StageResult) -> None:
        self.stages.append(result)

    @property
    def all_succeeded(self) -> bool:
        return all(s.success for s in self.stages)


def _run_discover(config_dir: Path, data_dir: Path) -> StageResult:
    """Run discover stage."""
    from job_hunter.config import load_config
    from job_hunter.database import JobDB
    from job_hunter.discover.jobspy_scraper import run_jobspy_search, parse_jobspy_results
    from job_hunter.discover.dedup import dedup_jobs

    config = load_config(config_dir, data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    db = JobDB(data_dir / "jobs.db")
    existing_urls = db.get_all_urls()
    all_jobs = []

    for search in config.searches:
        try:
            df = run_jobspy_search(
                query=search["query"],
                location=search.get("location", ""),
                boards=search.get("boards", ["indeed"]),
                max_results=search.get("max_results", 100),
                distance_km=search.get("distance_km"),
                remote_only=search.get("remote_only", False),
            )
            jobs = parse_jobspy_results(df)
            all_jobs.extend(jobs)
        except Exception as e:
            logger.warning(f"Search failed for '{search.get('query', '')}': {e}")

    new_jobs = dedup_jobs(all_jobs, existing_urls)
    for job in new_jobs:
        db.upsert_job(job)
    db.close()

    return StageResult(name="Discover", detail=f"{len(new_jobs)} new jobs")


def _run_enrich(config_dir: Path, data_dir: Path) -> StageResult:
    """Run enrich stage."""
    from job_hunter.config import load_config
    from job_hunter.database import JobDB
    from job_hunter.enrich.runner import run_enrichment

    config = load_config(config_dir, data_dir)
    db = JobDB(data_dir / "jobs.db")

    llm = None
    if config.llm_api_key or config.llm_provider == "ollama":
        try:
            from job_hunter.llm.base import get_provider
            llm = get_provider(config.llm_provider, api_key=config.llm_api_key, model=config.llm_model)
        except Exception:
            pass

    processed, total = asyncio.run(run_enrichment(db, llm=llm))
    db.close()

    return StageResult(name="Enrich", detail=f"{processed}/{total} enriched")


def _run_score(config_dir: Path, data_dir: Path) -> StageResult:
    """Run score stage."""
    from job_hunter.config import load_config
    from job_hunter.database import JobDB
    from job_hunter.llm.base import get_provider
    from job_hunter.score.scorer import run_scoring

    config = load_config(config_dir, data_dir)
    db = JobDB(data_dir / "jobs.db")

    llm = get_provider(config.llm_provider, api_key=config.llm_api_key, model=config.llm_model)
    profile = config.profile
    target_roles = profile.get("target_roles", [profile.get("target_role", "")])

    scored, filtered, total = asyncio.run(run_scoring(db, profile, llm, target_roles))
    db.close()

    return StageResult(name="Score", detail=f"{scored} scored, {filtered} filtered")


def _run_tailor(config_dir: Path, data_dir: Path) -> StageResult:
    """Run tailor stage."""
    from job_hunter.config import load_config
    from job_hunter.database import JobDB
    from job_hunter.llm.base import get_provider
    from job_hunter.tailor.parser import parse_latex_resume
    from job_hunter.tailor.tailor import tailor_resume
    from job_hunter.tailor.renderer import render_latex_to_pdf
    from job_hunter.tailor.cover_letter import generate_cover_letter
    from job_hunter.tailor.cover_letter_renderer import render_cover_letter

    config = load_config(config_dir, data_dir)
    db = JobDB(data_dir / "jobs.db")
    profile = config.profile

    llm = get_provider(config.llm_provider, api_key=config.llm_api_key, model=config.llm_model)

    resume_path = config_dir / "resume.tex"
    if not resume_path.exists():
        db.close()
        return StageResult(name="Tailor", detail="no resume.tex found")

    resume = parse_latex_resume(resume_path.read_text())
    output_dir = data_dir / "output"
    output_dir.mkdir(exist_ok=True)

    jobs = db.get_untailored_jobs(min_score=int(config.score_threshold or 3))
    success = 0

    for job in jobs:
        tailored = asyncio.run(tailor_resume(job, resume, profile, llm))
        if tailored:
            pdf = render_latex_to_pdf(resume.preamble, tailored, output_dir, job.url)
            if pdf:
                job.resume_path = str(pdf)

            cl_text = asyncio.run(generate_cover_letter(job, profile, llm))
            if cl_text:
                _, cl_txt = render_cover_letter(cl_text, profile, job.title, job.company, output_dir, job.url)
                job.cover_letter_path = str(cl_txt) if cl_txt else None

            job.status = "tailored"
            db.upsert_job(job)
            success += 1

    db.close()
    return StageResult(name="Tailor", detail=f"{success}/{len(jobs)} tailored")


def _run_sync(data_dir: Path) -> StageResult:
    """Run sync push stage."""
    from job_hunter.database import JobDB
    from job_hunter.notion.client import NotionJobDB
    from job_hunter.notion.sync import push_jobs_to_notion

    token = os.environ.get("NOTION_TOKEN")
    db_id = os.environ.get("NOTION_DATABASE_ID")
    if not token or not db_id:
        return StageResult(name="Sync", detail="NOTION_TOKEN/DATABASE_ID not set")

    db = JobDB(data_dir / "jobs.db")
    notion = NotionJobDB(token=token, database_id=db_id)
    created, updated = push_jobs_to_notion(db, notion)
    db.close()

    return StageResult(name="Sync", detail=f"{created} created, {updated} updated")


def _run_apply(config_dir: Path, data_dir: Path, dry_run: bool = False) -> StageResult:
    """Run apply stage."""
    import json
    import time
    from job_hunter.config import load_config
    from job_hunter.database import JobDB
    from job_hunter.apply.applicant import Applicant

    config = load_config(config_dir, data_dir)
    profile_path = config_dir / "profile.json"
    if not profile_path.exists():
        return StageResult(name="Apply", detail="no profile.json")

    profile = json.loads(profile_path.read_text())

    llm = None
    if config.llm_api_key or config.llm_provider == "ollama":
        try:
            from job_hunter.llm.base import get_provider
            llm = get_provider(config.llm_provider, api_key=config.llm_api_key, model=config.llm_model)
        except Exception:
            pass

    applicant = Applicant(
        profile=profile,
        session_dir=data_dir / "sessions",
        llm=llm,
        log_path=data_dir / "output" / "apply_log.json",
        dry_run=dry_run,
    )

    db = JobDB(data_dir / "jobs.db")
    jobs = []
    for s in ("tailored", "synced"):
        jobs.extend(db.get_jobs_by_status(s))
    jobs = [j for j in jobs if applicant.is_eligible(j)]

    applied = 0
    for i, job in enumerate(jobs):
        result = asyncio.run(applicant.apply_to_job(job))
        applicant._log_result(result)
        if result.status == "applied":
            job.status = "applied"
            db.upsert_job(job)
            applied += 1
        if i < len(jobs) - 1:
            time.sleep(2)

    db.close()
    return StageResult(name="Apply", detail=f"{applied}/{len(jobs)} applied")


def run_pipeline(
    config_dir: Path,
    skip_discover: bool = False,
    run_apply: bool = False,
    dry_run: bool = False,
    data_dir: Path | None = None,
) -> PipelineSummary:
    """Run the full job-hunting pipeline with best-effort error handling."""
    from job_hunter.config import get_data_dir

    if data_dir is None:
        data_dir = get_data_dir()

    summary = PipelineSummary()

    stages: list[tuple[str, object]] = []
    if not skip_discover:
        stages.append(("Discover", lambda: _run_discover(config_dir, data_dir)))
    stages.append(("Enrich", lambda: _run_enrich(config_dir, data_dir)))
    stages.append(("Score", lambda: _run_score(config_dir, data_dir)))
    stages.append(("Tailor", lambda: _run_tailor(config_dir, data_dir)))
    stages.append(("Sync", lambda: _run_sync(data_dir)))
    if run_apply:
        stages.append(("Apply", lambda: _run_apply(config_dir, data_dir, dry_run)))

    for name, stage_fn in stages:
        try:
            result = stage_fn()
            summary.add(result)
            logger.info("Stage %s completed: %s", name, result.detail)
        except Exception as e:
            logger.error("Stage %s failed: %s", name, e)
            summary.add(StageResult(name=name, success=False, error=str(e)))

    return summary
