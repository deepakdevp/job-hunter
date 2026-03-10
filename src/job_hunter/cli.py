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
