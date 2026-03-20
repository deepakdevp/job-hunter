#!/usr/bin/env python3
"""Japan-focused job hunting pipeline example.

This standalone script demonstrates how to compose a custom regional pipeline
using job-hunter's building blocks. It includes:
- JobSpy searches for Japan (Indeed, LinkedIn)
- Japan-specific board scrapers (TokyoDev, JapanDev, GaijinPot)
- Workday employer scraping for Japan offices
- Autoresearch stages (source validation, score audit, resume audit)
- Deep research with Karpathy-style iterative loops
- Notion sync

To use: copy this file, modify the searches/employers configs for your
target region, and run directly with `python examples/japan_pipeline.py`.
"""
from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import sys
import time
from datetime import datetime
from pathlib import Path

import yaml
from dotenv import load_dotenv
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

# ── Setup ───────────────────────────────────────────────────────────────────
PROJECT_ROOT = Path(__file__).resolve().parent
CONFIG_DIR = PROJECT_ROOT / "config"
JAPAN_DB_PATH = CONFIG_DIR / "japan_jobs.db"
JAPAN_OUTPUT_DIR = CONFIG_DIR / "japan_output"

console = Console()
logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
logger = logging.getLogger("japan_pipeline")

# Load env
env_path = CONFIG_DIR / ".env"
if env_path.exists():
    load_dotenv(env_path, override=True)


def _load_yaml(path: Path) -> dict:
    if path.exists():
        return yaml.safe_load(path.read_text()) or {}
    return {}


def _load_profile() -> dict:
    p = CONFIG_DIR / "profile.json"
    return json.loads(p.read_text())


def _get_llm():
    from job_hunter.llm.base import get_provider
    return get_provider(
        os.environ.get("LLM_PROVIDER", "gemini"),
        api_key=os.environ.get("GEMINI_API_KEY", ""),
        model=os.environ.get("LLM_MODEL", "gemini-2.5-flash"),
    )


# ── Stage 1: Discover ──────────────────────────────────────────────────────
def stage_discover():
    from job_hunter.database import JobDB
    from job_hunter.discover.jobspy_scraper import run_jobspy_search, parse_jobspy_results
    from job_hunter.discover.japan_scrapers import run_japan_scrapers
    from job_hunter.discover.workday_scraper import run_workday_scrapers
    from job_hunter.discover.dedup import dedup_jobs

    db = JobDB(JAPAN_DB_PATH)
    existing_urls = db.get_all_urls()
    all_jobs = []

    # 1. JobSpy boards (Japan-only searches)
    console.print("\n[bold cyan]━━━ Stage 1a: JobSpy boards (Japan) ━━━[/]")
    searches_data = _load_yaml(CONFIG_DIR / "japan_searches.yaml")
    searches = searches_data.get("searches", [])

    for search in searches:
        try:
            df = run_jobspy_search(
                query=search["query"],
                location=search.get("location", "Tokyo, Japan"),
                boards=search.get("boards", ["indeed", "linkedin"]),
                max_results=search.get("max_results", 50),
                distance_km=search.get("distance_km"),
                remote_only=search.get("remote_only", False),
            )
            jobs = parse_jobspy_results(df)
            all_jobs.extend(jobs)
            console.print(f"  {search['query']} → {len(jobs)} jobs")
        except Exception as e:
            console.print(f"  [red]{search['query']}: {e}[/]")

    # 2. Japan custom scrapers (TokyoDev, JapanDev, GaijinPot)
    console.print("\n[bold cyan]━━━ Stage 1b: Japan boards ━━━[/]")
    japan_queries = ["software engineer", "AI engineer", "full stack", "python", "react"]
    for q in japan_queries:
        try:
            japan_jobs = asyncio.run(run_japan_scrapers(query=q, max_results=50))
            all_jobs.extend(japan_jobs)
            console.print(f"  Japan scrapers ({q}) → {len(japan_jobs)} jobs")
        except Exception as e:
            console.print(f"  [red]Japan scrapers ({q}): {e}[/]")

    # 3. Workday employers (Japan-filtered)
    console.print("\n[bold cyan]━━━ Stage 1c: Workday portals (Japan) ━━━[/]")
    employers_data = _load_yaml(CONFIG_DIR / "japan_employers.yaml")
    employers_raw = employers_data.get("employers", {})
    employers = list(employers_raw.values()) if isinstance(employers_raw, dict) else employers_raw

    workday_queries = ["software engineer", "AI engineer", "developer"]
    for q in workday_queries:
        try:
            workday_jobs = asyncio.run(
                run_workday_scrapers(employers, query=q, max_results_per_employer=20)
            )
            # Filter to Japan locations only
            japan_workday = []
            for job in workday_jobs:
                loc = (job.location or "").lower()
                if any(kw in loc for kw in ("japan", "tokyo", "osaka", "jp", "remote",
                                             "yokohama", "fukuoka", "nagoya", "kyoto",
                                             "shibuya", "shinjuku", "minato", "roppongi")):
                    japan_workday.append(job)
                elif not job.location or job.location.strip() == "":
                    japan_workday.append(job)  # unknown location → keep
            all_jobs.extend(japan_workday)
            console.print(f"  Workday ({q}) → {len(japan_workday)} Japan jobs (of {len(workday_jobs)} total)")
        except Exception as e:
            console.print(f"  [red]Workday ({q}): {e}[/]")

    # Dedup and store
    new_jobs = dedup_jobs(all_jobs, existing_urls)
    for job in new_jobs:
        db.upsert_job(job)
    db.close()

    console.print(
        f"\n[green bold]Discovered {len(new_jobs)} new Japan jobs[/] "
        f"({len(all_jobs)} total found, {len(all_jobs) - len(new_jobs)} dupes removed)"
    )
    return len(new_jobs)


# ── Stage 2: Enrich ────────────────────────────────────────────────────────
def stage_enrich():
    from job_hunter.database import JobDB
    from job_hunter.enrich.runner import run_enrichment

    db = JobDB(JAPAN_DB_PATH)
    unenriched = db.get_unenriched_jobs()
    if not unenriched:
        console.print("[yellow]No unenriched jobs.[/]")
        db.close()
        return 0

    console.print(f"\n[bold cyan]━━━ Stage 2: Enriching {len(unenriched)} jobs ━━━[/]")

    llm = None
    try:
        llm = _get_llm()
    except Exception:
        pass

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        BarColumn(), TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(), console=console,
    ) as progress:
        task = progress.add_task("Enriching", total=len(unenriched))

        def on_progress(done, total):
            progress.update(task, completed=done)

        enriched, total = asyncio.run(
            run_enrichment(db, llm=llm, on_progress=on_progress)
        )

    db.close()
    console.print(f"[green bold]Enriched {enriched}/{total} jobs[/]")
    return enriched


# ── Stage 3: Score ──────────────────────────────────────────────────────────
def stage_score():
    from job_hunter.database import JobDB
    from job_hunter.score.scorer import run_scoring

    db = JobDB(JAPAN_DB_PATH)
    unscored = db.get_unscored_jobs()
    if not unscored:
        console.print("[yellow]No unscored jobs.[/]")
        db.close()
        return 0, 0

    console.print(f"\n[bold cyan]━━━ Stage 3: Scoring {len(unscored)} jobs ━━━[/]")

    llm = _get_llm()
    profile = _load_profile()

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        BarColumn(), TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(), console=console,
    ) as progress:
        task = progress.add_task("Scoring", total=len(unscored))

        def on_progress(done, total):
            progress.update(task, completed=done)

        scored, filtered, total = asyncio.run(
            run_scoring(db, profile, llm, on_progress=on_progress)
        )

    db.close()
    console.print(f"[green bold]Scored {scored}, filtered {filtered} (of {total})[/]")
    return scored, filtered


# ── Stage 4: Tailor (resume only, no cover letter) ─────────────────────────
def stage_tailor(score_threshold: int = 7):
    from job_hunter.database import JobDB
    from job_hunter.tailor.parser import parse_latex_resume
    from job_hunter.tailor.tailor import tailor_resume as do_tailor
    from job_hunter.tailor.renderer import render_latex_to_pdf
    from job_hunter.tailor.validator import ValidationMode

    db = JobDB(JAPAN_DB_PATH)

    resume_path = CONFIG_DIR / "resume.tex"
    if not resume_path.exists():
        console.print("[red]No resume.tex found.[/]")
        db.close()
        return 0

    resume = parse_latex_resume(resume_path.read_text(encoding="utf-8"))
    profile = _load_profile()
    llm = _get_llm()

    JAPAN_OUTPUT_DIR.mkdir(exist_ok=True)

    jobs = db.get_untailored_jobs(min_score=score_threshold)
    if not jobs:
        console.print("[yellow]No jobs to tailor.[/]")
        db.close()
        return 0

    console.print(f"\n[bold cyan]━━━ Stage 4: Tailoring {len(jobs)} resumes (score >= {score_threshold}) ━━━[/]")

    success = 0
    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        BarColumn(), TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(), console=console,
    ) as progress:
        task = progress.add_task("Tailoring", total=len(jobs))

        for job in jobs:
            try:
                tailored_latex = asyncio.run(
                    do_tailor(job, resume, profile, llm, mode=ValidationMode.NORMAL)
                )

                if tailored_latex:
                    pdf_path = render_latex_to_pdf(
                        resume.preamble, tailored_latex, JAPAN_OUTPUT_DIR, job.url
                    )
                    if pdf_path:
                        job.resume_path = str(pdf_path)
                        job.status = "tailored"
                        db.upsert_job(job)
                        success += 1
                    else:
                        console.print(f"  [yellow]PDF render failed: {job.title[:50]}[/]")
                else:
                    console.print(f"  [yellow]Tailor failed: {job.title[:50]}[/]")
            except Exception as e:
                console.print(f"  [red]Error: {job.title[:50]}: {e}[/]")

            progress.update(task, advance=1)

    db.close()
    console.print(f"[green bold]Tailored {success}/{len(jobs)} resumes[/]")
    return success


# ── Stage 5: Sync to Notion (new DB) ───────────────────────────────────────
def stage_sync():
    from job_hunter.database import JobDB
    from job_hunter.notion.client import NotionJobDB
    from job_hunter.notion.sync import push_jobs_to_notion

    token = os.environ.get("NOTION_TOKEN")
    parent_page_id = os.environ.get("NOTION_PAGE_ID")
    if not token or not parent_page_id:
        console.print("[red]NOTION_TOKEN or NOTION_PAGE_ID not set.[/]")
        return 0, 0

    console.print(f"\n[bold cyan]━━━ Stage 5: Syncing to Notion ━━━[/]")

    # Create a NEW Notion database for Japan jobs
    notion = NotionJobDB(token=token)

    # Check if we already have a Japan DB (stored in a local marker file)
    japan_notion_marker = CONFIG_DIR / ".japan_notion_db_id"
    japan_db_id = None

    if japan_notion_marker.exists():
        japan_db_id = japan_notion_marker.read_text().strip()
        console.print(f"  Using existing Japan Notion DB: {japan_db_id[:12]}...")
        notion.database_id = japan_db_id
    else:
        console.print("  Creating new Notion database: Job Hunter Japan")
        japan_db_id = notion.create_database(parent_page_id, title="Job Hunter Japan")
        japan_notion_marker.write_text(japan_db_id)
        console.print(f"  [green]Created: {japan_db_id}[/]")

    db = JobDB(JAPAN_DB_PATH)

    # Push with local file:// links for resume PDFs
    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        BarColumn(), TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(), console=console,
    ) as progress:
        prog_task = None

        def on_progress(done, total):
            nonlocal prog_task
            if prog_task is None:
                prog_task = progress.add_task("Syncing", total=total)
            progress.update(prog_task, completed=done)

        created, updated = push_jobs_to_notion(db, notion, on_progress=on_progress)

    db.close()
    console.print(f"[green bold]Synced: {created} created, {updated} updated[/]")
    return created, updated


# ── Autoresearch: Source Research ─────────────────────────────────────────
def stage_source_research():
    from job_hunter.autoresearch.source_research import run_source_research

    console.print("\n[bold cyan]━━━ AR-1: Source Research (health check) ━━━[/]")

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        BarColumn(), TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(), console=console,
    ) as progress:
        task = progress.add_task("Checking sources", total=1)

        def on_progress(done, total):
            progress.update(task, total=total, completed=done)

        results = asyncio.run(
            run_source_research(CONFIG_DIR / "japan_employers.yaml", on_progress=on_progress)
        )

    console.print(
        f"[green bold]Sources: {results['healthy']} healthy, "
        f"{results['unhealthy']} unhealthy[/]"
    )
    return results["healthy"], results["unhealthy"]


# ── Autoresearch: Data Validation ────────────────────────────────────────
def stage_data_validate():
    from job_hunter.database import JobDB
    from job_hunter.autoresearch.data_validation import run_data_validation

    console.print("\n[bold cyan]━━━ AR-2: Data Validation ━━━[/]")

    db = JobDB(JAPAN_DB_PATH)

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        BarColumn(), TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(), console=console,
    ) as progress:
        task = progress.add_task("Validating", total=4)

        def on_progress(done, total):
            progress.update(task, completed=done)

        results = asyncio.run(run_data_validation(db, on_progress=on_progress))

    db.close()
    console.print(
        f"[green bold]Validated {results['total_checked']} jobs: "
        f"{results['dead_urls']} dead URLs, "
        f"{results['dupes_removed']} dupes, "
        f"{results['non_japan_filtered']} non-Japan, "
        f"{results['low_quality_flagged']} low quality[/]"
    )
    return results


# ── Autoresearch: Score Audit ────────────────────────────────────────────
def stage_score_audit():
    from job_hunter.database import JobDB
    from job_hunter.autoresearch.score_audit import run_score_audit

    console.print("\n[bold cyan]━━━ AR-3: Score Audit ━━━[/]")

    db = JobDB(JAPAN_DB_PATH)
    profile = _load_profile()
    llm = None
    try:
        llm = _get_llm()
    except Exception:
        pass

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        BarColumn(), TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(), console=console,
    ) as progress:
        prog_task = None

        def on_progress(done, total):
            nonlocal prog_task
            if prog_task is None:
                prog_task = progress.add_task("Auditing scores", total=total)
            progress.update(prog_task, completed=done)

        results = asyncio.run(run_score_audit(db, profile, llm=llm, on_progress=on_progress))

    db.close()
    console.print(
        f"[green bold]Audited {results['total_audited']} scores: "
        f"{results['rule_flagged']} rule-flagged, "
        f"{results['llm_flagged']} LLM-flagged, "
        f"{results['scores_adjusted']} adjusted[/]"
    )
    return results


# ── Autoresearch: Resume Audit ───────────────────────────────────────────
def stage_resume_audit():
    from job_hunter.database import JobDB
    from job_hunter.autoresearch.resume_audit import run_resume_audit

    console.print("\n[bold cyan]━━━ AR-4: Resume Audit ━━━[/]")

    db = JobDB(JAPAN_DB_PATH)
    profile = _load_profile()
    llm = None
    try:
        llm = _get_llm()
    except Exception:
        pass

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        BarColumn(), TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(), console=console,
    ) as progress:
        prog_task = None

        def on_progress(done, total):
            nonlocal prog_task
            if prog_task is None:
                prog_task = progress.add_task("Auditing resumes", total=total)
            progress.update(prog_task, completed=done)

        results = asyncio.run(run_resume_audit(db, profile, llm=llm, on_progress=on_progress))

    db.close()
    console.print(
        f"[green bold]Audited {results['total_audited']} resumes: "
        f"{results['quick_flagged']} flagged, "
        f"{results['needs_regeneration']} need regen, "
        f"avg match {results['avg_match_percentage']}%[/]"
    )
    return results


# ── Deep Autoresearch ───────────────────────────────────────────────────────
def stage_deep_research(min_score: int = 5, max_jobs: int = 50, loop: bool = False):
    from job_hunter.database import JobDB
    from job_hunter.autoresearch.deep_research import run_deep_research, run_deep_research_loop

    console.print("\n[bold cyan]━━━ Deep Autoresearch (Karpathy-style) ━━━[/]")
    if loop:
        console.print("[dim]Loop mode: runs until Ctrl+C. Re-researches LOW confidence jobs.[/]")
    else:
        console.print("[dim]Single pass — iterative web search + LLM per job...[/]")

    db = JobDB(JAPAN_DB_PATH)
    profile = _load_profile()
    llm = _get_llm()

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        BarColumn(), TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(), console=console,
    ) as progress:
        prog_task = None

        def on_progress(done, total):
            nonlocal prog_task
            if prog_task is None:
                prog_task = progress.add_task("Deep research", total=total)
            progress.update(prog_task, completed=done)

        def on_job_complete(job, evidence):
            # Color-coded status: keep=green, discard=yellow, skip=dim
            status = evidence.status
            if status == "keep":
                icon, color = "✓", "green"
            elif status == "discard":
                icon, color = "✗", "yellow"
            else:
                icon, color = "─", "dim"

            console.print(
                f"  [{color}]{icon}[/] {job.title[:40]} @ {job.company} — "
                f"[{color}]{status.upper()}[/] "
                f"score {evidence.rescore_info.get('final_score', '?')}/10 "
                f"visa={evidence.visa_info.get('visa_status', '?')} "
                f"conf={evidence.confidence} "
                f"({evidence.research_time_seconds:.0f}s)"
            )

        def on_iteration_complete(iteration, iter_results):
            console.print(
                f"\n[bold cyan]── Iteration {iteration} complete: "
                f"{iter_results['total_researched']} researched, "
                f"kept={iter_results.get('kept', 0)}, "
                f"discarded={iter_results.get('discarded', 0)} ──[/]"
            )

        if loop:
            results = asyncio.run(run_deep_research_loop(
                db, profile, llm,
                min_score=min_score,
                max_jobs=max_jobs,
                on_progress=on_progress,
                on_job_complete=on_job_complete,
                on_iteration_complete=on_iteration_complete,
            ))
        else:
            results = asyncio.run(run_deep_research(
                db, profile, llm,
                min_score=min_score,
                max_jobs=max_jobs,
                on_progress=on_progress,
                on_job_complete=on_job_complete,
            ))

    db.close()

    if loop:
        console.print(
            f"\n[green bold]Deep Research Loop: {results.get('iterations', 0)} iterations, "
            f"{results['total_researched']} total researched, "
            f"kept={results.get('total_kept', 0)}, "
            f"discarded={results.get('total_discarded', 0)}, "
            f"{results['total_time_seconds']:.0f}s total[/]"
        )
    else:
        console.print(
            f"\n[green bold]Deep Research: {results['total_researched']} jobs researched, "
            f"{results['scores_changed']} scores changed "
            f"(kept={results.get('kept', 0)} ↑{results['scores_increased']} ↓{results['scores_decreased']}, "
            f"discarded={results.get('discarded', 0)}), "
            f"{results['resumes_flagged']} resumes flagged, "
            f"{results['total_time_seconds']:.0f}s total[/]"
        )
    return results


# ── Main ────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="Japan-focused job hunting pipeline with autoresearch")
    parser.add_argument("--skip-discover", action="store_true", help="Skip discover stage")
    parser.add_argument("--skip-enrich", action="store_true", help="Skip enrich stage")
    parser.add_argument("--skip-score", action="store_true", help="Skip score stage")
    parser.add_argument("--skip-tailor", action="store_true", help="Skip tailor stage")
    parser.add_argument("--skip-sync", action="store_true", help="Skip sync stage")
    parser.add_argument("--skip-autoresearch", action="store_true", help="Skip all autoresearch stages")
    parser.add_argument("--autoresearch-only", action="store_true", help="Run only autoresearch stages")
    parser.add_argument("--deep-research", action="store_true", help="Run Karpathy-style deep autoresearch")
    parser.add_argument("--deep-research-only", action="store_true", help="Run only deep autoresearch")
    parser.add_argument("--deep-research-loop", action="store_true", help="Never-stop loop: re-researches LOW confidence until Ctrl+C")
    parser.add_argument("--deep-max-jobs", type=int, default=50, help="Max jobs for deep research (default: 50)")
    parser.add_argument("--deep-min-score", type=int, default=5, help="Min score for deep research (default: 5)")
    parser.add_argument("--score-threshold", type=int, default=7, help="Min score for tailoring (default: 7)")
    args = parser.parse_args()

    start = time.time()
    console.print("[bold magenta]╔══════════════════════════════════════════╗[/]")
    console.print("[bold magenta]║   Japan Job Hunter Pipeline + AR         ║[/]")
    console.print(f"[bold magenta]║   {datetime.now().strftime('%Y-%m-%d %H:%M')}                        ║[/]")
    console.print("[bold magenta]╚══════════════════════════════════════════╝[/]")

    results = {}

    # AR-1: Source Research (pre-discovery)
    if not args.skip_autoresearch:
        results["AR:sources"] = stage_source_research()

    if args.deep_research_loop:
        # Never-stop loop mode (Karpathy pattern)
        results["deep-research"] = stage_deep_research(
            min_score=args.deep_min_score, max_jobs=args.deep_max_jobs, loop=True,
        )
    elif args.deep_research_only:
        # Deep research only mode — skip everything else
        results["deep-research"] = stage_deep_research(
            min_score=args.deep_min_score, max_jobs=args.deep_max_jobs,
        )
    elif not args.autoresearch_only:
        if not args.skip_discover:
            results["discover"] = stage_discover()

        # AR-2: Data Validation (post-discovery)
        if not args.skip_autoresearch and not args.skip_discover:
            results["AR:validate"] = stage_data_validate()

        if not args.skip_enrich:
            results["enrich"] = stage_enrich()
        if not args.skip_score:
            results["score"] = stage_score()

        # AR-3: Score Audit (post-scoring)
        if not args.skip_autoresearch and not args.skip_score:
            results["AR:score-audit"] = stage_score_audit()

        if not args.skip_tailor:
            results["tailor"] = stage_tailor(args.score_threshold)

        # AR-4: Resume Audit (post-tailoring)
        if not args.skip_autoresearch and not args.skip_tailor:
            results["AR:resume-audit"] = stage_resume_audit()

        # Deep autoresearch (after scoring, before sync)
        if args.deep_research and not args.skip_score:
            results["deep-research"] = stage_deep_research(
                min_score=args.deep_min_score, max_jobs=args.deep_max_jobs,
            )

        if not args.skip_sync:
            results["sync"] = stage_sync()
    else:
        # Autoresearch-only mode: run all 4 AR stages on existing data
        results["AR:validate"] = stage_data_validate()
        results["AR:score-audit"] = stage_score_audit()
        results["AR:resume-audit"] = stage_resume_audit()

    elapsed = time.time() - start

    # Summary
    console.print("\n")
    table = Table(title="Japan Pipeline Summary")
    table.add_column("Stage", style="cyan")
    table.add_column("Result", justify="right")

    for stage, result in results.items():
        if isinstance(result, dict):
            # Compact dict display for AR results
            summary = ", ".join(f"{k}={v}" for k, v in result.items() if isinstance(v, (int, float, str)))
            table.add_row(stage, summary[:60])
        elif isinstance(result, tuple):
            table.add_row(stage, str(result))
        else:
            table.add_row(stage, str(result))

    table.add_row("Time", f"{elapsed:.0f}s", style="dim")
    console.print(table)
    console.print("[bold green]Done![/]")


if __name__ == "__main__":
    main()
