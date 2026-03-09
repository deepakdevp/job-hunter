"""Sync jobs to Notion and update their status."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .client import NotionClient


def _text(value: str) -> dict:
    return {"rich_text": [{"text": {"content": value[:2000] if value else ""}}]}


def _title(value: str) -> dict:
    return {"title": [{"text": {"content": value[:2000] if value else ""}}]}


def _select(value: str) -> dict:
    return {"select": {"name": value}}


def _multi_select(values: list[str]) -> dict:
    return {"multi_select": [{"name": v[:100]} for v in values[:25]]}


def _url(value: str) -> dict:
    return {"url": value if value else None}


def _number(value: int | float | None) -> dict:
    return {"number": value}


def _date(value: str | datetime | None) -> dict:
    if value is None:
        return {"date": None}
    if isinstance(value, datetime):
        value = value.isoformat()
    return {"date": {"start": value}}


def build_job_properties(job: dict[str, Any]) -> dict:
    """Convert a job dict to Notion property format."""
    return {
        "Job Title": _title(job.get("title", "Unknown")),
        "Company": _text(job.get("company", "")),
        "Location": _text(job.get("location", "")),
        "Score": _number(job.get("score")),
        "Status": _select(job.get("status", "New")),
        "Job URL": _url(job.get("job_url", "")),
        "Apply URL": _url(job.get("apply_url", "")),
        "Source": _select(job.get("source", "Other")),
        "Salary": _text(job.get("salary", "")),
        "Posted Date": _date(job.get("date_posted")),
        "Found Date": _date(job.get("date_found", datetime.now(timezone.utc).isoformat())),
        "Notes": _text(job.get("notes", "")),
        "Tags": _multi_select(job.get("tags", [])),
    }


def upsert_job(client: NotionClient, database_id: str, job: dict[str, Any]) -> tuple[str, bool]:
    """
    Create or update a job in Notion.
    Returns (page_id, created) where created=True if new.
    Uses job_url for deduplication.
    """
    job_url = job.get("job_url", "")

    # Search for existing page with same URL
    if job_url:
        results = client.query_database(
            database_id,
            filter={
                "property": "Job URL",
                "url": {"equals": job_url},
            },
        )
        if results:
            page_id = results[0]["id"]
            client.update_page(page_id, build_job_properties(job))
            return page_id, False

    # Create new
    page = client.create_page(database_id, build_job_properties(job))
    return page["id"], True


def update_job_status(client: NotionClient, page_id: str, status: str) -> None:
    """Update the Status field of a job page."""
    client.update_page(page_id, {"Status": _select(status)})


def update_job_score(client: NotionClient, page_id: str, score: int, notes: str = "") -> None:
    """Update score and notes for a job."""
    props: dict = {"Score": _number(score)}
    if notes:
        props["Notes"] = _text(notes)
    client.update_page(page_id, props)


def get_jobs_by_status(client: NotionClient, database_id: str, status: str) -> list[dict]:
    """Return all jobs with a given status, sorted by score desc."""
    return client.query_database(
        database_id,
        filter={"property": "Status", "select": {"equals": status}},
        sorts=[{"property": "Score", "direction": "descending"}],
    )


def get_unscored_jobs(client: NotionClient, database_id: str) -> list[dict]:
    """Return jobs with no score set yet."""
    return client.query_database(
        database_id,
        filter={"property": "Score", "number": {"is_empty": True}},
    )
