"""FastAPI dashboard backend for job-hunter.

Serves both REST API endpoints and a static HTML dashboard.
"""

from __future__ import annotations

import asyncio
import json
import sqlite3
import uuid
from collections import Counter, defaultdict
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

# ---------------------------------------------------------------------------
# Background task tracking
# ---------------------------------------------------------------------------

_tasks: dict[str, dict] = {}  # task_id -> {status, result, error, type}
_executor = ThreadPoolExecutor(max_workers=2)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

_STATIC_DIR = Path(__file__).parent / "static"

_VALID_STATUSES = {
    "new",
    "enriched",
    "scored",
    "evaluated",
    "tailored",
    "synced",
    "applied",
    "rejected",
    "filtered",
    "apply_failed",
    "closed",
    "discarded",
    "interviewing",
    "offered",
    "apply_pending",
}
_VALID_SORT_FIELDS = {
    "score",
    "title",
    "company",
    "location",
    "source",
    "status",
    "found_date",
    "posted_date",
}


def _safe_json(raw: str | None) -> dict | list | None:
    """Parse a JSON string, returning None on failure."""
    if not raw:
        return None
    try:
        return json.loads(raw)
    except (json.JSONDecodeError, TypeError):
        return None


def _encode_url(url: str) -> str:
    """Encode a job URL for use as a path parameter."""
    return quote(url, safe="")


def _decode_url(encoded: str) -> str:
    """Decode a URL-encoded job URL path parameter."""
    return unquote(encoded)


def _row_to_dict(row: sqlite3.Row) -> dict:
    """Convert a sqlite3.Row to a plain dict."""
    return dict(row)


def _score_bucket(score: int | None) -> str:
    """Map a numeric score to a bucket label."""
    if score is None:
        return "unscored"
    if score <= 2:
        return "0-2"
    if score <= 4:
        return "3-4"
    if score <= 6:
        return "5-6"
    if score <= 8:
        return "7-8"
    return "9-10"


# ---------------------------------------------------------------------------
# Pydantic request models
# ---------------------------------------------------------------------------


class StatusUpdate(BaseModel):
    status: str


class NoteUpdate(BaseModel):
    note: str


class BatchStatusUpdate(BaseModel):
    urls: list[str]
    status: str


class EvaluateRequest(BaseModel):
    job_url: str | None = None
    min_score: int = 5


class OutreachRequest(BaseModel):
    job_url: str


class NegotiateRequest(BaseModel):
    job_url: str


class PipelineRequest(BaseModel):
    stages: list[str] = ["discover", "enrich", "score", "evaluate", "tailor", "sync"]


class CompareRequest(BaseModel):
    min_score: int = 5
    limit: int = 10


class ApplyRequest(BaseModel):
    job_url: str | None = None
    dry_run: bool = False
    limit: int | None = None


# ---------------------------------------------------------------------------
# LLM + config helper
# ---------------------------------------------------------------------------


def _get_llm_and_profile(config_dir):
    """Load config, return (llm, profile) or raise."""
    from job_hunter.config import load_config
    from job_hunter.llm.base import get_provider

    config = load_config(config_dir)
    llm = get_provider(config.llm_provider, api_key=config.llm_api_key, model=config.llm_model)
    return llm, config.profile


# ---------------------------------------------------------------------------
# Background task runner functions
# ---------------------------------------------------------------------------


def _run_evaluate_task(task_id, db_path, config_dir, job_url, min_score):
    """Run evaluation in a background thread."""
    try:
        _tasks[task_id]["status"] = "running"
        from job_hunter.database import JobDB
        from job_hunter.evaluate.engine import run_evaluation
        from job_hunter.stories.bank import add_stories_to_bank, extract_stories_from_evaluation

        db = JobDB(db_path)
        llm, profile = _get_llm_and_profile(config_dir)
        evaluated, total = asyncio.run(
            run_evaluation(db, profile, llm, min_score=min_score, job_url=job_url)
        )

        # Extract stories from evaluated jobs
        stories_added = 0
        for job in db.get_evaluated_jobs(min_score=min_score):
            if job.evaluation:
                try:
                    eval_data = json.loads(job.evaluation)
                    new_stories = asyncio.run(
                        extract_stories_from_evaluation(eval_data, job.url)
                    )
                    if new_stories:
                        stories_added += add_stories_to_bank(db_path, new_stories)
                except Exception:
                    pass
        db.close()
        _tasks[task_id] = {
            "status": "completed",
            "result": {
                "evaluated": evaluated,
                "total": total,
                "stories_added": stories_added,
            },
            "type": "evaluate",
        }
    except Exception as e:
        _tasks[task_id] = {"status": "failed", "error": str(e), "type": "evaluate"}


def _run_outreach_task(task_id, db_path, config_dir, job_url):
    """Run outreach generation in a background thread."""
    try:
        _tasks[task_id]["status"] = "running"
        from job_hunter.database import JobDB
        from job_hunter.outreach.generator import run_outreach

        db = JobDB(db_path)
        llm, profile = _get_llm_and_profile(config_dir)
        result = asyncio.run(run_outreach(db, profile, llm, job_url))
        db.close()
        _tasks[task_id] = {
            "status": "completed",
            "result": {
                "targets": len(result.get("targets", [])),
                "error": result.get("error"),
            },
            "type": "outreach",
        }
    except Exception as e:
        _tasks[task_id] = {"status": "failed", "error": str(e), "type": "outreach"}


def _run_negotiate_task(task_id, db_path, config_dir, job_url):
    """Run negotiation intelligence in a background thread."""
    try:
        _tasks[task_id]["status"] = "running"
        from job_hunter.database import JobDB
        from job_hunter.negotiate.intelligence import run_negotiation

        db = JobDB(db_path)
        llm, profile = _get_llm_and_profile(config_dir)
        result = asyncio.run(run_negotiation(db, profile, llm, job_url))
        db.close()
        _tasks[task_id] = {
            "status": "completed",
            "result": {
                "has_market_data": "market_data" in result,
                "scripts_count": len(result.get("scripts", [])),
                "error": result.get("error"),
            },
            "type": "negotiate",
        }
    except Exception as e:
        _tasks[task_id] = {"status": "failed", "error": str(e), "type": "negotiate"}


def _run_pipeline_task(task_id, db_path, config_dir, stages):
    """Run pipeline stages sequentially in a background thread."""
    try:
        _tasks[task_id]["status"] = "running"
        from job_hunter.config import load_config

        config = load_config(config_dir)
        data_dir = config.data_dir

        stage_results = []
        valid_stages = {
            "discover", "enrich", "score", "evaluate", "tailor", "sync", "apply",
        }

        from job_hunter.pipeline import (
            _run_apply,
            _run_discover,
            _run_enrich,
            _run_evaluate,
            _run_score,
            _run_sync,
            _run_tailor,
        )

        stage_funcs = {
            "discover": lambda: _run_discover(config_dir, data_dir),
            "enrich": lambda: _run_enrich(config_dir, data_dir),
            "score": lambda: _run_score(config_dir, data_dir),
            "evaluate": lambda: _run_evaluate(config_dir, data_dir),
            "tailor": lambda: _run_tailor(config_dir, data_dir),
            "sync": lambda: _run_sync(data_dir),
            "apply": lambda: _run_apply(config_dir, data_dir, dry_run=False, confirm_submit=True),
        }

        for stage_name in stages:
            if stage_name not in valid_stages:
                stage_results.append(
                    {"stage": stage_name, "success": False, "detail": "unknown stage"}
                )
                continue
            try:
                result = stage_funcs[stage_name]()
                stage_results.append(
                    {
                        "stage": result.name,
                        "success": result.success,
                        "detail": result.detail,
                        "error": result.error,
                    }
                )
            except Exception as e:
                stage_results.append(
                    {"stage": stage_name, "success": False, "detail": "", "error": str(e)}
                )

        _tasks[task_id] = {
            "status": "completed",
            "result": {"stages": stage_results},
            "type": "pipeline",
        }
    except Exception as e:
        _tasks[task_id] = {"status": "failed", "error": str(e), "type": "pipeline"}


def _run_compare_task(task_id, db_path, config_dir, min_score, limit):
    """Run job comparison in a background thread."""
    try:
        _tasks[task_id]["status"] = "running"
        from job_hunter.database import JobDB
        from job_hunter.evaluate.compare import compare_jobs

        db = JobDB(db_path)
        llm, profile = _get_llm_and_profile(config_dir)

        # Get evaluated jobs above min_score
        jobs = db.get_evaluated_jobs(min_score=min_score)[:limit]
        if not jobs:
            db.close()
            _tasks[task_id] = {
                "status": "completed",
                "result": {"jobs_compared": 0, "comparison": []},
                "type": "compare",
            }
            return

        results = asyncio.run(compare_jobs(jobs, profile, llm))
        db.close()
        _tasks[task_id] = {
            "status": "completed",
            "result": {"jobs_compared": len(results), "comparison": results},
            "type": "compare",
        }
    except Exception as e:
        _tasks[task_id] = {"status": "failed", "error": str(e), "type": "compare"}


def _run_apply_task(task_id, db_path, config_dir, job_url=None, dry_run=False, limit=None):
    """Run auto-apply via Playwright in a background thread."""
    try:
        _tasks[task_id]["status"] = "running"
        import time
        from job_hunter.database import JobDB
        from job_hunter.apply.applicant import Applicant

        _, profile = _get_llm_and_profile(config_dir)
        db = JobDB(db_path)

        # Try to get LLM for field mapping (optional)
        llm = None
        try:
            llm, _ = _get_llm_and_profile(config_dir)
        except Exception:
            pass

        data_dir = Path(db_path).parent
        applicant = Applicant(
            profile=profile,
            session_dir=data_dir / "sessions",
            llm=llm,
            log_path=data_dir / "output" / "apply_log.json",
            dry_run=dry_run,
            confirm_submit=not dry_run,
        )

        results = []

        if job_url:
            job = db.get_job(job_url)
            if not job:
                _tasks[task_id] = {
                    "status": "failed",
                    "error": f"Job not found: {job_url}",
                    "type": "apply",
                }
                db.close()
                return
            jobs = [job]
        else:
            jobs = []
            for s in ("tailored", "synced"):
                jobs.extend(db.get_jobs_by_status(s))
            jobs = [j for j in jobs if applicant.is_eligible(j)]
            if limit:
                jobs = jobs[:limit]

        applied = 0
        for i, job in enumerate(jobs):
            result = asyncio.run(applicant.apply_to_job(job))
            status_str = result.status
            if status_str == "applied":
                job.status = "applied"
                db.upsert_job(job)
                applied += 1
            elif status_str == "dry_run":
                pass
            else:
                job.status = "apply_failed"
                db.upsert_job(job)
            results.append({
                "url": job.url,
                "company": job.company,
                "title": job.title,
                "status": status_str,
                "error": result.error,
            })
            if i < len(jobs) - 1:
                time.sleep(2)

        db.close()
        _tasks[task_id] = {
            "status": "completed",
            "result": {
                "total": len(jobs),
                "applied": applied,
                "dry_run": dry_run,
                "results": results,
            },
            "type": "apply",
        }
    except Exception as e:
        _tasks[task_id] = {"status": "failed", "error": str(e), "type": "apply"}


# ---------------------------------------------------------------------------
# Database access layer (thin wrapper for dashboard queries)
# ---------------------------------------------------------------------------


class _DashboardDB:
    """Read-only database access tailored for dashboard queries.

    Opens a connection with ``check_same_thread=False`` and WAL mode so it
    can be shared safely across FastAPI's threadpool workers.
    """

    def __init__(self, db_path: Path):
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None

    @property
    def conn(self) -> sqlite3.Connection:
        if self._conn is None:
            if not self._db_path.exists():
                raise FileNotFoundError(f"Database not found: {self._db_path}")
            self._conn = sqlite3.connect(str(self._db_path), check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
            self._conn.execute("PRAGMA journal_mode=WAL")
        return self._conn

    # -- stats ---------------------------------------------------------------

    def get_stats(self) -> dict:
        c = self.conn
        stats: dict = {}
        for status in (
            "new",
            "enriched",
            "scored",
            "tailored",
            "synced",
            "applied",
            "rejected",
        ):
            row = c.execute("SELECT COUNT(*) FROM jobs WHERE status = ?", (status,)).fetchone()
            stats[status] = row[0]

        stats["total"] = c.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        stats["evaluated"] = c.execute(
            "SELECT COUNT(*) FROM jobs WHERE evaluation IS NOT NULL"
        ).fetchone()[0]
        stats["stories"] = c.execute("SELECT COUNT(*) FROM story_bank").fetchone()[0]

        # by_source
        rows = c.execute("SELECT source, COUNT(*) AS cnt FROM jobs GROUP BY source").fetchall()
        stats["by_source"] = {r["source"] or "unknown": r["cnt"] for r in rows}

        # by_score
        scored_rows = c.execute("SELECT score FROM jobs WHERE score IS NOT NULL").fetchall()
        buckets: dict[str, int] = Counter()
        for r in scored_rows:
            buckets[_score_bucket(r["score"])] += 1
        stats["by_score"] = dict(buckets)

        # avg_score
        avg_row = c.execute("SELECT AVG(score) FROM jobs WHERE score IS NOT NULL").fetchone()
        stats["avg_score"] = round(avg_row[0], 1) if avg_row[0] is not None else None

        # top_companies
        company_rows = c.execute(
            "SELECT company, COUNT(*) AS cnt FROM jobs GROUP BY company ORDER BY cnt DESC LIMIT 20"
        ).fetchall()
        stats["top_companies"] = [
            {"company": r["company"], "count": r["cnt"]} for r in company_rows
        ]

        return stats

    # -- jobs list -----------------------------------------------------------

    def get_jobs(
        self,
        *,
        status: str | None = None,
        min_score: int | None = None,
        search: str | None = None,
        sort: str = "found_date",
        order: str = "desc",
        page: int = 1,
        limit: int = 25,
    ) -> tuple[list[dict], int]:
        """Return (jobs, total_count) with filtering, sorting, and pagination."""
        conditions: list[str] = []
        params: list = []

        if status:
            conditions.append("status = ?")
            params.append(status)
        if min_score is not None:
            conditions.append("score >= ?")
            params.append(min_score)
        if search:
            like = f"%{search}%"
            conditions.append(
                "(title LIKE ? OR company LIKE ? OR location LIKE ? OR description LIKE ?)"
            )
            params.extend([like, like, like, like])

        where = f"WHERE {' AND '.join(conditions)}" if conditions else ""

        # Validate sort/order to prevent SQL injection
        sort_col = sort if sort in _VALID_SORT_FIELDS else "found_date"
        order_dir = "ASC" if order.lower() == "asc" else "DESC"

        # Total count
        total = self.conn.execute(f"SELECT COUNT(*) FROM jobs {where}", params).fetchone()[0]

        # Paginated results
        offset = (page - 1) * limit
        rows = self.conn.execute(
            f"SELECT * FROM jobs {where} ORDER BY {sort_col} {order_dir} LIMIT ? OFFSET ?",
            [*params, limit, offset],
        ).fetchall()

        jobs = []
        for r in rows:
            d = _row_to_dict(r)
            jobs.append(
                {
                    "url": d["url"],
                    "title": d["title"],
                    "company": d["company"],
                    "location": d["location"],
                    "source": d["source"],
                    "status": d["status"],
                    "score": d["score"],
                    "score_reason": d["score_reason"],
                    "seniority": d["seniority"],
                    "remote_policy": d["remote_policy"],
                    "tech_stack": d["tech_stack"],
                    "visa_sponsorship": (
                        bool(d["visa_sponsorship"]) if d["visa_sponsorship"] is not None else None
                    ),
                    "salary_raw": d["salary_raw"],
                    "posted_date": d["posted_date"],
                    "found_date": d["found_date"],
                    "has_evaluation": d["evaluation"] is not None,
                    "has_resume": d["resume_path"] is not None,
                    "has_cover_letter": d["cover_letter_path"] is not None,
                    "has_outreach": d["outreach"] is not None,
                    "has_negotiation": d["negotiation"] is not None,
                }
            )

        return jobs, total

    # -- single job ----------------------------------------------------------

    def get_job(self, url: str) -> dict | None:
        row = self.conn.execute("SELECT * FROM jobs WHERE url = ?", (url,)).fetchone()
        return _row_to_dict(row) if row else None

    # -- stories -------------------------------------------------------------

    def get_stories(self) -> list[dict]:
        rows = self.conn.execute("SELECT * FROM story_bank").fetchall()
        return [_row_to_dict(r) for r in rows]

    def search_stories(self, query: str) -> list[dict]:
        pattern = f"%{query}%"
        rows = self.conn.execute(
            "SELECT * FROM story_bank WHERE "
            "title LIKE ? OR theme LIKE ? OR tags LIKE ? OR best_for LIKE ?",
            (pattern, pattern, pattern, pattern),
        ).fetchall()
        return [_row_to_dict(r) for r in rows]

    # -- timeline ------------------------------------------------------------

    def get_timeline(self) -> dict:
        rows = self.conn.execute(
            "SELECT found_date, status FROM jobs WHERE found_date IS NOT NULL"
        ).fetchall()

        daily_map: dict[str, dict[str, int]] = defaultdict(lambda: defaultdict(int))
        statuses: dict[str, int] = Counter()

        for r in rows:
            raw_date = r["found_date"]
            status = r["status"]
            date_str = raw_date[:10] if raw_date else "unknown"
            daily_map[date_str]["discovered"] += 1
            if status in (
                "scored",
                "evaluated",
                "tailored",
                "synced",
                "applied",
            ):
                daily_map[date_str]["scored"] += 1
            if status == "applied":
                daily_map[date_str]["applied"] += 1
            statuses[status] += 1

        daily = sorted(
            [{"date": d, **counts} for d, counts in daily_map.items()],
            key=lambda x: x["date"],
        )
        return {"daily": daily, "statuses": dict(statuses)}

    # -- comparison ----------------------------------------------------------

    def get_comparison(self, *, min_score: int = 5, limit: int = 10) -> list[dict]:
        rows = self.conn.execute(
            "SELECT * FROM jobs WHERE score >= ? AND evaluation IS NOT NULL "
            "ORDER BY score DESC LIMIT ?",
            (min_score, limit),
        ).fetchall()
        results = []
        for r in rows:
            d = _row_to_dict(r)
            results.append(
                {
                    "url": d["url"],
                    "title": d["title"],
                    "company": d["company"],
                    "location": d["location"],
                    "score": d["score"],
                    "score_reason": d["score_reason"],
                    "evaluation": _safe_json(d["evaluation"]),
                    "remote_policy": d["remote_policy"],
                    "salary_raw": d["salary_raw"],
                    "tech_stack": d["tech_stack"],
                }
            )
        return results

    # -- write helpers -------------------------------------------------------

    def update_status(self, url: str, status: str) -> bool:
        """Update a job's status. Returns True if job existed."""
        cursor = self.conn.execute("UPDATE jobs SET status = ? WHERE url = ?", (status, url))
        self.conn.commit()
        return cursor.rowcount > 0

    def add_note(self, url: str, note: str) -> bool:
        """Append a note to job's tags field. Returns True if job existed."""
        row = self.conn.execute("SELECT tags FROM jobs WHERE url = ?", (url,)).fetchone()
        if row is None:
            return False
        existing = row["tags"] or ""
        updated = f"{existing}\n[NOTE] {note}" if existing else f"[NOTE] {note}"
        self.conn.execute("UPDATE jobs SET tags = ? WHERE url = ?", (updated, url))
        self.conn.commit()
        return True

    def close(self) -> None:
        if self._conn is not None:
            self._conn.close()
            self._conn = None


# ---------------------------------------------------------------------------
# App factory
# ---------------------------------------------------------------------------


def create_app(
    db_path: str | Path,
    config_dir: str | Path | None = None,
) -> FastAPI:
    """Create and configure the FastAPI dashboard application.

    Args:
        db_path: Path to the job-hunter SQLite database.
        config_dir: Optional config directory for LLM/pipeline actions.

    Returns:
        Configured FastAPI application.
    """
    db_path = Path(db_path)
    if config_dir is not None:
        config_dir = Path(config_dir)

    app = FastAPI(
        title="job-hunter dashboard",
        version="0.1.0",
        docs_url="/docs",
        redoc_url=None,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=["*"],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # -----------------------------------------------------------------------
    # Shared DB instance
    # -----------------------------------------------------------------------

    _db = _DashboardDB(db_path)

    def get_db() -> _DashboardDB:
        return _db

    # -----------------------------------------------------------------------
    # Static files & index
    # -----------------------------------------------------------------------

    if _STATIC_DIR.is_dir():
        app.mount("/static", StaticFiles(directory=str(_STATIC_DIR)), name="static")

    @app.get("/", response_class=HTMLResponse, include_in_schema=False)
    async def index():
        index_path = _STATIC_DIR / "index.html"
        if index_path.exists():
            return HTMLResponse(content=index_path.read_text(), status_code=200)
        return HTMLResponse(
            content=(
                "<h1>job-hunter dashboard</h1>"
                "<p>No static/index.html found. Place your dashboard HTML in "
                "src/job_hunter/dashboard/static/</p>"
            ),
            status_code=200,
        )

    # -----------------------------------------------------------------------
    # API endpoints
    # -----------------------------------------------------------------------

    @app.get("/api/stats")
    async def api_stats(db: _DashboardDB = Depends(get_db)):
        try:
            return db.get_stats()
        except FileNotFoundError:
            return JSONResponse(
                content={"error": "Database not found", "total": 0},
                status_code=200,
            )
        except sqlite3.OperationalError:
            return JSONResponse(
                content={"error": "Database error", "total": 0},
                status_code=200,
            )

    @app.get("/api/jobs")
    async def api_jobs(
        db: _DashboardDB = Depends(get_db),
        status: str | None = Query(None, description="Filter by status"),
        min_score: int | None = Query(None, description="Minimum score"),
        search: str | None = Query(None, description="Full-text search"),
        sort: str = Query("found_date", description="Sort field"),
        order: str = Query("desc", description="Sort order: asc or desc"),
        page: int = Query(1, ge=1, description="Page number"),
        limit: int = Query(25, ge=1, le=200, description="Items per page"),
    ):
        if status and status not in _VALID_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status: {status}")
        try:
            jobs, total = db.get_jobs(
                status=status,
                min_score=min_score,
                search=search,
                sort=sort,
                order=order,
                page=page,
                limit=limit,
            )
            pages = (total + limit - 1) // limit if limit else 1
            return {
                "jobs": jobs,
                "total": total,
                "page": page,
                "pages": pages,
            }
        except FileNotFoundError:
            return {"jobs": [], "total": 0, "page": 1, "pages": 0}
        except sqlite3.OperationalError:
            return {"jobs": [], "total": 0, "page": 1, "pages": 0}

    @app.get("/api/jobs/{url_encoded:path}/detail")
    async def api_job_detail(url_encoded: str, db: _DashboardDB = Depends(get_db)):
        url = _decode_url(url_encoded)
        try:
            job = db.get_job(url)
        except FileNotFoundError:
            raise HTTPException(status_code=503, detail="Database not found")

        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")

        return {
            "job": job,
            "evaluation": _safe_json(job.get("evaluation")),
            "outreach": _safe_json(job.get("outreach")),
            "research_data": _safe_json(job.get("research_data")),
            "keywords": _safe_json(job.get("keywords")),
            "negotiation": _safe_json(job.get("negotiation")),
        }

    @app.get("/api/jobs/{url_encoded:path}/resume")
    async def api_job_resume(url_encoded: str, db: _DashboardDB = Depends(get_db)):
        url = _decode_url(url_encoded)
        try:
            job = db.get_job(url)
        except FileNotFoundError:
            raise HTTPException(status_code=503, detail="Database not found")

        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")

        resume_path = job.get("resume_path")
        if not resume_path:
            raise HTTPException(status_code=404, detail="No resume available for this job")

        path = Path(resume_path)
        if not path.is_file():
            raise HTTPException(status_code=404, detail="Resume file not found on disk")

        return FileResponse(
            path=str(path),
            media_type="application/pdf",
            filename=(f"resume_{job.get('company', 'unknown')}_{job.get('title', 'unknown')}.pdf"),
        )

    @app.get("/api/jobs/{url_encoded:path}/cover-letter")
    async def api_job_cover_letter(url_encoded: str, db: _DashboardDB = Depends(get_db)):
        url = _decode_url(url_encoded)
        try:
            job = db.get_job(url)
        except FileNotFoundError:
            raise HTTPException(status_code=503, detail="Database not found")

        if job is None:
            raise HTTPException(status_code=404, detail="Job not found")

        cl_path = job.get("cover_letter_path")
        if not cl_path:
            raise HTTPException(
                status_code=404,
                detail="No cover letter available for this job",
            )

        path = Path(cl_path)
        if not path.is_file():
            raise HTTPException(
                status_code=404,
                detail="Cover letter file not found on disk",
            )

        content = path.read_text(encoding="utf-8")
        return PlainTextResponse(content=content)

    @app.get("/api/stories")
    async def api_stories(db: _DashboardDB = Depends(get_db)):
        try:
            return {"stories": db.get_stories()}
        except FileNotFoundError:
            return {"stories": []}
        except sqlite3.OperationalError:
            return {"stories": []}

    @app.get("/api/stories/search")
    async def api_stories_search(
        q: str = Query(..., min_length=1, description="Search query"),
        db: _DashboardDB = Depends(get_db),
    ):
        try:
            return {"stories": db.search_stories(q)}
        except FileNotFoundError:
            return {"stories": []}
        except sqlite3.OperationalError:
            return {"stories": []}

    @app.get("/api/timeline")
    async def api_timeline(db: _DashboardDB = Depends(get_db)):
        try:
            return db.get_timeline()
        except FileNotFoundError:
            return {"daily": [], "statuses": {}}
        except sqlite3.OperationalError:
            return {"daily": [], "statuses": {}}

    @app.get("/api/comparison")
    async def api_comparison(
        min_score: int = Query(5, description="Minimum score"),
        limit: int = Query(10, ge=1, le=50, description="Max results"),
        db: _DashboardDB = Depends(get_db),
    ):
        try:
            return {
                "jobs": db.get_comparison(min_score=min_score, limit=limit),
            }
        except FileNotFoundError:
            return {"jobs": []}
        except sqlite3.OperationalError:
            return {"jobs": []}

    # -----------------------------------------------------------------------
    # Action (write) endpoints
    # -----------------------------------------------------------------------

    @app.patch("/api/jobs/{url_encoded:path}/status")
    async def api_update_status(
        url_encoded: str,
        body: StatusUpdate,
        db: _DashboardDB = Depends(get_db),
    ):
        if body.status not in _VALID_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status: {body.status}")
        url = _decode_url(url_encoded)
        try:
            found = db.update_status(url, body.status)
        except sqlite3.OperationalError as exc:
            raise HTTPException(status_code=500, detail=f"Database error: {exc}")
        if not found:
            raise HTTPException(status_code=404, detail="Job not found")
        return {"ok": True, "url": url, "new_status": body.status}

    @app.post("/api/jobs/{url_encoded:path}/discard")
    async def api_discard_job(
        url_encoded: str,
        db: _DashboardDB = Depends(get_db),
    ):
        url = _decode_url(url_encoded)
        try:
            found = db.update_status(url, "discarded")
        except sqlite3.OperationalError as exc:
            raise HTTPException(status_code=500, detail=f"Database error: {exc}")
        if not found:
            raise HTTPException(status_code=404, detail="Job not found")
        return {"ok": True, "url": url, "new_status": "discarded"}

    @app.post("/api/jobs/{url_encoded:path}/apply")
    async def api_apply_job(
        url_encoded: str,
        db: _DashboardDB = Depends(get_db),
    ):
        url = _decode_url(url_encoded)
        try:
            found = db.update_status(url, "apply_pending")
        except sqlite3.OperationalError as exc:
            raise HTTPException(status_code=500, detail=f"Database error: {exc}")
        if not found:
            raise HTTPException(status_code=404, detail="Job not found")
        return {
            "ok": True,
            "url": url,
            "message": f"Queued for apply. Run: hunt apply --job-url {url} --confirm",
        }

    @app.post("/api/jobs/{url_encoded:path}/note")
    async def api_add_note(
        url_encoded: str,
        body: NoteUpdate,
        db: _DashboardDB = Depends(get_db),
    ):
        url = _decode_url(url_encoded)
        try:
            found = db.add_note(url, body.note)
        except sqlite3.OperationalError as exc:
            raise HTTPException(status_code=500, detail=f"Database error: {exc}")
        if not found:
            raise HTTPException(status_code=404, detail="Job not found")
        return {"ok": True}

    @app.post("/api/jobs/batch-status")
    async def api_batch_status(
        body: BatchStatusUpdate,
        db: _DashboardDB = Depends(get_db),
    ):
        if body.status not in _VALID_STATUSES:
            raise HTTPException(status_code=400, detail=f"Invalid status: {body.status}")
        updated = 0
        try:
            for url in body.urls:
                if db.update_status(url, body.status):
                    updated += 1
        except sqlite3.OperationalError as exc:
            raise HTTPException(status_code=500, detail=f"Database error: {exc}")
        return {"ok": True, "updated": updated}

    # -----------------------------------------------------------------------
    # Pipeline action endpoints (background tasks)
    # -----------------------------------------------------------------------

    def _require_config_dir():
        """Raise 400 if config_dir was not set."""
        if config_dir is None:
            raise HTTPException(
                status_code=400,
                detail="Config directory not set. Start the dashboard with --config-dir.",
            )
        return config_dir

    @app.post("/api/actions/evaluate")
    async def api_action_evaluate(body: EvaluateRequest):
        cfg = _require_config_dir()
        task_id = str(uuid.uuid4())
        _tasks[task_id] = {"status": "pending", "type": "evaluate"}
        _executor.submit(
            _run_evaluate_task, task_id, db_path, cfg, body.job_url, body.min_score
        )
        return {"task_id": task_id, "message": "Evaluation started"}

    @app.post("/api/actions/outreach")
    async def api_action_outreach(body: OutreachRequest):
        cfg = _require_config_dir()
        task_id = str(uuid.uuid4())
        _tasks[task_id] = {"status": "pending", "type": "outreach"}
        _executor.submit(_run_outreach_task, task_id, db_path, cfg, body.job_url)
        return {"task_id": task_id, "message": "Outreach generation started"}

    @app.post("/api/actions/negotiate")
    async def api_action_negotiate(body: NegotiateRequest):
        cfg = _require_config_dir()
        task_id = str(uuid.uuid4())
        _tasks[task_id] = {"status": "pending", "type": "negotiate"}
        _executor.submit(_run_negotiate_task, task_id, db_path, cfg, body.job_url)
        return {"task_id": task_id, "message": "Negotiation intelligence started"}

    @app.post("/api/actions/pipeline")
    async def api_action_pipeline(body: PipelineRequest):
        cfg = _require_config_dir()
        task_id = str(uuid.uuid4())
        _tasks[task_id] = {"status": "pending", "type": "pipeline"}
        _executor.submit(_run_pipeline_task, task_id, db_path, cfg, body.stages)
        return {"task_id": task_id, "message": "Pipeline started"}

    @app.post("/api/actions/compare")
    async def api_action_compare(body: CompareRequest):
        cfg = _require_config_dir()
        task_id = str(uuid.uuid4())
        _tasks[task_id] = {"status": "pending", "type": "compare"}
        _executor.submit(
            _run_compare_task, task_id, db_path, cfg, body.min_score, body.limit
        )
        return {"task_id": task_id, "message": "Comparison started"}

    @app.post("/api/actions/apply")
    async def api_action_apply(body: ApplyRequest):
        cfg = _require_config_dir()
        task_id = str(uuid.uuid4())
        mode = "dry-run" if body.dry_run else "live"
        _tasks[task_id] = {"status": "pending", "type": f"apply ({mode})"}
        _executor.submit(
            _run_apply_task,
            task_id,
            db_path,
            cfg,
            body.job_url,
            body.dry_run,
            body.limit,
        )
        msg = "Auto-apply started (dry-run)" if body.dry_run else "Auto-apply started (LIVE)"
        return {"task_id": task_id, "message": msg}

    @app.get("/api/actions/tasks")
    async def api_action_tasks():
        tasks_list = [
            {"id": tid, **info} for tid, info in _tasks.items()
        ]
        return {"tasks": tasks_list}

    @app.get("/api/actions/tasks/{task_id}")
    async def api_action_task_status(task_id: str):
        if task_id not in _tasks:
            raise HTTPException(status_code=404, detail="Task not found")
        return {"id": task_id, **_tasks[task_id]}

    # -----------------------------------------------------------------------
    # Shutdown hook
    # -----------------------------------------------------------------------

    @app.on_event("shutdown")
    async def shutdown():
        _db.close()
        _executor.shutdown(wait=False)

    return app


# ---------------------------------------------------------------------------
# Standalone runner
# ---------------------------------------------------------------------------


def main() -> None:
    """Run the dashboard server standalone."""
    import argparse

    parser = argparse.ArgumentParser(description="job-hunter dashboard server")
    parser.add_argument(
        "--db",
        type=str,
        default=None,
        help="Path to the SQLite database (default: auto-detect from config)",
    )
    parser.add_argument("--host", type=str, default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8000)
    parser.add_argument("--reload", action="store_true", help="Enable auto-reload")
    parser.add_argument(
        "--config-dir",
        type=str,
        default=None,
        help="Config directory for LLM/pipeline actions (default: auto-detect)",
    )
    args = parser.parse_args()

    if args.db:
        db_path = Path(args.db)
    else:
        from job_hunter.config import get_data_dir

        db_path = get_data_dir() / "jobs.db"

    config_dir = Path(args.config_dir) if args.config_dir else None
    if config_dir is None:
        try:
            from job_hunter.config import get_config_dir

            config_dir = get_config_dir()
        except Exception:
            pass

    if not db_path.exists():
        print(f"Warning: Database not found at {db_path}. Starting with empty state.")

    import uvicorn

    app = create_app(db_path=db_path, config_dir=config_dir)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
