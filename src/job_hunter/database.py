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
    visa_sponsorship: bool | None = None
    remote_policy: str | None = None
    tech_stack: str | None = None
    seniority: str | None = None
    contract_type: str | None = None
    team_size: str | None = None
    benefits: str | None = None
    enrichment_raw: bool | None = None
    resume_path: str | None = None
    cover_letter_path: str | None = None
    evaluation: str | None = None  # JSON — full evaluation report
    outreach: str | None = None  # JSON — LinkedIn outreach messages
    research_data: str | None = None  # JSON — structured company research
    keywords: str | None = None  # JSON — ATS keywords + coverage %
    negotiation: str | None = None  # JSON — comp data + negotiation scripts


class JobDB:
    def __init__(self, db_path: Path | str):
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self._create_tables()
        self._migrate_schema()

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
                visa_sponsorship BOOLEAN,
                remote_policy TEXT,
                tech_stack TEXT,
                seniority TEXT,
                contract_type TEXT,
                team_size TEXT,
                benefits TEXT,
                enrichment_raw BOOLEAN,
                resume_path TEXT,
                cover_letter_path TEXT,
                evaluation TEXT,
                outreach TEXT,
                research_data TEXT,
                keywords TEXT,
                negotiation TEXT
            )
        """)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS story_bank (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                theme TEXT,
                situation TEXT,
                task TEXT,
                action TEXT,
                result TEXT,
                reflection TEXT,
                tags TEXT,
                best_for TEXT,
                source_job_url TEXT,
                created_at TEXT
            )
        """)
        self.conn.commit()

    def _migrate_schema(self):
        """Add new columns to existing databases (idempotent)."""
        new_columns = [
            ("evaluation", "TEXT"),
            ("outreach", "TEXT"),
            ("research_data", "TEXT"),
            ("keywords", "TEXT"),
            ("negotiation", "TEXT"),
        ]
        for col_name, col_type in new_columns:
            try:
                self.conn.execute(
                    f"ALTER TABLE jobs ADD COLUMN {col_name} {col_type}"
                )
            except sqlite3.OperationalError:
                pass  # column already exists
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

    def get_unevaluated_jobs(self, min_score: int = 5) -> list[Job]:
        """Scored jobs that don't yet have an evaluation."""
        rows = self.conn.execute(
            "SELECT * FROM jobs WHERE score >= ? AND evaluation IS NULL",
            (min_score,),
        ).fetchall()
        return [Job(**dict(r)) for r in rows]

    def get_evaluated_jobs(self, min_score: int = 0) -> list[Job]:
        """Jobs that have evaluation data."""
        rows = self.conn.execute(
            "SELECT * FROM jobs WHERE evaluation IS NOT NULL AND (score >= ? OR score IS NULL)",
            (min_score,),
        ).fetchall()
        return [Job(**dict(r)) for r in rows]

    def get_jobs_for_comparison(self, min_score: int = 5, limit: int = 20) -> list[Job]:
        """Scored + evaluated jobs ordered by score descending."""
        rows = self.conn.execute(
            "SELECT * FROM jobs WHERE score >= ? AND evaluation IS NOT NULL "
            "ORDER BY score DESC LIMIT ?",
            (min_score, limit),
        ).fetchall()
        return [Job(**dict(r)) for r in rows]

    def get_stats(self) -> dict:
        stats = {}
        for s in ("new", "enriched", "scored", "tailored", "synced", "applied", "rejected"):
            row = self.conn.execute("SELECT COUNT(*) FROM jobs WHERE status = ?", (s,)).fetchone()
            stats[s] = row[0]
        stats["total"] = self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        stats["evaluated"] = self.conn.execute(
            "SELECT COUNT(*) FROM jobs WHERE evaluation IS NOT NULL"
        ).fetchone()[0]
        stats["stories"] = self.conn.execute(
            "SELECT COUNT(*) FROM story_bank"
        ).fetchone()[0]
        return stats

    def close(self):
        self.conn.close()


class StoryBankDB:
    """STAR story bank backed by the same SQLite database."""

    def __init__(self, db_path: Path | str):
        self.db_path = str(db_path)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.row_factory = sqlite3.Row
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS story_bank (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                title TEXT NOT NULL,
                theme TEXT,
                situation TEXT,
                task TEXT,
                action TEXT,
                result TEXT,
                reflection TEXT,
                tags TEXT,
                best_for TEXT,
                source_job_url TEXT,
                created_at TEXT
            )
        """)
        self.conn.commit()

    def add_story(self, story: dict) -> int:
        """Insert a story and return its id."""
        story.setdefault("created_at", datetime.now().isoformat())
        columns = ", ".join(story.keys())
        placeholders = ", ".join(["?"] * len(story))
        cur = self.conn.execute(
            f"INSERT INTO story_bank ({columns}) VALUES ({placeholders})",
            list(story.values()),
        )
        self.conn.commit()
        return cur.lastrowid

    def get_stories(self) -> list[dict]:
        """Return all stories."""
        rows = self.conn.execute("SELECT * FROM story_bank").fetchall()
        return [dict(r) for r in rows]

    def search_stories(self, query: str) -> list[dict]:
        """Fuzzy search stories by title, theme, tags, and best_for."""
        pattern = f"%{query}%"
        rows = self.conn.execute(
            "SELECT * FROM story_bank WHERE "
            "title LIKE ? OR theme LIKE ? OR tags LIKE ? OR best_for LIKE ?",
            (pattern, pattern, pattern, pattern),
        ).fetchall()
        return [dict(r) for r in rows]

    def story_exists(self, title: str, situation: str) -> bool:
        """Check if a story with the same title and situation already exists."""
        row = self.conn.execute(
            "SELECT 1 FROM story_bank WHERE title = ? AND situation = ?",
            (title, situation),
        ).fetchone()
        return row is not None

    def close(self):
        self.conn.close()
