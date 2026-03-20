"""Pipeline 1: Source Research — health-check scrapers and fix broken Workday configs."""

from __future__ import annotations

import logging
from pathlib import Path

import httpx
import yaml

logger = logging.getLogger(__name__)


async def health_check_workday_employer(employer: dict) -> dict:
    """Test a single Workday employer API and return health status."""
    name = employer.get("name", "Unknown")
    base_url = employer.get("base_url", "")
    tenant = employer.get("tenant", "")
    site_id = employer.get("site_id", "")
    api_url = f"{base_url}/wday/cxs/{tenant}/{site_id}/jobs"

    result = {"name": name, "healthy": False, "jobs_found": 0, "error": None}

    try:
        async with httpx.AsyncClient(timeout=15) as client:
            resp = await client.post(
                api_url,
                json={"appliedFacets": {}, "limit": 1, "offset": 0, "searchText": ""},
                headers={"Content-Type": "application/json", "Accept": "application/json"},
            )
            resp.raise_for_status()
            data = resp.json()
            total = data.get("total", 0)
            result["healthy"] = True
            result["jobs_found"] = total
    except Exception as e:
        result["error"] = str(e)[:200]

    return result


async def health_check_japan_scraper(scraper_cls) -> dict:
    """Test a Japan scraper by running a minimal scrape."""
    result = {"name": scraper_cls.name, "healthy": False, "jobs_found": 0, "error": None}
    try:
        scraper = scraper_cls()
        jobs = await scraper.scrape(query="", max_results=3)
        await scraper.close()
        result["healthy"] = len(jobs) > 0
        result["jobs_found"] = len(jobs)
    except Exception as e:
        result["error"] = str(e)[:200]
    return result


async def run_source_research(
    employers_path: Path,
    on_progress=None,
) -> dict:
    """Run health checks on all sources and report status.

    Returns summary dict with healthy/unhealthy counts.
    """
    from job_hunter.discover.japan_scrapers import JAPAN_SCRAPERS

    results = {"workday": [], "japan_scrapers": [], "healthy": 0, "unhealthy": 0}

    # Load employers
    employers_data = yaml.safe_load(employers_path.read_text()) if employers_path.exists() else {}
    employers_raw = employers_data.get("employers", {})
    employers = list(employers_raw.values()) if isinstance(employers_raw, dict) else employers_raw

    total = len(employers) + len(JAPAN_SCRAPERS)
    done = 0

    # Health-check Workday employers
    for employer in employers:
        status = await health_check_workday_employer(employer)
        results["workday"].append(status)
        if status["healthy"]:
            results["healthy"] += 1
        else:
            results["unhealthy"] += 1
            logger.warning(f"Source unhealthy: Workday ({status['name']}): {status['error']}")
        done += 1
        if on_progress:
            on_progress(done, total)

    # Health-check Japan scrapers
    for scraper_cls in JAPAN_SCRAPERS:
        status = await health_check_japan_scraper(scraper_cls)
        results["japan_scrapers"].append(status)
        if status["healthy"]:
            results["healthy"] += 1
        else:
            results["unhealthy"] += 1
            logger.warning(f"Source unhealthy: {status['name']}: {status['error']}")
        done += 1
        if on_progress:
            on_progress(done, total)

    return results
