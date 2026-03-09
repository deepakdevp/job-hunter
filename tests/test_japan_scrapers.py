import pytest
from unittest.mock import AsyncMock, patch
from job_hunter.discover.japan_scrapers import TokyoDevScraper, JapanDevScraper, GaijinPotScraper


MOCK_TOKYODEV_HTML = """
<html><body>
<div class="jobs-list">
    <a href="/jobs/123-software-engineer">
        <h3 class="title">Software Engineer</h3>
        <span class="company">TechCo Japan</span>
    </a>
    <a href="/jobs/456-backend-dev">
        <h3 class="title">Backend Developer</h3>
        <span class="company">StartupX</span>
    </a>
</div>
</body></html>
"""

MOCK_JAPANDEV_HTML = """
<html><body>
<a href="/jobs/react-engineer-at-mercari">React Engineer | Mercari</a>
<a href="/jobs/python-dev-at-line">Python Developer | LINE</a>
<a href="/jobs">All Jobs</a>
</body></html>
"""

MOCK_GAIJINPOT_HTML = """
<html><body>
<a href="/job/12345">IT Support Specialist</a>
<span class="company">ABC Corp</span>
<span class="location">Tokyo</span>
<a href="/job/67890">Web Developer</a>
<span class="company">XYZ Inc</span>
<span class="location">Osaka</span>
</body></html>
"""


@pytest.mark.asyncio
async def test_tokyodev_scraper():
    scraper = TokyoDevScraper()
    scraper._fetch = AsyncMock(return_value=MOCK_TOKYODEV_HTML)
    jobs = await scraper.scrape()
    assert len(jobs) >= 2
    assert all(j.source == "tokyodev" for j in jobs)
    assert all("/jobs/" in j.url for j in jobs)
    await scraper.close()


@pytest.mark.asyncio
async def test_japandev_scraper():
    scraper = JapanDevScraper()
    scraper._fetch = AsyncMock(return_value=MOCK_JAPANDEV_HTML)
    jobs = await scraper.scrape()
    assert len(jobs) >= 2
    assert all(j.source == "japandev" for j in jobs)
    # Should not include the "/jobs" or "/jobs/" link
    assert not any(j.url.endswith("/jobs") or j.url.endswith("/jobs/") for j in jobs)
    await scraper.close()


@pytest.mark.asyncio
async def test_gaijinpot_scraper():
    scraper = GaijinPotScraper()
    scraper._fetch = AsyncMock(return_value=MOCK_GAIJINPOT_HTML)
    jobs = await scraper.scrape()
    assert len(jobs) >= 2
    assert all(j.source == "gaijinpot" for j in jobs)
    assert all("/job/" in j.url for j in jobs)
    await scraper.close()
