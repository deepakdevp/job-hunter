import asyncio
import pytest
from job_hunter.enrich.rate_limiter import DomainRateLimiter


def test_extract_domain():
    assert DomainRateLimiter.extract_domain("https://example.com/jobs/123") == "example.com"
    assert DomainRateLimiter.extract_domain("https://sub.example.com/path") == "sub.example.com"
    assert DomainRateLimiter.extract_domain("http://localhost:8080/x") == "localhost:8080"


@pytest.mark.asyncio
async def test_global_concurrency_limit():
    limiter = DomainRateLimiter(per_domain=10, global_limit=3, max_per_minute=100)
    active = 0
    max_active = 0

    async def task(url):
        nonlocal active, max_active
        await limiter.acquire(url)
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.05)
        active -= 1
        limiter.release(url)

    # 6 tasks across different domains, global limit 3
    urls = [f"https://domain{i}.com/job/{i}" for i in range(6)]
    await asyncio.gather(*[task(u) for u in urls])
    assert max_active <= 3


@pytest.mark.asyncio
async def test_per_domain_concurrency_limit():
    limiter = DomainRateLimiter(per_domain=2, global_limit=20, max_per_minute=100)
    active = 0
    max_active = 0

    async def task(url):
        nonlocal active, max_active
        await limiter.acquire(url)
        active += 1
        max_active = max(max_active, active)
        await asyncio.sleep(0.05)
        active -= 1
        limiter.release(url)

    # 5 tasks to the same domain, per_domain limit 2
    urls = ["https://example.com/job/1"] * 5
    await asyncio.gather(*[task(u) for u in urls])
    assert max_active <= 2


@pytest.mark.asyncio
async def test_acquire_release_cycle():
    limiter = DomainRateLimiter(per_domain=5, global_limit=20, max_per_minute=100)
    url = "https://example.com/job/1"
    await limiter.acquire(url)
    limiter.release(url)
    # Should not hang on second acquire
    await limiter.acquire(url)
    limiter.release(url)
