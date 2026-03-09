from __future__ import annotations

import logging
from urllib.parse import quote_plus

import httpx

from job_hunter.database import Job

logger = logging.getLogger(__name__)


async def scrape_workday_employer(
    employer: dict,
    query: str = "",
    max_results: int = 50,
) -> list[Job]:
    """Scrape a single Workday employer portal using their JSON API."""
    name = employer.get("name", "Unknown")
    base_url = employer.get("base_url", "")
    site_id = employer.get("site_id", "")

    if not base_url or not site_id:
        logger.warning(f"Workday: skipping {name} — missing base_url or site_id")
        return []

    api_url = f"{base_url}/wday/cxs/{employer.get('tenant', '')}/{site_id}/jobs"

    payload = {
        "appliedFacets": {},
        "limit": min(max_results, 20),
        "offset": 0,
        "searchText": query,
    }

    jobs = []
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            response = await client.post(
                api_url,
                json=payload,
                headers={
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
            )
            response.raise_for_status()
            data = response.json()

            job_postings = data.get("jobPostings", [])
            for posting in job_postings[:max_results]:
                title = posting.get("title", "Unknown")
                external_path = posting.get("externalPath", "")
                loc = posting.get("locationsText", "")
                posted = posting.get("postedOn", "")

                if external_path:
                    job_url = f"{base_url}/en-US{external_path}"
                else:
                    continue

                jobs.append(
                    Job(
                        url=job_url,
                        title=title,
                        company=name,
                        location=loc or "Unknown",
                        source="workday",
                        posted_date=posted if posted else None,
                    )
                )

        logger.info(f"Workday ({name}): found {len(jobs)} jobs")
    except Exception as e:
        logger.warning(f"Workday ({name}): failed — {e}")

    return jobs


async def run_workday_scrapers(
    employers: list[dict],
    query: str = "",
    max_results_per_employer: int = 20,
) -> list[Job]:
    """Scrape all Workday employers from the registry."""
    all_jobs = []
    for employer in employers:
        jobs = await scrape_workday_employer(employer, query, max_results_per_employer)
        all_jobs.extend(jobs)
    return all_jobs
