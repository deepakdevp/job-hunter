from __future__ import annotations

import asyncio
import logging
from pathlib import Path

import click
from rich.console import Console
from rich.progress import Progress, SpinnerColumn, BarColumn, TextColumn, TimeElapsedColumn
from rich.panel import Panel
from rich.table import Table

from job_hunter import __version__

console = Console()


def _setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


@click.group()
@click.version_option(version=__version__)
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
@click.option("--config-dir", type=click.Path(), default=None, help="Config directory")
@click.option("--data-dir", type=click.Path(), default=None, help="Data directory")
@click.pass_context
def cli(ctx, verbose, config_dir, data_dir):
    """Job Hunter — discover, score, tailor, apply."""
    from job_hunter.config import get_config_dir, get_data_dir

    _setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["config_dir"] = get_config_dir(Path(config_dir) if config_dir else None)
    ctx.obj["data_dir"] = get_data_dir(Path(data_dir) if data_dir else None)
    ctx.obj["verbose"] = verbose


@cli.command("init")
def init_cmd():
    """Interactive setup wizard — create profile, .env, and searches."""
    from job_hunter.init_wizard import interactive_init

    interactive_init()


@cli.command("dashboard")
@click.option("--port", "-p", default=8420, type=int, help="Port to serve on")
@click.option("--host", default="127.0.0.1", help="Host to bind to")
@click.option("--no-open", is_flag=True, help="Don't auto-open browser")
@click.pass_context
def dashboard_cmd(ctx, port, host, no_open):
    """Launch the web dashboard to monitor jobs, evaluations, and applications."""
    try:
        import uvicorn
    except ImportError:
        console.print("[red]Dashboard requires fastapi + uvicorn. Install with:[/]")
        console.print("[yellow]  pip install job-hunter\\[dashboard][/]")
        raise SystemExit(1)

    from job_hunter.dashboard.app import create_app

    data_dir = ctx.obj["data_dir"]
    config_dir = ctx.obj["config_dir"]
    db_path = data_dir / "jobs.db"

    if not db_path.exists():
        console.print("[yellow]No jobs database found. Run 'hunt discover' first.[/]")
        console.print(f"[dim]Expected at: {db_path}[/]")
        raise SystemExit(1)

    app = create_app(db_path=db_path, config_dir=config_dir)

    url = f"http://{host}:{port}"
    console.print("\n[bold green]Job Hunter Dashboard[/]")
    console.print(f"[cyan]{url}[/]\n")
    console.print("[dim]Press Ctrl+C to stop[/]\n")

    if not no_open:
        import webbrowser
        webbrowser.open(url)

    uvicorn.run(app, host=host, port=port, log_level="warning")


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
    data_dir = ctx.obj["data_dir"]
    db_path = data_dir / "jobs.db"
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
        style = ""
        if status_name == "evaluated":
            style = "magenta"
        elif status_name == "stories":
            style = "blue"
        table.add_row(status_name, f"[{style}]{count}[/]" if style else str(count))
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
    from job_hunter.discover.dedup import dedup_jobs

    try:
        from job_hunter.discover.jobspy_scraper import run_jobspy_search, parse_jobspy_results
    except ImportError:
        if not skip_jobspy:
            console.print("[red]Job discovery requires python-jobspy. Install with:[/]")
            console.print("[yellow]  pip install job-hunter\\[jobspy][/]")
            raise SystemExit(1)
        # If skipping jobspy, we don't need the import
        run_jobspy_search = None  # type: ignore[assignment]
        parse_jobspy_results = None  # type: ignore[assignment]

    config = load_config(ctx.obj["config_dir"])
    data_dir = ctx.obj["data_dir"]
    data_dir.mkdir(parents=True, exist_ok=True)
    db = JobDB(data_dir / "jobs.db")
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
                console.print(
                    f"  {search['query']} in {search.get('location', '?')}: {len(jobs)} jobs"
                )
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
            run_workday_scrapers(
                config.employers, query="software engineer", max_results_per_employer=20
            )
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
    db = JobDB(ctx.obj["data_dir"] / "jobs.db")

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
                api_key=config.llm_api_key,
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
    db = JobDB(ctx.obj["data_dir"] / "jobs.db")

    unscored = db.get_unscored_jobs()
    if not unscored:
        console.print("[yellow]No unscored jobs found.[/]")
        db.close()
        return

    try:
        llm = get_provider(
            config.llm_provider,
            api_key=config.llm_api_key,
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
@click.option(
    "--all", "tailor_all", is_flag=True, help="Tailor all untailored jobs above threshold"
)
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
    data_dir = ctx.obj["data_dir"]
    db = JobDB(data_dir / "jobs.db")
    output_dir = data_dir / "output"

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
            api_key=config.llm_api_key,
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
            tailored_latex = asyncio.run(do_tailor(job, resume, profile, llm, mode=mode))

            if tailored_latex:
                pdf_path = render_latex_to_pdf(resume.preamble, tailored_latex, output_dir, job.url)
                if pdf_path:
                    job.resume_path = str(pdf_path)
                else:
                    console.print(f"  [yellow]Resume PDF render failed for {job.title}[/]")

                # Parse evaluation data for richer cover letter
                eval_data = None
                if job.evaluation:
                    try:
                        import json as _j
                        eval_data = _j.loads(job.evaluation)
                    except Exception:
                        pass

                # Generate cover letter
                cl_text = asyncio.run(
                    generate_cover_letter(
                        job, profile, llm, mode=mode, evaluation_data=eval_data
                    )
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


@cli.group("export")
def export_group():
    """Export jobs to CSV or JSON."""
    pass


@export_group.command("csv")
@click.option("--output", "-o", required=True, type=click.Path(), help="Output CSV file path")
@click.option("--min-score", default=0, type=int, help="Minimum score filter")
@click.pass_context
def export_csv_cmd(ctx, output, min_score):
    """Export jobs to CSV file."""
    from job_hunter.database import JobDB
    from job_hunter.export import export_csv

    data_dir = ctx.obj["data_dir"]
    db_path = data_dir / "jobs.db"
    if not db_path.exists():
        console.print("[yellow]No jobs database found. Run 'hunt discover' first.[/]")
        return

    db = JobDB(db_path)
    count = export_csv(db, Path(output), min_score=min_score)
    db.close()
    console.print(f"[green bold]Exported {count} jobs to {output}[/]")


@export_group.command("json")
@click.option("--output", "-o", required=True, type=click.Path(), help="Output JSON file path")
@click.option("--min-score", default=0, type=int, help="Minimum score filter")
@click.pass_context
def export_json_cmd(ctx, output, min_score):
    """Export jobs to JSON file."""
    from job_hunter.database import JobDB
    from job_hunter.export import export_json

    data_dir = ctx.obj["data_dir"]
    db_path = data_dir / "jobs.db"
    if not db_path.exists():
        console.print("[yellow]No jobs database found. Run 'hunt discover' first.[/]")
        return

    db = JobDB(db_path)
    count = export_json(db, Path(output), min_score=min_score)
    db.close()
    console.print(f"[green bold]Exported {count} jobs to {output}[/]")


@cli.command()
@click.option("--job-url", default=None, help="Evaluate a specific job by URL")
@click.option("--all", "eval_all", is_flag=True, help="Evaluate all scored jobs above threshold")
@click.option("--min-score", default=5, type=int, help="Minimum score for evaluation")
@click.pass_context
def evaluate(ctx, job_url, eval_all, min_score):
    """Deep-evaluate scored jobs: comp intel, culture, interview prep."""
    from job_hunter.config import load_config
    from job_hunter.database import JobDB
    from job_hunter.llm.base import get_provider

    try:
        from job_hunter.evaluate.engine import run_evaluation
    except ImportError:
        console.print("[red]Evaluation module not available.[/]")
        raise SystemExit(1)

    if not job_url and not eval_all:
        console.print("[yellow]Use --job-url or --all to specify which jobs to evaluate.[/]")
        return

    config = load_config(ctx.obj["config_dir"])
    data_dir = ctx.obj["data_dir"]
    db = JobDB(data_dir / "jobs.db")

    try:
        llm = get_provider(
            config.llm_provider,
            api_key=config.llm_api_key,
            model=config.llm_model,
        )
    except Exception as e:
        console.print(f"[red]LLM required for evaluation but not available: {e}[/]")
        db.close()
        return

    profile = config.profile

    console.print(f"[bold]Evaluating jobs (min_score={min_score})...[/]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        prog_task = None

        def on_progress(done, total):
            nonlocal prog_task
            if prog_task is None:
                prog_task = progress.add_task("Evaluating", total=total)
            progress.update(prog_task, completed=done)

        evaluated, total = asyncio.run(
            run_evaluation(
                db,
                profile,
                llm,
                min_score=min_score,
                job_url=job_url,
                on_progress=on_progress,
            )
        )

    db.close()
    console.print(f"\n[green bold]Evaluated {evaluated}/{total} jobs[/]")


@cli.group()
def stories():
    """Manage interview story bank."""
    pass


@stories.command("list")
@click.pass_context
def stories_list(ctx):
    """List all stories grouped by theme."""
    from job_hunter.database import StoryBankDB

    data_dir = ctx.obj["data_dir"]
    db_path = data_dir / "jobs.db"
    if not db_path.exists():
        console.print("[yellow]No database found. Run 'hunt discover' first.[/]")
        return

    sdb = StoryBankDB(db_path)
    all_stories = sdb.get_stories()
    sdb.close()

    if not all_stories:
        console.print("[yellow]No stories in the bank yet. Use 'hunt stories add' to create one.[/]")
        return

    # Group by theme
    themes: dict[str, list[dict]] = {}
    for s in all_stories:
        theme = s.get("theme") or "Uncategorized"
        themes.setdefault(theme, []).append(s)

    for theme, group in sorted(themes.items()):
        table = Table(title=f"Theme: {theme}", show_lines=True)
        table.add_column("ID", style="dim", width=4)
        table.add_column("Title", style="cyan", max_width=30)
        table.add_column("Situation", max_width=40)
        table.add_column("Result", max_width=40)
        table.add_column("Best For", style="green", max_width=25)

        for s in group:
            table.add_row(
                str(s.get("id", "")),
                s.get("title", ""),
                (s.get("situation") or "")[:80],
                (s.get("result") or "")[:80],
                s.get("best_for") or "",
            )
        console.print(table)
        console.print()


@stories.command("search")
@click.argument("query")
@click.pass_context
def stories_search(ctx, query):
    """Search stories by keyword."""
    from job_hunter.database import StoryBankDB

    data_dir = ctx.obj["data_dir"]
    db_path = data_dir / "jobs.db"
    if not db_path.exists():
        console.print("[yellow]No database found.[/]")
        return

    sdb = StoryBankDB(db_path)
    results = sdb.search_stories(query)
    sdb.close()

    if not results:
        console.print(f"[yellow]No stories matching '{query}'.[/]")
        return

    table = Table(title=f"Stories matching: {query}", show_lines=True)
    table.add_column("ID", style="dim", width=4)
    table.add_column("Title", style="cyan", max_width=30)
    table.add_column("Theme", style="magenta", max_width=15)
    table.add_column("Situation", max_width=40)
    table.add_column("Action", max_width=40)
    table.add_column("Result", max_width=40)
    table.add_column("Best For", style="green", max_width=25)

    for s in results:
        table.add_row(
            str(s.get("id", "")),
            s.get("title", ""),
            s.get("theme") or "",
            (s.get("situation") or "")[:80],
            (s.get("action") or "")[:80],
            (s.get("result") or "")[:80],
            s.get("best_for") or "",
        )

    console.print(table)


@stories.command("add")
@click.option("--title", required=True, help="Story title")
@click.option("--theme", required=True, help="Story theme (e.g., leadership, conflict)")
@click.option("--situation", required=True, help="STAR: Situation")
@click.option("--task", required=True, help="STAR: Task")
@click.option("--action", required=True, help="STAR: Action")
@click.option("--result", required=True, help="STAR: Result")
@click.option("--reflection", default=None, help="STAR+R: Reflection / lesson learned")
@click.option("--tags", default=None, help="Comma-separated tags")
@click.option("--best-for", default=None, help="Best for which interview questions")
@click.pass_context
def stories_add(ctx, title, theme, situation, task, action, result, reflection, tags, best_for):
    """Manually add a STAR+R story to the bank."""
    from job_hunter.database import StoryBankDB

    data_dir = ctx.obj["data_dir"]
    data_dir.mkdir(parents=True, exist_ok=True)

    sdb = StoryBankDB(data_dir / "jobs.db")

    story = {
        "title": title,
        "theme": theme,
        "situation": situation,
        "task": task,
        "action": action,
        "result": result,
        "reflection": reflection,
        "tags": tags,
        "best_for": best_for,
    }
    story_id = sdb.add_story(story)
    sdb.close()

    console.print(f"[green bold]Story added (id={story_id}): {title}[/]")


@cli.command()
@click.option("--job-url", required=True, help="Job URL to generate outreach for")
@click.pass_context
def outreach(ctx, job_url):
    """Generate LinkedIn/email outreach messages for a job."""

    from job_hunter.config import load_config
    from job_hunter.database import JobDB
    from job_hunter.llm.base import get_provider

    try:
        from job_hunter.outreach.generator import run_outreach
    except ImportError:
        console.print("[red]Outreach module not available.[/]")
        raise SystemExit(1)

    config = load_config(ctx.obj["config_dir"])
    data_dir = ctx.obj["data_dir"]
    db = JobDB(data_dir / "jobs.db")

    job = db.get_job(job_url)
    if not job:
        console.print(f"[red]Job not found: {job_url}[/]")
        db.close()
        return

    try:
        llm = get_provider(
            config.llm_provider,
            api_key=config.llm_api_key,
            model=config.llm_model,
        )
    except Exception as e:
        console.print(f"[red]LLM required for outreach but not available: {e}[/]")
        db.close()
        return

    profile = config.profile

    console.print(f"[bold]Generating outreach for {job.title} @ {job.company}...[/]")

    result = asyncio.run(run_outreach(db, profile, llm, job_url))
    db.close()

    targets = result.get("targets", [])
    if not targets:
        console.print("[yellow]No outreach targets generated.[/]")
        if result.get("error"):
            console.print(f"[red]{result['error']}[/]")
        return

    for target in targets:
        role = target.get("role", "Unknown Role")
        for i, variant in enumerate(target.get("messages", []), 1):
            channel = variant.get("channel", "linkedin")
            body = variant.get("body", "")
            char_count = len(body)
            title = f"{role} — {channel} (variant {i}, {char_count} chars)"
            console.print(Panel(body, title=title, border_style="cyan"))
            console.print()

    console.print(f"[green bold]Generated outreach for {len(targets)} target(s)[/]")


@cli.command()
@click.option("--min-score", default=5, type=int, help="Minimum score for comparison")
@click.option("--limit", default=10, type=int, help="Max jobs to compare")
@click.pass_context
def compare(ctx, min_score, limit):
    """Compare top jobs across 10 weighted dimensions."""
    from job_hunter.config import load_config
    from job_hunter.database import JobDB
    from job_hunter.llm.base import get_provider

    try:
        from job_hunter.evaluate.compare import compare_jobs, DIMENSIONS
    except ImportError:
        console.print("[red]Evaluate module not available.[/]")
        raise SystemExit(1)

    config = load_config(ctx.obj["config_dir"])
    data_dir = ctx.obj["data_dir"]
    db = JobDB(data_dir / "jobs.db")

    jobs = db.get_jobs_for_comparison(min_score=min_score, limit=limit)
    if not jobs:
        console.print("[yellow]No evaluated jobs found for comparison.[/]")
        db.close()
        return

    try:
        llm = get_provider(
            config.llm_provider,
            api_key=config.llm_api_key,
            model=config.llm_model,
        )
    except Exception as e:
        console.print(f"[red]LLM required for comparison but not available: {e}[/]")
        db.close()
        return

    profile = config.profile

    console.print(f"[bold]Comparing {len(jobs)} jobs across {len(DIMENSIONS)} dimensions...[/]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        prog_task = progress.add_task("Comparing", total=len(jobs))

        results = asyncio.run(compare_jobs(jobs, profile, llm))
        progress.update(prog_task, completed=len(jobs))

    db.close()

    if not results:
        console.print("[yellow]No comparison results generated.[/]")
        return

    # Short labels for dimensions
    dim_labels = {
        "north_star_alignment": "N.Star",
        "cv_match": "CV",
        "seniority_level": "Level",
        "estimated_comp": "Comp",
        "growth_trajectory": "Growth",
        "remote_quality": "Remote",
        "company_reputation": "Rep",
        "tech_stack_modernity": "Tech",
        "speed_to_offer": "Speed",
        "cultural_signals": "Culture",
    }

    table = Table(title="Job Comparison Matrix", show_lines=True)
    table.add_column("#", style="bold", width=3)
    table.add_column("Company", style="cyan", max_width=20)
    table.add_column("Title", max_width=25)
    for dim_name in DIMENSIONS:
        label = dim_labels.get(dim_name, dim_name[:6])
        weight = DIMENSIONS[dim_name]["weight"]
        table.add_column(f"{label}\n({weight:.0%})", justify="center", width=8)
    table.add_column("Total", style="bold green", justify="right", width=7)

    for r in results:
        scores = r.get("scores", {})
        row = [
            str(r.get("rank", "")),
            r.get("company", "")[:20],
            r.get("title", "")[:25],
        ]
        for dim_name in DIMENSIONS:
            s = scores.get(dim_name, 0)
            color = "green" if s >= 4 else ("yellow" if s == 3 else "red")
            row.append(f"[{color}]{s}[/]")
        row.append(f"{r.get('weighted_total', 0):.2f}")
        table.add_row(*row)

    console.print(table)

    # Print notes
    notes_with_content = [
        r for r in results if r.get("notes") and "Scoring failed" not in r.get("notes", "")
    ]
    if notes_with_content:
        console.print("\n[bold]Notes:[/]")
        for r in notes_with_content:
            console.print(f"  [cyan]#{r['rank']} {r['company']}:[/] {r['notes']}")


@cli.command("evaluate-project")
@click.argument("idea")
@click.pass_context
def evaluate_project(ctx, idea):
    """Score a side-project idea for job-search signal value."""
    import json as _json

    from job_hunter.config import load_config
    from job_hunter.llm.base import get_provider

    config = load_config(ctx.obj["config_dir"])

    try:
        llm = get_provider(
            config.llm_provider,
            api_key=config.llm_api_key,
            model=config.llm_model,
        )
    except Exception as e:
        console.print(f"[red]LLM required but not available: {e}[/]")
        return

    profile = config.profile
    profile_summary = _json.dumps(
        {k: v for k, v in profile.items() if k in ("target_roles", "skills", "experience_years")},
        indent=2,
    )

    prompt = f"""You are a career strategist. Evaluate this side-project idea for a job seeker.

## Candidate Profile
{profile_summary}

## Project Idea
{idea}

Score on 6 dimensions (1-5 each):
1. signal — How strongly does this project signal competence to hiring managers?
2. uniqueness — How differentiated is this from typical portfolio projects?
3. demo_ability — How easy is it to demo in an interview or share a link?
4. metrics_potential — Can the candidate generate quantifiable results/metrics?
5. time_to_mvp — How quickly can an MVP be built? (5 = under 1 week, 1 = over 2 months)
6. star_story_potential — How well does building this lend itself to STAR interview stories?

Then give a verdict: BUILD, SKIP, or PIVOT (with reason).
If BUILD: provide 4 weekly milestones and an interview_pack (2-3 talking points).

Respond in JSON:
{{
  "scores": {{"signal": N, "uniqueness": N, "demo_ability": N, "metrics_potential": N, "time_to_mvp": N, "star_story_potential": N}},
  "verdict": "BUILD|SKIP|PIVOT",
  "reason": "...",
  "milestones": ["Week 1: ...", "Week 2: ...", "Week 3: ...", "Week 4: ..."],
  "interview_pack": ["talking point 1", "talking point 2"]
}}"""

    console.print(f"[bold]Evaluating project idea: {idea}[/]\n")

    try:
        response = asyncio.run(llm.generate(prompt, json_mode=True, max_tokens=1024))
        result = _json.loads(response)
    except Exception as e:
        console.print(f"[red]Evaluation failed: {e}[/]")
        return

    # Display scores
    scores = result.get("scores", {})
    dim_names = ["signal", "uniqueness", "demo_ability", "metrics_potential", "time_to_mvp", "star_story_potential"]

    table = Table(title="Project Evaluation", show_lines=True)
    table.add_column("Dimension", style="cyan")
    table.add_column("Score", justify="center", width=7)

    for dim in dim_names:
        s = scores.get(dim, 0)
        color = "green" if s >= 4 else ("yellow" if s == 3 else "red")
        table.add_row(dim.replace("_", " ").title(), f"[{color}]{s}/5[/]")

    console.print(table)

    # Verdict
    verdict = result.get("verdict", "UNKNOWN")
    verdict_color = {"BUILD": "green", "SKIP": "red", "PIVOT": "yellow"}.get(verdict, "white")
    console.print(f"\n[bold {verdict_color}]Verdict: {verdict}[/]")
    console.print(f"[dim]{result.get('reason', '')}[/]")

    # Milestones (if BUILD)
    milestones = result.get("milestones", [])
    if milestones:
        console.print("\n[bold]Weekly Milestones:[/]")
        for m in milestones:
            console.print(f"  {m}")

    # Interview pack
    interview_pack = result.get("interview_pack", [])
    if interview_pack:
        console.print("\n[bold]Interview Talking Points:[/]")
        for tp in interview_pack:
            console.print(f"  - {tp}")


@cli.command("evaluate-training")
@click.argument("course")
@click.pass_context
def evaluate_training(ctx, course):
    """Evaluate whether a course/certification is worth the time investment."""
    import json as _json

    from job_hunter.config import load_config
    from job_hunter.llm.base import get_provider

    config = load_config(ctx.obj["config_dir"])

    try:
        llm = get_provider(
            config.llm_provider,
            api_key=config.llm_api_key,
            model=config.llm_model,
        )
    except Exception as e:
        console.print(f"[red]LLM required but not available: {e}[/]")
        return

    profile = config.profile
    profile_summary = _json.dumps(
        {k: v for k, v in profile.items() if k in ("target_roles", "skills", "experience_years")},
        indent=2,
    )

    prompt = f"""You are a career strategist. Evaluate this course/certification for a job seeker.

## Candidate Profile
{profile_summary}

## Course / Certification
{course}

Score on 6 dimensions (1-5 each):
1. north_star — How well does this align with the candidate's long-term career goals?
2. recruiter_signal — How much does this credential catch a recruiter's eye on a resume?
3. time_investment — Is the time investment reasonable? (5 = quick win, 1 = massive time sink)
4. opportunity_cost — What is the candidate giving up? (5 = low cost, 1 = high cost)
5. risks — Are there risks like the cert becoming obsolete? (5 = low risk, 1 = high risk)
6. portfolio_deliverable — Does the course produce a tangible portfolio piece? (5 = strong deliverable)

Then give a verdict: DO, SKIP, or DO_WITH_TIMEBOX (with reason and suggested timebox if applicable).

Respond in JSON:
{{
  "scores": {{"north_star": N, "recruiter_signal": N, "time_investment": N, "opportunity_cost": N, "risks": N, "portfolio_deliverable": N}},
  "verdict": "DO|SKIP|DO_WITH_TIMEBOX",
  "reason": "...",
  "timebox": "e.g., 2 weeks max",
  "alternatives": ["alternative 1", "alternative 2"]
}}"""

    console.print(f"[bold]Evaluating training: {course}[/]\n")

    try:
        response = asyncio.run(llm.generate(prompt, json_mode=True, max_tokens=1024))
        result = _json.loads(response)
    except Exception as e:
        console.print(f"[red]Evaluation failed: {e}[/]")
        return

    # Display scores
    scores = result.get("scores", {})
    dim_names = ["north_star", "recruiter_signal", "time_investment", "opportunity_cost", "risks", "portfolio_deliverable"]

    table = Table(title="Training Evaluation", show_lines=True)
    table.add_column("Dimension", style="cyan")
    table.add_column("Score", justify="center", width=7)

    for dim in dim_names:
        s = scores.get(dim, 0)
        color = "green" if s >= 4 else ("yellow" if s == 3 else "red")
        table.add_row(dim.replace("_", " ").title(), f"[{color}]{s}/5[/]")

    console.print(table)

    # Verdict
    verdict = result.get("verdict", "UNKNOWN")
    verdict_color = {"DO": "green", "SKIP": "red", "DO_WITH_TIMEBOX": "yellow"}.get(verdict, "white")
    console.print(f"\n[bold {verdict_color}]Verdict: {verdict}[/]")
    console.print(f"[dim]{result.get('reason', '')}[/]")

    timebox = result.get("timebox")
    if timebox and verdict == "DO_WITH_TIMEBOX":
        console.print(f"[yellow]Suggested timebox: {timebox}[/]")

    alternatives = result.get("alternatives", [])
    if alternatives:
        console.print("\n[bold]Alternatives to consider:[/]")
        for alt in alternatives:
            console.print(f"  - {alt}")


@cli.command()
@click.option("--job-url", required=True, help="Job URL to generate negotiation scripts for")
@click.pass_context
def negotiate(ctx, job_url):
    """Generate word-for-word negotiation scripts using evaluation data."""
    import json as _json

    from job_hunter.config import load_config
    from job_hunter.database import JobDB
    from job_hunter.llm.base import get_provider

    config = load_config(ctx.obj["config_dir"])
    data_dir = ctx.obj["data_dir"]
    db = JobDB(data_dir / "jobs.db")

    job = db.get_job(job_url)
    if not job:
        console.print(f"[red]Job not found: {job_url}[/]")
        db.close()
        return

    try:
        llm = get_provider(
            config.llm_provider,
            api_key=config.llm_api_key,
            model=config.llm_model,
        )
    except Exception as e:
        console.print(f"[red]LLM required for negotiation but not available: {e}[/]")
        db.close()
        return

    profile = config.profile
    profile_summary = _json.dumps(
        {k: v for k, v in profile.items() if k in ("target_roles", "skills", "experience_years", "target_salary")},
        indent=2,
    )

    # Include evaluation data if available
    eval_context = ""
    if job.evaluation:
        try:
            eval_data = _json.loads(job.evaluation)
            eval_context = f"\n## Evaluation Data\n{_json.dumps(eval_data, indent=2)[:2000]}"
        except _json.JSONDecodeError:
            pass

    prompt = f"""You are a salary negotiation coach. Generate word-for-word negotiation scripts.

## Candidate Profile
{profile_summary}

## Job Details
- Title: {job.title}
- Company: {job.company}
- Location: {job.location or "Not specified"}
- Salary Range: {job.salary_raw or "Not specified"}
- Salary Min: {job.salary_min or "Unknown"}
- Salary Max: {job.salary_max or "Unknown"}
{eval_context}

Generate negotiation scripts for these scenarios:
1. initial_offer — Response when receiving the first offer
2. counter_offer — Script for presenting your counter
3. competing_offer — Leveraging a competing offer
4. benefits_negotiation — Negotiating non-salary benefits (equity, PTO, signing bonus, remote)
5. final_acceptance — Graceful acceptance script

For each script provide the exact words to say/write.

Also include:
- market_data: estimated market range for this role+location
- leverage_points: specific strengths to emphasize
- walk_away_number: the minimum acceptable offer

Respond in JSON:
{{
  "scripts": {{
    "initial_offer": "exact words...",
    "counter_offer": "exact words...",
    "competing_offer": "exact words...",
    "benefits_negotiation": "exact words...",
    "final_acceptance": "exact words..."
  }},
  "market_data": {{"low": N, "mid": N, "high": N, "currency": "USD"}},
  "leverage_points": ["point 1", "point 2"],
  "walk_away_number": N,
  "tips": ["tip 1", "tip 2"]
}}"""

    console.print(f"[bold]Generating negotiation scripts for {job.title} @ {job.company}...[/]")

    try:
        response = asyncio.run(llm.generate(prompt, json_mode=True, max_tokens=2048))
        result = _json.loads(response)
    except Exception as e:
        console.print(f"[red]Negotiation script generation failed: {e}[/]")
        db.close()
        return

    # Store in database
    job.negotiation = _json.dumps(result)
    db.upsert_job(job)
    db.close()

    # Display scripts
    scripts = result.get("scripts", {})
    for scenario, script in scripts.items():
        title = scenario.replace("_", " ").title()
        console.print(Panel(script, title=title, border_style="green"))
        console.print()

    # Market data
    market = result.get("market_data", {})
    if market:
        currency = market.get("currency", "USD")
        console.print("[bold]Market Data:[/]")
        console.print(
            f"  Low: {currency} {market.get('low', 'N/A'):,} | "
            f"Mid: {currency} {market.get('mid', 'N/A'):,} | "
            f"High: {currency} {market.get('high', 'N/A'):,}"
        )

    walk_away = result.get("walk_away_number")
    if walk_away:
        console.print(f"  [bold red]Walk-away number: {market.get('currency', 'USD')} {walk_away:,}[/]")

    # Leverage points
    leverage = result.get("leverage_points", [])
    if leverage:
        console.print("\n[bold]Leverage Points:[/]")
        for lp in leverage:
            console.print(f"  - {lp}")

    # Tips
    tips = result.get("tips", [])
    if tips:
        console.print("\n[bold]Tips:[/]")
        for tip in tips:
            console.print(f"  - {tip}")

    console.print(f"\n[green bold]Negotiation scripts saved for {job.company}[/]")


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

    try:
        from job_hunter.notion.client import NotionJobDB
    except ImportError:
        console.print("[red]Notion sync requires notion-client. Install with:[/]")
        console.print("[yellow]  pip install job-hunter\\[notion][/]")
        raise SystemExit(1)

    token = os.environ.get("NOTION_TOKEN")
    if not token:
        console.print("[red]NOTION_TOKEN not set in environment.[/]")
        raise SystemExit(1)

    notion = NotionJobDB(token=token)
    db_id = notion.init_database(page_id)
    console.print(f"[green]Notion database ready: {db_id}[/]")
    console.print(f"Add to .env: NOTION_DATABASE_ID={db_id}")


@sync.command("push")
@click.option(
    "--drive-creds", type=click.Path(exists=True), default=None, help="Google service account JSON"
)
@click.pass_context
def sync_push(ctx, drive_creds):
    """Push jobs to Notion (and optionally upload PDFs to Drive)."""
    import os
    from job_hunter.database import JobDB

    try:
        from job_hunter.notion.client import NotionJobDB
        from job_hunter.notion.drive_uploader import DriveUploader
        from job_hunter.notion.sync import push_jobs_to_notion
    except ImportError:
        console.print("[red]Notion sync requires notion-client. Install with:[/]")
        console.print("[yellow]  pip install job-hunter\\[notion][/]")
        raise SystemExit(1)

    token = os.environ.get("NOTION_TOKEN")
    db_id = os.environ.get("NOTION_DATABASE_ID")
    if not token or not db_id:
        console.print("[red]Set NOTION_TOKEN and NOTION_DATABASE_ID in .env[/]")
        raise SystemExit(1)

    data_dir = ctx.obj["data_dir"]
    db = JobDB(data_dir / "jobs.db")
    notion = NotionJobDB(token=token, database_id=db_id)

    drive = None
    if drive_creds:
        drive = DriveUploader(credentials_path=drive_creds)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
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

    try:
        from job_hunter.notion.client import NotionJobDB
        from job_hunter.notion.sync import pull_status_from_notion
    except ImportError:
        console.print("[red]Notion sync requires notion-client. Install with:[/]")
        console.print("[yellow]  pip install job-hunter\\[notion][/]")
        raise SystemExit(1)

    token = os.environ.get("NOTION_TOKEN")
    db_id = os.environ.get("NOTION_DATABASE_ID")
    if not token or not db_id:
        console.print("[red]Set NOTION_TOKEN and NOTION_DATABASE_ID in .env[/]")
        raise SystemExit(1)

    data_dir = ctx.obj["data_dir"]
    db = JobDB(data_dir / "jobs.db")
    notion = NotionJobDB(token=token, database_id=db_id)

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
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
@click.option(
    "--login", "login_domain", default=None, help="Open browser to save login session for a domain"
)
@click.option("--dry-run", is_flag=True, help="Fill forms without submitting")
@click.option("--confirm", is_flag=True, help="Actually submit applications (required for real apply)")
@click.pass_context
def apply_cmd(ctx, job_url, apply_all, limit, login_domain, dry_run, confirm):
    """Apply to jobs using browser automation."""
    import json as _json
    import time

    try:
        from job_hunter.apply.applicant import Applicant
        from job_hunter.apply.strategies.base import detect_platform
    except ImportError:
        console.print("[red]Auto-apply requires playwright. Install with:[/]")
        console.print("[yellow]  pip install job-hunter\\[apply][/]")
        raise SystemExit(1)

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
        llm = get_provider(config.llm_provider, api_key=config.llm_api_key, model=config.llm_model)
    except Exception:
        pass

    data_dir = ctx.obj["data_dir"]

    applicant = Applicant(
        profile=profile,
        session_dir=data_dir / "sessions",
        llm=llm,
        log_path=data_dir / "output" / "apply_log.json",
        dry_run=dry_run,
        confirm_submit=confirm,
    )

    # Login mode
    if login_domain:
        console.print(f"[bold]Opening browser for {login_domain} — log in then close the window[/]")
        asyncio.run(applicant.login_and_save(login_domain))
        console.print(f"[green]Session saved for {login_domain}[/]")
        return

    from job_hunter.database import JobDB

    db = JobDB(data_dir / "jobs.db")

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
@click.option("--skip-evaluate", is_flag=True, help="Skip evaluate stage")
@click.option("--dry-run", is_flag=True, help="Dry-run apply (no submit)")
@click.option("--confirm", is_flag=True, help="Actually submit applications (required for real apply)")
@click.pass_context
def run_cmd(ctx, run_apply, skip_discover, skip_evaluate, dry_run, confirm):
    """Run the full pipeline: discover -> enrich -> score -> evaluate -> tailor -> sync."""
    from job_hunter.pipeline import run_pipeline

    config_dir = ctx.obj["config_dir"]
    data_dir = ctx.obj["data_dir"]

    console.print("[bold]Starting pipeline run...[/]\n")

    summary = run_pipeline(
        config_dir,
        skip_discover=skip_discover,
        skip_evaluate=skip_evaluate,
        run_apply=run_apply,
        dry_run=dry_run,
        confirm_submit=confirm,
        data_dir=data_dir,
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


@cli.group()
def research():
    """Deep autoresearch on scored jobs."""
    pass


@research.command("run")
@click.option("--min-score", default=5, type=int, help="Minimum job score to research")
@click.option("--max-jobs", default=50, type=int, help="Maximum jobs to research")
@click.pass_context
def research_run(ctx, min_score, max_jobs):
    """Single-pass deep research on high-value jobs."""
    from job_hunter.config import load_config
    from job_hunter.database import JobDB
    from job_hunter.autoresearch.deep_research import run_deep_research
    from job_hunter.llm.base import get_provider

    config = load_config(ctx.obj["config_dir"])
    data_dir = ctx.obj["data_dir"]
    db = JobDB(data_dir / "jobs.db")

    try:
        llm = get_provider(
            config.llm_provider,
            api_key=config.gemini_api_key,
            model=config.llm_model,
        )
    except Exception as e:
        console.print(f"[red]LLM required for deep research but not available: {e}[/]")
        db.close()
        return

    profile = config.profile

    console.print(f"[bold]Deep research: min_score={min_score}, max_jobs={max_jobs}[/]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        prog_task = None

        def on_progress(done, total):
            nonlocal prog_task
            if prog_task is None:
                prog_task = progress.add_task("Deep research", total=total)
            progress.update(prog_task, completed=done)

        results = asyncio.run(
            run_deep_research(
                db,
                profile,
                llm,
                min_score=min_score,
                max_jobs=max_jobs,
                on_progress=on_progress,
            )
        )

    db.close()

    console.print(
        f"\n[green bold]Deep Research: {results['total_researched']} jobs researched, "
        f"{results['scores_changed']} scores changed, "
        f"{results['resumes_flagged']} resumes flagged, "
        f"{results['total_time_seconds']:.0f}s total[/]"
    )


@research.command("loop")
@click.option("--min-score", default=5, type=int, help="Minimum job score to research")
@click.option("--max-jobs", default=50, type=int, help="Maximum jobs per iteration")
@click.pass_context
def research_loop(ctx, min_score, max_jobs):
    """Never-stop loop -- re-researches low confidence until Ctrl+C."""
    from job_hunter.config import load_config
    from job_hunter.database import JobDB
    from job_hunter.autoresearch.deep_research import run_deep_research_loop
    from job_hunter.llm.base import get_provider

    config = load_config(ctx.obj["config_dir"])
    data_dir = ctx.obj["data_dir"]
    db = JobDB(data_dir / "jobs.db")

    try:
        llm = get_provider(
            config.llm_provider,
            api_key=config.gemini_api_key,
            model=config.llm_model,
        )
    except Exception as e:
        console.print(f"[red]LLM required for deep research but not available: {e}[/]")
        db.close()
        return

    profile = config.profile

    console.print(f"[bold]Deep research loop: min_score={min_score}, max_jobs={max_jobs}[/]")
    console.print("[dim]Runs until Ctrl+C. Re-researches LOW confidence jobs each iteration.[/]")

    with Progress(
        SpinnerColumn(),
        TextColumn("[progress.description]{task.description}"),
        BarColumn(),
        TextColumn("{task.completed}/{task.total}"),
        TimeElapsedColumn(),
        console=console,
    ) as progress:
        prog_task = None

        def on_progress(done, total):
            nonlocal prog_task
            if prog_task is None:
                prog_task = progress.add_task("Deep research", total=total)
            progress.update(prog_task, completed=done)

        def on_iteration_complete(iteration, iter_results):
            console.print(
                f"\n[bold cyan]Iteration {iteration} complete: "
                f"{iter_results['total_researched']} researched, "
                f"kept={iter_results.get('kept', 0)}, "
                f"discarded={iter_results.get('discarded', 0)}[/]"
            )

        results = asyncio.run(
            run_deep_research_loop(
                db,
                profile,
                llm,
                min_score=min_score,
                max_jobs=max_jobs,
                on_progress=on_progress,
                on_iteration_complete=on_iteration_complete,
            )
        )

    db.close()

    console.print(
        f"\n[green bold]Deep Research Loop: {results.get('iterations', 0)} iterations, "
        f"{results['total_researched']} total researched, "
        f"kept={results.get('total_kept', 0)}, "
        f"discarded={results.get('total_discarded', 0)}, "
        f"{results['total_time_seconds']:.0f}s total[/]"
    )
