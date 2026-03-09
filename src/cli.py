"""Job Hunter CLI — hunt command group."""

from __future__ import annotations

import json
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

console = Console()

ROOT = Path(__file__).parent.parent
CONFIG_DIR = ROOT / "config"
OUTPUT_DIR = ROOT / "output"
SEEN_FILE = ROOT / ".seen_jobs"


def _load_config():
    from src.config import AppConfig
    return AppConfig.load()


def _get_llm(cfg):
    from src.llm.factory import create_llm
    return create_llm(
        provider=cfg.llm_provider,
        model=cfg.llm_model,
        gemini_key=cfg.gemini_api_key,
        anthropic_key=cfg.anthropic_api_key,
    )


def _get_notion(cfg):
    from src.notion.client import NotionClient
    return NotionClient(cfg.notion_token)


@click.group()
def cli():
    """Job Hunter — AI-powered job search and application pipeline."""


# ──────────────────────────────────────────────
# hunt init
# ──────────────────────────────────────────────

@cli.command()
def init():
    """Setup wizard: create profile, config files, and verify API keys."""
    console.print("[bold green]Job Hunter — Setup Wizard[/bold green]\n")

    CONFIG_DIR.mkdir(exist_ok=True)
    OUTPUT_DIR.mkdir(exist_ok=True)
    (OUTPUT_DIR / "resumes").mkdir(exist_ok=True)
    (OUTPUT_DIR / "cover_letters").mkdir(exist_ok=True)

    env_path = ROOT / ".env"
    if not env_path.exists():
        notion_token = click.prompt("Notion Integration Token (secret_...)")
        notion_db_id = click.prompt("Notion Database ID (or leave blank to create one)", default="")
        gemini_key = click.prompt("Gemini API Key (or leave blank)", default="")
        anthropic_key = click.prompt("Anthropic API Key (or leave blank)", default="")

        env_path.write_text(
            f"NOTION_TOKEN={notion_token}\n"
            f"NOTION_DATABASE_ID={notion_db_id}\n"
            f"GEMINI_API_KEY={gemini_key}\n"
            f"ANTHROPIC_API_KEY={anthropic_key}\n"
            f"LLM_PROVIDER={'gemini' if gemini_key else 'claude'}\n"
            f"LLM_MODEL={'gemini-2.0-flash' if gemini_key else 'claude-sonnet-4-6'}\n"
        )
        console.print(f"[green]✓[/green] Created {env_path}")

    profile_path = CONFIG_DIR / "profile.json"
    if not profile_path.exists():
        import shutil
        template = CONFIG_DIR / "profile.example.json"
        if template.exists():
            shutil.copy(template, profile_path)
            console.print(f"[green]✓[/green] Copied profile template to {profile_path}")
            console.print("[yellow]Edit config/profile.json with your details before running hunt.[/yellow]")
        else:
            console.print(f"[red]Profile template not found. Copy config/profile.example.json manually.[/red]")

    searches_path = CONFIG_DIR / "searches.yaml"
    if not searches_path.exists():
        template = CONFIG_DIR / "searches.example.yaml"
        if template.exists():
            import shutil
            shutil.copy(template, searches_path)
            console.print(f"[green]✓[/green] Copied searches template to {searches_path}")
        else:
            console.print("[yellow]Create config/searches.yaml from the example.[/yellow]")

    console.print("\n[bold green]Setup complete![/bold green]")
    console.print("Next: Edit [bold]config/profile.json[/bold] and [bold]config/searches.yaml[/bold]")
    console.print("Then run: [bold]hunt run[/bold]")


# ──────────────────────────────────────────────
# hunt discover
# ──────────────────────────────────────────────

@cli.command()
@click.option("--no-dedup", is_flag=True, help="Skip deduplication (re-discover seen jobs)")
def discover(no_dedup):
    """Scrape all configured job platforms."""
    cfg = _load_config()
    searches = cfg.searches

    from src.discover.jobspy_scraper import scrape_all
    from src.discover.japan_scraper import scrape_japan_platforms
    from src.discover.dedup import SeenSet

    console.print(f"[bold]Discovering jobs from {len(searches.platforms)} platforms...[/bold]\n")

    jobs = scrape_all(
        platforms=searches.platforms,
        queries=searches.queries,
        results_per_query=searches.results_per_query,
        hours_old=searches.hours_old,
    )

    jp_jobs = scrape_japan_platforms(searches.queries, searches.platforms)
    jobs.extend(jp_jobs)

    console.print(f"\n[bold]Total discovered:[/bold] {len(jobs)} jobs")

    if not no_dedup:
        seen = SeenSet(SEEN_FILE)
        before = len(jobs)
        jobs = seen.dedup(jobs)
        console.print(f"[bold]After dedup:[/bold] {len(jobs)} new jobs ({before - len(jobs)} already seen)")

    # Save to cache for next pipeline step
    cache = ROOT / ".jobs_cache.json"
    cache.write_text(json.dumps(jobs, indent=2, default=str))
    console.print(f"\n[green]✓[/green] Saved {len(jobs)} jobs to cache")
    return jobs


# ──────────────────────────────────────────────
# hunt enrich
# ──────────────────────────────────────────────

@cli.command()
def enrich():
    """Fetch full job descriptions for cached jobs."""
    cache = ROOT / ".jobs_cache.json"
    if not cache.exists():
        console.print("[red]No cached jobs. Run `hunt discover` first.[/red]")
        sys.exit(1)

    jobs = json.loads(cache.read_text())
    needs = [j for j in jobs if not j.get("description")]
    console.print(f"[bold]Enriching {len(needs)}/{len(jobs)} jobs with full descriptions...[/bold]")

    from src.enrich.description import enrich_jobs
    enrich_jobs(jobs, delay=2.0)

    enriched = sum(1 for j in jobs if j.get("description"))
    console.print(f"[green]✓[/green] {enriched} jobs now have full descriptions")
    cache.write_text(json.dumps(jobs, indent=2, default=str))


# ──────────────────────────────────────────────
# hunt score
# ──────────────────────────────────────────────

@cli.command()
@click.option("--threshold", default=None, type=int, help="Score threshold (overrides config)")
def score(threshold):
    """AI score all cached jobs against your profile."""
    cfg = _load_config()
    cache = ROOT / ".jobs_cache.json"
    if not cache.exists():
        console.print("[red]No cached jobs. Run `hunt discover` first.[/red]")
        sys.exit(1)

    jobs = json.loads(cache.read_text())
    llm = _get_llm(cfg)
    thresh = threshold or cfg.searches.score_threshold

    from src.score.scorer import score_jobs
    qualified = score_jobs(llm, jobs, cfg.profile.as_text(), threshold=thresh)

    cache.write_text(json.dumps(jobs, indent=2, default=str))
    console.print(f"\n[green]✓[/green] {len(qualified)} jobs scored >= {thresh}")


# ──────────────────────────────────────────────
# hunt tailor
# ──────────────────────────────────────────────

@cli.command()
@click.argument("job_id", required=False)
@click.option("--all", "tailor_all", is_flag=True, help="Tailor all qualified jobs")
@click.option("--threshold", default=None, type=int)
def tailor(job_id, tailor_all, threshold):
    """Generate tailored resume + cover letter for a job."""
    cfg = _load_config()
    cache = ROOT / ".jobs_cache.json"
    if not cache.exists():
        console.print("[red]No cached jobs. Run `hunt discover` first.[/red]")
        sys.exit(1)

    jobs = json.loads(cache.read_text())
    llm = _get_llm(cfg)
    thresh = threshold or cfg.searches.score_threshold

    import json as _json
    profile_dict = _json.loads((CONFIG_DIR / "profile.json").read_text())

    from src.tailor.resume_tailor import tailor_resume, write_cover_letter
    from src.tailor.renderer import render_resume_pdf, render_cover_letter_pdf

    if job_id:
        targets = [j for j in jobs if j.get("job_url", "").endswith(job_id) or str(j.get("id", "")) == job_id]
        if not targets:
            console.print(f"[red]Job not found: {job_id}[/red]")
            sys.exit(1)
    elif tailor_all:
        targets = [j for j in jobs if (j.get("score") or 0) >= thresh]
        console.print(f"[bold]Tailoring {len(targets)} jobs (score >= {thresh})...[/bold]")
    else:
        console.print("[red]Specify a job ID or use --all[/red]")
        sys.exit(1)

    for job in targets:
        console.print(f"\n[bold]Tailoring:[/bold] {job.get('title')} @ {job.get('company')}")

        tailored = tailor_resume(llm, profile_dict, job)
        if tailored:
            resume_pdf = render_resume_pdf(tailored, job)
            console.print(f"  [green]✓[/green] Resume → {resume_pdf}")
            job["resume_pdf"] = str(resume_pdf)

        cl_text = write_cover_letter(llm, cfg.profile.as_text(), job)
        if cl_text:
            cl_pdf = render_cover_letter_pdf(cl_text, profile_dict, job)
            console.print(f"  [green]✓[/green] Cover letter → {cl_pdf}")
            job["cover_letter_pdf"] = str(cl_pdf)

    cache.write_text(json.dumps(jobs, indent=2, default=str))


# ──────────────────────────────────────────────
# hunt apply
# ──────────────────────────────────────────────

@cli.command()
@click.argument("job_id")
def apply(job_id):
    """Open browser and auto-fill application for a job."""
    cfg = _load_config()
    cache = ROOT / ".jobs_cache.json"
    if not cache.exists():
        console.print("[red]No cached jobs.[/red]")
        sys.exit(1)

    jobs = json.loads(cache.read_text())
    targets = [j for j in jobs if j.get("job_url", "").endswith(job_id) or str(j.get("id", "")) == job_id]
    if not targets:
        console.print(f"[red]Job not found: {job_id}[/red]")
        sys.exit(1)

    job = targets[0]
    resume_pdf = Path(job.get("resume_pdf", ""))
    cl_pdf = Path(job.get("cover_letter_pdf", "")) if job.get("cover_letter_pdf") else None

    if not resume_pdf.exists():
        console.print("[yellow]No tailored resume found. Run `hunt tailor` first.[/yellow]")
        if not click.confirm("Continue with un-tailored application?"):
            sys.exit(0)

    import json as _json
    profile_dict = _json.loads((CONFIG_DIR / "profile.json").read_text())

    from src.apply.applicant import apply_sync
    submitted = apply_sync(job, profile_dict, resume_pdf, cl_pdf)

    if submitted:
        job["status"] = "Applied"
        # Sync to Notion
        notion = _get_notion(cfg)
        from src.notion.sync import upsert_job
        page_id, _ = upsert_job(notion, cfg.notion_database_id, job)
        console.print(f"\n[bold green]✓ Applied![/bold green] Notion updated.")
    else:
        console.print("[yellow]Application not submitted.[/yellow]")

    cache.write_text(json.dumps(jobs, indent=2, default=str))


# ──────────────────────────────────────────────
# hunt status
# ──────────────────────────────────────────────

@cli.command()
def status():
    """Show pipeline stats for cached jobs."""
    cache = ROOT / ".jobs_cache.json"
    if not cache.exists():
        console.print("[yellow]No cached jobs. Run `hunt discover` first.[/yellow]")
        return

    jobs = json.loads(cache.read_text())

    table = Table(title="Job Hunt Pipeline Status")
    table.add_column("Metric", style="bold")
    table.add_column("Count", justify="right")

    total = len(jobs)
    has_desc = sum(1 for j in jobs if j.get("description"))
    has_score = sum(1 for j in jobs if j.get("score") is not None)
    has_resume = sum(1 for j in jobs if j.get("resume_pdf"))
    applied = sum(1 for j in jobs if j.get("status") == "Applied")
    high_score = sum(1 for j in jobs if (j.get("score") or 0) >= 7)

    table.add_row("Total jobs", str(total))
    table.add_row("With full description", str(has_desc))
    table.add_row("Scored", str(has_score))
    table.add_row("Score >= 7", str(high_score))
    table.add_row("Tailored (resume ready)", str(has_resume))
    table.add_row("Applied", str(applied))

    console.print(table)

    if has_score:
        scores = [j["score"] for j in jobs if j.get("score") is not None]
        avg = sum(scores) / len(scores)
        console.print(f"\nAverage score: [bold]{avg:.1f}/10[/bold]")


# ──────────────────────────────────────────────
# hunt sync
# ──────────────────────────────────────────────

@cli.command()
@click.option("--threshold", default=None, type=int)
def sync(threshold):
    """Push cached jobs to Notion database."""
    cfg = _load_config()
    cache = ROOT / ".jobs_cache.json"
    if not cache.exists():
        console.print("[red]No cached jobs.[/red]")
        sys.exit(1)

    jobs = json.loads(cache.read_text())
    thresh = threshold or cfg.searches.score_threshold
    targets = [j for j in jobs if (j.get("score") or 0) >= thresh]

    console.print(f"[bold]Syncing {len(targets)} jobs to Notion...[/bold]")

    notion = _get_notion(cfg)
    from src.notion.sync import upsert_job

    created = updated = 0
    for job in targets:
        try:
            _, is_new = upsert_job(notion, cfg.notion_database_id, job)
            if is_new:
                created += 1
            else:
                updated += 1
        except Exception as exc:
            console.print(f"  [red]Error syncing {job.get('title')}: {exc}[/red]")

    console.print(f"\n[green]✓[/green] Created: {created}, Updated: {updated}")


# ──────────────────────────────────────────────
# hunt run
# ──────────────────────────────────────────────

@cli.command()
@click.option("--daily", is_flag=True, help="Quiet mode for cron jobs")
@click.option("--threshold", default=None, type=int)
def run(daily, threshold):
    """Run the full pipeline: discover → enrich → score → tailor → sync."""
    cfg = _load_config()
    searches = cfg.searches
    thresh = threshold or searches.score_threshold

    if daily:
        console.print("[dim]Job Hunter daily run started[/dim]")
    else:
        console.print("[bold green]Job Hunter — Full Pipeline Run[/bold green]\n")

    # 1. Discover
    console.print("[bold]Step 1/5 — Discover[/bold]")
    from src.discover.jobspy_scraper import scrape_all
    from src.discover.japan_scraper import scrape_japan_platforms
    from src.discover.dedup import SeenSet

    jobs = scrape_all(
        platforms=searches.platforms,
        queries=searches.queries,
        results_per_query=searches.results_per_query,
        hours_old=searches.hours_old,
    )
    jobs.extend(scrape_japan_platforms(searches.queries, searches.platforms))

    seen = SeenSet(SEEN_FILE)
    jobs = seen.dedup(jobs)
    console.print(f"  {len(jobs)} new jobs discovered\n")

    if not jobs:
        console.print("[yellow]No new jobs found.[/yellow]")
        return

    # 2. Enrich
    console.print("[bold]Step 2/5 — Enrich[/bold]")
    from src.enrich.description import enrich_jobs
    enrich_jobs(jobs, delay=2.0)
    console.print(f"  {sum(1 for j in jobs if j.get('description'))} jobs enriched\n")

    # 3. Score
    console.print("[bold]Step 3/5 — Score[/bold]")
    llm = _get_llm(cfg)
    from src.score.scorer import score_jobs
    qualified = score_jobs(llm, jobs, cfg.profile.as_text(), threshold=thresh)
    console.print(f"  {len(qualified)} jobs scored >= {thresh}\n")

    if not qualified:
        console.print("[yellow]No jobs met the score threshold.[/yellow]")
        return

    # 4. Tailor
    console.print(f"[bold]Step 4/5 — Tailor ({len(qualified)} jobs)[/bold]")
    import json as _json
    profile_dict = _json.loads((CONFIG_DIR / "profile.json").read_text())
    from src.tailor.resume_tailor import tailor_resume, write_cover_letter
    from src.tailor.renderer import render_resume_pdf, render_cover_letter_pdf

    for job in qualified:
        console.print(f"  Tailoring: {job.get('title')} @ {job.get('company')}")
        tailored = tailor_resume(llm, profile_dict, job)
        if tailored:
            resume_pdf = render_resume_pdf(tailored, job)
            job["resume_pdf"] = str(resume_pdf)
        cl_text = write_cover_letter(llm, cfg.profile.as_text(), job)
        if cl_text:
            cl_pdf = render_cover_letter_pdf(cl_text, profile_dict, job)
            job["cover_letter_pdf"] = str(cl_pdf)

    console.print()

    # 5. Sync to Notion
    console.print("[bold]Step 5/5 — Sync to Notion[/bold]")
    notion = _get_notion(cfg)
    from src.notion.sync import upsert_job

    created = updated = 0
    for job in qualified:
        try:
            _, is_new = upsert_job(notion, cfg.notion_database_id, job)
            if is_new:
                created += 1
            else:
                updated += 1
        except Exception as exc:
            console.print(f"  [red]Notion sync error: {exc}[/red]")

    console.print(f"  Notion: {created} created, {updated} updated\n")

    # Save cache
    cache = ROOT / ".jobs_cache.json"
    cache.write_text(json.dumps(jobs, indent=2, default=str))

    console.print(f"[bold green]✓ Pipeline complete![/bold green] {len(qualified)} jobs ready in Notion.")


if __name__ == "__main__":
    cli()
