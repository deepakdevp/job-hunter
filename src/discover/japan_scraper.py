"""Custom scrapers for Japanese job portals (GaijinPot, Daijob, JREC-IN)."""

from __future__ import annotations

import time
from datetime import datetime, timezone
from urllib.parse import urlencode

import requests
from bs4 import BeautifulSoup
from rich.console import Console

console = Console()

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/120.0.0.0 Safari/537.36"
    ),
    "Accept-Language": "en-US,en;q=0.9,ja;q=0.8",
}

RATE_LIMIT_SECONDS = 7  # conservative


def _get(url: str, **kwargs) -> requests.Response | None:
    try:
        resp = requests.get(url, headers=HEADERS, timeout=15, **kwargs)
        resp.raise_for_status()
        return resp
    except requests.RequestException as exc:
        console.print(f"[red]Request failed: {url} — {exc}[/red]")
        return None


def scrape_gaijinpot(search_term: str, location: str = "", max_pages: int = 3) -> list[dict]:
    """Scrape GaijinPot Jobs."""
    jobs = []
    params = {"q": search_term, "page": 1}
    if location:
        params["location"] = location

    for page in range(1, max_pages + 1):
        params["page"] = page
        url = f"https://jobs.gaijinpot.com/index/index/search?{urlencode(params)}"
        resp = _get(url)
        if not resp:
            break

        soup = BeautifulSoup(resp.text, "html.parser")
        listings = soup.select("div.job-listing, article.job-card, .job-result-item")
        if not listings:
            break

        for item in listings:
            title_el = item.select_one("h2, h3, .job-title, a.job-title")
            company_el = item.select_one(".company-name, .employer")
            location_el = item.select_one(".location, .job-location")
            link_el = item.select_one("a[href]")

            title = title_el.get_text(strip=True) if title_el else ""
            company = company_el.get_text(strip=True) if company_el else ""
            loc = location_el.get_text(strip=True) if location_el else location
            href = link_el.get("href", "") if link_el else ""
            if href and not href.startswith("http"):
                href = "https://jobs.gaijinpot.com" + href

            if title and href:
                jobs.append({
                    "title": title,
                    "company": company,
                    "location": loc,
                    "job_url": href,
                    "apply_url": href,
                    "description": "",
                    "salary": "",
                    "date_posted": None,
                    "date_found": datetime.now(timezone.utc).isoformat(),
                    "source": "GaijinPot",
                    "status": "New",
                    "score": None,
                    "notes": "",
                    "tags": [],
                })

        time.sleep(RATE_LIMIT_SECONDS)

    return jobs


def scrape_jrec_in(search_term: str, max_pages: int = 3) -> list[dict]:
    """Scrape JREC-IN (academic/research jobs in Japan)."""
    jobs = []
    for page in range(1, max_pages + 1):
        params = {"keyword": search_term, "page": page}
        url = f"https://jrecin.jst.go.jp/seek/SeekJorList?{urlencode(params)}&lang=1"
        resp = _get(url)
        if not resp:
            break

        soup = BeautifulSoup(resp.content, "html.parser", from_encoding="utf-8")
        rows = soup.select("table.list tr, .job-list-item, li.result-item")
        if not rows:
            break

        for row in rows:
            link = row.select_one("a[href]")
            if not link:
                continue
            href = link.get("href", "")
            if not href.startswith("http"):
                href = "https://jrecin.jst.go.jp" + href
            title = link.get_text(strip=True)
            org_el = row.select_one(".organization, td:nth-child(2)")
            org = org_el.get_text(strip=True) if org_el else ""

            if title:
                jobs.append({
                    "title": title,
                    "company": org,
                    "location": "Japan",
                    "job_url": href,
                    "apply_url": href,
                    "description": "",
                    "salary": "",
                    "date_posted": None,
                    "date_found": datetime.now(timezone.utc).isoformat(),
                    "source": "JREC-IN",
                    "status": "New",
                    "score": None,
                    "notes": "",
                    "tags": [],
                })

        time.sleep(RATE_LIMIT_SECONDS)

    return jobs


def scrape_japan_platforms(queries: list[dict], platforms: list[str]) -> list[dict]:
    """Run Japan-specific scrapers for configured queries."""
    all_jobs: list[dict] = []
    jp_platforms = [p for p in platforms if p.lower() in ("gaijinpot", "jrec-in", "daijob")]

    for query in queries:
        search_term = query.get("search_term", "")
        location = query.get("location", "")

        for platform in jp_platforms:
            console.print(f"  Scraping [cyan]{platform}[/cyan] for '[bold]{search_term}[/bold]'...")
            if platform.lower() == "gaijinpot":
                jobs = scrape_gaijinpot(search_term, location)
            elif platform.lower() == "jrec-in":
                jobs = scrape_jrec_in(search_term)
            else:
                console.print(f"  [yellow]{platform} scraper not yet implemented[/yellow]")
                continue

            all_jobs.extend(jobs)
            console.print(f"    → {len(jobs)} jobs found")

    return all_jobs
