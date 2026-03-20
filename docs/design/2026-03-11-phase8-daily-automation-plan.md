# Phase 8: Daily Automation — Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Single `hunt run` command that chains all pipeline stages with best-effort error handling and a summary table.

**Architecture:** A `run_pipeline()` function calls each stage sequentially, collecting results. Each stage is wrapped in try/except for best-effort continuation. A Rich summary table is printed at the end. The `hunt run` CLI command wires it all together.

**Tech Stack:** Click CLI, Rich tables, asyncio, existing stage modules

---

### Task 1: Pipeline Runner + Summary

**Files:**
- Create: `src/job_hunter/pipeline.py`
- Test: `tests/test_pipeline.py`

**Step 1: Write the failing test**

```python
"""Tests for the pipeline runner."""
from __future__ import annotations

from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from job_hunter.pipeline import run_pipeline, StageResult, PipelineSummary


def test_stage_result_defaults():
    r = StageResult(name="discover")
    assert r.success is True
    assert r.detail == ""
    assert r.error is None


def test_stage_result_failed():
    r = StageResult(name="enrich", success=False, error="timeout")
    assert r.success is False
    assert r.error == "timeout"


def test_pipeline_summary_empty():
    s = PipelineSummary()
    assert len(s.stages) == 0


def test_pipeline_summary_add_stage():
    s = PipelineSummary()
    s.add(StageResult(name="discover", detail="47 new jobs"))
    assert len(s.stages) == 1
    assert s.stages[0].detail == "47 new jobs"


def test_pipeline_summary_all_succeeded():
    s = PipelineSummary()
    s.add(StageResult(name="discover", detail="10 jobs"))
    s.add(StageResult(name="enrich", detail="8/10 enriched"))
    assert s.all_succeeded is True


def test_pipeline_summary_has_failure():
    s = PipelineSummary()
    s.add(StageResult(name="discover", detail="10 jobs"))
    s.add(StageResult(name="enrich", success=False, error="failed"))
    assert s.all_succeeded is False


@patch("job_hunter.pipeline._run_discover")
@patch("job_hunter.pipeline._run_enrich")
@patch("job_hunter.pipeline._run_score")
@patch("job_hunter.pipeline._run_tailor")
@patch("job_hunter.pipeline._run_sync")
def test_run_pipeline_calls_all_stages(mock_sync, mock_tailor, mock_score, mock_enrich, mock_discover):
    mock_discover.return_value = StageResult(name="Discover", detail="5 jobs")
    mock_enrich.return_value = StageResult(name="Enrich", detail="5/5")
    mock_score.return_value = StageResult(name="Score", detail="3 scored")
    mock_tailor.return_value = StageResult(name="Tailor", detail="3/3")
    mock_sync.return_value = StageResult(name="Sync", detail="3 created")

    config_dir = MagicMock()
    summary = run_pipeline(config_dir, skip_discover=False, run_apply=False)

    assert len(summary.stages) == 5
    mock_discover.assert_called_once()
    mock_enrich.assert_called_once()
    mock_score.assert_called_once()
    mock_tailor.assert_called_once()
    mock_sync.assert_called_once()


@patch("job_hunter.pipeline._run_discover")
@patch("job_hunter.pipeline._run_enrich")
@patch("job_hunter.pipeline._run_score")
@patch("job_hunter.pipeline._run_tailor")
@patch("job_hunter.pipeline._run_sync")
def test_run_pipeline_skip_discover(mock_sync, mock_tailor, mock_score, mock_enrich, mock_discover):
    mock_enrich.return_value = StageResult(name="Enrich", detail="ok")
    mock_score.return_value = StageResult(name="Score", detail="ok")
    mock_tailor.return_value = StageResult(name="Tailor", detail="ok")
    mock_sync.return_value = StageResult(name="Sync", detail="ok")

    config_dir = MagicMock()
    summary = run_pipeline(config_dir, skip_discover=True, run_apply=False)

    mock_discover.assert_not_called()
    assert len(summary.stages) == 4


@patch("job_hunter.pipeline._run_discover")
@patch("job_hunter.pipeline._run_enrich")
@patch("job_hunter.pipeline._run_score")
@patch("job_hunter.pipeline._run_tailor")
@patch("job_hunter.pipeline._run_sync")
def test_run_pipeline_stage_failure_continues(mock_sync, mock_tailor, mock_score, mock_enrich, mock_discover):
    mock_discover.side_effect = Exception("network error")
    mock_enrich.return_value = StageResult(name="Enrich", detail="3/3")
    mock_score.return_value = StageResult(name="Score", detail="ok")
    mock_tailor.return_value = StageResult(name="Tailor", detail="ok")
    mock_sync.return_value = StageResult(name="Sync", detail="ok")

    config_dir = MagicMock()
    summary = run_pipeline(config_dir, skip_discover=False, run_apply=False)

    # Discover failed but rest continued
    assert len(summary.stages) == 5
    assert summary.stages[0].success is False
    assert summary.stages[1].success is True
```

**Step 2: Run test to verify it fails**

Run: `pytest tests/test_pipeline.py -v`
Expected: FAIL — ModuleNotFoundError

**Step 3: Write minimal implementation**

```python
"""Pipeline runner — chains all stages with best-effort error handling."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
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

    def __init__(self):
        self.stages: list[StageResult] = []

    def add(self, result: StageResult) -> None:
        self.stages.append(result)

    @property
    def all_succeeded(self) -> bool:
        return all(s.success for s in self.stages)


def _run_discover(config_dir: Path) -> StageResult:
    """Run discover stage."""
    from job_hunter.config import load_config
    from job_hunter.database import JobDB
    from job_hunter.discover.jobspy_scraper import run_jobspy_search, parse_jobspy_results
    from job_hunter.discover.dedup import dedup_jobs

    config = load_config(config_dir)
    db = JobDB(config_dir / "jobs.db")
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
            logger.warning(f"Search failed: {e}")

    new_jobs = dedup_jobs(all_jobs, existing_urls)
    for job in new_jobs:
        db.upsert_job(job)
    db.close()

    return StageResult(name="Discover", detail=f"{len(new_jobs)} new jobs")


def _run_enrich(config_dir: Path) -> StageResult:
    """Run enrich stage."""
    from job_hunter.config import load_config
    from job_hunter.database import JobDB
    from job_hunter.enrich.runner import run_enrichment
    from job_hunter.llm.base import get_provider

    config = load_config(config_dir)
    db = JobDB(config_dir / "jobs.db")

    llm = None
    try:
        llm = get_provider(config.llm_provider, api_key=config.gemini_api_key, model=config.llm_model)
    except Exception:
        pass

    processed, total = asyncio.run(run_enrichment(db, llm=llm))
    db.close()

    return StageResult(name="Enrich", detail=f"{processed}/{total} enriched")


def _run_score(config_dir: Path) -> StageResult:
    """Run score stage."""
    from job_hunter.config import load_config
    from job_hunter.database import JobDB
    from job_hunter.llm.base import get_provider
    from job_hunter.score.scorer import run_scoring

    config = load_config(config_dir)
    db = JobDB(config_dir / "jobs.db")

    llm = get_provider(config.llm_provider, api_key=config.gemini_api_key, model=config.llm_model)
    profile = config.profile
    target_roles = profile.get("target_roles", [profile.get("target_role", "")])

    scored, filtered, total = asyncio.run(run_scoring(db, profile, llm, target_roles))
    db.close()

    return StageResult(name="Score", detail=f"{scored} scored, {filtered} filtered")


def _run_tailor(config_dir: Path) -> StageResult:
    """Run tailor stage."""
    from job_hunter.config import load_config
    from job_hunter.database import JobDB
    from job_hunter.llm.base import get_provider
    from job_hunter.tailor.parser import parse_latex_resume
    from job_hunter.tailor.tailor import tailor_resume
    from job_hunter.tailor.renderer import render_latex_to_pdf
    from job_hunter.tailor.cover_letter import generate_cover_letter
    from job_hunter.tailor.cover_letter_renderer import render_cover_letter

    config = load_config(config_dir)
    db = JobDB(config_dir / "jobs.db")
    profile = config.profile

    llm = get_provider(config.llm_provider, api_key=config.gemini_api_key, model=config.llm_model)

    resume_path = config_dir / "resume.tex"
    if not resume_path.exists():
        db.close()
        return StageResult(name="Tailor", detail="no resume.tex found")

    resume = parse_latex_resume(resume_path.read_text())
    output_dir = config_dir / "output"
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


def _run_sync(config_dir: Path) -> StageResult:
    """Run sync push stage."""
    import os
    from job_hunter.database import JobDB
    from job_hunter.notion.client import NotionJobDB
    from job_hunter.notion.sync import push_jobs_to_notion

    token = os.environ.get("NOTION_TOKEN")
    db_id = os.environ.get("NOTION_DATABASE_ID")
    if not token or not db_id:
        return StageResult(name="Sync", detail="NOTION_TOKEN/DATABASE_ID not set")

    db = JobDB(config_dir / "jobs.db")
    notion = NotionJobDB(token=token, database_id=db_id)
    created, updated = push_jobs_to_notion(db, notion)
    db.close()

    return StageResult(name="Sync", detail=f"{created} created, {updated} updated")


def _run_apply(config_dir: Path, dry_run: bool = False) -> StageResult:
    """Run apply stage."""
    import json
    from job_hunter.config import load_config
    from job_hunter.database import JobDB
    from job_hunter.apply.applicant import Applicant

    config = load_config(config_dir)
    profile_path = config_dir / "profile.json"
    if not profile_path.exists():
        return StageResult(name="Apply", detail="no profile.json")

    profile = json.loads(profile_path.read_text())

    llm = None
    try:
        from job_hunter.llm.base import get_provider
        llm = get_provider(config.llm_provider, api_key=config.gemini_api_key, model=config.llm_model)
    except Exception:
        pass

    applicant = Applicant(
        profile=profile,
        session_dir=config_dir / "sessions",
        llm=llm,
        log_path=config_dir / "output" / "apply_log.json",
        dry_run=dry_run,
    )

    db = JobDB(config_dir / "jobs.db")
    jobs = []
    for s in ("tailored", "synced"):
        jobs.extend(db.get_jobs_by_status(s))
    jobs = [j for j in jobs if applicant.is_eligible(j)]

    applied = 0
    import time
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
) -> PipelineSummary:
    """Run the full job-hunting pipeline with best-effort error handling."""
    summary = PipelineSummary()

    stages: list[tuple[str, callable]] = []
    if not skip_discover:
        stages.append(("Discover", lambda: _run_discover(config_dir)))
    stages.append(("Enrich", lambda: _run_enrich(config_dir)))
    stages.append(("Score", lambda: _run_score(config_dir)))
    stages.append(("Tailor", lambda: _run_tailor(config_dir)))
    stages.append(("Sync", lambda: _run_sync(config_dir)))
    if run_apply:
        stages.append(("Apply", lambda: _run_apply(config_dir, dry_run)))

    for name, stage_fn in stages:
        try:
            result = stage_fn()
            summary.add(result)
        except Exception as e:
            logger.error(f"{name} stage failed: {e}")
            summary.add(StageResult(name=name, success=False, error=str(e)))

    return summary
```

**Step 4: Run test to verify it passes**

Run: `pytest tests/test_pipeline.py -v`
Expected: 9 PASS

**Step 5: Commit**

```bash
git add src/job_hunter/pipeline.py tests/test_pipeline.py
git commit -m "feat: pipeline runner with best-effort stage chaining"
```

---

### Task 2: `hunt run` CLI Command

**Files:**
- Modify: `src/job_hunter/cli.py` (add `run` command after `apply`)
- No new test file needed — verify with `hunt run --help`

**Step 1: Add CLI command**

Add after the `apply_cmd` function in `cli.py`:

```python
@cli.command("run")
@click.option("--apply", "run_apply", is_flag=True, help="Include auto-apply stage")
@click.option("--skip-discover", is_flag=True, help="Skip discover stage")
@click.option("--dry-run", is_flag=True, help="Dry-run apply (no submit)")
@click.pass_context
def run_cmd(ctx, run_apply, skip_discover, dry_run):
    """Run the full pipeline: discover → enrich → score → tailor → sync."""
    from job_hunter.pipeline import run_pipeline

    config_dir = ctx.obj["config_dir"]

    console.print("[bold]Starting pipeline run...[/]\n")

    summary = run_pipeline(
        config_dir,
        skip_discover=skip_discover,
        run_apply=run_apply,
        dry_run=dry_run,
    )

    # Print summary table
    table = Table(title="Run Summary")
    table.add_column("Stage", style="cyan")
    table.add_column("Result")

    for stage in summary.stages:
        if stage.success:
            table.add_row(stage.name, f"[green]{stage.detail}[/]")
        else:
            table.add_row(stage.name, f"[red]FAILED: {stage.error}[/]")

    if not run_apply:
        table.add_row("Apply", "[dim]skipped (use --apply)[/]")

    console.print()
    console.print(table)
```

**Step 2: Verify CLI help works**

Run: `hunt run --help`
Expected: Shows help with --apply, --skip-discover, --dry-run options

**Step 3: Commit**

```bash
git add src/job_hunter/cli.py
git commit -m "feat: hunt run CLI command with summary table"
```
