"""Tests for the FastAPI dashboard backend."""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from job_hunter.dashboard.app import create_app


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _create_db(db_path):
    """Create a fresh job-hunter database with the expected schema."""
    conn = sqlite3.connect(str(db_path))
    conn.execute("""
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
    conn.execute("""
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
    conn.commit()
    return conn


def _seed_jobs(conn):
    """Insert a set of diverse test jobs."""
    jobs = [
        {
            "url": "https://example.com/job/1",
            "title": "Backend Engineer",
            "company": "Acme Corp",
            "location": "Tokyo",
            "source": "indeed",
            "status": "new",
            "description": "Build backend services in Python.",
            "found_date": "2026-04-01T10:00:00",
            "score": None,
            "evaluation": None,
            "resume_path": None,
            "cover_letter_path": None,
            "outreach": None,
            "negotiation": None,
            "research_data": None,
            "keywords": None,
            "score_reason": None,
            "seniority": None,
            "remote_policy": None,
            "tech_stack": None,
            "visa_sponsorship": None,
            "salary_raw": None,
            "posted_date": None,
        },
        {
            "url": "https://example.com/job/2",
            "title": "Frontend Developer",
            "company": "Beta Inc",
            "location": "Osaka",
            "source": "linkedin",
            "status": "scored",
            "description": "React and TypeScript development.",
            "found_date": "2026-04-02T10:00:00",
            "score": 7,
            "score_reason": "Good skill match",
            "evaluation": json.dumps({"fit": "strong", "notes": "React expert"}),
            "resume_path": "/tmp/fake_resume.pdf",
            "cover_letter_path": None,
            "outreach": None,
            "negotiation": None,
            "research_data": None,
            "keywords": json.dumps(["React", "TypeScript"]),
            "seniority": "mid",
            "remote_policy": "hybrid",
            "tech_stack": "React, TypeScript",
            "visa_sponsorship": 1,
            "salary_raw": "8M-12M JPY",
            "posted_date": "2026-03-30",
        },
        {
            "url": "https://example.com/job/3",
            "title": "Data Scientist",
            "company": "Acme Corp",
            "location": "Remote",
            "source": "indeed",
            "status": "evaluated",
            "description": "ML model development and data pipelines.",
            "found_date": "2026-04-03T10:00:00",
            "score": 9,
            "score_reason": "Excellent match",
            "evaluation": json.dumps({"fit": "excellent", "notes": "Perfect role"}),
            "resume_path": "/tmp/fake_resume2.pdf",
            "cover_letter_path": "/tmp/fake_cl.txt",
            "outreach": json.dumps({"linkedin": "Hi, I am interested..."}),
            "negotiation": json.dumps({"target": "12M JPY"}),
            "research_data": json.dumps({"glassdoor": 4.2}),
            "keywords": json.dumps(["Python", "ML", "Data"]),
            "seniority": "senior",
            "remote_policy": "remote",
            "tech_stack": "Python, TensorFlow",
            "visa_sponsorship": 0,
            "salary_raw": "10M-15M JPY",
            "posted_date": "2026-03-28",
        },
        {
            "url": "https://example.com/job/4",
            "title": "DevOps Engineer",
            "company": "Gamma LLC",
            "location": "Tokyo",
            "source": "tokyodev",
            "status": "tailored",
            "description": "Kubernetes and CI/CD pipelines.",
            "found_date": "2026-04-03T12:00:00",
            "score": 5,
            "score_reason": "Partial match",
            "evaluation": None,
            "resume_path": None,
            "cover_letter_path": None,
            "outreach": None,
            "negotiation": None,
            "research_data": None,
            "keywords": None,
            "seniority": "mid",
            "remote_policy": "onsite",
            "tech_stack": "Kubernetes, Terraform",
            "visa_sponsorship": 1,
            "salary_raw": "7M-10M JPY",
            "posted_date": "2026-03-29",
        },
    ]
    cols = list(jobs[0].keys())
    placeholders = ", ".join(["?"] * len(cols))
    col_names = ", ".join(cols)
    for j in jobs:
        conn.execute(
            f"INSERT INTO jobs ({col_names}) VALUES ({placeholders})",
            [j[c] for c in cols],
        )
    conn.commit()


def _seed_stories(conn):
    """Insert test stories into story_bank."""
    stories = [
        {
            "title": "Led migration to microservices",
            "theme": "leadership",
            "situation": "Monolith was slowing delivery",
            "task": "Plan and execute migration",
            "action": "Designed service boundaries, led team",
            "result": "Deploy frequency 3x improvement",
            "reflection": "Communication was key",
            "tags": "architecture,leadership",
            "best_for": "senior backend roles",
            "source_job_url": "https://example.com/job/1",
            "created_at": "2026-04-01T10:00:00",
        },
        {
            "title": "Built real-time dashboard",
            "theme": "technical",
            "situation": "No visibility into system health",
            "task": "Create monitoring dashboard",
            "action": "Used WebSocket and React",
            "result": "MTTR reduced by 60%",
            "reflection": "Start simple, iterate",
            "tags": "frontend,monitoring",
            "best_for": "fullstack roles",
            "source_job_url": "https://example.com/job/2",
            "created_at": "2026-04-02T10:00:00",
        },
    ]
    cols = list(stories[0].keys())
    placeholders = ", ".join(["?"] * len(cols))
    col_names = ", ".join(cols)
    for s in stories:
        conn.execute(
            f"INSERT INTO story_bank ({col_names}) VALUES ({placeholders})",
            [s[c] for c in cols],
        )
    conn.commit()


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture
def empty_db_path(tmp_path):
    """Create an empty database (tables exist but no rows)."""
    db_path = tmp_path / "empty.db"
    conn = _create_db(db_path)
    conn.close()
    return db_path


@pytest.fixture
def seeded_db_path(tmp_path):
    """Create a database seeded with test jobs and stories."""
    db_path = tmp_path / "seeded.db"
    conn = _create_db(db_path)
    _seed_jobs(conn)
    _seed_stories(conn)
    conn.close()
    return db_path


@pytest.fixture
def empty_client(empty_db_path):
    app = create_app(db_path=empty_db_path)
    return TestClient(app)


@pytest.fixture
def client(seeded_db_path):
    app = create_app(db_path=seeded_db_path)
    return TestClient(app)


# ---------------------------------------------------------------------------
# 1. GET /api/stats
# ---------------------------------------------------------------------------

class TestStats:
    def test_stats_structure(self, client):
        resp = client.get("/api/stats")
        assert resp.status_code == 200
        data = resp.json()
        # Required top-level keys
        for key in ("total", "new", "scored", "tailored", "evaluated", "stories",
                     "by_source", "by_score", "avg_score", "top_companies"):
            assert key in data, f"Missing key: {key}"

    def test_stats_counts(self, client):
        data = client.get("/api/stats").json()
        assert data["total"] == 4
        assert data["new"] == 1
        assert data["scored"] == 1
        assert data["tailored"] == 1
        assert data["stories"] == 2
        # evaluated counts jobs with evaluation != NULL (job/2 and job/3)
        assert data["evaluated"] == 2

    def test_stats_by_source(self, client):
        data = client.get("/api/stats").json()
        assert data["by_source"]["indeed"] == 2
        assert data["by_source"]["linkedin"] == 1
        assert data["by_source"]["tokyodev"] == 1

    def test_stats_avg_score(self, client):
        data = client.get("/api/stats").json()
        # scores: 7, 9, 5 => avg = 7.0
        assert data["avg_score"] == 7.0

    def test_stats_top_companies(self, client):
        data = client.get("/api/stats").json()
        companies = {c["company"] for c in data["top_companies"]}
        assert "Acme Corp" in companies

    def test_stats_empty_db(self, empty_client):
        data = empty_client.get("/api/stats").json()
        assert data["total"] == 0
        assert data["stories"] == 0


# ---------------------------------------------------------------------------
# 2. GET /api/jobs
# ---------------------------------------------------------------------------

class TestJobs:
    def test_jobs_returns_paginated(self, client):
        resp = client.get("/api/jobs")
        assert resp.status_code == 200
        data = resp.json()
        assert "jobs" in data
        assert "total" in data
        assert "page" in data
        assert "pages" in data
        assert data["total"] == 4
        assert len(data["jobs"]) == 4

    def test_jobs_pagination(self, client):
        data = client.get("/api/jobs", params={"limit": 2, "page": 1}).json()
        assert len(data["jobs"]) == 2
        assert data["total"] == 4
        assert data["pages"] == 2

        data2 = client.get("/api/jobs", params={"limit": 2, "page": 2}).json()
        assert len(data2["jobs"]) == 2
        # No overlap in URLs
        urls_p1 = {j["url"] for j in data["jobs"]}
        urls_p2 = {j["url"] for j in data2["jobs"]}
        assert urls_p1.isdisjoint(urls_p2)

    def test_jobs_filter_by_status(self, client):
        data = client.get("/api/jobs", params={"status": "scored"}).json()
        assert data["total"] == 1
        assert data["jobs"][0]["status"] == "scored"

    def test_jobs_filter_invalid_status(self, client):
        resp = client.get("/api/jobs", params={"status": "bogus"})
        assert resp.status_code == 400

    def test_jobs_filter_by_min_score(self, client):
        data = client.get("/api/jobs", params={"min_score": 7}).json()
        assert data["total"] == 2
        for j in data["jobs"]:
            assert j["score"] >= 7

    def test_jobs_search(self, client):
        data = client.get("/api/jobs", params={"search": "Kubernetes"}).json()
        assert data["total"] == 1
        assert data["jobs"][0]["title"] == "DevOps Engineer"

    def test_jobs_search_by_company(self, client):
        data = client.get("/api/jobs", params={"search": "Acme"}).json()
        assert data["total"] == 2

    def test_jobs_combined_filters(self, client):
        data = client.get("/api/jobs", params={"min_score": 5, "search": "Tokyo"}).json()
        for j in data["jobs"]:
            assert j["score"] >= 5

    def test_jobs_has_flags(self, client):
        """Check boolean flags like has_evaluation, has_resume."""
        data = client.get("/api/jobs").json()
        by_url = {j["url"]: j for j in data["jobs"]}

        job2 = by_url["https://example.com/job/2"]
        assert job2["has_evaluation"] is True
        assert job2["has_resume"] is True
        assert job2["has_cover_letter"] is False

        job3 = by_url["https://example.com/job/3"]
        assert job3["has_evaluation"] is True
        assert job3["has_outreach"] is True
        assert job3["has_negotiation"] is True

        job1 = by_url["https://example.com/job/1"]
        assert job1["has_evaluation"] is False
        assert job1["has_resume"] is False

    def test_jobs_empty_db(self, empty_client):
        data = empty_client.get("/api/jobs").json()
        assert data["jobs"] == []
        assert data["total"] == 0


# ---------------------------------------------------------------------------
# 3. GET /api/jobs/{url}/detail
# ---------------------------------------------------------------------------

class TestJobDetail:
    def test_detail_returns_full_job(self, client):
        encoded_url = "https://example.com/job/2"
        resp = client.get(f"/api/jobs/{encoded_url}/detail")
        assert resp.status_code == 200
        data = resp.json()
        assert "job" in data
        assert data["job"]["url"] == "https://example.com/job/2"
        assert data["job"]["title"] == "Frontend Developer"

    def test_detail_parsed_json_fields(self, client):
        resp = client.get("/api/jobs/https://example.com/job/3/detail")
        data = resp.json()
        # evaluation should be parsed from JSON
        assert data["evaluation"] is not None
        assert data["evaluation"]["fit"] == "excellent"
        # outreach, research_data, keywords, negotiation parsed
        assert data["outreach"] is not None
        assert data["research_data"] is not None
        assert data["keywords"] is not None
        assert data["negotiation"] is not None

    def test_detail_null_json_fields(self, client):
        resp = client.get("/api/jobs/https://example.com/job/1/detail")
        data = resp.json()
        assert data["evaluation"] is None
        assert data["outreach"] is None

    def test_detail_invalid_url_404(self, client):
        resp = client.get("/api/jobs/https://example.com/nonexistent/detail")
        assert resp.status_code == 404

    def test_detail_empty_db_404(self, empty_client):
        resp = empty_client.get("/api/jobs/https://example.com/job/1/detail")
        assert resp.status_code == 404


# ---------------------------------------------------------------------------
# 4. GET /api/stories
# ---------------------------------------------------------------------------

class TestStories:
    def test_stories_returns_list(self, client):
        resp = client.get("/api/stories")
        assert resp.status_code == 200
        data = resp.json()
        assert "stories" in data
        assert len(data["stories"]) == 2

    def test_stories_content(self, client):
        stories = client.get("/api/stories").json()["stories"]
        titles = {s["title"] for s in stories}
        assert "Led migration to microservices" in titles
        assert "Built real-time dashboard" in titles

    def test_stories_empty_db(self, empty_client):
        data = empty_client.get("/api/stories").json()
        assert data["stories"] == []


# ---------------------------------------------------------------------------
# 5. GET /api/stories/search
# ---------------------------------------------------------------------------

class TestStoriesSearch:
    def test_search_by_theme(self, client):
        data = client.get("/api/stories/search", params={"q": "leadership"}).json()
        assert len(data["stories"]) == 1
        assert data["stories"][0]["theme"] == "leadership"

    def test_search_by_tags(self, client):
        data = client.get("/api/stories/search", params={"q": "frontend"}).json()
        assert len(data["stories"]) == 1

    def test_search_by_title(self, client):
        data = client.get("/api/stories/search", params={"q": "migration"}).json()
        assert len(data["stories"]) == 1

    def test_search_by_best_for(self, client):
        data = client.get("/api/stories/search", params={"q": "fullstack"}).json()
        assert len(data["stories"]) == 1

    def test_search_no_results(self, client):
        data = client.get("/api/stories/search", params={"q": "blockchain"}).json()
        assert data["stories"] == []

    def test_search_empty_db(self, empty_client):
        data = empty_client.get("/api/stories/search", params={"q": "test"}).json()
        assert data["stories"] == []


# ---------------------------------------------------------------------------
# 6. GET /api/timeline
# ---------------------------------------------------------------------------

class TestTimeline:
    def test_timeline_returns_daily(self, client):
        resp = client.get("/api/timeline")
        assert resp.status_code == 200
        data = resp.json()
        assert "daily" in data
        assert "statuses" in data
        assert isinstance(data["daily"], list)
        assert len(data["daily"]) > 0

    def test_timeline_daily_structure(self, client):
        daily = client.get("/api/timeline").json()["daily"]
        for entry in daily:
            assert "date" in entry
            assert "discovered" in entry

    def test_timeline_statuses(self, client):
        statuses = client.get("/api/timeline").json()["statuses"]
        # We have: new(1), scored(1), evaluated(1), tailored(1)
        assert statuses["new"] == 1
        assert statuses["scored"] == 1

    def test_timeline_scored_counted(self, client):
        """Jobs with status scored/evaluated/tailored count as 'scored' in daily."""
        daily = client.get("/api/timeline").json()["daily"]
        total_scored = sum(d.get("scored", 0) for d in daily)
        # job/2 (scored), job/3 (evaluated), job/4 (tailored) = 3
        assert total_scored == 3

    def test_timeline_empty_db(self, empty_client):
        data = empty_client.get("/api/timeline").json()
        assert data["daily"] == []
        assert data["statuses"] == {}


# ---------------------------------------------------------------------------
# 7. GET /api/comparison
# ---------------------------------------------------------------------------

class TestComparison:
    def test_comparison_returns_jobs(self, client):
        resp = client.get("/api/comparison")
        assert resp.status_code == 200
        data = resp.json()
        assert "jobs" in data
        # Default min_score=5; job/2 (score=7, has eval) and job/3 (score=9, has eval)
        assert len(data["jobs"]) == 2

    def test_comparison_has_parsed_evaluation(self, client):
        jobs = client.get("/api/comparison").json()["jobs"]
        for j in jobs:
            assert j["evaluation"] is not None
            assert isinstance(j["evaluation"], dict)

    def test_comparison_ordered_by_score_desc(self, client):
        jobs = client.get("/api/comparison").json()["jobs"]
        scores = [j["score"] for j in jobs]
        assert scores == sorted(scores, reverse=True)

    def test_comparison_respects_min_score(self, client):
        data = client.get("/api/comparison", params={"min_score": 8}).json()
        # Only job/3 has score 9 with evaluation
        assert len(data["jobs"]) == 1
        assert data["jobs"][0]["score"] == 9

    def test_comparison_respects_limit(self, client):
        data = client.get("/api/comparison", params={"min_score": 5, "limit": 1}).json()
        assert len(data["jobs"]) == 1

    def test_comparison_empty_db(self, empty_client):
        data = empty_client.get("/api/comparison").json()
        assert data["jobs"] == []


# ---------------------------------------------------------------------------
# 8. GET / (index)
# ---------------------------------------------------------------------------

class TestIndex:
    def test_index_returns_200(self, client):
        resp = client.get("/")
        assert resp.status_code == 200

    def test_index_returns_html(self, client):
        resp = client.get("/")
        assert "text/html" in resp.headers["content-type"]


# ---------------------------------------------------------------------------
# 9. Empty DB returns empty results, not errors
# ---------------------------------------------------------------------------

class TestEmptyDB:
    """Verify all endpoints return gracefully on an empty database."""

    def test_all_endpoints_succeed(self, empty_client):
        endpoints = [
            "/api/stats",
            "/api/jobs",
            "/api/stories",
            "/api/stories/search?q=test",
            "/api/timeline",
            "/api/comparison",
        ]
        for ep in endpoints:
            resp = empty_client.get(ep)
            assert resp.status_code == 200, f"{ep} returned {resp.status_code}"


# ---------------------------------------------------------------------------
# 10. Invalid job URL returns 404
# ---------------------------------------------------------------------------

class TestNotFound:
    def test_nonexistent_job_detail_404(self, client):
        resp = client.get("/api/jobs/https://example.com/does-not-exist/detail")
        assert resp.status_code == 404

    def test_nonexistent_job_resume_404(self, client):
        resp = client.get("/api/jobs/https://example.com/does-not-exist/resume")
        assert resp.status_code == 404

    def test_nonexistent_job_cover_letter_404(self, client):
        resp = client.get("/api/jobs/https://example.com/does-not-exist/cover-letter")
        assert resp.status_code == 404
