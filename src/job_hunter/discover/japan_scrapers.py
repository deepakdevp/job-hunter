from __future__ import annotations

import logging
from urllib.parse import quote_plus, urljoin

from bs4 import BeautifulSoup

from job_hunter.database import Job
from job_hunter.discover.base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class TokyoDevScraper(BaseScraper):
    name = "TokyoDev"
    base_url = "https://www.tokyodev.com"

    async def scrape(self, query: str = "", location: str = "", max_results: int = 100) -> list[Job]:
        jobs = []
        url = f"{self.base_url}/jobs"
        try:
            html = await self._fetch(url)
            soup = BeautifulSoup(html, "html.parser")

            # Real job listings are at /companies/{company}/jobs/{slug}
            # Filter out tag/filter pages like /jobs/salary-data, /jobs/python
            seen = set()
            for link in soup.select("a[href*='/companies/'][href*='/jobs/']"):
                href = link.get("href", "")
                if not href.startswith("http"):
                    href = urljoin(self.base_url, href)
                if href in seen:
                    continue
                seen.add(href)

                title = link.get_text(strip=True)
                if not title or len(title) < 3:
                    continue

                # Extract company from URL: /companies/{company}/jobs/{slug}
                parts = href.split("/companies/")
                company = "Unknown"
                if len(parts) > 1:
                    company_slug = parts[1].split("/")[0]
                    company = company_slug.replace("-", " ").title()

                jobs.append(
                    Job(
                        url=href,
                        title=title,
                        company=company,
                        location="Japan",
                        source="tokyodev",
                    )
                )

            logger.info(f"TokyoDev: found {len(jobs)} jobs")
        except Exception as e:
            logger.error(f"TokyoDev scrape failed: {e}")
        return jobs[:max_results]


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

            for item in listings[: max_results * 2]:
                href = item.get("href", "")
                if not href or href in seen:
                    continue
                if not href.startswith("http"):
                    href = urljoin(self.base_url, href)
                if (
                    "/jobs/" not in href
                    or href == f"{self.base_url}/jobs"
                    or href == f"{self.base_url}/jobs/"
                ):
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
        # function=7000 is IT/Internet/Telecom category
        params = "function=7000&employment_terms=full-time&order_by=latest"
        if query:
            params += f"&keyword={quote_plus(query)}"
        url = f"{self.base_url}/en/job?{params}"
        try:
            html = await self._fetch(url)
            soup = BeautifulSoup(html, "html.parser")

            # Job links follow /en/job/{numeric_id} pattern
            listings = soup.select("a[href*='/en/job/']")
            seen = set()

            for item in listings[: max_results * 2]:
                href = item.get("href", "")
                if not href or href in seen:
                    continue
                # Strip query params from href for dedup
                clean_href = href.split("?")[0]
                if not clean_href.startswith("http"):
                    clean_href = urljoin(self.base_url, clean_href)
                # Must be an individual job page (has numeric ID)
                if clean_href.rstrip("/") == f"{self.base_url}/en/job":
                    continue
                if clean_href in seen:
                    continue
                seen.add(clean_href)

                title = item.get_text(strip=True) or "Unknown"
                if len(title) < 3 or title.lower() in ("unknown", "post jobs", "apply"):
                    continue

                jobs.append(
                    Job(
                        url=clean_href,
                        title=title,
                        company="Unknown",  # Parsed during enrichment
                        location="Japan",
                        source="gaijinpot",
                    )
                )

            logger.info(f"GaijinPot: found {len(jobs)} IT jobs")
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
