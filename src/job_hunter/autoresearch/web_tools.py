"""Web research tools for deep autoresearch agents."""

from __future__ import annotations

import logging
import re
from urllib.parse import quote_plus

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)


async def web_search(query: str, max_results: int = 5) -> list[dict]:
    """Search the web using DuckDuckGo HTML and return results.

    Returns list of {title, url, snippet}.
    """
    results = []
    url = f"https://html.duckduckgo.com/html/?q={quote_plus(query)}"

    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                },
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            for result in soup.select(".result")[:max_results]:
                title_el = result.select_one(".result__title a, .result__a")
                snippet_el = result.select_one(".result__snippet")
                link = title_el.get("href", "") if title_el else ""

                # DuckDuckGo wraps URLs - extract actual URL
                if "uddg=" in link:
                    from urllib.parse import parse_qs, urlparse

                    parsed = urlparse(link)
                    actual = parse_qs(parsed.query).get("uddg", [""])[0]
                    if actual:
                        link = actual

                results.append(
                    {
                        "title": title_el.get_text(strip=True) if title_el else "",
                        "url": link,
                        "snippet": snippet_el.get_text(strip=True) if snippet_el else "",
                    }
                )
    except Exception as e:
        logger.warning(f"Web search failed for '{query}': {e}")

    return results


async def fetch_page_text(url: str, max_chars: int = 5000) -> str:
    """Fetch a web page and return cleaned text content."""
    try:
        async with httpx.AsyncClient(timeout=15, follow_redirects=True) as client:
            resp = await client.get(
                url,
                headers={
                    "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7)",
                },
            )
            resp.raise_for_status()
            soup = BeautifulSoup(resp.text, "html.parser")

            # Remove script/style/nav
            for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
                tag.decompose()

            text = soup.get_text(separator="\n", strip=True)
            # Collapse whitespace
            text = re.sub(r"\n{3,}", "\n\n", text)
            return text[:max_chars]
    except Exception as e:
        logger.warning(f"Fetch failed for {url}: {e}")
        return ""
