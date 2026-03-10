from __future__ import annotations

import logging
from urllib.parse import urlparse

import httpx

logger = logging.getLogger(__name__)

# Domains known to require JavaScript rendering
JS_HEAVY_DOMAINS = [
    "lever.co",
    "greenhouse.io",
    "boards.eu.greenhouse.io",
    "ashby.io",
    "jobs.smartrecruiters.com",
    "myworkdayjobs.com",
    "icims.com",
]

_USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
)


def _is_js_heavy(url: str) -> bool:
    """Check if URL belongs to a JS-heavy domain."""
    host = urlparse(url).netloc.lower()
    return any(domain in host for domain in JS_HEAVY_DOMAINS)


async def fetch_page(url: str) -> str | None:
    """Fetch a page, using Playwright for JS-heavy domains if static fetch is insufficient."""
    html = await _fetch_static(url)
    if html is None:
        return None

    # If JS-heavy domain and content looks too short, try Playwright
    if _is_js_heavy(url) and len(html.strip()) < 5000:
        logger.info(f"JS-heavy domain detected, trying Playwright for {url}")
        pw_html = await _fetch_with_playwright(url)
        if pw_html and len(pw_html) > len(html):
            return pw_html

    return html


async def _fetch_static(url: str) -> str | None:
    """Fetch page with httpx (static, no JS)."""
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=30,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            response = await client.get(url)
            response.raise_for_status()
            return response.text
    except Exception as e:
        logger.warning(f"Static fetch failed for {url}: {e}")
        return None


async def _fetch_with_playwright(url: str) -> str | None:
    """Fetch page with Playwright headless browser for JS-rendered content."""
    try:
        from playwright.async_api import async_playwright

        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(user_agent=_USER_AGENT)
            await page.goto(url, wait_until="networkidle", timeout=30000)
            html = await page.content()
            await browser.close()
            return html
    except ImportError:
        logger.warning("Playwright not installed, skipping JS rendering")
        return None
    except Exception as e:
        logger.warning(f"Playwright fetch failed for {url}: {e}")
        return None
