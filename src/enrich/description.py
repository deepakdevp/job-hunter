"""Fetch full job descriptions from job posting URLs."""

from __future__ import annotations

import json
import re
import time

import requests
from bs4 import BeautifulSoup

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
}

# CSS selectors for common job board containers
DESCRIPTION_SELECTORS = [
    "[data-testid='jobDescriptionText']",  # Indeed
    ".description__text",                  # LinkedIn
    ".jobs-description__content",          # LinkedIn alt
    "#jobDescriptionText",                 # Indeed alt
    ".job-description",
    "#job-description",
    ".jobsearch-jobDescriptionText",
    "[itemprop='description']",
    ".job-details",
    "article",
]


def fetch_description(url: str) -> str:
    """
    Attempt to fetch the full job description from a URL.
    Tries JSON-LD first, then CSS selectors, then falls back to body text.
    Returns empty string on failure.
    """
    try:
        resp = requests.get(url, headers=HEADERS, timeout=20, allow_redirects=True)
        resp.raise_for_status()
    except requests.RequestException:
        return ""

    soup = BeautifulSoup(resp.text, "html.parser")

    # 1. Try JSON-LD structured data
    for script in soup.find_all("script", type="application/ld+json"):
        try:
            data = json.loads(script.string or "")
            if isinstance(data, list):
                data = data[0]
            if data.get("@type") in ("JobPosting", "jobPosting"):
                desc = data.get("description", "")
                if desc:
                    return BeautifulSoup(desc, "html.parser").get_text(separator="\n").strip()
        except (json.JSONDecodeError, AttributeError):
            continue

    # 2. Try known CSS selectors
    for selector in DESCRIPTION_SELECTORS:
        el = soup.select_one(selector)
        if el:
            text = el.get_text(separator="\n").strip()
            if len(text) > 200:
                return text

    # 3. Fallback: extract main content heuristically
    # Remove nav, header, footer, scripts, styles
    for tag in soup(["script", "style", "nav", "header", "footer", "aside"]):
        tag.decompose()

    main = soup.find("main") or soup.find("body")
    if main:
        text = main.get_text(separator="\n").strip()
        # Collapse excessive whitespace
        text = re.sub(r"\n{3,}", "\n\n", text)
        return text[:8000]  # Cap at 8k chars

    return ""


def enrich_jobs(jobs: list[dict], delay: float = 2.0) -> list[dict]:
    """
    Fetch full descriptions for jobs that have an empty description.
    Modifies jobs in place and returns them.
    """
    needs_enrich = [j for j in jobs if not j.get("description")]
    for i, job in enumerate(needs_enrich):
        url = job.get("job_url", "")
        if not url:
            continue
        desc = fetch_description(url)
        if desc:
            job["description"] = desc
        if i < len(needs_enrich) - 1:
            time.sleep(delay)
    return jobs
