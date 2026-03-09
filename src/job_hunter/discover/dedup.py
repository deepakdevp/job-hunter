from __future__ import annotations

import logging

from job_hunter.database import Job

logger = logging.getLogger(__name__)


def dedup_jobs(jobs: list[Job], existing_urls: set[str]) -> list[Job]:
    seen = set(existing_urls)
    unique = []
    for job in jobs:
        if job.url not in seen:
            seen.add(job.url)
            unique.append(job)
    dupes = len(jobs) - len(unique)
    if dupes:
        logger.info(f"Deduped {dupes} jobs ({len(unique)} new)")
    return unique
