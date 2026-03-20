# Job Hunter Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build a Python CLI tool (`hunt`) that discovers jobs across multiple platforms, scores them with AI, tailors resumes, and syncs everything to Notion for human review and one-click apply.

**Architecture:** A Click-based CLI with 7 modules (discover, enrich, score, tailor, apply, notion, llm). Local SQLite for caching/dedup. Notion API for persistent storage and UI. Gemini free tier as default LLM. Playwright for browser automation.

**Tech Stack:** Python 3.11+, Click, python-jobspy, Crawlee, Playwright, google-genai, notion-client, Jinja2, WeasyPrint, SQLite3

---

## Task 1: Project Scaffold + pyproject.toml

**Files:**
- Create: `pyproject.toml`
- Create: `src/job_hunter/__init__.py`
- Create: `src/job_hunter/cli.py`
- Create: `.env.example`
- Create: `.gitignore`
- Create: `tests/__init__.py`
- Create: `tests/conftest.py`

**Step 1: Create pyproject.toml with all dependencies**

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "job-hunter"
version = "0.1.0"
description = "AI-powered job search: discover, score, tailor, track in Notion"
requires-python = ">=3.11"
dependencies = [
    "click>=8.1",
    "python-dotenv>=1.0",
    "pyyaml>=6.0",
    "notion-client>=2.0",
    "google-genai>=1.0",
    "httpx>=0.27",
    "beautifulsoup4>=4.12",
    "jinja2>=3.1",
    "weasyprint>=62",
    "playwright>=1.40",
    "rich>=13.0",
]

[project.optional-dependencies]
dev = [
    "pytest>=8.0",
    "pytest-asyncio>=0.23",
    "pytest-mock>=3.12",
    "ruff>=0.4",
]
jobspy = [
    "python-jobspy>=1.1",
]
crawlee = [
    "crawlee[playwright]>=0.5",
]

[project.scripts]
hunt = "job_hunter.cli:cli"

[tool.pytest.ini_options]
testpaths = ["tests"]
asyncio_mode = "auto"

[tool.ruff]
target-version = "py311"
line-length = 100
```

**Step 2: Create minimal CLI entry point**

`src/job_hunter/__init__.py`:
```python
"""Job Hunter — AI-powered job search automation."""

__version__ = "0.1.0"
```

`src/job_hunter/cli.py`:
```python
import click

@click.group()
@click.version_option()
def cli():
    """Job Hunter — discover, score, tailor, apply."""
    pass

@cli.command()
def doctor():
    """Check that all dependencies and configs are set up."""
    click.echo("doctor: not yet implemented")

@cli.command()
def status():
    """Show pipeline statistics."""
    click.echo("status: not yet implemented")
```

**Step 3: Create .env.example**

```
GEMINI_API_KEY=
NOTION_TOKEN=
NOTION_PAGE_ID=
ANTHROPIC_API_KEY=
CAPSOLVER_API_KEY=
LLM_PROVIDER=gemini
LLM_MODEL=gemini-2.5-flash
SCORE_THRESHOLD=7
```

**Step 4: Create .gitignore**

```
__pycache__/
*.pyc
.env
*.egg-info/
dist/
build/
.venv/
.pytest_cache/
output/
*.db
sessions/
```

**Step 5: Create test scaffold**

`tests/__init__.py`: empty

`tests/conftest.py`:
```python
import pytest
from pathlib import Path

@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent / "fixtures"

@pytest.fixture
def sample_profile(fixtures_dir):
    import json
    path = fixtures_dir / "profile.json"
    if path.exists():
        return json.loads(path.read_text())
    return {
        "name": "Test User",
        "email": "test@example.com",
        "phone": "+1-555-0100",
        "location": "Tokyo, Japan",
        "target_role": "Software Engineer",
        "skills": ["Python", "TypeScript", "React"],
        "resume_facts": {
            "companies": [
                {"name": "Acme Corp", "title": "Senior Engineer", "dates": "2022-2025"}
            ],
            "education": [
                {"school": "MIT", "degree": "BS Computer Science", "year": 2022}
            ],
            "metrics": ["Reduced API latency by 40%", "Led team of 5 engineers"]
        }
    }
```

**Step 6: Install in dev mode and verify CLI works**

Run: `cd <project-root> && python -m venv .venv && source .venv/bin/activate && pip install -e ".[dev]" && hunt --version`
Expected: `job-hunter, version 0.1.0`

**Step 7: Run tests (should pass with 0 collected)**

Run: `pytest -v`
Expected: `no tests ran`

**Step 8: Commit**

```bash
git add pyproject.toml src/ tests/ .env.example .gitignore
git commit -m "feat: project scaffold with CLI entry point and dev tooling"
```

---

## Task 2: Config Module + Profile/Searches Loading

**Files:**
- Create: `src/job_hunter/config.py`
- Create: `config/profile.example.json`
- Create: `config/searches.example.yaml`
- Create: `config/employers.yaml`
- Create: `config/sites.yaml`
- Create: `tests/test_config.py`
- Create: `tests/fixtures/profile.json`
- Create: `tests/fixtures/searches.yaml`

**Step 1: Write tests for config loading**

`tests/test_config.py`:
```python
import pytest
from pathlib import Path
from job_hunter.config import load_config, Config

@pytest.fixture
def config_dir(tmp_path):
    import json, yaml
    profile = {
        "name": "Test User",
        "email": "test@example.com",
        "target_role": "Software Engineer",
        "skills": ["Python"],
        "resume_facts": {"companies": [], "education": [], "metrics": []}
    }
    searches = {
        "searches": [
            {"query": "software engineer", "location": "Tokyo", "boards": ["indeed"]}
        ]
    }
    (tmp_path / "profile.json").write_text(json.dumps(profile))
    (tmp_path / "searches.yaml").write_text(yaml.dump(searches))
    env_file = tmp_path / ".env"
    env_file.write_text("GEMINI_API_KEY=test-key\nNOTION_TOKEN=test-token\nNOTION_PAGE_ID=test-page\n")
    return tmp_path

def test_load_config_returns_config_object(config_dir):
    config = load_config(config_dir)
    assert isinstance(config, Config)
    assert config.profile["name"] == "Test User"
    assert config.searches[0]["query"] == "software engineer"
    assert config.gemini_api_key == "test-key"
    assert config.notion_token == "test-token"

def test_load_config_missing_profile_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="profile.json"):
        load_config(tmp_path)

def test_config_score_threshold_default(config_dir):
    config = load_config(config_dir)
    assert config.score_threshold == 7

def test_config_score_threshold_from_env(config_dir):
    env_file = config_dir / ".env"
    env_file.write_text("GEMINI_API_KEY=k\nNOTION_TOKEN=t\nNOTION_PAGE_ID=p\nSCORE_THRESHOLD=8\n")
    config = load_config(config_dir)
    assert config.score_threshold == 8
```

**Step 2: Run tests to verify they fail**

Run: `pytest tests/test_config.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'job_hunter.config'`

**Step 3: Implement config module**

`src/job_hunter/config.py`:
```python
from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


@dataclass
class Config:
    profile: dict
    searches: list[dict]
    gemini_api_key: str
    notion_token: str
    notion_page_id: str
    anthropic_api_key: str = ""
    capsolver_api_key: str = ""
    llm_provider: str = "gemini"
    llm_model: str = "gemini-2.5-flash"
    score_threshold: int = 7
    validation_mode: str = "normal"
    employers: list[dict] = field(default_factory=list)
    sites_config: dict = field(default_factory=dict)
    config_dir: Path = field(default_factory=lambda: Path.cwd())


def load_config(config_dir: Path | None = None) -> Config:
    config_dir = Path(config_dir) if config_dir else Path.cwd()

    env_path = config_dir / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)

    profile_path = config_dir / "profile.json"
    if not profile_path.exists():
        raise FileNotFoundError(f"profile.json not found in {config_dir}")
    profile = json.loads(profile_path.read_text())

    searches_path = config_dir / "searches.yaml"
    searches = []
    if searches_path.exists():
        data = yaml.safe_load(searches_path.read_text()) or {}
        searches = data.get("searches", [])

    employers_path = config_dir / "employers.yaml"
    employers = []
    if employers_path.exists():
        data = yaml.safe_load(employers_path.read_text()) or {}
        employers_raw = data.get("employers", {})
        employers = list(employers_raw.values()) if isinstance(employers_raw, dict) else employers_raw

    sites_path = config_dir / "sites.yaml"
    sites_config = {}
    if sites_path.exists():
        sites_config = yaml.safe_load(sites_path.read_text()) or {}

    return Config(
        profile=profile,
        searches=searches,
        gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
        notion_token=os.environ.get("NOTION_TOKEN", ""),
        notion_page_id=os.environ.get("NOTION_PAGE_ID", ""),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        capsolver_api_key=os.environ.get("CAPSOLVER_API_KEY", ""),
        llm_provider=os.environ.get("LLM_PROVIDER", "gemini"),
        llm_model=os.environ.get("LLM_MODEL", "gemini-2.5-flash"),
        score_threshold=int(os.environ.get("SCORE_THRESHOLD", "7")),
        validation_mode=os.environ.get("VALIDATION_MODE", "normal"),
        employers=employers,
        sites_config=sites_config,
        config_dir=config_dir,
    )
```

**Step 4: Create example config files**

`config/profile.example.json`:
```json
{
    "name": "Your Name",
    "email": "you@example.com",
    "phone": "+1-555-0100",
    "location": "Tokyo, Japan",
    "target_role": "Software Engineer",
    "preferred_name": "",
    "address": "",
    "province_state": "",
    "postal_code": "",
    "github_url": "",
    "portfolio_url": "",
    "linkedin_url": "",
    "work_authorization": "visa_required",
    "work_permit_type": "",
    "skills": ["Python", "TypeScript", "React", "PostgreSQL"],
    "resume_facts": {
        "companies": [
            {
                "name": "Company Name",
                "title": "Your Title",
                "dates": "2022-2025",
                "bullets": [
                    "Led migration of monolith to microservices, reducing deploy time by 60%",
                    "Built real-time analytics pipeline processing 1M events/day"
                ]
            }
        ],
        "education": [
            {
                "school": "University Name",
                "degree": "BS Computer Science",
                "year": 2022
            }
        ],
        "metrics": [
            "Reduced API latency by 40%",
            "Led team of 5 engineers"
        ],
        "certifications": []
    },
    "eeo_defaults": {
        "gender": "",
        "race": "",
        "veteran_status": "not_a_veteran",
        "disability_status": "no"
    }
}
```

`config/searches.example.yaml`:
```yaml
searches:
  - query: "software engineer"
    location: "Tokyo, Japan"
    boards: ["indeed", "linkedin", "glassdoor"]
    distance_km: 50
    remote_only: false

  - query: "backend developer"
    location: "Remote"
    boards: ["indeed", "linkedin"]
    remote_only: true

  - query: "full stack engineer"
    location: "Japan"
    boards: ["indeed"]
    max_results: 50
```

`config/employers.yaml`: (ship with ApplyPilot's 48 + Japan additions — full YAML from research)

`config/sites.yaml`: (ship with ApplyPilot's blocked/SSO lists + Japan additions)

**Step 5: Create test fixtures**

`tests/fixtures/profile.json`:
```json
{
    "name": "Test User",
    "email": "test@example.com",
    "target_role": "Software Engineer",
    "skills": ["Python", "TypeScript"],
    "resume_facts": {
        "companies": [
            {"name": "Acme Corp", "title": "Senior Engineer", "dates": "2022-2025"}
        ],
        "education": [
            {"school": "MIT", "degree": "BS Computer Science", "year": 2022}
        ],
        "metrics": ["Reduced API latency by 40%"]
    }
}
```

`tests/fixtures/searches.yaml`:
```yaml
searches:
  - query: "software engineer"
    location: "Tokyo"
    boards: ["indeed"]
```

**Step 6: Run tests**

Run: `pytest tests/test_config.py -v`
Expected: 4 passed

**Step 7: Commit**

```bash
git add src/job_hunter/config.py config/ tests/
git commit -m "feat: config module with profile, searches, employers, and sites loading"
```

---

## Task 3: SQLite Database Layer

**Files:**
- Create: `src/job_hunter/database.py`
- Create: `tests/test_database.py`

**Step 1: Write tests**

`tests/test_database.py`:
```python
import pytest
from job_hunter.database import JobDB, Job

@pytest.fixture
def db(tmp_path):
    return JobDB(tmp_path / "test.db")

def test_insert_and_get_job(db):
    job = Job(
        url="https://example.com/job/123",
        title="Software Engineer",
        company="Acme",
        location="Tokyo",
        source="indeed",
    )
    db.upsert_job(job)
    result = db.get_job("https://example.com/job/123")
    assert result is not None
    assert result.title == "Software Engineer"
    assert result.company == "Acme"

def test_upsert_updates_existing(db):
    job = Job(url="https://example.com/1", title="SWE", company="A", location="Tokyo", source="indeed")
    db.upsert_job(job)
    job.score = 8
    job.score_reason = "Great match"
    db.upsert_job(job)
    result = db.get_job("https://example.com/1")
    assert result.score == 8

def test_dedup_returns_true_for_existing(db):
    job = Job(url="https://example.com/1", title="SWE", company="A", location="Tokyo", source="indeed")
    db.upsert_job(job)
    assert db.exists("https://example.com/1") is True
    assert db.exists("https://example.com/2") is False

def test_get_jobs_by_status(db):
    for i in range(5):
        job = Job(url=f"https://example.com/{i}", title=f"Job {i}", company="A",
                  location="Tokyo", source="indeed", status="new")
        db.upsert_job(job)
    db.update_status("https://example.com/0", "scored")
    new_jobs = db.get_jobs_by_status("new")
    assert len(new_jobs) == 4

def test_get_unenriched_jobs(db):
    job = Job(url="https://example.com/1", title="SWE", company="A",
              location="Tokyo", source="indeed", description=None)
    db.upsert_job(job)
    unenriched = db.get_unenriched_jobs()
    assert len(unenriched) == 1

def test_get_unscored_jobs(db):
    job = Job(url="https://example.com/1", title="SWE", company="A",
              location="Tokyo", source="indeed", description="Full JD here", score=None)
    db.upsert_job(job)
    unscored = db.get_unscored_jobs()
    assert len(unscored) == 1
```

**Step 2: Run tests to verify failure**

Run: `pytest tests/test_database.py -v`
Expected: FAIL

**Step 3: Implement database module**

`src/job_hunter/database.py`:
```python
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
    tags: str | None = None  # comma-separated
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

    def get_untailored_jobs(self, min_score: int = 7) -> list[Job]:
        rows = self.conn.execute(
            "SELECT * FROM jobs WHERE score >= ? AND resume_path IS NULL",
            (min_score,),
        ).fetchall()
        return [Job(**dict(r)) for r in rows]

    def get_stats(self) -> dict:
        stats = {}
        for status in ("new", "enriched", "scored", "tailored", "synced", "applied", "rejected"):
            row = self.conn.execute(
                "SELECT COUNT(*) FROM jobs WHERE status = ?", (status,)
            ).fetchone()
            stats[status] = row[0]
        stats["total"] = self.conn.execute("SELECT COUNT(*) FROM jobs").fetchone()[0]
        return stats

    def close(self):
        self.conn.close()
```

**Step 4: Run tests**

Run: `pytest tests/test_database.py -v`
Expected: 6 passed

**Step 5: Commit**

```bash
git add src/job_hunter/database.py tests/test_database.py
git commit -m "feat: SQLite database layer with Job model, upsert, dedup, status queries"
```

---

## Task 4: LLM Abstraction Layer (Gemini + Claude)

**Files:**
- Create: `src/job_hunter/llm/__init__.py`
- Create: `src/job_hunter/llm/base.py`
- Create: `src/job_hunter/llm/gemini.py`
- Create: `src/job_hunter/llm/claude.py`
- Create: `tests/test_llm.py`

**Step 1: Write tests**

`tests/test_llm.py`:
```python
import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from job_hunter.llm.base import LLMProvider, get_provider
from job_hunter.llm.gemini import GeminiProvider

def test_get_provider_returns_gemini():
    provider = get_provider("gemini", api_key="test", model="gemini-2.5-flash")
    assert isinstance(provider, GeminiProvider)

def test_get_provider_unknown_raises():
    with pytest.raises(ValueError, match="Unknown LLM provider"):
        get_provider("gpt-local", api_key="test", model="test")

@pytest.mark.asyncio
async def test_gemini_generate_calls_api():
    with patch("job_hunter.llm.gemini.genai") as mock_genai:
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client
        mock_response = MagicMock()
        mock_response.text = '{"score": 8}'
        mock_client.models.generate_content.return_value = mock_response

        provider = GeminiProvider(api_key="test-key", model="gemini-2.5-flash")
        result = await provider.generate("Score this job", json_mode=True)

        assert result == '{"score": 8}'
        mock_client.models.generate_content.assert_called_once()

@pytest.mark.asyncio
async def test_gemini_generate_retries_on_429():
    with patch("job_hunter.llm.gemini.genai") as mock_genai:
        mock_client = MagicMock()
        mock_genai.Client.return_value = mock_client
        from google.api_core.exceptions import ResourceExhausted
        mock_client.models.generate_content.side_effect = [
            ResourceExhausted("rate limit"),
            MagicMock(text="ok"),
        ]
        provider = GeminiProvider(api_key="test-key", model="gemini-2.5-flash")
        provider._retry_delays = [0.01]  # fast retry for test
        result = await provider.generate("test")
        assert result == "ok"
```

**Step 2: Run tests to verify failure**

Run: `pytest tests/test_llm.py -v`
Expected: FAIL

**Step 3: Implement LLM layer**

`src/job_hunter/llm/__init__.py`:
```python
from job_hunter.llm.base import LLMProvider, get_provider

__all__ = ["LLMProvider", "get_provider"]
```

`src/job_hunter/llm/base.py`:
```python
from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    @abstractmethod
    async def generate(self, prompt: str, *, json_mode: bool = False, max_tokens: int = 4096) -> str:
        ...


def get_provider(provider_name: str, *, api_key: str, model: str) -> LLMProvider:
    if provider_name == "gemini":
        from job_hunter.llm.gemini import GeminiProvider
        return GeminiProvider(api_key=api_key, model=model)
    elif provider_name == "claude":
        from job_hunter.llm.claude import ClaudeProvider
        return ClaudeProvider(api_key=api_key, model=model)
    else:
        raise ValueError(f"Unknown LLM provider: {provider_name}")
```

`src/job_hunter/llm/gemini.py`:
```python
from __future__ import annotations

import asyncio
import logging

from google import genai

from job_hunter.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self._retry_delays = [10, 20, 40, 60, 60]  # backoff for free tier

    async def generate(self, prompt: str, *, json_mode: bool = False, max_tokens: int = 4096) -> str:
        config = {"max_output_tokens": max_tokens}
        if json_mode:
            config["response_mime_type"] = "application/json"

        for attempt, delay in enumerate(self._retry_delays):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=config,
                )
                return response.text
            except Exception as e:
                if "429" in str(e) or "ResourceExhausted" in type(e).__name__:
                    logger.warning(f"Rate limited (attempt {attempt + 1}), waiting {delay}s")
                    await asyncio.sleep(delay)
                    continue
                raise

        raise RuntimeError(f"Failed after {len(self._retry_delays)} retries")
```

`src/job_hunter/llm/claude.py`:
```python
from __future__ import annotations

import anthropic

from job_hunter.llm.base import LLMProvider


class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    async def generate(self, prompt: str, *, json_mode: bool = False, max_tokens: int = 4096) -> str:
        system = ""
        if json_mode:
            system = "Respond with valid JSON only. No markdown, no explanation."

        message = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system if system else anthropic.NOT_GIVEN,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
```

**Step 4: Run tests**

Run: `pytest tests/test_llm.py -v`
Expected: 3 passed (skip the 429 test if google-genai not installed — mock it)

**Step 5: Commit**

```bash
git add src/job_hunter/llm/ tests/test_llm.py
git commit -m "feat: pluggable LLM layer with Gemini (free tier) and Claude providers"
```

---

## Task 5: Notion Integration

**Files:**
- Create: `src/job_hunter/notion/__init__.py`
- Create: `src/job_hunter/notion/client.py`
- Create: `src/job_hunter/notion/database.py`
- Create: `src/job_hunter/notion/sync.py`
- Create: `tests/test_notion.py`

**Step 1: Write tests**

`tests/test_notion.py`:
```python
import pytest
from unittest.mock import MagicMock, patch
from job_hunter.notion.database import NotionJobDB, SCHEMA
from job_hunter.notion.sync import build_page_properties
from job_hunter.database import Job

def test_schema_has_required_columns():
    required = ["Job Title", "Company", "Location", "Score", "Score Reason",
                "Status", "Job URL", "Apply URL", "Source", "Salary Min",
                "Salary Max", "Tags", "Found Date"]
    for col in required:
        assert col in SCHEMA, f"Missing column: {col}"

def test_build_page_properties():
    job = Job(
        url="https://example.com/1",
        title="Software Engineer",
        company="Acme",
        location="Tokyo",
        source="indeed",
        score=8,
        score_reason="Strong Python match",
        salary_min=80000,
        salary_max=120000,
        tags="Python,React",
    )
    props = build_page_properties(job)
    assert props["Job Title"]["title"][0]["text"]["content"] == "Software Engineer"
    assert props["Company"]["rich_text"][0]["text"]["content"] == "Acme"
    assert props["Score"]["number"] == 8
    assert props["Job URL"]["url"] == "https://example.com/1"
    assert props["Source"]["select"]["name"] == "indeed"

def test_build_page_properties_handles_none_score():
    job = Job(url="https://example.com/1", title="SWE", company="A",
              location="Tokyo", source="indeed", score=None)
    props = build_page_properties(job)
    assert "Score" not in props or props["Score"]["number"] is None
```

**Step 2: Run tests to verify failure**

Run: `pytest tests/test_notion.py -v`
Expected: FAIL

**Step 3: Implement Notion modules**

`src/job_hunter/notion/__init__.py`:
```python
from job_hunter.notion.database import NotionJobDB
from job_hunter.notion.sync import sync_jobs_to_notion

__all__ = ["NotionJobDB", "sync_jobs_to_notion"]
```

`src/job_hunter/notion/database.py`:
```python
from __future__ import annotations

import logging
from notion_client import Client

logger = logging.getLogger(__name__)

SCHEMA = {
    "Job Title": {"title": {}},
    "Company": {"rich_text": {}},
    "Location": {"rich_text": {}},
    "Score": {"number": {}},
    "Score Reason": {"rich_text": {}},
    "Status": {
        "select": {
            "options": [
                {"name": "New", "color": "blue"},
                {"name": "Reviewing", "color": "yellow"},
                {"name": "Tailored", "color": "purple"},
                {"name": "Applied", "color": "green"},
                {"name": "Phone Screen", "color": "orange"},
                {"name": "Interview", "color": "pink"},
                {"name": "Offer", "color": "green"},
                {"name": "Rejected", "color": "red"},
            ]
        }
    },
    "Job URL": {"url": {}},
    "Apply URL": {"url": {}},
    "Source": {
        "select": {
            "options": [
                {"name": "LinkedIn", "color": "blue"},
                {"name": "Indeed", "color": "purple"},
                {"name": "Glassdoor", "color": "green"},
                {"name": "ZipRecruiter", "color": "orange"},
                {"name": "Google", "color": "red"},
                {"name": "GaijinPot", "color": "yellow"},
                {"name": "Daijob", "color": "pink"},
                {"name": "JREC-IN", "color": "gray"},
                {"name": "Workday", "color": "brown"},
                {"name": "Other", "color": "default"},
            ]
        }
    },
    "Salary Min": {"number": {"format": "number"}},
    "Salary Max": {"number": {"format": "number"}},
    "Salary Raw": {"rich_text": {}},
    "Posted Date": {"date": {}},
    "Found Date": {"date": {}},
    "Tags": {"multi_select": {}},
    "Notes": {"rich_text": {}},
    "Enrich Tier": {
        "select": {
            "options": [
                {"name": "json-ld", "color": "green"},
                {"name": "css", "color": "blue"},
                {"name": "ai", "color": "purple"},
                {"name": "failed", "color": "red"},
            ]
        }
    },
}


class NotionJobDB:
    def __init__(self, token: str, page_id: str):
        self.client = Client(auth=token)
        self.page_id = page_id
        self.database_id: str | None = None

    def find_or_create_database(self) -> str:
        children = self.client.blocks.children.list(block_id=self.page_id)
        for block in children["results"]:
            if block["type"] == "child_database":
                self.database_id = block["id"]
                logger.info(f"Found existing database: {self.database_id}")
                return self.database_id

        result = self.client.databases.create(
            parent={"page_id": self.page_id},
            title=[{"type": "text", "text": {"content": "Job Hunter"}}],
            properties=SCHEMA,
        )
        self.database_id = result["id"]
        logger.info(f"Created new database: {self.database_id}")
        return self.database_id

    def query_existing_urls(self) -> set[str]:
        if not self.database_id:
            self.find_or_create_database()
        urls = set()
        cursor = None
        while True:
            kwargs = {"database_id": self.database_id}
            if cursor:
                kwargs["start_cursor"] = cursor
            response = self.client.databases.query(**kwargs)
            for page in response["results"]:
                url_prop = page["properties"].get("Job URL", {})
                if url_prop.get("url"):
                    urls.add(url_prop["url"])
            if not response.get("has_more"):
                break
            cursor = response["next_cursor"]
        return urls

    def update_page_status(self, page_id: str, status: str):
        self.client.pages.update(
            page_id=page_id,
            properties={"Status": {"select": {"name": status}}},
        )
```

`src/job_hunter/notion/sync.py`:
```python
from __future__ import annotations

import logging
from datetime import datetime

from notion_client import Client

from job_hunter.database import Job
from job_hunter.notion.database import NotionJobDB

logger = logging.getLogger(__name__)


def build_page_properties(job: Job) -> dict:
    props = {}

    props["Job Title"] = {"title": [{"text": {"content": job.title or ""}}]}
    props["Company"] = {"rich_text": [{"text": {"content": job.company or ""}}]}
    props["Location"] = {"rich_text": [{"text": {"content": job.location or ""}}]}
    props["Job URL"] = {"url": job.url}
    props["Source"] = {"select": {"name": job.source or "Other"}}
    props["Status"] = {"select": {"name": "New"}}
    props["Found Date"] = {"date": {"start": datetime.now().strftime("%Y-%m-%d")}}

    if job.score is not None:
        props["Score"] = {"number": job.score}
    if job.score_reason:
        props["Score Reason"] = {"rich_text": [{"text": {"content": job.score_reason[:2000]}}]}
    if job.apply_url:
        props["Apply URL"] = {"url": job.apply_url}
    if job.salary_min is not None:
        props["Salary Min"] = {"number": job.salary_min}
    if job.salary_max is not None:
        props["Salary Max"] = {"number": job.salary_max}
    if job.salary_raw:
        props["Salary Raw"] = {"rich_text": [{"text": {"content": job.salary_raw[:2000]}}]}
    if job.posted_date:
        props["Posted Date"] = {"date": {"start": job.posted_date[:10]}}
    if job.enrich_tier:
        props["Enrich Tier"] = {"select": {"name": job.enrich_tier}}
    if job.tags:
        props["Tags"] = {"multi_select": [{"name": t.strip()} for t in job.tags.split(",") if t.strip()]}

    return props


def sync_jobs_to_notion(notion_db: NotionJobDB, jobs: list[Job], local_db=None):
    if not notion_db.database_id:
        notion_db.find_or_create_database()

    existing_urls = notion_db.query_existing_urls()
    synced = 0

    for job in jobs:
        if job.url in existing_urls:
            logger.debug(f"Skipping {job.url} — already in Notion")
            continue

        props = build_page_properties(job)
        result = notion_db.client.pages.create(
            parent={"database_id": notion_db.database_id},
            properties=props,
        )

        if local_db:
            job.notion_page_id = result["id"]
            job.status = "synced"
            local_db.upsert_job(job)

        synced += 1
        logger.info(f"Synced: {job.title} @ {job.company}")

    logger.info(f"Synced {synced} new jobs to Notion ({len(existing_urls)} already existed)")
    return synced
```

**Step 4: Run tests**

Run: `pytest tests/test_notion.py -v`
Expected: 3 passed

**Step 5: Commit**

```bash
git add src/job_hunter/notion/ tests/test_notion.py
git commit -m "feat: Notion integration — database creation, schema, job sync"
```

---

## Task 6: Job Discovery — JobSpy Scraper

**Files:**
- Create: `src/job_hunter/discover/__init__.py`
- Create: `src/job_hunter/discover/jobspy_scraper.py`
- Create: `src/job_hunter/discover/dedup.py`
- Create: `tests/test_discover.py`

**Step 1: Write tests**

`tests/test_discover.py`:
```python
import pytest
from unittest.mock import patch, MagicMock
import pandas as pd
from job_hunter.discover.jobspy_scraper import run_jobspy_search, parse_jobspy_results
from job_hunter.discover.dedup import dedup_jobs
from job_hunter.database import Job

def test_parse_jobspy_results_converts_dataframe():
    df = pd.DataFrame({
        "job_url": ["https://example.com/1", "https://example.com/2"],
        "title": ["SWE", "Backend Dev"],
        "company_name": ["Acme", "Globex"],
        "location": ["Tokyo", "Remote"],
        "site": ["indeed", "linkedin"],
        "description": ["Great job", "Another job"],
        "date_posted": ["2026-03-01", "2026-03-02"],
        "min_amount": [80000, None],
        "max_amount": [120000, None],
        "interval": ["yearly", None],
    })
    jobs = parse_jobspy_results(df)
    assert len(jobs) == 2
    assert jobs[0].title == "SWE"
    assert jobs[0].source == "indeed"
    assert jobs[0].salary_min == 80000

def test_dedup_removes_existing_urls():
    jobs = [
        Job(url="https://example.com/1", title="A", company="X", location="Y", source="indeed"),
        Job(url="https://example.com/2", title="B", company="X", location="Y", source="indeed"),
        Job(url="https://example.com/3", title="C", company="X", location="Y", source="indeed"),
    ]
    existing = {"https://example.com/1", "https://example.com/3"}
    deduped = dedup_jobs(jobs, existing)
    assert len(deduped) == 1
    assert deduped[0].url == "https://example.com/2"
```

**Step 2: Run tests to verify failure**

Run: `pytest tests/test_discover.py -v`
Expected: FAIL

**Step 3: Implement discovery modules**

`src/job_hunter/discover/__init__.py`:
```python
from job_hunter.discover.jobspy_scraper import run_jobspy_search, parse_jobspy_results
from job_hunter.discover.dedup import dedup_jobs

__all__ = ["run_jobspy_search", "parse_jobspy_results", "dedup_jobs"]
```

`src/job_hunter/discover/jobspy_scraper.py`:
```python
from __future__ import annotations

import logging
from jobspy import scrape_jobs
import pandas as pd

from job_hunter.database import Job

logger = logging.getLogger(__name__)


def run_jobspy_search(
    query: str,
    location: str,
    boards: list[str],
    max_results: int = 100,
    distance_km: int | None = None,
    remote_only: bool = False,
) -> pd.DataFrame:
    kwargs = {
        "site_name": boards,
        "search_term": query,
        "location": location,
        "results_wanted": max_results,
        "country_indeed": "Japan" if "japan" in location.lower() else None,
    }
    if distance_km:
        kwargs["distance"] = distance_km
    if remote_only:
        kwargs["is_remote"] = True

    logger.info(f"Searching: '{query}' in '{location}' on {boards}")
    results = scrape_jobs(**kwargs)
    logger.info(f"Found {len(results)} jobs")
    return results


def parse_jobspy_results(df: pd.DataFrame) -> list[Job]:
    jobs = []
    for _, row in df.iterrows():
        url = str(row.get("job_url", ""))
        if not url or url == "nan":
            continue
        salary_min = None
        salary_max = None
        salary_raw = None
        if pd.notna(row.get("min_amount")):
            salary_min = int(row["min_amount"])
        if pd.notna(row.get("max_amount")):
            salary_max = int(row["max_amount"])
        if salary_min or salary_max:
            interval = row.get("interval", "")
            salary_raw = f"{salary_min or '?'}-{salary_max or '?'} {interval or ''}".strip()

        jobs.append(Job(
            url=url,
            title=str(row.get("title", "Unknown")),
            company=str(row.get("company_name", "Unknown")),
            location=str(row.get("location", "")),
            source=str(row.get("site", "unknown")),
            description=str(row.get("description", "")) if pd.notna(row.get("description")) else None,
            posted_date=str(row.get("date_posted", "")) if pd.notna(row.get("date_posted")) else None,
            salary_min=salary_min,
            salary_max=salary_max,
            salary_raw=salary_raw,
        ))
    return jobs
```

`src/job_hunter/discover/dedup.py`:
```python
from __future__ import annotations

import logging
from job_hunter.database import Job

logger = logging.getLogger(__name__)


def dedup_jobs(jobs: list[Job], existing_urls: set[str]) -> list[Job]:
    seen = set(existing_urls)
    unique = []
    for job in jobs:
        if job.url not in seen:
            seen.add(job.url)
            unique.append(job)
    dupes = len(jobs) - len(unique)
    if dupes:
        logger.info(f"Deduped {dupes} jobs ({len(unique)} new)")
    return unique
```

**Step 4: Run tests**

Run: `pytest tests/test_discover.py -v`
Expected: 2 passed

**Step 5: Commit**

```bash
git add src/job_hunter/discover/ tests/test_discover.py
git commit -m "feat: job discovery with python-jobspy scraper and URL deduplication"
```

---

## Task 7: JD Enrichment — 3-Tier Cascade

**Files:**
- Create: `src/job_hunter/enrich/__init__.py`
- Create: `src/job_hunter/enrich/detail.py`
- Create: `tests/test_enrich.py`
- Create: `tests/fixtures/job_page_jsonld.html`
- Create: `tests/fixtures/job_page_css.html`

**Step 1: Write tests**

`tests/test_enrich.py`:
```python
import pytest
from job_hunter.enrich.detail import extract_from_json_ld, extract_description_css, EnrichResult

def test_extract_from_json_ld():
    html = '''
    <html><head>
    <script type="application/ld+json">
    {"@type": "JobPosting", "description": "<p>We need a Python developer</p>",
     "url": "https://example.com/apply", "directApply": true}
    </script>
    </head><body></body></html>
    '''
    result = extract_from_json_ld(html)
    assert result is not None
    assert "Python developer" in result.description
    assert result.tier == "json-ld"

def test_extract_from_json_ld_graph():
    html = '''
    <html><head>
    <script type="application/ld+json">
    {"@graph": [{"@type": "Organization"}, {"@type": "JobPosting",
     "description": "React engineer needed"}]}
    </script>
    </head><body></body></html>
    '''
    result = extract_from_json_ld(html)
    assert result is not None
    assert "React engineer" in result.description

def test_extract_from_json_ld_returns_none_for_no_job():
    html = '<html><head></head><body>No jobs here</body></html>'
    result = extract_from_json_ld(html)
    assert result is None

def test_extract_description_css():
    html = '''
    <html><body>
    <div id="job-description">
        <p>Looking for a senior engineer with 5+ years experience.</p>
    </div>
    </body></html>
    '''
    result = extract_description_css(html)
    assert result is not None
    assert "senior engineer" in result.description
    assert result.tier == "css"

def test_extract_description_css_fallback_selectors():
    html = '''
    <html><body>
    <div class="job-description">
        <p>Machine learning role</p>
    </div>
    </body></html>
    '''
    result = extract_description_css(html)
    assert result is not None
    assert "Machine learning" in result.description
```

**Step 2: Run tests to verify failure**

Run: `pytest tests/test_enrich.py -v`
Expected: FAIL

**Step 3: Implement enrichment**

`src/job_hunter/enrich/__init__.py`:
```python
from job_hunter.enrich.detail import enrich_job

__all__ = ["enrich_job"]
```

`src/job_hunter/enrich/detail.py`:
```python
from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass

import httpx
from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DESCRIPTION_SELECTORS = [
    "#job-description",
    "[data-testid='job-description']",
    ".job-description",
    ".jobsearch-JobComponent-description",
    ".ashby-job-posting-description",
    ".job-details",
    "[class*='job-description']",
    "[class*='jobDescription']",
    ".description__text",
    ".posting-requirements",
    "[role='main'] article",
    ".job__description",
    ".job-posting-content",
    "#jobDescriptionText",
    ".jobs-description",
    ".job_description",
    "[data-automation='jobDescription']",
    ".content-section",
    "article.job-posting",
    "main .content",
]

APPLY_SELECTORS = [
    "a[href*='apply']",
    "a.apply-button",
    "a.ashby-job-posting-apply-button",
    "#grnhse_app a[href*='apply']",
    "a[data-testid='apply-button']",
    "a[class*='apply']",
    "button[class*='apply']",
    "a[href*='lever.co']",
    "a[href*='greenhouse.io']",
    "a[href*='workday']",
    "a[href*='smartrecruiters']",
    "a[href*='icims']",
    "a[href*='taleo']",
]


@dataclass
class EnrichResult:
    description: str
    apply_url: str | None = None
    tier: str = "unknown"


def extract_from_json_ld(html: str) -> EnrichResult | None:
    soup = BeautifulSoup(html, "html.parser")
    scripts = soup.find_all("script", type="application/ld+json")

    for script in scripts:
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue

        posting = _find_job_posting(data)
        if posting and posting.get("description"):
            desc_html = posting["description"]
            description = BeautifulSoup(desc_html, "html.parser").get_text(separator="\n", strip=True)
            apply_url = (
                posting.get("url")
                or posting.get("applicationContact", {}).get("url")
                if isinstance(posting.get("applicationContact"), dict)
                else None
            )
            return EnrichResult(description=description, apply_url=apply_url, tier="json-ld")

    return None


def _find_job_posting(data) -> dict | None:
    if isinstance(data, dict):
        if data.get("@type") == "JobPosting":
            return data
        if "@graph" in data:
            for item in data["@graph"]:
                result = _find_job_posting(item)
                if result:
                    return result
    elif isinstance(data, list):
        for item in data:
            result = _find_job_posting(item)
            if result:
                return result
    return None


def extract_description_css(html: str) -> EnrichResult | None:
    soup = BeautifulSoup(html, "html.parser")
    description = None
    apply_url = None

    for selector in DESCRIPTION_SELECTORS:
        try:
            el = soup.select_one(selector)
        except Exception:
            continue
        if el:
            text = el.get_text(separator="\n", strip=True)
            if len(text) > 100:
                description = text
                break

    for selector in APPLY_SELECTORS:
        try:
            el = soup.select_one(selector)
        except Exception:
            continue
        if el and el.get("href"):
            apply_url = el["href"]
            break

    if not apply_url:
        for a in soup.find_all("a", href=True):
            if re.search(r"apply", a.get_text(), re.IGNORECASE):
                apply_url = a["href"]
                break

    if description:
        return EnrichResult(description=description, apply_url=apply_url, tier="css")
    return None


async def extract_with_llm(html: str, llm) -> EnrichResult | None:
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["nav", "header", "footer", "script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)[:30000]

    prompt = f"""Extract the job description and application URL from this page content.
Return JSON only: {{"full_description": "...", "application_url": "..." or null}}

Page content:
{text}"""

    try:
        response = await llm.generate(prompt, json_mode=True)
        data = json.loads(response)
        desc = data.get("full_description", "")
        if desc and len(desc) > 50:
            return EnrichResult(
                description=desc,
                apply_url=data.get("application_url"),
                tier="ai",
            )
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"LLM extraction failed: {e}")

    return None


async def enrich_job(url: str, llm=None) -> EnrichResult | None:
    try:
        async with httpx.AsyncClient(follow_redirects=True, timeout=30) as client:
            response = await client.get(url, headers={
                "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                              "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
            })
            html = response.text
    except Exception as e:
        logger.warning(f"Failed to fetch {url}: {e}")
        return None

    # Tier 1: JSON-LD
    result = extract_from_json_ld(html)
    if result and result.description:
        logger.debug(f"Tier 1 (JSON-LD) succeeded for {url}")
        return result

    # Tier 2: CSS selectors
    result = extract_description_css(html)
    if result and result.description:
        logger.debug(f"Tier 2 (CSS) succeeded for {url}")
        return result

    # Tier 3: LLM extraction
    if llm:
        result = await extract_with_llm(html, llm)
        if result:
            logger.debug(f"Tier 3 (AI) succeeded for {url}")
            return result

    logger.warning(f"All enrichment tiers failed for {url}")
    return None
```

**Step 4: Run tests**

Run: `pytest tests/test_enrich.py -v`
Expected: 5 passed

**Step 5: Commit**

```bash
git add src/job_hunter/enrich/ tests/test_enrich.py
git commit -m "feat: 3-tier JD enrichment cascade (JSON-LD → CSS → AI)"
```

---

## Task 8: AI Scoring

**Files:**
- Create: `src/job_hunter/score/__init__.py`
- Create: `src/job_hunter/score/scorer.py`
- Create: `tests/test_scorer.py`

**Step 1: Write tests**

`tests/test_scorer.py`:
```python
import pytest
import json
from unittest.mock import AsyncMock
from job_hunter.score.scorer import score_job, parse_score_response
from job_hunter.database import Job

def test_parse_score_response_valid():
    response = '{"score": 8, "reason": "Strong Python match with relevant experience."}'
    score, reason = parse_score_response(response)
    assert score == 8
    assert "Python" in reason

def test_parse_score_response_clamps():
    response = '{"score": 15, "reason": "Off the charts"}'
    score, reason = parse_score_response(response)
    assert score == 10

    response2 = '{"score": -3, "reason": "Terrible"}'
    score2, reason2 = parse_score_response(response2)
    assert score2 == 1

def test_parse_score_response_invalid_json():
    response = "This is not JSON"
    score, reason = parse_score_response(response)
    assert score == 0
    assert "parse" in reason.lower() or "failed" in reason.lower()

@pytest.mark.asyncio
async def test_score_job_calls_llm():
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = '{"score": 7, "reason": "Decent match for backend role."}'

    job = Job(url="https://example.com/1", title="Backend Dev", company="Acme",
              location="Tokyo", source="indeed",
              description="Looking for Python backend developer with 3+ years experience.")
    profile = {"target_role": "Backend Developer", "skills": ["Python", "PostgreSQL"]}

    score, reason = await score_job(job, profile, mock_llm)
    assert score == 7
    assert "backend" in reason.lower() or "match" in reason.lower()
    mock_llm.generate.assert_called_once()
```

**Step 2: Run tests to verify failure**

Run: `pytest tests/test_scorer.py -v`
Expected: FAIL

**Step 3: Implement scorer**

`src/job_hunter/score/__init__.py`:
```python
from job_hunter.score.scorer import score_job

__all__ = ["score_job"]
```

`src/job_hunter/score/scorer.py`:
```python
from __future__ import annotations

import json
import logging

from job_hunter.database import Job
from job_hunter.llm.base import LLMProvider

logger = logging.getLogger(__name__)

SCORE_PROMPT = """You are a job fit scorer. Rate how well this job matches the candidate's profile.

CANDIDATE PROFILE:
- Target role: {target_role}
- Skills: {skills}
- Experience summary: {experience_summary}

JOB POSTING:
- Title: {title}
- Company: {company}
- Location: {location}
- Description: {description}

SCORING CRITERIA:
- 9-10: Excellent match — role, skills, and experience align closely
- 7-8: Good match — most requirements met, minor gaps
- 5-6: Moderate match — some relevant skills but significant gaps
- 3-4: Weak match — few overlapping requirements
- 1-2: Poor match — unrelated role or requirements

Return JSON only: {{"score": <1-10>, "reason": "<2 sentences explaining the score>"}}"""


def parse_score_response(response: str) -> tuple[int, str]:
    try:
        text = response.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
        data = json.loads(text)
        score = int(data.get("score", 0))
        score = max(1, min(10, score))
        reason = str(data.get("reason", "No reason provided"))
        return score, reason
    except (json.JSONDecodeError, ValueError, TypeError) as e:
        logger.warning(f"Failed to parse score response: {e}")
        return 0, f"Failed to parse LLM response"


async def score_job(job: Job, profile: dict, llm: LLMProvider) -> tuple[int, str]:
    skills = ", ".join(profile.get("skills", []))
    facts = profile.get("resume_facts", {})
    companies = facts.get("companies", [])
    experience_summary = "; ".join(
        f"{c.get('title', '?')} at {c.get('name', '?')} ({c.get('dates', '?')})"
        for c in companies
    )
    if not experience_summary:
        experience_summary = "Not provided"

    prompt = SCORE_PROMPT.format(
        target_role=profile.get("target_role", "Not specified"),
        skills=skills or "Not specified",
        experience_summary=experience_summary,
        title=job.title,
        company=job.company,
        location=job.location or "Not specified",
        description=(job.description or "No description available")[:5000],
    )

    response = await llm.generate(prompt, json_mode=True)
    return parse_score_response(response)
```

**Step 4: Run tests**

Run: `pytest tests/test_scorer.py -v`
Expected: 4 passed

**Step 5: Commit**

```bash
git add src/job_hunter/score/ tests/test_scorer.py
git commit -m "feat: AI job scoring with 1-10 rating and 2-sentence explanation"
```

---

## Task 9: Resume Tailoring + Validation + PDF Rendering

**Files:**
- Create: `src/job_hunter/tailor/__init__.py`
- Create: `src/job_hunter/tailor/resume_tailor.py`
- Create: `src/job_hunter/tailor/cover_letter.py`
- Create: `src/job_hunter/tailor/validator.py`
- Create: `src/job_hunter/tailor/renderer.py`
- Create: `templates/resume_clean.html`
- Create: `templates/cover_letter.html`
- Create: `tests/test_tailor.py`

**Step 1: Write tests**

`tests/test_tailor.py`:
```python
import pytest
import json
from job_hunter.tailor.validator import (
    validate_resume, validate_cover_letter,
    BANNED_WORDS, LLM_LEAK_PHRASES, ValidationMode
)

def test_banned_words_list_has_entries():
    assert len(BANNED_WORDS) >= 30

def test_llm_leak_phrases_has_entries():
    assert len(LLM_LEAK_PHRASES) >= 15

def test_validate_resume_catches_fabrication():
    resume_facts = {"companies": [{"name": "Acme Corp"}], "education": [{"school": "MIT"}]}
    resume_text = "I worked at Acme Corp and also at Google where I led the AI team."
    errors = validate_resume(resume_text, resume_facts, mode=ValidationMode.STRICT)
    assert any("fabricat" in e.lower() or "Google" in e for e in errors)

def test_validate_resume_passes_clean():
    resume_facts = {"companies": [{"name": "Acme Corp"}], "education": [{"school": "MIT"}]}
    resume_text = "Senior Engineer at Acme Corp. Built distributed systems. MIT graduate."
    errors = validate_resume(resume_text, resume_facts, mode=ValidationMode.NORMAL)
    assert len(errors) == 0

def test_validate_resume_catches_llm_leak():
    resume_facts = {"companies": [], "education": []}
    resume_text = "Here is the corrected resume:\nJohn Doe\nSoftware Engineer"
    errors = validate_resume(resume_text, resume_facts, mode=ValidationMode.NORMAL)
    assert any("llm" in e.lower() or "leak" in e.lower() or "self-talk" in e.lower() for e in errors)

def test_validate_cover_letter_strict_word_limit():
    long_text = "Dear Hiring Manager,\n" + " ".join(["word"] * 260) + "\nSincerely, Me"
    errors = validate_cover_letter(long_text, mode=ValidationMode.STRICT)
    assert any("word" in e.lower() for e in errors)

def test_validate_cover_letter_lenient_ignores_banned():
    text = "Dear Hiring Manager,\nI am passionate about this opportunity. I spearheaded many projects.\nSincerely, Me"
    errors = validate_cover_letter(text, mode=ValidationMode.LENIENT)
    banned_errors = [e for e in errors if "banned" in e.lower() or "filler" in e.lower()]
    assert len(banned_errors) == 0
```

**Step 2: Run tests to verify failure**

Run: `pytest tests/test_tailor.py -v`
Expected: FAIL

**Step 3: Implement tailor modules**

`src/job_hunter/tailor/__init__.py`:
```python
from job_hunter.tailor.resume_tailor import tailor_resume
from job_hunter.tailor.cover_letter import generate_cover_letter
from job_hunter.tailor.validator import validate_resume, validate_cover_letter
from job_hunter.tailor.renderer import render_resume_pdf, render_cover_letter_pdf

__all__ = [
    "tailor_resume", "generate_cover_letter",
    "validate_resume", "validate_cover_letter",
    "render_resume_pdf", "render_cover_letter_pdf",
]
```

`src/job_hunter/tailor/validator.py`:
```python
from __future__ import annotations

import re
import logging
from enum import Enum

logger = logging.getLogger(__name__)


class ValidationMode(Enum):
    STRICT = "strict"
    NORMAL = "normal"
    LENIENT = "lenient"


BANNED_WORDS = [
    "passionate", "spearheaded", "robust", "synergy", "proven track record",
    "i am excited", "furthermore", "adept at", "extensive experience", "proactive",
    "dynamic", "self-starter", "go-getter", "think outside the box", "team player",
    "detail-oriented", "results-driven", "hard-working", "motivated", "dedicated",
    "leverage", "utilize", "cutting-edge", "innovative", "strategic",
    "streamlined", "orchestrated", "facilitated", "pioneered", "championed",
    "revolutionized", "transformed", "this demonstrates", "i believe",
    "in conclusion", "moreover", "henceforth", "thus", "whereby",
    "aforementioned", "notwithstanding", "par excellence", "second to none",
    "unparalleled", "best-in-class", "world-class", "top-notch",
    "game-changer", "synergize", "holistic", "ecosystem",
    "deep dive", "circle back", "move the needle", "low-hanging fruit",
    "boil the ocean", "value-add", "core competency",
]

LLM_LEAK_PHRASES = [
    "i am sorry", "here is the corrected", "per your feedback",
    "the following resume", "here is the updated", "as requested",
    "i have revised", "i've updated", "here's the tailored",
    "based on your instructions", "as per the job description",
    "i hope this helps", "let me know if", "feel free to",
    "happy to help", "is there anything else",
    "sure, here", "certainly!", "of course!",
    "note:", "disclaimer:", "important:",
]


def validate_resume(text: str, resume_facts: dict, mode: ValidationMode = ValidationMode.NORMAL) -> list[str]:
    errors = []
    text_lower = text.lower()

    # Always check: LLM self-talk leaks
    for phrase in LLM_LEAK_PHRASES:
        if phrase in text_lower:
            errors.append(f"LLM self-talk detected: '{phrase}'")
            break

    # Always check: fabricated companies
    known_companies = {c["name"].lower() for c in resume_facts.get("companies", []) if c.get("name")}
    known_schools = {e["school"].lower() for e in resume_facts.get("education", []) if e.get("school")}
    known_entities = known_companies | known_schools

    company_pattern = re.compile(
        r'(?:at|with|for|@)\s+([A-Z][A-Za-z\s&.\-]+?)(?:\s*[,.\n(]|\s+(?:where|as|from|during))',
    )
    for match in company_pattern.finditer(text):
        entity = match.group(1).strip().lower()
        if entity and len(entity) > 2 and entity not in known_entities:
            is_known = any(known in entity or entity in known for known in known_entities)
            if not is_known:
                errors.append(f"Possible fabrication — unknown entity: '{match.group(1).strip()}'")

    # Mode-dependent: banned words
    if mode == ValidationMode.STRICT:
        for word in BANNED_WORDS:
            if word in text_lower:
                errors.append(f"Banned filler word: '{word}'")
    elif mode == ValidationMode.NORMAL:
        for word in BANNED_WORDS:
            if word in text_lower:
                logger.warning(f"Banned filler word (warning only): '{word}'")

    return errors


def validate_cover_letter(text: str, mode: ValidationMode = ValidationMode.NORMAL) -> list[str]:
    errors = []
    text_lower = text.lower()

    # Always check: LLM self-talk
    for phrase in LLM_LEAK_PHRASES:
        if phrase in text_lower:
            errors.append(f"LLM self-talk detected: '{phrase}'")
            break

    # Word count
    word_count = len(text.split())
    if mode == ValidationMode.STRICT and word_count > 250:
        errors.append(f"Cover letter too long: {word_count} words (max 250)")
    elif mode == ValidationMode.NORMAL and word_count > 275:
        logger.warning(f"Cover letter slightly long: {word_count} words (soft limit 275)")

    # Banned words (mode-dependent)
    if mode == ValidationMode.STRICT:
        for word in BANNED_WORDS:
            if word in text_lower:
                errors.append(f"Banned filler word: '{word}'")
    elif mode == ValidationMode.NORMAL:
        for word in BANNED_WORDS:
            if word in text_lower:
                logger.warning(f"Banned word in cover letter (warning): '{word}'")

    return errors
```

`src/job_hunter/tailor/resume_tailor.py`:
```python
from __future__ import annotations

import json
import logging

from job_hunter.database import Job
from job_hunter.llm.base import LLMProvider

logger = logging.getLogger(__name__)

TAILOR_PROMPT = """You are an expert resume writer optimizing for ATS (Applicant Tracking Systems).

CANDIDATE RESUME FACTS (these are TRUE — never fabricate beyond these):
{resume_facts}

JOB DESCRIPTION:
Title: {title}
Company: {company}
Description: {description}

INSTRUCTIONS:
1. Rewrite the resume to maximize match with this job description
2. Reorder sections and bullets to emphasize the most relevant experience
3. Mirror exact phrases and keywords from the job description
4. Quantify achievements wherever the facts support it
5. NEVER fabricate companies, titles, degrees, dates, or certifications
6. NEVER use these filler words: {banned_words_sample}
7. Use standard section headings: "Professional Experience", "Education", "Skills", "Summary"

Return JSON only:
{{
    "summary": "2-3 sentence professional summary",
    "skills": ["skill1", "skill2", ...],
    "experience": [
        {{
            "company": "exact company from resume_facts",
            "title": "exact title from resume_facts",
            "dates": "exact dates from resume_facts",
            "bullets": ["tailored bullet 1", "tailored bullet 2", ...]
        }}
    ],
    "education": [
        {{
            "school": "exact school from resume_facts",
            "degree": "exact degree",
            "year": exact_year
        }}
    ]
}}"""


async def tailor_resume(job: Job, profile: dict, llm: LLMProvider) -> dict | None:
    resume_facts = profile.get("resume_facts", {})
    banned_sample = ", ".join([
        "passionate", "spearheaded", "robust", "synergy", "proven track record",
        "extensive experience", "proactive", "dynamic", "self-starter",
        "results-driven", "cutting-edge", "innovative", "leveraged",
    ])

    prompt = TAILOR_PROMPT.format(
        resume_facts=json.dumps(resume_facts, indent=2),
        title=job.title,
        company=job.company,
        description=(job.description or "")[:5000],
        banned_words_sample=banned_sample,
    )

    try:
        response = await llm.generate(prompt, json_mode=True, max_tokens=4096)
        text = response.strip()
        if text.startswith("```"):
            text = text.split("\n", 1)[-1].rsplit("```", 1)[0]
        return json.loads(text)
    except (json.JSONDecodeError, Exception) as e:
        logger.error(f"Failed to tailor resume for {job.title}: {e}")
        return None
```

`src/job_hunter/tailor/cover_letter.py`:
```python
from __future__ import annotations

import logging

from job_hunter.database import Job
from job_hunter.llm.base import LLMProvider

logger = logging.getLogger(__name__)

COVER_LETTER_PROMPT = """Write a cover letter for this job application.

CANDIDATE:
- Name: {name}
- Target role: {target_role}
- Key skills: {skills}
- Experience highlights: {highlights}

JOB:
- Title: {title}
- Company: {company}
- Description excerpt: {description}

RULES:
- Start with "Dear Hiring Manager,"
- Under 250 words
- Reference the specific company and role
- Connect candidate's experience to job requirements
- Be specific and concrete — no generic filler
- NEVER use: passionate, spearheaded, robust, synergy, proven track record,
  extensive experience, proactive, dynamic, self-starter, results-driven,
  cutting-edge, innovative, furthermore, I am excited, adept at, this demonstrates
- End with "Sincerely," and the candidate's name
- Do NOT include any preamble like "Here is the cover letter:"
- Return ONLY the cover letter text"""


async def generate_cover_letter(job: Job, profile: dict, llm: LLMProvider) -> str | None:
    facts = profile.get("resume_facts", {})
    highlights = "; ".join(facts.get("metrics", [])[:5])
    skills = ", ".join(profile.get("skills", [])[:10])

    prompt = COVER_LETTER_PROMPT.format(
        name=profile.get("name", "Candidate"),
        target_role=profile.get("target_role", "Software Engineer"),
        skills=skills or "Not specified",
        highlights=highlights or "Not specified",
        title=job.title,
        company=job.company,
        description=(job.description or "")[:3000],
    )

    try:
        response = await llm.generate(prompt, max_tokens=1024)
        text = response.strip()
        # Strip LLM preamble if present
        if not text.startswith("Dear") and "Dear" in text:
            text = text[text.index("Dear"):]
        return text
    except Exception as e:
        logger.error(f"Failed to generate cover letter for {job.title}: {e}")
        return None
```

`src/job_hunter/tailor/renderer.py`:
```python
from __future__ import annotations

import logging
from pathlib import Path

from jinja2 import Environment, FileSystemLoader

logger = logging.getLogger(__name__)


def _get_template_env(templates_dir: Path | None = None) -> Environment:
    if templates_dir is None:
        templates_dir = Path(__file__).parent.parent.parent.parent / "templates"
    return Environment(loader=FileSystemLoader(str(templates_dir)))


def render_resume_pdf(
    resume_data: dict,
    output_path: Path,
    template_name: str = "resume_clean.html",
    templates_dir: Path | None = None,
) -> Path:
    env = _get_template_env(templates_dir)
    template = env.get_template(template_name)
    html = template.render(**resume_data)

    from weasyprint import HTML
    HTML(string=html).write_pdf(str(output_path))
    logger.info(f"Resume PDF written to {output_path}")
    return output_path


def render_cover_letter_pdf(
    cover_letter_text: str,
    candidate_name: str,
    output_path: Path,
    template_name: str = "cover_letter.html",
    templates_dir: Path | None = None,
) -> Path:
    env = _get_template_env(templates_dir)
    template = env.get_template(template_name)
    paragraphs = [p.strip() for p in cover_letter_text.split("\n") if p.strip()]
    html = template.render(paragraphs=paragraphs, name=candidate_name)

    from weasyprint import HTML
    HTML(string=html).write_pdf(str(output_path))
    logger.info(f"Cover letter PDF written to {output_path}")
    return output_path
```

**Step 4: Create HTML templates**

`templates/resume_clean.html`:
```html
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    @page { margin: 0.7in; size: letter; }
    body { font-family: Calibri, Arial, sans-serif; font-size: 11pt; line-height: 1.4; color: #333; margin: 0; }
    h1 { font-size: 18pt; margin: 0 0 4px 0; color: #1a1a1a; }
    h2 { font-size: 12pt; border-bottom: 1px solid #999; padding-bottom: 2px; margin: 14px 0 6px 0; color: #1a1a1a; text-transform: uppercase; letter-spacing: 0.5px; }
    .contact { font-size: 10pt; color: #555; margin-bottom: 10px; }
    .summary { margin-bottom: 10px; }
    .job { margin-bottom: 10px; }
    .job-header { display: flex; justify-content: space-between; margin-bottom: 2px; }
    .job-title { font-weight: bold; }
    .job-dates { color: #555; font-size: 10pt; }
    .job-company { font-style: italic; }
    ul { margin: 4px 0; padding-left: 20px; }
    li { margin-bottom: 2px; }
    .skills { margin: 4px 0; }
    .edu { margin-bottom: 6px; }
    .edu-header { display: flex; justify-content: space-between; }
</style>
</head>
<body>
    <h1>{{ name | default("Candidate Name") }}</h1>
    <div class="contact">
        {{ email | default("") }}{% if phone %} | {{ phone }}{% endif %}{% if location %} | {{ location }}{% endif %}
        {% if linkedin_url %} | {{ linkedin_url }}{% endif %}
        {% if github_url %} | {{ github_url }}{% endif %}
    </div>

    {% if summary %}
    <h2>Summary</h2>
    <div class="summary">{{ summary }}</div>
    {% endif %}

    {% if skills %}
    <h2>Skills</h2>
    <div class="skills">{{ skills | join(", ") }}</div>
    {% endif %}

    {% if experience %}
    <h2>Professional Experience</h2>
    {% for job in experience %}
    <div class="job">
        <div class="job-header">
            <span class="job-title">{{ job.title }}</span>
            <span class="job-dates">{{ job.dates }}</span>
        </div>
        <div class="job-company">{{ job.company }}</div>
        <ul>
        {% for bullet in job.bullets %}
            <li>{{ bullet }}</li>
        {% endfor %}
        </ul>
    </div>
    {% endfor %}
    {% endif %}

    {% if education %}
    <h2>Education</h2>
    {% for edu in education %}
    <div class="edu">
        <div class="edu-header">
            <span><strong>{{ edu.degree }}</strong> — {{ edu.school }}</span>
            <span class="job-dates">{{ edu.year | default("") }}</span>
        </div>
    </div>
    {% endfor %}
    {% endif %}
</body>
</html>
```

`templates/cover_letter.html`:
```html
<!DOCTYPE html>
<html>
<head>
<meta charset="utf-8">
<style>
    @page { margin: 1in; size: letter; }
    body { font-family: Calibri, Arial, sans-serif; font-size: 11pt; line-height: 1.5; color: #333; margin: 0; }
    p { margin: 0 0 10px 0; }
    .signature { margin-top: 20px; }
</style>
</head>
<body>
    {% for para in paragraphs %}
    <p>{{ para }}</p>
    {% endfor %}
</body>
</html>
```

**Step 5: Run tests**

Run: `pytest tests/test_tailor.py -v`
Expected: 7 passed

**Step 6: Commit**

```bash
git add src/job_hunter/tailor/ templates/ tests/test_tailor.py
git commit -m "feat: resume tailoring, cover letters, 3-mode validation, PDF rendering"
```

---

## Task 10: Full CLI Wiring

**Files:**
- Modify: `src/job_hunter/cli.py` (rewrite)
- Create: `tests/test_cli.py`

**Step 1: Write tests**

`tests/test_cli.py`:
```python
from click.testing import CliRunner
from job_hunter.cli import cli

def test_cli_version():
    runner = CliRunner()
    result = runner.invoke(cli, ["--version"])
    assert result.exit_code == 0
    assert "0.1.0" in result.output

def test_cli_help():
    runner = CliRunner()
    result = runner.invoke(cli, ["--help"])
    assert result.exit_code == 0
    assert "discover" in result.output
    assert "score" in result.output
    assert "tailor" in result.output
    assert "status" in result.output

def test_doctor_runs():
    runner = CliRunner()
    result = runner.invoke(cli, ["doctor"])
    assert result.exit_code == 0

def test_status_runs():
    runner = CliRunner()
    result = runner.invoke(cli, ["status"])
    assert result.exit_code == 0
```

**Step 2: Run tests to verify failure**

Run: `pytest tests/test_cli.py -v`
Expected: Some FAIL (discover/score not in help yet)

**Step 3: Wire up full CLI**

`src/job_hunter/cli.py`:
```python
from __future__ import annotations

import asyncio
import logging
import sys
from pathlib import Path

import click
from rich.console import Console
from rich.table import Table

from job_hunter import __version__

console = Console()


def _setup_logging(verbose: bool):
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(level=level, format="%(levelname)s %(name)s: %(message)s")


@click.group()
@click.version_option(version=__version__)
@click.option("-v", "--verbose", is_flag=True, help="Enable debug logging")
@click.option("--config-dir", type=click.Path(exists=True), default=".", help="Config directory")
@click.pass_context
def cli(ctx, verbose, config_dir):
    """Job Hunter — discover, score, tailor, apply."""
    _setup_logging(verbose)
    ctx.ensure_object(dict)
    ctx.obj["config_dir"] = Path(config_dir)
    ctx.obj["verbose"] = verbose


@cli.command()
@click.pass_context
def doctor(ctx):
    """Check that all dependencies and configs are set up."""
    config_dir = ctx.obj["config_dir"]
    checks = [
        ("profile.json", (config_dir / "profile.json").exists()),
        ("searches.yaml", (config_dir / "searches.yaml").exists()),
        (".env", (config_dir / ".env").exists()),
    ]

    # Check Python packages
    for pkg, name in [("jobspy", "python-jobspy"), ("notion_client", "notion-client"),
                       ("google.genai", "google-genai"), ("weasyprint", "weasyprint")]:
        try:
            __import__(pkg)
            checks.append((name, True))
        except ImportError:
            checks.append((name, False))

    table = Table(title="Job Hunter Doctor")
    table.add_column("Check", style="cyan")
    table.add_column("Status")
    for name, ok in checks:
        table.add_row(name, "[green]OK[/]" if ok else "[red]MISSING[/]")
    console.print(table)


@cli.command()
@click.pass_context
def status(ctx):
    """Show pipeline statistics."""
    config_dir = ctx.obj["config_dir"]
    db_path = config_dir / "jobs.db"
    if not db_path.exists():
        console.print("[yellow]No jobs database found. Run 'hunt discover' first.[/]")
        return

    from job_hunter.database import JobDB
    db = JobDB(db_path)
    stats = db.get_stats()
    db.close()

    table = Table(title="Pipeline Status")
    table.add_column("Stage", style="cyan")
    table.add_column("Count", justify="right")
    for status_name, count in stats.items():
        table.add_row(status_name, str(count))
    console.print(table)


@cli.command()
@click.option("--workers", "-w", default=1, help="Parallel workers")
@click.pass_context
def discover(ctx, workers):
    """Scrape all configured job platforms."""
    from job_hunter.config import load_config
    from job_hunter.database import JobDB
    from job_hunter.discover import run_jobspy_search, parse_jobspy_results, dedup_jobs

    config = load_config(ctx.obj["config_dir"])
    db = JobDB(ctx.obj["config_dir"] / "jobs.db")

    all_jobs = []
    for search in config.searches:
        try:
            df = run_jobspy_search(
                query=search["query"],
                location=search.get("location", ""),
                boards=search.get("boards", ["indeed"]),
                max_results=search.get("max_results", 100),
                distance_km=search.get("distance_km"),
                remote_only=search.get("remote_only", False),
            )
            jobs = parse_jobspy_results(df)
            all_jobs.extend(jobs)
        except Exception as e:
            console.print(f"[red]Search failed: {search.get('query')}: {e}[/]")

    existing = {j.url for j in db.get_jobs_by_status("new")} | {j.url for j in db.get_jobs_by_status("scored")}
    new_jobs = dedup_jobs(all_jobs, existing)

    for job in new_jobs:
        db.upsert_job(job)

    db.close()
    console.print(f"[green]Discovered {len(new_jobs)} new jobs ({len(all_jobs)} total found)[/]")


@cli.command()
@click.pass_context
def enrich(ctx):
    """Fetch full job descriptions using 3-tier cascade."""
    from job_hunter.config import load_config
    from job_hunter.database import JobDB
    from job_hunter.enrich.detail import enrich_job
    from job_hunter.llm import get_provider

    config = load_config(ctx.obj["config_dir"])
    db = JobDB(ctx.obj["config_dir"] / "jobs.db")
    llm = get_provider(config.llm_provider, api_key=config.gemini_api_key, model=config.llm_model)

    unenriched = db.get_unenriched_jobs()
    console.print(f"Enriching {len(unenriched)} jobs...")

    async def _enrich():
        enriched = 0
        for job in unenriched:
            result = await enrich_job(job.url, llm=llm)
            if result:
                job.description = result.description
                job.apply_url = result.apply_url or job.apply_url
                job.enrich_tier = result.tier
                job.status = "enriched"
                db.upsert_job(job)
                enriched += 1
        return enriched

    count = asyncio.run(_enrich())
    db.close()
    console.print(f"[green]Enriched {count}/{len(unenriched)} jobs[/]")


@cli.command()
@click.option("--min-score", type=int, default=None, help="Override score threshold")
@click.pass_context
def score(ctx, min_score):
    """AI score all unscored jobs against your profile."""
    from job_hunter.config import load_config
    from job_hunter.database import JobDB
    from job_hunter.score import score_job
    from job_hunter.llm import get_provider

    config = load_config(ctx.obj["config_dir"])
    db = JobDB(ctx.obj["config_dir"] / "jobs.db")
    llm = get_provider(config.llm_provider, api_key=config.gemini_api_key, model=config.llm_model)
    threshold = min_score or config.score_threshold

    unscored = db.get_unscored_jobs()
    console.print(f"Scoring {len(unscored)} jobs (threshold: {threshold})...")

    async def _score():
        scored = 0
        for job in unscored:
            s, reason = await score_job(job, config.profile, llm)
            job.score = s
            job.score_reason = reason
            job.status = "scored"
            db.upsert_job(job)
            icon = "[green]^[/]" if s >= threshold else "[dim].[/]"
            console.print(f"  {icon} {s}/10 {job.title} @ {job.company} — {reason[:60]}")
            scored += 1
        return scored

    count = asyncio.run(_score())
    db.close()
    console.print(f"[green]Scored {count} jobs[/]")


@cli.command()
@click.argument("job_id", required=False)
@click.option("--all", "tailor_all", is_flag=True, help="Tailor all jobs above threshold")
@click.option("--validation", type=click.Choice(["strict", "normal", "lenient"]), default="normal")
@click.pass_context
def tailor(ctx, job_id, tailor_all, validation):
    """Generate tailored resume + cover letter for a job."""
    from job_hunter.config import load_config
    from job_hunter.database import JobDB
    from job_hunter.tailor.resume_tailor import tailor_resume
    from job_hunter.tailor.cover_letter import generate_cover_letter
    from job_hunter.tailor.validator import validate_resume, validate_cover_letter, ValidationMode
    from job_hunter.tailor.renderer import render_resume_pdf, render_cover_letter_pdf
    from job_hunter.llm import get_provider

    config = load_config(ctx.obj["config_dir"])
    db = JobDB(ctx.obj["config_dir"] / "jobs.db")
    llm = get_provider(config.llm_provider, api_key=config.gemini_api_key, model=config.llm_model)
    mode = ValidationMode(validation)
    output_dir = ctx.obj["config_dir"] / "output"
    output_dir.mkdir(exist_ok=True)

    if tailor_all:
        jobs = db.get_untailored_jobs(config.score_threshold)
    elif job_id:
        job = db.get_job(job_id)
        jobs = [job] if job else []
    else:
        console.print("[red]Specify a job URL or use --all[/]")
        return

    console.print(f"Tailoring {len(jobs)} jobs (validation: {validation})...")

    async def _tailor():
        tailored = 0
        for job in jobs:
            resume_data = await tailor_resume(job, config.profile, llm)
            if not resume_data:
                console.print(f"  [red]Failed: {job.title}[/]")
                continue

            # Merge profile info into resume data for template
            resume_data["name"] = config.profile.get("name", "")
            resume_data["email"] = config.profile.get("email", "")
            resume_data["phone"] = config.profile.get("phone", "")
            resume_data["location"] = config.profile.get("location", "")
            resume_data["linkedin_url"] = config.profile.get("linkedin_url", "")
            resume_data["github_url"] = config.profile.get("github_url", "")

            # Validate
            resume_text = str(resume_data)
            errors = validate_resume(resume_text, config.profile.get("resume_facts", {}), mode)
            if errors and mode == ValidationMode.STRICT:
                console.print(f"  [red]Validation failed for {job.title}: {errors}[/]")
                continue

            # Render PDF
            safe_name = f"{job.company}_{job.title}".replace(" ", "_")[:50]
            resume_path = output_dir / f"resume_{safe_name}.pdf"
            render_resume_pdf(resume_data, resume_path)
            job.resume_path = str(resume_path)

            # Cover letter
            cl_text = await generate_cover_letter(job, config.profile, llm)
            if cl_text:
                cl_errors = validate_cover_letter(cl_text, mode)
                if not cl_errors or mode != ValidationMode.STRICT:
                    cl_path = output_dir / f"cover_{safe_name}.pdf"
                    render_cover_letter_pdf(cl_text, config.profile.get("name", ""), cl_path)
                    job.cover_letter_path = str(cl_path)

            job.status = "tailored"
            db.upsert_job(job)
            tailored += 1
            console.print(f"  [green]Tailored: {job.title} @ {job.company}[/]")
        return tailored

    count = asyncio.run(_tailor())
    db.close()
    console.print(f"[green]Tailored {count} jobs[/]")


@cli.command()
@click.option("--daily", is_flag=True, help="Optimized for daily cron runs")
@click.option("--workers", "-w", default=1, help="Parallel workers for discovery")
@click.option("--min-score", type=int, default=None, help="Override score threshold")
@click.option("--validation", type=click.Choice(["strict", "normal", "lenient"]), default="normal")
@click.option("--dry-run", is_flag=True, help="Preview without writing to Notion")
@click.pass_context
def run(ctx, daily, workers, min_score, validation, dry_run):
    """Run full pipeline: discover -> enrich -> score -> tailor -> sync."""
    console.print("[bold]Job Hunter — Full Pipeline[/]")

    ctx.invoke(discover, workers=workers)
    ctx.invoke(enrich)
    ctx.invoke(score, min_score=min_score)
    ctx.invoke(tailor, tailor_all=True, validation=validation)

    if not dry_run:
        # Sync to Notion
        from job_hunter.config import load_config
        from job_hunter.database import JobDB
        from job_hunter.notion import NotionJobDB, sync_jobs_to_notion

        config = load_config(ctx.obj["config_dir"])
        if config.notion_token and config.notion_page_id:
            db = JobDB(ctx.obj["config_dir"] / "jobs.db")
            notion_db = NotionJobDB(config.notion_token, config.notion_page_id)
            notion_db.find_or_create_database()
            tailored = db.get_jobs_by_status("tailored")
            synced = sync_jobs_to_notion(notion_db, tailored, db)
            db.close()
            console.print(f"[green]Synced {synced} jobs to Notion[/]")
        else:
            console.print("[yellow]Notion not configured — skipping sync[/]")

    console.print("[bold green]Pipeline complete![/]")
```

**Step 4: Run tests**

Run: `pytest tests/test_cli.py -v`
Expected: 4 passed

**Step 5: Commit**

```bash
git add src/job_hunter/cli.py tests/test_cli.py
git commit -m "feat: wire full CLI with discover, enrich, score, tailor, run commands"
```

---

## Task 11: Config Files — employers.yaml + sites.yaml

**Files:**
- Create: `config/employers.yaml` (full Workday registry)
- Create: `config/sites.yaml` (blocked sites, SSO, base URLs)

**Step 1: Create employers.yaml**

Ship ApplyPilot's 48 employers + add Japanese tech companies. Full YAML content from the research agent output (Task noted in design doc — copy the full YAML from the ApplyPilot extraction).

Add these Japanese employers:
```yaml
  # ── Japanese Tech ───────────────────────────────────────────────────────
  rakuten:
    name: "Rakuten"
    tenant: "rakuten"
    site_id: "External"
    base_url: "https://rakuten.wd1.myworkdayjobs.com"
    region: "japan"
```

**Step 2: Create sites.yaml**

Ship ApplyPilot's blocked/SSO lists + add Japanese sites.

**Step 3: Commit**

```bash
git add config/
git commit -m "feat: ship Workday employer registry (48+) and sites config"
```

---

## Task 12: Integration Test — Full Pipeline (Mocked)

**Files:**
- Create: `tests/test_pipeline_integration.py`

**Step 1: Write integration test**

```python
import pytest
import json
from pathlib import Path
from unittest.mock import AsyncMock, patch, MagicMock
import pandas as pd

from job_hunter.config import load_config
from job_hunter.database import JobDB, Job
from job_hunter.discover import parse_jobspy_results, dedup_jobs
from job_hunter.enrich.detail import extract_from_json_ld
from job_hunter.score.scorer import parse_score_response
from job_hunter.tailor.validator import validate_resume, ValidationMode
from job_hunter.notion.sync import build_page_properties


def test_full_pipeline_flow(tmp_path):
    """End-to-end test: discover -> dedup -> enrich -> score -> tailor -> notion sync."""

    # 1. Parse discovery results
    df = pd.DataFrame({
        "job_url": ["https://example.com/1", "https://example.com/2"],
        "title": ["Python Developer", "Java Developer"],
        "company_name": ["TechCo", "BigCorp"],
        "location": ["Tokyo", "Remote"],
        "site": ["indeed", "linkedin"],
        "description": [None, None],
        "date_posted": ["2026-03-01", "2026-03-02"],
        "min_amount": [80000, None],
        "max_amount": [120000, None],
        "interval": ["yearly", None],
    })
    jobs = parse_jobspy_results(df)
    assert len(jobs) == 2

    # 2. Dedup
    existing = {"https://example.com/2"}
    new_jobs = dedup_jobs(jobs, existing)
    assert len(new_jobs) == 1
    assert new_jobs[0].title == "Python Developer"

    # 3. Store in DB
    db = JobDB(tmp_path / "test.db")
    for job in new_jobs:
        db.upsert_job(job)
    assert db.exists("https://example.com/1")

    # 4. Enrich (JSON-LD)
    html = '''<html><head>
    <script type="application/ld+json">
    {"@type": "JobPosting", "description": "We need a Python developer with 3+ years exp.",
     "url": "https://example.com/apply/1"}
    </script></head></html>'''
    result = extract_from_json_ld(html)
    assert result is not None
    job = db.get_job("https://example.com/1")
    job.description = result.description
    job.enrich_tier = result.tier
    db.upsert_job(job)

    # 5. Score
    score_resp = '{"score": 8, "reason": "Strong Python match with backend experience."}'
    score, reason = parse_score_response(score_resp)
    job.score = score
    job.score_reason = reason
    db.upsert_job(job)
    assert job.score == 8

    # 6. Validate (would fail with fabrication)
    resume_facts = {"companies": [{"name": "Acme"}], "education": [{"school": "MIT"}]}
    errors = validate_resume("Senior Engineer at Acme. MIT graduate.", resume_facts, ValidationMode.NORMAL)
    assert len(errors) == 0

    # 7. Build Notion properties
    props = build_page_properties(job)
    assert props["Job Title"]["title"][0]["text"]["content"] == "Python Developer"
    assert props["Score"]["number"] == 8
    assert props["Source"]["select"]["name"] == "indeed"

    db.close()
```

**Step 2: Run integration test**

Run: `pytest tests/test_pipeline_integration.py -v`
Expected: 1 passed

**Step 3: Commit**

```bash
git add tests/test_pipeline_integration.py
git commit -m "test: end-to-end integration test covering full pipeline flow"
```

---

## Task 13: Push to GitHub

**Step 1: Push all commits**

```bash
git push origin main
```

---

## Build Order Summary

| Task | What | Depends On |
|------|------|-----------|
| 1 | Project scaffold + CLI shell | — |
| 2 | Config module | Task 1 |
| 3 | SQLite database | Task 1 |
| 4 | LLM abstraction | Task 1 |
| 5 | Notion integration | Tasks 1, 3 |
| 6 | Job discovery (JobSpy) | Tasks 2, 3 |
| 7 | JD enrichment (3-tier) | Tasks 3, 4 |
| 8 | AI scoring | Tasks 3, 4 |
| 9 | Resume tailoring + validation + PDF | Task 4 |
| 10 | CLI wiring (all commands) | Tasks 2-9 |
| 11 | Config files (employers, sites) | Task 2 |
| 12 | Integration test | Tasks 3-9 |
| 13 | Push to GitHub | All |

**Tasks 3, 4, 5 can be built in parallel** (no dependencies on each other).
**Tasks 6, 7, 8, 9 can be built in parallel** (only depend on 3 and 4).
