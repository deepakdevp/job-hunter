from __future__ import annotations

import logging

import pandas as pd
from jobspy import scrape_jobs

from job_hunter.database import Job

logger = logging.getLogger(__name__)


def run_jobspy_search(
    query: str,
    location: str,
    boards: list[str],
    max_results: int = 100,
    distance_km: int | None = None,
    remote_only: bool = False,
) -> pd.DataFrame:
    kwargs: dict = {
        "site_name": boards,
        "search_term": query,
        "location": location,
        "results_wanted": max_results,
    }
    loc_lower = location.lower()
    if "japan" in loc_lower or "tokyo" in loc_lower or "osaka" in loc_lower:
        kwargs["country_indeed"] = "Japan"
    elif "germany" in loc_lower or "berlin" in loc_lower or "munich" in loc_lower:
        kwargs["country_indeed"] = "Germany"
    elif "netherlands" in loc_lower or "amsterdam" in loc_lower:
        kwargs["country_indeed"] = "Netherlands"
    elif "uk" in loc_lower or "london" in loc_lower:
        kwargs["country_indeed"] = "UK"

    if distance_km:
        kwargs["distance"] = distance_km
    if remote_only:
        kwargs["is_remote"] = True

    logger.info(f"JobSpy: searching '{query}' in '{location}' on {boards}")
    try:
        results = scrape_jobs(**kwargs)
        logger.info(f"JobSpy: found {len(results)} jobs")
        return results
    except Exception as e:
        logger.error(f"JobSpy search failed: {e}")
        return pd.DataFrame()


def parse_jobspy_results(df: pd.DataFrame) -> list[Job]:
    jobs = []
    for _, row in df.iterrows():
        url = str(row.get("job_url", ""))
        if not url or url == "nan" or url == "None":
            continue

        salary_min = None
        salary_max = None
        salary_raw = None
        if pd.notna(row.get("min_amount")):
            salary_min = int(row["min_amount"])
        if pd.notna(row.get("max_amount")):
            salary_max = int(row["max_amount"])
        if salary_min is not None or salary_max is not None:
            interval = row.get("interval", "")
            parts = []
            if salary_min is not None:
                parts.append(str(salary_min))
            else:
                parts.append("?")
            parts.append("-")
            if salary_max is not None:
                parts.append(str(salary_max))
            else:
                parts.append("?")
            if pd.notna(interval) and interval:
                parts.append(str(interval))
            salary_raw = " ".join(parts)

        jobs.append(
            Job(
                url=url,
                title=str(row.get("title", "Unknown")),
                company=str(row.get("company_name", "Unknown")),
                location=str(row.get("location", "")),
                source=str(row.get("site", "unknown")),
                description=str(row["description"]) if pd.notna(row.get("description")) else None,
                posted_date=str(row["date_posted"]) if pd.notna(row.get("date_posted")) else None,
                salary_min=salary_min,
                salary_max=salary_max,
                salary_raw=salary_raw,
            )
        )
    return jobs
