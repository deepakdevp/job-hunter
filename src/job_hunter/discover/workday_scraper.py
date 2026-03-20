from __future__ import annotations

import logging

import httpx

from job_hunter.database import Job

logger = logging.getLogger(__name__)

# Known Japan country ID in Workday (consistent across most employers)
JAPAN_COUNTRY_ID = "8b705da2becf43cfaccc091da0988ab2"


async def _discover_japan_facet(
    client: httpx.AsyncClient,
    api_url: str,
    name: str,
) -> dict[str, list[str]] | None:
    """Auto-discover the correct facet key + value for Japan filtering.

    Queries the employer API with empty facets, inspects the returned facet
    metadata to find the one containing Japan, and returns the appliedFacets
    dict to use.
    """
    try:
        resp = await client.post(
            api_url,
            json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""},
            headers={"Content-Type": "application/json", "Accept": "application/json"},
        )
        resp.raise_for_status()
        data = resp.json()

        for facet in data.get("facets", []):
            # Check top-level facets
            japan_value = _find_japan_in_facet(facet)
            if japan_value:
                return {facet["facetParameter"]: [japan_value]}

            # Check nested facets inside groups (e.g. locationMainGroup)
            for child in facet.get("facets", []):
                japan_value = _find_japan_in_facet(child)
                if japan_value:
                    return {child["facetParameter"]: [japan_value]}

    except Exception as e:
        logger.debug(f"Workday ({name}): facet discovery failed — {e}")

    return None


def _find_japan_in_facet(facet: dict) -> str | None:
    """Search a single facet's values for Japan and return the value ID."""
    for value in facet.get("values", []):
        label = value.get("label", "").lower()
        if label in ("japan", "日本"):
            return value.get("id", "")
    return None


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

    jobs = []
    try:
        async with httpx.AsyncClient(timeout=30) as client:
            # Auto-discover the correct Japan facet for this employer
            facets = {}
            if employer.get("location_filter"):
                discovered = await _discover_japan_facet(client, api_url, name)
                if discovered:
                    facets = discovered
                    logger.debug(f"Workday ({name}): using facets {facets}")
                else:
                    logger.debug(
                        f"Workday ({name}): no Japan facet found, searching without filter"
                    )

            payload = {
                "appliedFacets": facets,
                "limit": min(max_results, 20),
                "offset": 0,
                "searchText": query,
            }

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
