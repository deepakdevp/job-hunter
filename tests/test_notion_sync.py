"""Tests for job_hunter.notion.sync — push/pull sync."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from job_hunter.database import Job
from job_hunter.notion.sync import push_jobs_to_notion, pull_status_from_notion


@pytest.fixture
def mock_db():
    db = MagicMock()
    return db


@pytest.fixture
def mock_notion():
    notion = MagicMock()
    return notion


@pytest.fixture
def sample_jobs():
    return [
        Job(
            url="https://example.com/job/1",
            title="Engineer",
            company="Acme",
            location="Tokyo",
            source="indeed",
            status="scored",
        ),
        Job(
            url="https://example.com/job/2",
            title="Dev",
            company="Beta Corp",
            location="Remote",
            source="linkedin",
            status="tailored",
            notion_page_id="existing-page-id",
        ),
    ]


# --- Push sync ---

def test_push_creates_new_pages(mock_db, mock_notion, sample_jobs):
    # Only return the first job (no notion_page_id) for "scored" status
    def get_by_status(status):
        if status == "scored":
            return [sample_jobs[0]]
        return []

    mock_db.get_jobs_by_status.side_effect = get_by_status
    mock_notion.create_page.return_value = "new-page-id"

    created, updated = push_jobs_to_notion(mock_db, mock_notion)

    assert created == 1
    assert updated == 0
    mock_notion.create_page.assert_called_once()
    mock_db.upsert_job.assert_called_once()
    # Job should be marked as synced
    saved_job = mock_db.upsert_job.call_args[0][0]
    assert saved_job.status == "synced"
    assert saved_job.notion_page_id == "new-page-id"


def test_push_updates_existing_pages(mock_db, mock_notion, sample_jobs):
    def get_by_status(status):
        if status == "tailored":
            return [sample_jobs[1]]
        return []

    mock_db.get_jobs_by_status.side_effect = get_by_status

    created, updated = push_jobs_to_notion(mock_db, mock_notion)

    assert created == 0
    assert updated == 1
    mock_notion.update_page.assert_called_once_with(
        "existing-page-id", sample_jobs[1], None, None
    )


def test_push_with_drive_upload(mock_db, mock_notion, tmp_path):
    resume = tmp_path / "resume.pdf"
    resume.write_bytes(b"%PDF")
    cl = tmp_path / "cover.txt"
    cl.write_text("Dear Manager")

    job = Job(
        url="https://example.com/job/3",
        title="Dev",
        company="Corp",
        location="SF",
        source="indeed",
        status="scored",
        resume_path=str(resume),
        cover_letter_path=str(cl),
    )

    def get_by_status(status):
        if status == "scored":
            return [job]
        return []

    mock_db.get_jobs_by_status.side_effect = get_by_status
    mock_notion.create_page.return_value = "page-id"

    drive = MagicMock()
    drive.upload_resume.return_value = "https://drive/resume"
    drive.upload_cover_letter.return_value = "https://drive/cl"

    created, updated = push_jobs_to_notion(mock_db, mock_notion, drive=drive)

    assert created == 1
    drive.upload_resume.assert_called_once()
    drive.upload_cover_letter.assert_called_once()
    mock_notion.create_page.assert_called_once_with(
        job, "https://drive/resume", "https://drive/cl"
    )


def test_push_preserves_applied_status(mock_db, mock_notion):
    job = Job(
        url="https://example.com/job/4",
        title="Dev",
        company="Corp",
        location="Tokyo",
        source="indeed",
        status="applied",
    )

    def get_by_status(status):
        if status == "applied":
            return [job]
        return []

    mock_db.get_jobs_by_status.side_effect = get_by_status
    mock_notion.create_page.return_value = "page-id"

    push_jobs_to_notion(mock_db, mock_notion)

    saved_job = mock_db.upsert_job.call_args[0][0]
    assert saved_job.status == "applied"  # Not overwritten to "synced"


def test_push_handles_notion_error(mock_db, mock_notion, sample_jobs):
    def get_by_status(status):
        if status == "scored":
            return [sample_jobs[0]]
        return []

    mock_db.get_jobs_by_status.side_effect = get_by_status
    mock_notion.create_page.side_effect = Exception("Notion API error")

    created, updated = push_jobs_to_notion(mock_db, mock_notion)

    assert created == 0
    assert updated == 0


def test_push_progress_callback(mock_db, mock_notion, sample_jobs):
    def get_by_status(status):
        if status == "scored":
            return sample_jobs[:1]
        if status == "tailored":
            return sample_jobs[1:]
        return []

    mock_db.get_jobs_by_status.side_effect = get_by_status
    mock_notion.create_page.return_value = "p1"

    progress_calls = []

    def on_progress(done, total):
        progress_calls.append((done, total))

    push_jobs_to_notion(mock_db, mock_notion, on_progress=on_progress)

    assert len(progress_calls) == 2
    assert progress_calls[-1] == (2, 2)


# --- Pull sync ---

def test_pull_updates_local_status(mock_db, mock_notion):
    mock_notion.get_all_pages.return_value = [
        {"id": "page-1", "properties": {}},
    ]
    mock_notion.get_page_status.return_value = ("https://example.com/job/1", "applied")

    job = Job(
        url="https://example.com/job/1",
        title="Dev",
        company="Corp",
        location="Tokyo",
        source="indeed",
        status="synced",
    )
    mock_db.get_job.return_value = job

    updated = pull_status_from_notion(mock_db, mock_notion)

    assert updated == 1
    mock_db.upsert_job.assert_called_once()
    saved = mock_db.upsert_job.call_args[0][0]
    assert saved.status == "applied"
    assert saved.notion_page_id == "page-1"


def test_pull_skips_same_status(mock_db, mock_notion):
    mock_notion.get_all_pages.return_value = [{"id": "page-1"}]
    mock_notion.get_page_status.return_value = ("https://example.com/job/1", "scored")

    job = Job(
        url="https://example.com/job/1",
        title="Dev",
        company="Corp",
        location="Tokyo",
        source="indeed",
        status="scored",
    )
    mock_db.get_job.return_value = job

    updated = pull_status_from_notion(mock_db, mock_notion)

    assert updated == 0
    mock_db.upsert_job.assert_not_called()


def test_pull_skips_unknown_jobs(mock_db, mock_notion):
    mock_notion.get_all_pages.return_value = [{"id": "page-1"}]
    mock_notion.get_page_status.return_value = ("https://unknown.com/job/99", "applied")

    mock_db.get_job.return_value = None

    updated = pull_status_from_notion(mock_db, mock_notion)

    assert updated == 0


def test_pull_skips_pages_without_url(mock_db, mock_notion):
    mock_notion.get_all_pages.return_value = [{"id": "page-1"}]
    mock_notion.get_page_status.return_value = ("", "applied")

    updated = pull_status_from_notion(mock_db, mock_notion)

    assert updated == 0
    mock_db.get_job.assert_not_called()


def test_pull_progress_callback(mock_db, mock_notion):
    mock_notion.get_all_pages.return_value = [{"id": "p1"}, {"id": "p2"}]
    mock_notion.get_page_status.side_effect = [
        ("https://example.com/1", "applied"),
        ("", "new"),
    ]
    mock_db.get_job.return_value = None

    progress_calls = []

    def on_progress(done, total):
        progress_calls.append((done, total))

    pull_status_from_notion(mock_db, mock_notion, on_progress=on_progress)

    assert len(progress_calls) == 2
    assert progress_calls[-1] == (2, 2)
