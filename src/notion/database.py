"""Notion database schema — create and manage the job tracking database."""

from __future__ import annotations

from .client import NotionClient

# The full schema for the job tracking database
JOB_DB_PROPERTIES = {
    "Job Title": {"title": {}},
    "Company": {"rich_text": {}},
    "Location": {"rich_text": {}},
    "Score": {"number": {"format": "number"}},
    "Status": {
        "select": {
            "options": [
                {"name": "New", "color": "blue"},
                {"name": "Reviewing", "color": "yellow"},
                {"name": "Tailored", "color": "orange"},
                {"name": "Applied", "color": "green"},
                {"name": "Rejected", "color": "red"},
                {"name": "Interview", "color": "purple"},
            ]
        }
    },
    "Job URL": {"url": {}},
    "Apply URL": {"url": {}},
    "Source": {
        "select": {
            "options": [
                {"name": "LinkedIn", "color": "blue"},
                {"name": "Indeed", "color": "default"},
                {"name": "Glassdoor", "color": "green"},
                {"name": "Google", "color": "red"},
                {"name": "ZipRecruiter", "color": "orange"},
                {"name": "GaijinPot", "color": "purple"},
                {"name": "Daijob", "color": "pink"},
                {"name": "JREC-IN", "color": "gray"},
                {"name": "Other", "color": "default"},
            ]
        }
    },
    "Salary": {"rich_text": {}},
    "Posted Date": {"date": {}},
    "Found Date": {"date": {}},
    "Notes": {"rich_text": {}},
    "Tags": {"multi_select": {}},
}


def create_job_database(client: NotionClient, parent_page_id: str, name: str = "Job Hunt") -> str:
    """Create the job tracking database and return its ID."""
    db = client.create_database(
        parent_page_id=parent_page_id,
        title=name,
        properties=JOB_DB_PROPERTIES,
    )
    return db["id"]


def ensure_database_schema(client: NotionClient, database_id: str) -> None:
    """Verify database exists and is accessible (no-op if fine)."""
    client.get_database(database_id)
