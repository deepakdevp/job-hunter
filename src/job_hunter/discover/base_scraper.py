from __future__ import annotations

import logging
from abc import ABC, abstractmethod

import httpx

from job_hunter.database import Job

logger = logging.getLogger(__name__)

DEFAULT_HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.9,ja;q=0.8",
}


class BaseScraper(ABC):
    name: str = "unknown"
    base_url: str = ""

    def __init__(self):
        self.client = httpx.AsyncClient(
            headers=DEFAULT_HEADERS,
            follow_redirects=True,
            timeout=30,
        )

    @abstractmethod
    async def scrape(
        self, query: str = "", location: str = "", max_results: int = 50
    ) -> list[Job]: ...

    async def close(self):
        await self.client.aclose()

    async def _fetch(self, url: str) -> str:
        """Fetch URL with automatic Playwright fallback on 403."""
        response = await self.client.get(url)
        if response.status_code == 403:
            logger.info(f"Got 403 for {url}, trying Playwright fallback...")
            html = await self._fetch_with_playwright(url)
            if html:
                return html
            response.raise_for_status()  # raise if Playwright also failed
        response.raise_for_status()
        return response.text

    async def _fetch_with_playwright(self, url: str) -> str | None:
        """Fetch URL using headless browser. Returns None if Playwright not installed."""
        try:
            from playwright.async_api import async_playwright
        except ImportError:
            logger.warning("Playwright not installed — cannot bypass 403. pip install job-hunter[apply]")
            return None
        try:
            async with async_playwright() as p:
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                await page.goto(url, wait_until="networkidle", timeout=30000)
                html = await page.content()
                await browser.close()
                if len(html) > 1000:
                    logger.info(f"Playwright fetched {len(html)} chars from {url}")
                    return html
                return None
        except Exception as e:
            logger.warning(f"Playwright fetch failed for {url}: {e}")
            return None

    async def _fetch_json(self, url: str) -> dict | list:
        response = await self.client.get(url)
        response.raise_for_status()
        return response.json()
