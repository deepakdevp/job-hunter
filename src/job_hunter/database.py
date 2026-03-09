from __future__ import annotations

import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime
from pathlib import Path


@dataclass
class Job:
    url: str
    title: str
    company: str
    location: str
    source: str
    status: str = "new"
    description: str | None = None
    apply_url: str | None = None
    score: int | None = None
    score_reason: str | None = None
    salary_raw: str | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    posted_date: str | None = None
    found_date: str = field(default_factory=lambda: datetime.now().isoformat())
    enrich_tier: str | None = None
    tags: str | None = None
    notion_page_id: str | None = None
    resume_path: str | None = None
    cover_letter_path: str | None = None


class JobDB:
    def __init__(self, db_path: Path | str):
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()

    def _create_tables(self):
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS jobs (
                url TEXT PRIMARY KEY,
                title TEXT NOT NULL,
                company TEXT NOT NULL,
                location TEXT,
                source TEXT,
                status TEXT DEFAULT 'new',
                description TEXT,
                apply_url TEXT,
                score INTEGER,
                score_reason TEXT,
                salary_raw TEXT,
                salary_min INTEGER,
                salary_max INTEGER,
                posted_date TEXT,
                found_date TEXT,
                enrich_tier TEXT,
                tags TEXT,
                notion_page_id TEXT,
                resume_path TEXT,
                cover_letter_path TEXT
            )
        """)
        self.conn.commit()

    def upsert_job(self, job: Job):
        data = asdict(job)
        columns = ", ".join(data.keys())
        placeholders = ", ".join(["?"] * len(data))
        updates = ", ".join(f"{k}=excluded.{k}" for k in data if k != "url")
        self.conn.execute(
            f"INSERT INTO jobs ({columns}) VALUES ({placeholders}) "
            f"ON CONFLICT(url) DO UPDATE SET {updates}",
            list(data.values()),
        )
        self.conn.commit()

    def get_job(self, url: str) -> Job | None:
        row = self.conn.execute("SELECT * FROM jobs WHERE url = ?", (url,)).fetchone()
        if row is None:
            return None
        return Job(**dict(row))

    def exists(self, url: str) -> bool:
        row = self.conn.execute("SELECT 1 FROM jobs WHERE url = ?", (url,)).fetchone()
        return row is not None

    def update_status(self, url: str, status: str):
        self.conn.execute("UPDATE jobs SET status = ? WHERE url = ?", (status, url))
        self.conn.commit()

    def get_jobs_by_status(self, status: str) -> list[Job]:
        rows = self.conn.execute("SELECT * FROM jobs WHERE status = ?", (status,)).fetchall()
        return [Job(**dict(r)) for r in rows]

    def get_unenriched_jobs(self) -> list[Job]:
        rows = self.conn.execute("SELECT * FROM jobs WHERE description IS NULL").fetchall()
        return [Job(**dict(r)) for r in rows]

    def get_unscored_jobs(self) -> list[Job]:
        rows = self.conn.execute(
            "SELECT * FROM jobs WHERE score IS NULL AND description IS NOT NULL"
        ).fetchall()
        return [Job(**dict(r)) for r in rows]

    def get_untailored_jobs(self, min_score: int = 3) -> list[Job]:
        rows = self.conn.execute(
            "SELECT * FROM jobs WHERE score >= ? AND resume_path IS NULL",
            (min_score,),
        ).fetchall()
        return [Job(**dict(r)) for r in rows]

    def get_all_urls(self) -> set[str]:
        rows = self.conn.execute("SELECT url FROM jobs").fetchall()
        return {r["url"] for r in rows}

    def get_stats(self) -> dict:
        stats = {}
        for s in ("new", "enriched", "scored", "tailored", "synced", "applied", "rejected"):
            row = self.conn.execute("SELECT COUNT(*) FROM jobs WHERE status = ?", (s,)).fetchone()
            stats[s] = row[0]
        stats["total"] = self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        return stats

    def close(self):
        self.conn.close()
