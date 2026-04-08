"""FastAPI dashboard backend for job-hunter.

Serves both REST API endpoints and a static HTML dashboard.
"""

from __future__ import annotations

import json
import sqlite3
from collections import Counter, defaultdict
from pathlib import Path
from urllib.parse import quote, unquote

from fastapi import Depends, FastAPI, HTTPException, Query
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, HTMLResponse, JSONResponse, PlainTextResponse
from fastapi.staticfiles import StaticFiles

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
        config_dir: Optional config directory (reserved for future use).

    Returns:
        Configured FastAPI application.
    """
    db_path = Path(db_path)

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
    # Shutdown hook
    # -----------------------------------------------------------------------

    @app.on_event("shutdown")
    async def shutdown():
        _db.close()

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
    args = parser.parse_args()

    if args.db:
        db_path = Path(args.db)
    else:
        from job_hunter.config import get_data_dir

        db_path = get_data_dir() / "jobs.db"

    if not db_path.exists():
        print(f"Warning: Database not found at {db_path}. Starting with empty state.")

    import uvicorn

    app = create_app(db_path=db_path)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
