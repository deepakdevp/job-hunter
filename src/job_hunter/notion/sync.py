from __future__ import annotations

import logging
from pathlib import Path

from job_hunter.database import JobDB

try:
    from job_hunter.notion.client import NotionJobDB
    from job_hunter.notion.drive_uploader import DriveUploader
except ImportError:
    NotionJobDB = None  # type: ignore[assignment,misc]
    DriveUploader = None  # type: ignore[assignment,misc]

logger = logging.getLogger(__name__)


def push_jobs_to_notion(
    db: JobDB,
    notion: NotionJobDB,
    drive: DriveUploader | None = None,
    on_progress=None,
    new_db_only: bool = False,
) -> tuple[int, int]:
    """Push new/updated jobs from local DB to Notion.

    If new_db_only=True, only push jobs that have never been synced (no notion_page_id).
    Returns (created_count, updated_count).
    """
    # Get all jobs that should be synced
    all_jobs = []
    for status in (
        "new",
        "enriched",
        "scored",
        "tailored",
        "synced",
        "applied",
        "reviewing",
        "phone_screen",
        "interview",
        "offer",
    ):
        all_jobs.extend(db.get_jobs_by_status(status))

    # When syncing to a brand new DB, only push jobs that haven't been synced before
    if new_db_only:
        all_jobs = [j for j in all_jobs if not j.notion_page_id]

    total = len(all_jobs)
    created = 0
    updated = 0
    done = 0

    for job in all_jobs:
        resume_url = None
        cover_letter_url = None

        # Upload PDFs to Drive if available, otherwise use local file:// links
        if drive:
            if job.resume_path and Path(job.resume_path).exists():
                resume_url = drive.upload_resume(Path(job.resume_path))
            if job.cover_letter_path and Path(job.cover_letter_path).exists():
                cover_letter_url = drive.upload_cover_letter(Path(job.cover_letter_path))
        else:
            if job.resume_path and Path(job.resume_path).exists():
                resume_url = Path(job.resume_path).as_uri()
            if job.cover_letter_path and Path(job.cover_letter_path).exists():
                cover_letter_url = Path(job.cover_letter_path).as_uri()

        try:
            if job.notion_page_id:
                # Update existing page
                notion.update_page(job.notion_page_id, job, resume_url, cover_letter_url)
                updated += 1
            else:
                # Create new page
                page_id = notion.create_page(job, resume_url, cover_letter_url)
                job.notion_page_id = page_id
                if job.status not in ("applied", "reviewing", "interview", "offer"):
                    job.status = "synced"
                db.upsert_job(job)
                created += 1
        except Exception as e:
            logger.warning(f"Failed to sync {job.url} to Notion: {e}")

        done += 1
        if on_progress:
            on_progress(done, total)

    return created, updated


def pull_status_from_notion(
    db: JobDB,
    notion: NotionJobDB,
    on_progress=None,
) -> int:
    """Pull status changes from Notion back to local DB.

    Returns count of updated jobs.
    """
    pages = notion.get_all_pages()
    updated = 0
    done = 0
    total = len(pages)

    for page in pages:
        url, notion_status = notion.get_page_status(page)
        if not url:
            done += 1
            if on_progress:
                on_progress(done, total)
            continue

        job = db.get_job(url)
        if job and job.status != notion_status:
            old_status = job.status
            job.status = notion_status
            job.notion_page_id = page["id"]
            db.upsert_job(job)
            updated += 1
            logger.info(f"Status updated: {url} — {old_status} → {notion_status}")

        done += 1
        if on_progress:
            on_progress(done, total)

    return updated
