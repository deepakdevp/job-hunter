from __future__ import annotations

import asyncio
import logging

from job_hunter.database import Job, JobDB
from job_hunter.enrich.detail import (
    EnrichResult,
    extract_from_json_ld,
    extract_description_css,
    extract_with_llm,
    extract_raw_text,
)
from job_hunter.enrich.fetcher import fetch_page
from job_hunter.enrich.rate_limiter import DomainRateLimiter

logger = logging.getLogger(__name__)


async def enrich_job(
    url: str, llm=None, rate_limiter: DomainRateLimiter | None = None
) -> EnrichResult | None:
    """Run the 4-tier enrichment cascade for a single job URL."""
    if rate_limiter:
        await rate_limiter.acquire(url)

    try:
        html = await fetch_page(url)
        if not html:
            return None

        # Tier 1: JSON-LD
        result = extract_from_json_ld(html)
        if result and result.description:
            logger.debug(f"Tier 1 (JSON-LD) succeeded for {url}")
            return result

        # Tier 2: CSS selectors
        result = extract_description_css(html)
        if result and result.description:
            logger.debug(f"Tier 2 (CSS) succeeded for {url}")
            return result

        # Tier 3: LLM extraction
        if llm:
            result = await extract_with_llm(html, llm)
            if result:
                logger.debug(f"Tier 3 (AI) succeeded for {url}")
                return result

        # Tier 4: Raw text fallback (flagged)
        logger.info(f"All tiers failed for {url}, using raw text fallback")
        return extract_raw_text(html)

    finally:
        if rate_limiter:
            rate_limiter.release(url)


def _apply_enrichment(job: Job, result: EnrichResult) -> Job:
    """Apply enrichment result to a Job object."""
    job.description = result.description
    job.apply_url = result.apply_url or job.apply_url
    job.enrich_tier = result.tier
    job.enrichment_raw = result.enrichment_raw or None
    job.visa_sponsorship = result.visa_sponsorship
    job.remote_policy = result.remote_policy
    job.tech_stack = ", ".join(result.tech_stack) if result.tech_stack else None
    job.seniority = result.seniority
    job.contract_type = result.contract_type
    job.team_size = result.team_size
    job.benefits = result.benefits
    job.status = "enriched"
    return job


async def run_enrichment(
    db: JobDB,
    llm=None,
    limit: int | None = None,
    tier1_only: bool = False,
    on_progress=None,
) -> tuple[int, int]:
    """Enrich all unenriched jobs concurrently.

    Returns (enriched_count, total_count).
    on_progress: optional callback(done, total) for progress reporting.
    """
    jobs = db.get_unenriched_jobs()
    if limit:
        jobs = jobs[:limit]

    total = len(jobs)
    if total == 0:
        return 0, 0

    rate_limiter = DomainRateLimiter(per_domain=5, global_limit=20, max_per_minute=5)
    enriched = 0
    done = 0

    effective_llm = None if tier1_only else llm

    async def process_job(job: Job):
        nonlocal enriched, done
        result = await enrich_job(job.url, llm=effective_llm, rate_limiter=rate_limiter)
        if result:
            _apply_enrichment(job, result)
            db.upsert_job(job)
            enriched += 1
        done += 1
        if on_progress:
            on_progress(done, total)

    # Run all jobs concurrently (rate limiter handles throttling)
    await asyncio.gather(*[process_job(job) for job in jobs], return_exceptions=True)

    return enriched, total
