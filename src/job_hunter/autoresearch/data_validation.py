"""Pipeline 2: Data Validation — URL checks, smart dedup, non-Japan filter, field quality."""

from __future__ import annotations

import logging
import re
from difflib import SequenceMatcher

import httpx

from job_hunter.database import Job, JobDB

logger = logging.getLogger(__name__)

# Japan location keywords
JAPAN_KEYWORDS = (
    "japan",
    "tokyo",
    "osaka",
    "jp",
    "yokohama",
    "fukuoka",
    "nagoya",
    "kyoto",
    "shibuya",
    "shinjuku",
    "minato",
    "roppongi",
    "meguro",
    "chiyoda",
    "remote",
    "千代田",
    "渋谷",
    "新宿",
    "港区",
    "品川",
    "大手町",
    "高輪",
    "千駄ヶ谷",
)


async def check_urls_alive(jobs: list[Job], sample_size: int = 50) -> list[str]:
    """HEAD-check a sample of job URLs, return list of dead URLs."""
    dead_urls = []
    sample = jobs[:sample_size]

    async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
        for job in sample:
            try:
                resp = await client.head(job.url)
                if resp.status_code >= 400:
                    dead_urls.append(job.url)
            except Exception:
                dead_urls.append(job.url)

    return dead_urls


def find_title_company_dupes(jobs: list[Job], threshold: float = 0.85) -> list[str]:
    """Find jobs with very similar title+company (fuzzy dedup). Returns URLs to remove."""
    dupes = []
    seen = []

    for job in jobs:
        key = f"{job.title.lower().strip()} @ {job.company.lower().strip()}"
        for seen_key, seen_url in seen:
            ratio = SequenceMatcher(None, key, seen_key).ratio()
            if ratio >= threshold:
                dupes.append(job.url)
                break
        else:
            seen.append((key, job.url))

    return dupes


def filter_non_japan(jobs: list[Job]) -> list[str]:
    """Find jobs that are clearly not in Japan. Returns URLs to filter."""
    non_japan = []
    for job in jobs:
        loc = (job.location or "").lower()
        # If location is set and doesn't match any Japan keyword
        if loc and loc.strip() != "" and loc != "unknown":
            if not any(kw in loc for kw in JAPAN_KEYWORDS):
                non_japan.append(job.url)
    return non_japan


def find_low_quality(jobs: list[Job]) -> list[dict]:
    """Find jobs with quality issues. Returns list of {url, issues}."""
    flagged = []
    for job in jobs:
        issues = []
        if not job.title or len(job.title.strip()) < 5:
            issues.append("title_too_short")
        if job.company in ("Unknown", "", None) or len((job.company or "").strip()) < 2:
            issues.append("missing_company")
        if job.title and job.title == job.company:
            issues.append("title_equals_company")
        if job.title and re.match(r"^(unknown|test|n/a|none|null)$", job.title.strip(), re.I):
            issues.append("garbage_title")
        if issues:
            flagged.append({"url": job.url, "issues": issues})
    return flagged


async def run_data_validation(
    db: JobDB,
    statuses: tuple[str, ...] = ("new", "enriched", "scored", "tailored", "synced"),
    on_progress=None,
) -> dict:
    """Run all data validation checks on jobs in the DB.

    Returns summary dict with counts of issues found and fixed.
    """
    all_jobs = []
    for status in statuses:
        all_jobs.extend(db.get_jobs_by_status(status))

    total_steps = 4
    done = 0

    results = {
        "total_checked": len(all_jobs),
        "dead_urls": 0,
        "dupes_removed": 0,
        "non_japan_filtered": 0,
        "low_quality_flagged": 0,
    }

    # 1. URL alive check (sample)
    dead = await check_urls_alive(all_jobs, sample_size=50)
    for url in dead:
        job = db.get_job(url)
        if job and job.status not in ("filtered",):
            job.status = "filtered"
            job.score_reason = "Dead URL (autoresearch validation)"
            db.upsert_job(job)
    results["dead_urls"] = len(dead)
    done += 1
    if on_progress:
        on_progress(done, total_steps)

    # 2. Fuzzy title+company dedup
    dupes = find_title_company_dupes(all_jobs)
    for url in dupes:
        job = db.get_job(url)
        if job and job.status not in ("filtered",):
            job.status = "filtered"
            job.score_reason = "Duplicate (title+company match)"
            db.upsert_job(job)
    results["dupes_removed"] = len(dupes)
    done += 1
    if on_progress:
        on_progress(done, total_steps)

    # 3. Non-Japan filter
    non_japan = filter_non_japan(all_jobs)
    for url in non_japan:
        job = db.get_job(url)
        if job and job.status not in ("filtered", "synced"):
            job.status = "filtered"
            job.score_reason = f"Non-Japan location: {job.location}"
            db.upsert_job(job)
    results["non_japan_filtered"] = len(non_japan)
    done += 1
    if on_progress:
        on_progress(done, total_steps)

    # 4. Low quality detection
    low_quality = find_low_quality(all_jobs)
    results["low_quality_flagged"] = len(low_quality)
    # Don't auto-filter these, just log
    for item in low_quality:
        logger.info(f"Low quality job: {item['url']} — {item['issues']}")
    done += 1
    if on_progress:
        on_progress(done, total_steps)

    return results
