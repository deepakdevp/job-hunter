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
    """Fetch a page, using Playwright fallback on failure or for JS-heavy domains."""
    html = await _fetch_static(url)

    # If static fetch failed entirely (403, timeout, etc.), try Playwright
    if html is None:
        logger.info(f"Static fetch failed, trying Playwright fallback for {url}")
        return await _fetch_with_playwright(url)

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


# ---------------------------------------------------------------------------
# Offer verification
# ---------------------------------------------------------------------------

# Common indicators that a job listing is closed or expired.
_CLOSED_INDICATORS = [
    "position has been filled",
    "no longer accepting applications",
    "this job has expired",
    "this position is closed",
    "job is no longer available",
    "listing has been removed",
    "application deadline has passed",
    "posting has expired",
    "role has been filled",
]


async def verify_offer_active(url: str) -> dict:
    """Check whether a job listing is still active.

    Strategy
    --------
    1. Try Playwright first — navigate, look for a title, description, and an
       "Apply" button.
    2. Fall back to a plain HTTP fetch if Playwright is unavailable.
    3. Return ``{"active": bool, "verified_method": str, "reason": str}``.

    The function never raises; errors are reported via *reason*.
    """
    # --- Try Playwright first ---
    result = await _verify_with_playwright(url)
    if result is not None:
        return result

    # --- Fall back to HTTP ---
    return await _verify_with_http(url)


async def _verify_with_playwright(url: str) -> dict | None:
    """Verify offer using Playwright. Returns *None* if Playwright is unavailable."""
    try:
        from playwright.async_api import async_playwright
    except ImportError:
        return None

    try:
        async with async_playwright() as p:
            browser = await p.chromium.launch(headless=True)
            page = await browser.new_page(user_agent=_USER_AGENT)

            response = await page.goto(url, wait_until="networkidle", timeout=30000)

            # HTTP-level check
            if response and response.status >= 400:
                await browser.close()
                return {
                    "active": False,
                    "verified_method": "playwright",
                    "reason": f"HTTP {response.status}",
                }

            text = (await page.content()).lower()

            # Check for closed/expired indicators
            for indicator in _CLOSED_INDICATORS:
                if indicator in text:
                    await browser.close()
                    return {
                        "active": False,
                        "verified_method": "playwright",
                        "reason": f"Closed indicator found: '{indicator}'",
                    }

            # Look for title (h1/h2) and an apply-like button
            has_title = await page.query_selector("h1, h2, [class*='title']")
            has_apply = await page.query_selector(
                "a[href*='apply'], button:has-text('Apply'), "
                "a:has-text('Apply'), input[value*='Apply']"
            )

            await browser.close()

            if has_title and has_apply:
                return {
                    "active": True,
                    "verified_method": "playwright",
                    "reason": "Title and Apply button detected",
                }

            if has_title:
                return {
                    "active": True,
                    "verified_method": "playwright",
                    "reason": "Title found but no explicit Apply button",
                }

            return {
                "active": False,
                "verified_method": "playwright",
                "reason": "No job title or apply button detected",
            }

    except Exception as e:
        logger.warning("Playwright verification failed for %s: %s", url, e)
        return None


async def _verify_with_http(url: str) -> dict:
    """Verify offer using a plain HTTP fetch."""
    try:
        async with httpx.AsyncClient(
            follow_redirects=True,
            timeout=30,
            headers={"User-Agent": _USER_AGENT},
        ) as client:
            response = await client.get(url)

            if response.status_code >= 400:
                return {
                    "active": False,
                    "verified_method": "http",
                    "reason": f"HTTP {response.status_code}",
                }

            text = response.text.lower()

            for indicator in _CLOSED_INDICATORS:
                if indicator in text:
                    return {
                        "active": False,
                        "verified_method": "http",
                        "reason": f"Closed indicator found: '{indicator}'",
                    }

            # Basic heuristic: page has reasonable content length
            if len(text.strip()) < 500:
                return {
                    "active": False,
                    "verified_method": "http",
                    "reason": "Page content too short — likely removed",
                }

            return {
                "active": True,
                "verified_method": "http",
                "reason": "Page loaded with content; no closed indicators found",
            }

    except Exception as e:
        logger.warning("HTTP verification failed for %s: %s", url, e)
        return {
            "active": False,
            "verified_method": "unverified",
            "reason": f"Verification failed: {e}",
        }
