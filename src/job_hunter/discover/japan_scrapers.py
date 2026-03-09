from __future__ import annotations

import json
import logging
import re
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from job_hunter.database import Job
from job_hunter.discover.base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class TokyoDevScraper(BaseScraper):
    name = "TokyoDev"
    base_url = "https://www.tokyodev.com"

    async def scrape(self, query: str = "", location: str = "", max_results: int = 50) -> list[Job]:
        jobs = []
        url = f"{self.base_url}/jobs"
        try:
            html = await self._fetch(url)
            soup = BeautifulSoup(html, "html.parser")

            listings = soup.select("article.job-listing, .job-card, [data-job], .jobs-list-item")
            if not listings:
                listings = soup.select("a[href*='/jobs/']")

            for item in listings[:max_results]:
                title_el = item.select_one("h2, h3, .job-title, .title")
                company_el = item.select_one(".company, .company-name, .employer")
                link_el = item if item.name == "a" else item.select_one("a[href]")

                if not link_el or not link_el.get("href"):
                    continue

                href = link_el["href"]
                if not href.startswith("http"):
                    href = urljoin(self.base_url, href)

                if "/jobs/" not in href:
                    continue

                title = title_el.get_text(strip=True) if title_el else ""
                company = company_el.get_text(strip=True) if company_el else ""

                if not title:
                    title = link_el.get_text(strip=True)

                if title and query and query.lower() not in title.lower():
                    pass  # include all, scoring filters later

                jobs.append(
                    Job(
                        url=href,
                        title=title or "Unknown",
                        company=company or "Unknown",
                        location="Japan",
                        source="tokyodev",
                    )
                )
            logger.info(f"TokyoDev: found {len(jobs)} jobs")
        except Exception as e:
            logger.error(f"TokyoDev scrape failed: {e}")
        return jobs


class JapanDevScraper(BaseScraper):
    name = "JapanDev"
    base_url = "https://japan-dev.com"

    async def scrape(self, query: str = "", location: str = "", max_results: int = 50) -> list[Job]:
        jobs = []
        url = f"{self.base_url}/jobs"
        try:
            html = await self._fetch(url)
            soup = BeautifulSoup(html, "html.parser")

            listings = soup.select("a[href*='/jobs/']")
            seen = set()

            for item in listings[:max_results * 2]:
                href = item.get("href", "")
                if not href or href in seen:
                    continue
                if not href.startswith("http"):
                    href = urljoin(self.base_url, href)
                if "/jobs/" not in href or href == f"{self.base_url}/jobs" or href == f"{self.base_url}/jobs/":
                    continue
                seen.add(href)

                text_parts = item.get_text(separator=" | ", strip=True).split("|")
                title = text_parts[0].strip() if text_parts else "Unknown"
                company = text_parts[1].strip() if len(text_parts) > 1 else "Unknown"

                jobs.append(
                    Job(
                        url=href,
                        title=title,
                        company=company,
                        location="Japan",
                        source="japandev",
                    )
                )

            logger.info(f"JapanDev: found {len(jobs)} jobs")
        except Exception as e:
            logger.error(f"JapanDev scrape failed: {e}")
        return jobs[:max_results]


class GaijinPotScraper(BaseScraper):
    name = "GaijinPot Jobs"
    base_url = "https://jobs.gaijinpot.com"

    async def scrape(self, query: str = "", location: str = "", max_results: int = 50) -> list[Job]:
        jobs = []
        url = self.base_url
        if query:
            url = f"{self.base_url}/search?keyword={quote_plus(query)}"
        try:
            html = await self._fetch(url)
            soup = BeautifulSoup(html, "html.parser")

            listings = soup.select("a[href*='/job/']")
            seen = set()

            for item in listings[:max_results * 2]:
                href = item.get("href", "")
                if not href or href in seen:
                    continue
                if not href.startswith("http"):
                    href = urljoin(self.base_url, href)
                if "/job/" not in href:
                    continue
                seen.add(href)

                title = item.get_text(strip=True) or "Unknown"
                company_el = item.find_next(class_=re.compile(r"company|employer", re.I))
                company = company_el.get_text(strip=True) if company_el else "Unknown"
                location_el = item.find_next(class_=re.compile(r"location", re.I))
                loc = location_el.get_text(strip=True) if location_el else "Japan"

                jobs.append(
                    Job(
                        url=href,
                        title=title,
                        company=company,
                        location=loc,
                        source="gaijinpot",
                    )
                )

            logger.info(f"GaijinPot: found {len(jobs)} jobs")
        except Exception as e:
            logger.error(f"GaijinPot scrape failed: {e}")
        return jobs[:max_results]


# Registry of all Japan scrapers
JAPAN_SCRAPERS = [
    TokyoDevScraper,
    JapanDevScraper,
    GaijinPotScraper,
]


async def run_japan_scrapers(query: str = "", max_results: int = 50) -> list[Job]:
    all_jobs = []
    for scraper_cls in JAPAN_SCRAPERS:
        scraper = scraper_cls()
        try:
            jobs = await scraper.scrape(query=query, max_results=max_results)
            all_jobs.extend(jobs)
        except Exception as e:
            logger.error(f"{scraper.name} failed: {e}")
        finally:
            await scraper.close()
    return all_jobs
