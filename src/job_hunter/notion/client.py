from __future__ import annotations

import logging
from typing import Any

import httpx
from notion_client import Client

from job_hunter.database import Job

logger = logging.getLogger(__name__)

# Notion database schema
DATABASE_TITLE = "Job Hunter"

DATABASE_PROPERTIES = {
    "Job Title": {"title": {}},
    "Company": {"rich_text": {}},
    "Location": {"rich_text": {}},
    "Score": {"number": {}},
    "Score Reason": {"rich_text": {}},
    "Status": {
        "select": {
            "options": [
                {"name": "new", "color": "gray"},
                {"name": "enriched", "color": "blue"},
                {"name": "scored", "color": "purple"},
                {"name": "filtered", "color": "red"},
                {"name": "tailored", "color": "yellow"},
                {"name": "synced", "color": "orange"},
                {"name": "reviewing", "color": "pink"},
                {"name": "applied", "color": "green"},
                {"name": "phone_screen", "color": "blue"},
                {"name": "interview", "color": "purple"},
                {"name": "offer", "color": "green"},
                {"name": "rejected", "color": "red"},
                {"name": "withdrawn", "color": "gray"},
            ]
        }
    },
    "Job URL": {"url": {}},
    "Apply URL": {"url": {}},
    "Source": {
        "select": {
            "options": [
                {"name": "indeed", "color": "blue"},
                {"name": "linkedin", "color": "blue"},
                {"name": "glassdoor", "color": "green"},
                {"name": "google", "color": "red"},
                {"name": "ziprecruiter", "color": "orange"},
                {"name": "tokyodev", "color": "purple"},
                {"name": "japandev", "color": "purple"},
                {"name": "gaijinpot", "color": "purple"},
                {"name": "workday", "color": "yellow"},
            ]
        }
    },
    "Salary Min": {"number": {"format": "number"}},
    "Salary Max": {"number": {"format": "number"}},
    "Salary Raw": {"rich_text": {}},
    "Posted Date": {"date": {}},
    "Found Date": {"date": {}},
    "Resume PDF": {"url": {}},
    "Cover Letter": {"url": {}},
    "Country": {
        "select": {
            "options": [
                {"name": "Japan", "color": "red"},
                {"name": "Germany", "color": "yellow"},
                {"name": "Netherlands", "color": "orange"},
                {"name": "UK", "color": "blue"},
                {"name": "Europe", "color": "purple"},
                {"name": "Remote", "color": "green"},
                {"name": "India", "color": "brown"},
                {"name": "Other", "color": "gray"},
            ]
        }
    },
    "Visa Mentioned": {"checkbox": {}},
    "Tags": {"multi_select": {"options": []}},
    "Notes": {"rich_text": {}},
}


def _extract_country(location: str) -> str:
    """Extract country from a location string."""
    loc = location.lower().strip()
    # Japanese locations
    if any(
        x in loc
        for x in (
            "japan",
            "tokyo",
            "osaka",
            "jp",
            "yokohama",
            "fukuoka",
            "nagoya",
            "kyoto",
            "shibuya",
            "shinjuku",
            "minato",
            "meguro",
            "sumida",
            "chiyoda",
            "千",
            "渋谷",
            "大手町",
            "高輪",
            "千駄",
            "港区",
            "新宿",
        )
    ):
        return "Japan"
    if any(
        x in loc for x in ("germany", "berlin", "munich", "frankfurt", "hamburg", "deutschland")
    ):
        return "Germany"
    if any(
        x in loc
        for x in ("netherlands", "amsterdam", "rotterdam", "den haag", "eindhoven", "nederland")
    ):
        return "Netherlands"
    if any(
        x in loc
        for x in (
            "uk",
            "united kingdom",
            "london",
            "manchester",
            "edinburgh",
            "cambridge",
            "england",
            "scotland",
        )
    ):
        return "UK"
    if any(
        x in loc
        for x in (
            "france",
            "paris",
            "spain",
            "madrid",
            "barcelona",
            "italy",
            "rome",
            "milan",
            "sweden",
            "stockholm",
            "ireland",
            "dublin",
            "europe",
            "switzerland",
            "zurich",
            "austria",
            "vienna",
            "poland",
            "warsaw",
            "denmark",
            "copenhagen",
            "finland",
            "helsinki",
            "norway",
            "oslo",
            "portugal",
            "lisbon",
            "prague",
            "belgium",
            "brussels",
        )
    ):
        return "Europe"
    if any(x in loc for x in ("remote", "anywhere", "worldwide", "global", "work from home")):
        return "Remote"
    if any(
        x in loc
        for x in (
            "india",
            "bangalore",
            "mumbai",
            "delhi",
            "hyderabad",
            "pune",
            "gurugram",
            "noida",
            "chennai",
        )
    ):
        return "India"
    return "Other"


class NotionJobDB:
    """Wrapper around Notion API for the Job Hunter database."""

    def __init__(self, token: str, database_id: str | None = None):
        self.client = Client(auth=token)
        self._token = token
        self.database_id = database_id

    def create_database(self, parent_page_id: str, title: str = DATABASE_TITLE) -> str:
        """Create the Job Hunter database under a parent page.

        Uses raw HTTP because notion-client v3 drops 'properties' from
        databases.create (breaking change for API version 2025-09-03).
        """
        response = httpx.post(
            "https://api.notion.com/v1/databases",
            headers={
                "Authorization": f"Bearer {self._token}",
                "Content-Type": "application/json",
                "Notion-Version": "2022-06-28",
            },
            json={
                "parent": {"type": "page_id", "page_id": parent_page_id},
                "title": [{"type": "text", "text": {"content": title}}],
                "properties": DATABASE_PROPERTIES,
            },
            timeout=60,
        )
        response.raise_for_status()
        data = response.json()
        self.database_id = data["id"]
        logger.info(f"Created Notion database: {self.database_id}")
        return self.database_id

    def find_existing_database(self, parent_page_id: str) -> str | None:
        """Search for an existing Job Hunter database under the parent page."""
        try:
            # Search for databases with our title
            response = self.client.search(
                query=DATABASE_TITLE,
            )
            for result in response.get("results", []):
                if result.get("object") != "database":
                    continue
                title_parts = result.get("title", [])
                title = "".join(t.get("plain_text", "") for t in title_parts)
                if title == DATABASE_TITLE:
                    self.database_id = result["id"]
                    logger.info(f"Found existing Notion database: {self.database_id}")
                    return self.database_id
        except Exception as e:
            logger.warning(f"Search for existing database failed: {e}")
        return None

    def init_database(self, parent_page_id: str) -> str:
        """Find or create the Job Hunter database."""
        existing = self.find_existing_database(parent_page_id)
        if existing:
            return existing
        return self.create_database(parent_page_id)

    def create_page(
        self, job: Job, resume_url: str | None = None, cover_letter_url: str | None = None
    ) -> str:
        """Create a Notion page for a job. Returns the page ID."""
        if not self.database_id:
            raise ValueError("Database ID not set. Call init_database first.")

        props = self._job_to_properties(job, resume_url, cover_letter_url)

        response = self.client.pages.create(
            parent={"database_id": self.database_id},
            properties=props,
        )
        page_id = response["id"]
        logger.debug(f"Created Notion page {page_id} for {job.url}")
        return page_id

    def update_page(
        self,
        page_id: str,
        job: Job,
        resume_url: str | None = None,
        cover_letter_url: str | None = None,
    ):
        """Update an existing Notion page."""
        props = self._job_to_properties(job, resume_url, cover_letter_url)
        self.client.pages.update(page_id=page_id, properties=props)
        logger.debug(f"Updated Notion page {page_id}")

    def get_all_pages(self) -> list[dict]:
        """Fetch all pages from the database."""
        if not self.database_id:
            raise ValueError("Database ID not set.")

        pages = []
        cursor = None
        while True:
            kwargs: dict[str, Any] = {"database_id": self.database_id, "page_size": 100}
            if cursor:
                kwargs["start_cursor"] = cursor
            response = self.client.databases.query(**kwargs)
            pages.extend(response.get("results", []))
            if not response.get("has_more"):
                break
            cursor = response.get("next_cursor")
        return pages

    def get_page_status(self, page: dict) -> tuple[str, str]:
        """Extract (job_url, status) from a Notion page.

        Returns (url, status) tuple.
        """
        props = page.get("properties", {})

        # Extract Job URL
        url_prop = props.get("Job URL", {})
        job_url = url_prop.get("url", "")

        # Extract Status
        status_prop = props.get("Status", {})
        select = status_prop.get("select")
        status = select.get("name", "new") if select else "new"

        return job_url, status

    def _job_to_properties(
        self, job: Job, resume_url: str | None = None, cover_letter_url: str | None = None
    ) -> dict:
        """Convert a Job to Notion page properties."""
        props: dict[str, Any] = {
            "Job Title": {"title": [{"text": {"content": job.title[:2000]}}]},
            "Company": {"rich_text": [{"text": {"content": job.company[:2000]}}]},
            "Location": {"rich_text": [{"text": {"content": job.location[:2000]}}]},
            "Status": {"select": {"name": job.status or "new"}},
            "Source": {"select": {"name": job.source or "unknown"}},
            "Country": {"select": {"name": _extract_country(job.location)}},
        }

        if job.visa_sponsorship is not None:
            props["Visa Mentioned"] = {"checkbox": bool(job.visa_sponsorship)}
        if job.url:
            props["Job URL"] = {"url": job.url}
        if job.apply_url:
            props["Apply URL"] = {"url": job.apply_url}
        if job.score is not None:
            props["Score"] = {"number": job.score}
        if job.score_reason:
            props["Score Reason"] = {"rich_text": [{"text": {"content": job.score_reason[:2000]}}]}
        if job.salary_min is not None:
            props["Salary Min"] = {"number": job.salary_min}
        if job.salary_max is not None:
            props["Salary Max"] = {"number": job.salary_max}
        if job.salary_raw:
            props["Salary Raw"] = {"rich_text": [{"text": {"content": job.salary_raw[:2000]}}]}
        if job.posted_date:
            props["Posted Date"] = {"date": {"start": job.posted_date[:10]}}
        if job.found_date:
            props["Found Date"] = {"date": {"start": job.found_date[:10]}}
        if resume_url:
            props["Resume PDF"] = {"url": resume_url}
        if cover_letter_url:
            props["Cover Letter"] = {"url": cover_letter_url}
        if job.tech_stack:
            tags = [t.strip() for t in job.tech_stack.split(",") if t.strip()]
            props["Tags"] = {"multi_select": [{"name": t[:100]} for t in tags[:20]]}

        return props
