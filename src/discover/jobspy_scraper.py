"""python-jobspy wrapper for Western job boards."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from rich.console import Console

console = Console()

PLATFORM_MAP = {
    "linkedin": "linkedin",
    "indeed": "indeed",
    "glassdoor": "glassdoor",
    "google": "google",
    "ziprecruiter": "zip_recruiter",
}


def _normalize_job(row: Any, source: str) -> dict:
    """Convert a jobspy DataFrame row to our standard job dict."""
    # jobspy returns a pandas DataFrame; each row is a namedtuple/dict-like
    def _get(field: str, default: Any = "") -> Any:
        try:
            v = getattr(row, field, None)
            if v is None or (hasattr(v, "__class__") and v.__class__.__name__ == "NAType"):
                return default
            return v
        except Exception:
            return default

    salary = ""
    min_s = _get("min_amount")
    max_s = _get("max_amount")
    interval = _get("interval", "year")
    currency = _get("currency", "USD")
    if min_s or max_s:
        salary = f"{currency} {min_s or '?'}-{max_s or '?'}/{interval}"

    date_posted = None
    dp = _get("date_posted")
    if dp:
        try:
            if hasattr(dp, "isoformat"):
                date_posted = dp.isoformat()
            else:
                date_posted = str(dp)
        except Exception:
            pass

    return {
        "title": str(_get("title", "Unknown")),
        "company": str(_get("company", "")),
        "location": str(_get("location", "")),
        "job_url": str(_get("job_url", "")),
        "apply_url": str(_get("job_url_direct", _get("job_url", ""))),
        "description": str(_get("description", "")),
        "salary": salary,
        "date_posted": date_posted,
        "date_found": datetime.now(timezone.utc).isoformat(),
        "source": source.capitalize(),
        "status": "New",
        "score": None,
        "notes": "",
        "tags": [],
    }


def scrape_platform(
    platform: str,
    search_term: str,
    location: str = "remote",
    results_wanted: int = 50,
    hours_old: int = 24,
    country: str = "USA",
) -> list[dict]:
    """
    Scrape a single platform via python-jobspy.
    Returns list of normalized job dicts.
    """
    try:
        from jobspy import scrape_jobs
    except ImportError:
        console.print(
            "[yellow]Warning: python-jobspy not installed. "
            "Run: pip install 'python-jobspy==1.1.82' --no-deps[/yellow]"
        )
        return []

    site_name = PLATFORM_MAP.get(platform.lower())
    if not site_name:
        console.print(f"[red]Unknown platform: {platform}[/red]")
        return []

    try:
        df = scrape_jobs(
            site_name=[site_name],
            search_term=search_term,
            location=location,
            results_wanted=results_wanted,
            hours_old=hours_old,
            country_indeed=country,
        )
        if df is None or len(df) == 0:
            return []

        jobs = [_normalize_job(row, platform) for _, row in df.iterrows()]
        return [j for j in jobs if j["job_url"]]  # filter blank URLs
    except Exception as exc:
        console.print(f"[red]Error scraping {platform}: {exc}[/red]")
        return []


def scrape_all(
    platforms: list[str],
    queries: list[dict],
    results_per_query: int = 50,
    hours_old: int = 24,
) -> list[dict]:
    """
    Run all queries across all platforms.
    queries: list of {search_term, location, country}
    """
    all_jobs: list[dict] = []
    for query in queries:
        search_term = query.get("search_term", "")
        location = query.get("location", "remote")
        country = query.get("country", "USA")

        for platform in platforms:
            if platform.lower() in ("gaijinpot", "daijob", "jrec-in"):
                continue  # Handled by japan_scraper

            console.print(f"  Scraping [cyan]{platform}[/cyan] for '[bold]{search_term}[/bold]' in {location}...")
            jobs = scrape_platform(
                platform=platform,
                search_term=search_term,
                location=location,
                results_wanted=results_per_query,
                hours_old=hours_old,
                country=country,
            )
            all_jobs.extend(jobs)
            console.print(f"    → {len(jobs)} jobs found")

    return all_jobs
