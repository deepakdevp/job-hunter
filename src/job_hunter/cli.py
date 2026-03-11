from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.table import Table

from job_hunter import __version__

console = Console()


def _setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


@click.group()
@click.version_option(version=__version__)
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
@click.option("--config-dir", type=click.Path(exists=True), default=".", help="Config directory")
@click.pass_context
def cli(ctx, verbose, config_dir):
    """Job Hunter — discover, score, tailor, apply."""
    _setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["config_dir"] = Path(config_dir)
    ctx.obj["verbose"] = verbose


@cli.command()
@click.pass_context
def doctor(ctx):
    """Check that all dependencies and configs are set up."""
    config_dir = ctx.obj["config_dir"]
    checks = [
        ("profile.json", (config_dir / "profile.json").exists()),
        ("searches.yaml", (config_dir / "searches.yaml").exists()),
        ("employers.yaml", (config_dir / "employers.yaml").exists()),
        (".env", (config_dir / ".env").exists()),
    ]

    for pkg, name in [
        ("jobspy", "python-jobspy"),
        ("notion_client", "notion-client"),
        ("google.genai", "google-genai"),
        ("weasyprint", "weasyprint"),
        ("playwright", "playwright"),
        ("bs4", "beautifulsoup4"),
    ]:
        try:
            __import__(pkg)
            checks.append((name, True))
        except (ImportError, OSError):
            checks.append((name, False))

    table = Table(title="Job Hunter Doctor")
    table.add_column("Check", style="cyan")
    table.add_column("Status")
    for name, ok in checks:
        table.add_row(name, "[green]OK[/]" if ok else "[red]MISSING[/]")
    console.print(table)


@cli.command()
@click.pass_context
def status(ctx):
    """Show pipeline statistics."""
    config_dir = ctx.obj["config_dir"]
    db_path = config_dir / "jobs.db"
    if not db_path.exists():
        console.print("[yellow]No jobs database found. Run 'hunt discover' first.[/]")
        return

    from job_hunter.database import JobDB

    db = JobDB(db_path)
    stats = db.get_stats()
    db.close()

    table = Table(title="Pipeline Status")
    table.add_column("Stage", style="cyan")
    table.add_column("Count", justify="right")
    for status_name, count in stats.items():
        table.add_row(status_name, str(count))
    console.print(table)


@cli.command()
@click.option("--workers", "-w", default=1, help="Parallel workers")
@click.option("--skip-jobspy", is_flag=True, help="Skip JobSpy boards")
@click.option("--skip-japan", is_flag=True, help="Skip Japan custom scrapers")
@click.option("--skip-workday", is_flag=True, help="Skip Workday portals")
@click.pass_context
def discover(ctx, workers, skip_jobspy, skip_japan, skip_workday):
    """Scrape all configured job platforms."""
    from job_hunter.config import load_config
    from job_hunter.database import JobDB
    from job_hunter.discover.jobspy_scraper import run_jobspy_search, parse_jobspy_results
    from job_hunter.discover.dedup import dedup_jobs

    config = load_config(ctx.obj["config_dir"])
    db = JobDB(ctx.obj["config_dir"] / "jobs.db")
    existing_urls = db.get_all_urls()

    all_jobs = []

    # 1. JobSpy boards (LinkedIn, Indeed, Glassdoor, Google, ZipRecruiter)
    if not skip_jobspy:
        console.print("[bold]Stage 1: JobSpy boards[/]")
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
                console.print(f"  {search['query']} in {search.get('location', '?')}: {len(jobs)} jobs")
            except Exception as e:
                console.print(f"  [red]Failed: {search.get('query')}: {e}[/]")

    # 2. Japan custom scrapers
    if not skip_japan:
        console.print("[bold]Stage 2: Japan boards[/]")
        from job_hunter.discover.japan_scrapers import run_japan_scrapers

        japan_jobs = asyncio.run(run_japan_scrapers(query="software engineer", max_results=50))
        all_jobs.extend(japan_jobs)
        console.print(f"  Japan scrapers: {len(japan_jobs)} jobs")

    # 3. Workday employer portals
    if not skip_workday and config.employers:
        console.print("[bold]Stage 3: Workday portals[/]")
        from job_hunter.discover.workday_scraper import run_workday_scrapers

        workday_jobs = asyncio.run(
            run_workday_scrapers(config.employers, query="software engineer", max_results_per_employer=20)
        )
        all_jobs.extend(workday_jobs)
        console.print(f"  Workday portals: {len(workday_jobs)} jobs")

    # Dedup and store
    new_jobs = dedup_jobs(all_jobs, existing_urls)
    for job in new_jobs:
        db.upsert_job(job)
    db.close()

    console.print(
        f"\n[green bold]Discovered {len(new_jobs)} new jobs[/] "
        f"({len(all_jobs)} total found, {len(all_jobs) - len(new_jobs)} duplicates removed)"
    )


@cli.command()
@click.option("--limit", "-l", default=None, type=int, help="Max jobs to enrich")
@click.option("--tier1-only", is_flag=True, help="Skip LLM tier (zero cost)")
@click.pass_context
def enrich(ctx, limit, tier1_only):
    """Fetch full job descriptions using 3-tier cascade."""
    from job_hunter.config import load_config
    from job_hunter.database import JobDB
    from job_hunter.enrich.runner import run_enrichment

    config = load_config(ctx.obj["config_dir"])
    db = JobDB(ctx.obj["config_dir"] / "jobs.db")

    unenriched = db.get_unenriched_jobs()
    count = min(len(unenriched), limit) if limit else len(unenriched)

    if count == 0:
        console.print("[yellow]No unenriched jobs found.[/]")
        db.close()
        return

    llm = None
    if not tier1_only:
        from job_hunter.llm.base import get_provider
        try:
            llm = get_provider(
                config.llm_provider,
                api_key=config.gemini_api_key,
                model=config.llm_model,
            )
        except Exception as e:
            console.print(f"[yellow]LLM not available ({e}), using Tier 1-2 only[/]")

    console.print(f"[bold]Enriching {count} jobs...[/]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Enriching", total=count)

        def on_progress(done, total):
            progress.update(task, completed=done)

        enriched, total = asyncio.run(
            run_enrichment(db, llm=llm, limit=limit, tier1_only=tier1_only, on_progress=on_progress)
        )

    db.close()
    console.print(f"\n[green bold]Enriched {enriched}/{total} jobs[/]")


@cli.command()
@click.pass_context
def score(ctx):
    """Score jobs using pre-filter + multi-criteria LLM scoring."""
    from job_hunter.config import load_config
    from job_hunter.database import JobDB
    from job_hunter.score.scorer import run_scoring
    from job_hunter.llm.base import get_provider

    config = load_config(ctx.obj["config_dir"])
    db = JobDB(ctx.obj["config_dir"] / "jobs.db")

    unscored = db.get_unscored_jobs()
    if not unscored:
        console.print("[yellow]No unscored jobs found.[/]")
        db.close()
        return

    try:
        llm = get_provider(
            config.llm_provider,
            api_key=config.gemini_api_key,
            model=config.llm_model,
        )
    except Exception as e:
        console.print(f"[red]LLM required for scoring but not available: {e}[/]")
        db.close()
        return

    profile = config.profile
    console.print(f"[bold]Scoring {len(unscored)} jobs (pre-filter + LLM)...[/]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Scoring", total=len(unscored))

        def on_progress(done, total):
            progress.update(task, completed=done)

        scored, filtered, total = asyncio.run(
            run_scoring(db, profile, llm, on_progress=on_progress)
        )

    db.close()
    console.print(
        f"\n[green bold]Scored {scored} jobs[/], "
        f"[yellow]filtered {filtered}[/] "
        f"(out of {total} total)"
    )


@cli.command()
@click.option("--all", "tailor_all", is_flag=True, help="Tailor all untailored jobs above threshold")
@click.option("--job-url", default=None, help="Tailor a specific job by URL")
@click.option("--validation", type=click.Choice(["strict", "normal", "lenient"]), default="strict")
@click.pass_context
def tailor(ctx, tailor_all, job_url, validation):
    """Generate tailored resumes for scored jobs."""
    from job_hunter.config import load_config
    from job_hunter.database import JobDB
    from job_hunter.tailor.parser import parse_latex_resume
    from job_hunter.tailor.tailor import tailor_resume as do_tailor
    from job_hunter.tailor.renderer import render_latex_to_pdf
    from job_hunter.tailor.cover_letter import generate_cover_letter
    from job_hunter.tailor.cover_letter_renderer import render_cover_letter
    from job_hunter.tailor.validator import ValidationMode
    from job_hunter.llm.base import get_provider

    config = load_config(ctx.obj["config_dir"])
    db = JobDB(ctx.obj["config_dir"] / "jobs.db")
    output_dir = ctx.obj["config_dir"] / "output"

    mode = ValidationMode(validation)

    # Load resume
    resume_path = ctx.obj["config_dir"] / "config" / "resume.tex"
    if not resume_path.exists():
        resume_path = ctx.obj["config_dir"] / "resume.tex"
    if not resume_path.exists():
        console.print("[red]No resume.tex found in config/ or project root.[/]")
        db.close()
        return

    resume_source = resume_path.read_text(encoding="utf-8")
    resume = parse_latex_resume(resume_source)
    profile = config.profile

    # Get jobs to tailor
    if job_url:
        job = db.get_job(job_url)
        if not job:
            console.print(f"[red]Job not found: {job_url}[/]")
            db.close()
            return
        jobs = [job]
    elif tailor_all:
        jobs = db.get_untailored_jobs(min_score=config.score_threshold)
    else:
        console.print("[yellow]Use --all or --job-url to specify which jobs to tailor.[/]")
        db.close()
        return

    if not jobs:
        console.print("[yellow]No jobs to tailor.[/]")
        db.close()
        return

    try:
        llm = get_provider(
            config.llm_provider,
            api_key=config.gemini_api_key,
            model=config.llm_model,
        )
    except Exception as e:
        console.print(f"[red]LLM required for tailoring but not available: {e}[/]")
        db.close()
        return

    console.print(f"[bold]Tailoring {len(jobs)} resumes (mode: {validation})...[/]")

    success = 0
    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        task = progress.add_task("Tailoring", total=len(jobs))

        for job in jobs:
            tailored_latex = asyncio.run(
                do_tailor(job, resume, profile, llm, mode=mode)
            )

            if tailored_latex:
                pdf_path = render_latex_to_pdf(
                    resume.preamble, tailored_latex, output_dir, job.url
                )
                if pdf_path:
                    job.resume_path = str(pdf_path)
                else:
                    console.print(f"  [yellow]Resume PDF render failed for {job.title}[/]")

                # Generate cover letter
                cl_text = asyncio.run(
                    generate_cover_letter(job, profile, llm, mode=mode)
                )
                if cl_text:
                    cl_pdf, cl_txt = render_cover_letter(
                        cl_text, profile, job.title, job.company, output_dir, job.url
                    )
                    job.cover_letter_path = str(cl_txt) if cl_txt else None
                else:
                    console.print(f"  [yellow]Cover letter failed for {job.title}[/]")

                job.status = "tailored"
                db.upsert_job(job)
                success += 1
            else:
                console.print(f"  [yellow]Tailoring failed for {job.title}[/]")

            progress.update(task, advance=1)

    db.close()
    console.print(f"\n[green bold]Tailored {success}/{len(jobs)} resumes[/]")


@cli.group()
def sync():
    """Notion sync commands."""
    pass


@sync.command("init")
@click.option("--page-id", required=True, help="Notion parent page ID")
@click.pass_context
def sync_init(ctx, page_id):
    """Initialize Notion database under a parent page."""
    import os
    from job_hunter.notion.client import NotionJobDB

    token = os.environ.get("NOTION_TOKEN")
    if not token:
        console.print("[red]NOTION_TOKEN not set in environment.[/]")
        raise SystemExit(1)

    notion = NotionJobDB(token=token)
    db_id = notion.init_database(page_id)
    console.print(f"[green]Notion database ready: {db_id}[/]")
    console.print(f"Add to .env: NOTION_DATABASE_ID={db_id}")


@sync.command("push")
@click.option("--drive-creds", type=click.Path(exists=True), default=None, help="Google service account JSON")
@click.pass_context
def sync_push(ctx, drive_creds):
    """Push jobs to Notion (and optionally upload PDFs to Drive)."""
    import os
    from job_hunter.database import JobDB
    from job_hunter.notion.client import NotionJobDB
    from job_hunter.notion.drive_uploader import DriveUploader
    from job_hunter.notion.sync import push_jobs_to_notion

    token = os.environ.get("NOTION_TOKEN")
    db_id = os.environ.get("NOTION_DATABASE_ID")
    if not token or not db_id:
        console.print("[red]Set NOTION_TOKEN and NOTION_DATABASE_ID in .env[/]")
        raise SystemExit(1)

    config_dir = ctx.obj["config_dir"]
    db = JobDB(config_dir / "jobs.db")
    notion = NotionJobDB(token=token, database_id=db_id)

    drive = None
    if drive_creds:
        drive = DriveUploader(credentials_path=drive_creds)

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        BarColumn(), TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(), console=console,
    ) as progress:
        task = None

        def on_progress(done, total):
            nonlocal task
            if task is None:
                task = progress.add_task("Pushing", total=total)
            progress.update(task, completed=done)

        created, updated = push_jobs_to_notion(db, notion, drive, on_progress)

    db.close()
    console.print(f"\n[green bold]Pushed to Notion: {created} created, {updated} updated[/]")


@sync.command("pull")
@click.pass_context
def sync_pull(ctx):
    """Pull status changes from Notion back to local DB."""
    import os
    from job_hunter.database import JobDB
    from job_hunter.notion.client import NotionJobDB
    from job_hunter.notion.sync import pull_status_from_notion

    token = os.environ.get("NOTION_TOKEN")
    db_id = os.environ.get("NOTION_DATABASE_ID")
    if not token or not db_id:
        console.print("[red]Set NOTION_TOKEN and NOTION_DATABASE_ID in .env[/]")
        raise SystemExit(1)

    config_dir = ctx.obj["config_dir"]
    db = JobDB(config_dir / "jobs.db")
    notion = NotionJobDB(token=token, database_id=db_id)

    with Progress(
        SpinnerColumn(), TextColumn("[progress.description]{task.description}"),
        BarColumn(), TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(), console=console,
    ) as progress:
        task = None

        def on_progress(done, total):
            nonlocal task
            if task is None:
                task = progress.add_task("Pulling", total=total)
            progress.update(task, completed=done)

        updated = pull_status_from_notion(db, notion, on_progress)

    db.close()
    console.print(f"\n[green bold]Pulled from Notion: {updated} status updates[/]")


@cli.command("apply")
@click.option("--job-url", default=None, help="Apply to a single job by URL")
@click.option("--all", "apply_all", is_flag=True, help="Apply to all eligible jobs")
@click.option("--limit", default=None, type=int, help="Max applications in batch mode")
@click.option("--login", "login_domain", default=None, help="Open browser to save login session for a domain")
@click.option("--dry-run", is_flag=True, help="Fill forms without submitting")
@click.pass_context
def apply_cmd(ctx, job_url, apply_all, limit, login_domain, dry_run):
    """Apply to jobs using browser automation."""
    import json as _json
    import os
    import time

    from job_hunter.apply.applicant import Applicant
    from job_hunter.apply.strategies.base import detect_platform

    config_dir = ctx.obj["config_dir"]
    profile_path = config_dir / "profile.json"
    if not profile_path.exists():
        console.print("[red]profile.json not found[/]")
        raise SystemExit(1)

    profile = _json.loads(profile_path.read_text())

    llm = None
    try:
        from job_hunter.config import load_config
        from job_hunter.llm.base import get_provider
        config = load_config(config_dir)
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

    # Login mode
    if login_domain:
        console.print(f"[bold]Opening browser for {login_domain} — log in then close the window[/]")
        asyncio.run(applicant.login_and_save(login_domain))
        console.print(f"[green]Session saved for {login_domain}[/]")
        return

    from job_hunter.database import JobDB

    db = JobDB(config_dir / "jobs.db")

    # Single job mode
    if job_url:
        job = db.get_job(job_url)
        if not job:
            console.print(f"[red]Job not found: {job_url}[/]")
            db.close()
            raise SystemExit(1)

        console.print(f"[bold]Applying: {job.title} @ {job.company}[/]")
        result = asyncio.run(applicant.apply_to_job(job))
        applicant._log_result(result)

        if result.status == "applied":
            job.status = "applied"
            db.upsert_job(job)
            console.print("[green bold]Applied successfully[/]")
        elif result.status == "dry_run":
            console.print("[yellow]Dry run — form filled but not submitted[/]")
        else:
            job.status = "apply_failed"
            db.upsert_job(job)
            console.print(f"[red]Failed: {result.error}[/]")

        db.close()
        return

    # Batch mode
    if not apply_all:
        console.print("[yellow]Use --job-url or --all[/]")
        db.close()
        return

    jobs = []
    for s in ("tailored", "synced"):
        jobs.extend(db.get_jobs_by_status(s))
    jobs = [j for j in jobs if applicant.is_eligible(j)]

    if limit:
        jobs = jobs[:limit]

    if not jobs:
        console.print("[yellow]No eligible jobs to apply to[/]")
        db.close()
        return

    console.print(f"[bold]Applying to {len(jobs)} jobs{' (dry run)' if dry_run else ''}[/]\n")

    applied = 0
    for i, job in enumerate(jobs, 1):
        platform = detect_platform(job.apply_url or job.url)
        console.print(f"[bold][{i}/{len(jobs)}] {job.title} @ {job.company}[/]")
        console.print(f"      Platform: {platform}")

        result = asyncio.run(applicant.apply_to_job(job))
        applicant._log_result(result)

        if result.status == "applied":
            job.status = "applied"
            db.upsert_job(job)
            applied += 1
            console.print("      [green]Applied[/]")
        elif result.status == "dry_run":
            console.print("      [yellow]Dry run[/]")
        else:
            job.status = "apply_failed"
            db.upsert_job(job)
            console.print(f"      [red]Failed: {result.error}[/]")

        if i < len(jobs):
            time.sleep(2)

    db.close()
    console.print(f"\n[green bold]Done: {applied}/{len(jobs)} applied[/]")


@cli.command("run")
@click.option("--apply", "run_apply", is_flag=True, help="Include auto-apply stage")
@click.option("--skip-discover", is_flag=True, help="Skip discover stage")
@click.option("--dry-run", is_flag=True, help="Dry-run apply (no submit)")
@click.pass_context
def run_cmd(ctx, run_apply, skip_discover, dry_run):
    """Run the full pipeline: discover -> enrich -> score -> tailor -> sync."""
    from job_hunter.pipeline import run_pipeline

    config_dir = ctx.obj["config_dir"]

    console.print("[bold]Starting pipeline run...[/]\n")

    summary = run_pipeline(
        config_dir,
        skip_discover=skip_discover,
        run_apply=run_apply,
        dry_run=dry_run,
    )

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
