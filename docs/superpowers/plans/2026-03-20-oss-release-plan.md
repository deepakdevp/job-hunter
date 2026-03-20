# job-hunter OSS Release Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Transform job-hunter from a personal tool into a public open-source project with clean history, proper docs, multi-LLM support, and a frictionless setup experience.

**Architecture:** The existing 8-phase pipeline (discover → enrich → score → tailor → cover-letter → sync → apply → autoresearch) stays intact. Changes are: (1) purge secrets from git history, (2) relocate config to XDG paths, (3) add OpenAI + Ollama LLM providers, (4) add CSV export + HTML resume fallback, (5) add `hunt init` wizard + `hunt export` + `hunt research` commands, (6) write README + docs + CI.

**Tech Stack:** Python 3.11+, Click (CLI), Rich (terminal UI), httpx, SQLite, Jinja2, weasyprint, pdflatex (optional), Gemini/OpenAI/Claude/Ollama (LLM).

**Spec:** `docs/superpowers/specs/2026-03-20-oss-release-design.md`

---

## File Map

### New files to create
- `LICENSE` — MIT license
- `README.md` — project README
- `CONTRIBUTING.md` — contributor guide
- `CLAUDE.md` — AI contributor context
- `CHANGELOG.md` — version history
- `SECURITY.md` — vulnerability reporting
- `requirements.txt` — pinned dependencies
- `.github/workflows/ci.yml` — GitHub Actions CI
- `.pre-commit-config.yaml` — detect-secrets hook
- `.secrets.baseline` — secrets scan baseline
- `src/job_hunter/llm/openai.py` — OpenAI provider
- `src/job_hunter/llm/ollama.py` — Ollama provider
- `src/job_hunter/export.py` — CSV/JSON export
- `src/job_hunter/init_wizard.py` — `hunt init` setup wizard
- `src/job_hunter/tailor/html_renderer.py` — HTML→PDF resume fallback
- `config/resume_template.html` — Jinja2 HTML resume template
- `examples/japan_pipeline.py` — Japan regional pipeline example
- `examples/README.md` — examples documentation
- `tests/test_openai_provider.py` — OpenAI provider tests
- `tests/test_ollama_provider.py` — Ollama provider tests
- `tests/test_export.py` — export command tests
- `tests/test_init_wizard.py` — init wizard tests
- `tests/test_html_renderer.py` — HTML renderer tests
- `docs/getting-started.md`
- `docs/configuration.md`
- `docs/architecture.md`
- `docs/llm-providers.md`
- `docs/adding-job-boards.md`
- `docs/adding-ats-strategies.md`
- `docs/autoresearch.md`
- `docs/faq.md`

### Files to modify
- `.gitignore` — expand exclusion rules
- `.env.example` — add OpenAI, Ollama vars
- `pyproject.toml` — metadata, optional deps restructure
- `config/profile.json.example` — sanitize to "Jane Doe"
- `config/resume.tex` — sanitize to "Jane Doe"
- `src/job_hunter/config.py` — XDG paths, provider-aware API key
- `src/job_hunter/llm/base.py` — add openai + ollama to factory
- `src/job_hunter/cli.py` — add `init`, `export`, `research` commands; fix gemini_api_key refs
- `src/job_hunter/pipeline.py` — fix gemini_api_key refs, add autoresearch stages
- `src/job_hunter/tailor/renderer.py` — add HTML fallback dispatch
- `tests/test_config.py` — update for XDG paths
- `tests/test_llm.py` — update for new providers

### Files to move
- `run_japan.py` → `examples/japan_pipeline.py`
- `docs/plans/` → `docs/design/`

### Files to delete from tracked history (git filter-repo)
- `config/.env`, `.env`, `config/profile.json`, `config/*.db`, `config/output/`, `config/japan_output/`, `config/sessions/`, `config/.japan_notion_db_id`, `config/deep_research_results.tsv`, `config/deep_research_program.md`

---

## Task 1: Security Cleanup — Git History Rewrite

**Files:**
- Modify: `.gitignore`
- Create: `.pre-commit-config.yaml`, `.secrets.baseline`
- Delete from history: all secrets/PII/binary files listed above

- [ ] **Step 1: Back up current working state**

```bash
cp -r config/ /tmp/job-hunter-config-backup/
```

- [ ] **Step 2: Install git-filter-repo**

```bash
pip install git-filter-repo
```

- [ ] **Step 3: Run git filter-repo to purge sensitive files**

```bash
git filter-repo --invert-paths \
  --path .env \
  --path config/.env \
  --path config/profile.json \
  --path config/japan_jobs.db \
  --path config/jobs.db \
  --path config/japan_output/ \
  --path config/output/ \
  --path config/sessions/ \
  --path config/.japan_notion_db_id \
  --path config/deep_research_results.tsv \
  --path config/deep_research_program.md \
  --force
```

Note: `git filter-repo --force` removes the remote. Re-add it after:
```bash
git remote add origin git@github.com:deepakdevp/job-hunter.git
```

- [ ] **Step 4: Update .gitignore**

Replace `.gitignore` with the expanded version from the spec (Section 1).

- [ ] **Step 5: Sanitize config/profile.json.example**

Replace all personal data with "Jane Doe" example data. Remove real phone, email, LinkedIn, GitHub, company names.

- [ ] **Step 6: Sanitize config/resume.tex**

Replace personal content with "Jane Doe" example. Keep the LaTeX structure intact.

- [ ] **Step 7: Update .env.example with all vars**

```
# LLM Configuration
LLM_PROVIDER=ollama          # gemini | openai | claude | ollama
LLM_MODEL=llama3.1           # model name for your provider
GEMINI_API_KEY=              # required for gemini
OPENAI_API_KEY=              # required for openai
ANTHROPIC_API_KEY=           # required for claude
OLLAMA_HOST=http://localhost:11434  # required for ollama

# Notion Sync (optional)
NOTION_TOKEN=
NOTION_PAGE_ID=
NOTION_DATABASE_ID=

# Other
CAPSOLVER_API_KEY=           # for CAPTCHA solving during apply
SCORE_THRESHOLD=3            # minimum score for tailoring
```

- [ ] **Step 8: Install and configure detect-secrets**

```bash
pip install detect-secrets pre-commit
```

Create `.pre-commit-config.yaml`:
```yaml
repos:
  - repo: https://github.com/Yelp/detect-secrets
    rev: v1.4.0
    hooks:
      - id: detect-secrets
        args: ['--baseline', '.secrets.baseline']
```

- [ ] **Step 9: Generate secrets baseline**

```bash
detect-secrets scan > .secrets.baseline
pre-commit install
```

- [ ] **Step 10: Commit**

```bash
git add .gitignore .env.example .pre-commit-config.yaml .secrets.baseline config/profile.json.example config/resume.tex
git commit -m "chore: purge secrets from history, update gitignore and examples"
```

- [ ] **Step 11: Rotate all API keys**

Go to Google AI Studio and regenerate Gemini API key. Go to Notion integrations and regenerate token. Update your local (non-committed) `.env` files.

---

## Task 2: Repository Essentials — LICENSE, README, CONTRIBUTING

**Files:**
- Create: `LICENSE`, `README.md`, `CONTRIBUTING.md`, `CLAUDE.md`, `CHANGELOG.md`, `SECURITY.md`
- Modify: `pyproject.toml`

- [ ] **Step 1: Create LICENSE**

MIT license with current year and "Deepak Dev Panwar" as copyright holder.

- [ ] **Step 2: Create README.md**

Follow the structure from spec Section 2:
1. Hero line + badges (Python version, License, CI status)
2. Features list (8 pipeline stages)
3. Quickstart (pip install → hunt init → hunt discover → hunt score → hunt status)
4. Pipeline ASCII diagram
5. Supported job boards table
6. Supported LLM providers table (Gemini, OpenAI, Claude, Ollama)
7. Configuration overview with link to docs
8. Contributing link
9. License

- [ ] **Step 3: Create CONTRIBUTING.md**

Sections: Prerequisites, Dev Setup (`git clone` → `pip install -e ".[dev,all]"` → `pytest`), Code Style (ruff), PR Process, How to Add a Job Board Scraper, How to Add an ATS Strategy.

- [ ] **Step 4: Create CLAUDE.md**

Project structure overview, key patterns (strategy pattern for ATS, LLM provider ABC, pipeline stages as independent functions), important files, common commands (`hunt doctor`, `pytest`, `ruff check`), test conventions.

- [ ] **Step 5: Create CHANGELOG.md**

```markdown
# Changelog

## v0.1.0 — Initial Public Release

### Features
- 8-phase pipeline: discover → enrich → score → tailor → cover-letter → sync → apply → autoresearch
- Job board support: Indeed, LinkedIn, TokyoDev, JapanDev, GaijinPot, 20+ Workday employers
- LLM providers: Gemini, OpenAI, Claude, Ollama (local)
- Resume tailoring with LaTeX or HTML→PDF output
- Cover letter generation
- Notion sync (beta)
- Automated form filling for Workday, Greenhouse, Lever, Ashby, Japan ATS
- Karpathy-style deep autoresearch engine
- CSV/JSON export
```

- [ ] **Step 6: Create SECURITY.md**

Vulnerability reporting via email (deepakdevp@gmail.com), note about API keys and PII handling, `.env` and `profile.json` guidance.

- [ ] **Step 7: Update pyproject.toml**

Add metadata:
```toml
[project]
name = "job-hunter"
version = "0.1.0"
description = "AI-powered job hunting pipeline: discover, score, tailor resumes, and auto-apply"
readme = "README.md"
license = {text = "MIT"}
authors = [{name = "Deepak Dev Panwar", email = "deepakdevp@gmail.com"}]
requires-python = ">=3.11"
classifiers = [
    "Development Status :: 3 - Alpha",
    "License :: OSI Approved :: MIT License",
    "Programming Language :: Python :: 3.11",
    "Programming Language :: Python :: 3.12",
    "Programming Language :: Python :: 3.13",
]

[project.urls]
Homepage = "https://github.com/deepakdevp/job-hunter"
Repository = "https://github.com/deepakdevp/job-hunter"
Issues = "https://github.com/deepakdevp/job-hunter/issues"
```

Restructure dependencies — move `notion-client`, `google-genai`, `weasyprint`, `playwright` to optional extras:
```toml
dependencies = [
    "click>=8.1",
    "python-dotenv>=1.0",
    "pyyaml>=6.0",
    "httpx>=0.27",
    "beautifulsoup4>=4.12",
    "jinja2>=3.1",
    "rich>=13.0",
]

[project.optional-dependencies]
gemini = ["google-genai>=1.0"]
claude = ["anthropic>=0.30"]
openai = ["openai>=1.0"]
notion = ["notion-client>=2.0"]
pdf = ["weasyprint>=62"]
apply = ["playwright>=1.40"]
jobspy = ["python-jobspy>=1.1"]
dev = ["pytest>=8.0", "pytest-asyncio>=0.23", "pytest-mock>=3.12", "ruff>=0.4"]
all = ["job-hunter[gemini,claude,openai,notion,pdf,apply,jobspy]"]
```

Remove the dead `crawlee` extra.

- [ ] **Step 8: Commit**

```bash
git add LICENSE README.md CONTRIBUTING.md CLAUDE.md CHANGELOG.md SECURITY.md pyproject.toml
git commit -m "docs: add LICENSE, README, CONTRIBUTING, CLAUDE.md, CHANGELOG, SECURITY"
```

---

## Task 3: XDG Config Paths

**Files:**
- Modify: `src/job_hunter/config.py`
- Modify: `src/job_hunter/cli.py` (lines 25-31, 39-44, 74)
- Modify: `src/job_hunter/pipeline.py` (all `config_dir` references)
- Test: `tests/test_config.py`

- [ ] **Step 1: Write failing tests for XDG path resolution**

```python
# tests/test_config.py — add new tests

def test_default_config_dir_is_xdg(monkeypatch, tmp_path):
    """Config dir defaults to XDG_CONFIG_HOME/job-hunter."""
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    from job_hunter.config import get_config_dir
    assert get_config_dir() == tmp_path / "job-hunter"

def test_default_data_dir_is_xdg(monkeypatch, tmp_path):
    """Data dir defaults to XDG_DATA_HOME/job-hunter."""
    monkeypatch.setenv("XDG_DATA_HOME", str(tmp_path))
    from job_hunter.config import get_data_dir
    assert get_data_dir() == tmp_path / "job-hunter"

def test_config_dir_override(tmp_path):
    """--config-dir flag overrides XDG default."""
    from job_hunter.config import get_config_dir
    assert get_config_dir(override=tmp_path) == tmp_path
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_config.py -v -k "xdg or override"
```

- [ ] **Step 3: Add `get_config_dir()` and `get_data_dir()` to config.py**

```python
def get_config_dir(override: Path | None = None) -> Path:
    """Resolve config directory: explicit override > XDG > ~/.config/job-hunter."""
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "job-hunter"

def get_data_dir(override: Path | None = None) -> Path:
    """Resolve data directory: explicit override > XDG > ~/.local/share/job-hunter."""
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_DATA_HOME", "")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "job-hunter"
```

- [ ] **Step 4: Update `load_config()` to use XDG defaults**

Change `load_config(config_dir=None)` to call `get_config_dir(config_dir)` instead of `Path.cwd()`. Add `data_dir` field to `Config` dataclass.

- [ ] **Step 5: Update CLI default for --config-dir**

In `cli.py`, change `default="."` to `default=None` and resolve via `get_config_dir()`. Update `status`, `doctor`, and all commands that reference `config_dir / "jobs.db"` to use `get_data_dir() / "jobs.db"`.

- [ ] **Step 6: Update pipeline.py references**

Replace all `config.config_dir / "jobs.db"` with `get_data_dir() / "jobs.db"`. Same for `output/`, `sessions/`.

- [ ] **Step 7: Run tests**

```bash
pytest tests/test_config.py -v
```

- [ ] **Step 8: Commit**

```bash
git add src/job_hunter/config.py src/job_hunter/cli.py src/job_hunter/pipeline.py tests/test_config.py
git commit -m "feat: use XDG-compliant config and data directories"
```

---

## Task 4: `hunt init` Setup Wizard

**Files:**
- Create: `src/job_hunter/init_wizard.py`
- Modify: `src/job_hunter/cli.py` (add `init` command)
- Test: `tests/test_init_wizard.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_init_wizard.py

def test_init_creates_profile_json(tmp_path, monkeypatch):
    """hunt init creates profile.json in config dir."""
    from job_hunter.init_wizard import run_init
    answers = {
        "config_dir": str(tmp_path),
        "llm_provider": "ollama",
        "api_key": "",
        "name": "Jane Doe",
        "email": "jane@example.com",
        "target_roles": "Software Engineer, AI Engineer",
        "skills": "Python, React",
    }
    run_init(answers)
    assert (tmp_path / "profile.json").exists()
    assert (tmp_path / ".env").exists()
    assert (tmp_path / "searches.yaml").exists()

def test_init_env_has_correct_provider(tmp_path):
    from job_hunter.init_wizard import run_init
    answers = {
        "config_dir": str(tmp_path),
        "llm_provider": "gemini",
        "api_key": "test-key",
        "name": "Jane Doe",
        "email": "jane@example.com",
        "target_roles": "Software Engineer",
        "skills": "Python",
    }
    run_init(answers)
    env_content = (tmp_path / ".env").read_text()
    assert "LLM_PROVIDER=gemini" in env_content
    assert "GEMINI_API_KEY=test-key" in env_content
```

- [ ] **Step 2: Run tests to verify they fail**

```bash
pytest tests/test_init_wizard.py -v
```

- [ ] **Step 3: Implement `init_wizard.py`**

Create `src/job_hunter/init_wizard.py` with:
- `run_init(answers: dict)` — creates `profile.json`, `.env`, `searches.yaml` from answers dict
- `interactive_init(config_dir: Path)` — Click-based interactive prompts that collect answers then call `run_init`

The wizard should:
1. Ask for config directory (default: XDG)
2. Ask LLM provider (ollama/gemini/openai/claude)
3. Ask API key (skip for ollama)
4. Ask name, email, target roles, skills
5. Generate all config files
6. Create data directory
7. Print success message with next steps

- [ ] **Step 4: Wire into CLI**

Add `@cli.command()` for `init` in `cli.py` that calls `interactive_init()`.

- [ ] **Step 5: Run tests**

```bash
pytest tests/test_init_wizard.py -v
```

- [ ] **Step 6: Commit**

```bash
git add src/job_hunter/init_wizard.py src/job_hunter/cli.py tests/test_init_wizard.py
git commit -m "feat: add hunt init setup wizard"
```

---

## Task 5: Refactor run_japan.py → Examples

**Files:**
- Move: `run_japan.py` → `examples/japan_pipeline.py`
- Create: `examples/README.md`
- Modify: `src/job_hunter/pipeline.py` (add autoresearch stages)
- Modify: `src/job_hunter/cli.py` (add `hunt research` command)

- [ ] **Step 1: Move run_japan.py to examples/ (preserving git history)**

```bash
mkdir -p examples
git mv run_japan.py examples/japan_pipeline.py
```

- [ ] **Step 2: Add explanatory header to examples/japan_pipeline.py**

Add a docstring explaining this is a standalone Japan-focused pipeline example showing how to compose custom regional pipelines.

- [ ] **Step 3: Add `hunt research` CLI command**

In `cli.py`, add a `research` command group with:
- `hunt research run` — single pass deep research (wraps `run_deep_research`)
- `hunt research loop` — never-stop loop mode (wraps `run_deep_research_loop`)

Options: `--min-score`, `--max-jobs`

- [ ] **Step 4: Move autoresearch stage orchestration into pipeline.py**

Extract the autoresearch stage functions (source research, data validation, score audit, resume audit) from `run_japan.py` patterns into `pipeline.py` so `hunt run` can optionally include them.

- [ ] **Step 5: Create examples/README.md**

Document what the example does, how to configure it, how to run it.

- [ ] **Step 6: Commit**

```bash
git add examples/ src/job_hunter/cli.py src/job_hunter/pipeline.py
git commit -m "refactor: move run_japan.py to examples, add hunt research command"
```

Note: `config/japan_searches.yaml` contains no PII (only search queries and board names). It stays in the repo as an example of regional search configuration.

---

## Task 6: LLM Provider Refactor — Fix gemini_api_key Bug

**Files:**
- Modify: `src/job_hunter/config.py`
- Modify: `src/job_hunter/llm/base.py`
- Modify: `src/job_hunter/cli.py` (12 call sites)
- Modify: `src/job_hunter/pipeline.py` (12 call sites)
- Test: `tests/test_config.py`, `tests/test_llm.py`

- [ ] **Step 1: Write failing test**

```python
# tests/test_config.py — add

def test_llm_api_key_resolves_from_provider(monkeypatch):
    """Config.llm_api_key returns the right key for each provider."""
    monkeypatch.setenv("LLM_PROVIDER", "openai")
    monkeypatch.setenv("OPENAI_API_KEY", "sk-test")
    monkeypatch.setenv("GEMINI_API_KEY", "gemini-test")
    from job_hunter.config import resolve_llm_api_key
    assert resolve_llm_api_key("openai") == "sk-test"
    assert resolve_llm_api_key("gemini") == "gemini-test"
    assert resolve_llm_api_key("ollama") == ""  # no key needed
```

- [ ] **Step 2: Run test to verify it fails**

```bash
pytest tests/test_config.py::test_llm_api_key_resolves_from_provider -v
```

- [ ] **Step 3: Add `resolve_llm_api_key()` to config.py**

```python
def resolve_llm_api_key(provider: str) -> str:
    """Resolve API key based on LLM provider."""
    key_map = {
        "gemini": "GEMINI_API_KEY",
        "openai": "OPENAI_API_KEY",
        "claude": "ANTHROPIC_API_KEY",
        "ollama": "",  # no key needed
    }
    env_var = key_map.get(provider, "")
    return os.environ.get(env_var, "") if env_var else ""
```

Add `llm_api_key` property to `Config` dataclass that calls `resolve_llm_api_key(self.llm_provider)`.

- [ ] **Step 4: Update all call sites**

Replace every `config.gemini_api_key` with `config.llm_api_key` in:
- `src/job_hunter/cli.py` (4 occurrences)
- `src/job_hunter/pipeline.py` (6 occurrences)

Replace `if config.gemini_api_key:` guards with `if config.llm_api_key or config.llm_provider == "ollama":`.

- [ ] **Step 5: Run all tests**

```bash
pytest tests/ -v
```

- [ ] **Step 6: Commit**

```bash
git add src/job_hunter/config.py src/job_hunter/cli.py src/job_hunter/pipeline.py tests/test_config.py
git commit -m "fix: resolve LLM API key based on provider, not hardcoded gemini"
```

---

## Task 7: OpenAI + Ollama LLM Providers

**Files:**
- Create: `src/job_hunter/llm/openai.py`
- Create: `src/job_hunter/llm/ollama.py`
- Modify: `src/job_hunter/llm/base.py` (update factory)
- Test: `tests/test_openai_provider.py`, `tests/test_ollama_provider.py`

- [ ] **Step 1: Write failing test for OpenAI provider**

```python
# tests/test_openai_provider.py

import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_openai_generate_returns_text():
    from job_hunter.llm.openai import OpenAIProvider
    provider = OpenAIProvider(api_key="test", model="gpt-4o-mini")
    with patch.object(provider, '_client') as mock:
        mock.chat.completions.create = AsyncMock(return_value=type('R', (), {
            'choices': [type('C', (), {'message': type('M', (), {'content': 'hello'})()})]
        })())
        result = await provider.generate("test prompt")
        assert result == "hello"
```

- [ ] **Step 2: Write failing test for Ollama provider**

```python
# tests/test_ollama_provider.py

import pytest
from unittest.mock import AsyncMock, patch

@pytest.mark.asyncio
async def test_ollama_generate_returns_text():
    from job_hunter.llm.ollama import OllamaProvider
    provider = OllamaProvider(model="llama3.1", host="http://localhost:11434")
    with patch("httpx.AsyncClient.post", new_callable=AsyncMock) as mock_post:
        mock_post.return_value = type('R', (), {
            'json': lambda: {'response': 'hello'},
            'raise_for_status': lambda: None,
        })()
        result = await provider.generate("test prompt")
        assert result == "hello"
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/test_openai_provider.py tests/test_ollama_provider.py -v
```

- [ ] **Step 4: Implement OpenAI provider**

Create `src/job_hunter/llm/openai.py`:
```python
from __future__ import annotations
from job_hunter.llm.base import LLMProvider

class OpenAIProvider(LLMProvider):
    def __init__(self, *, api_key: str, model: str = "gpt-4o-mini"):
        from openai import AsyncOpenAI
        self._client = AsyncOpenAI(api_key=api_key)
        self._model = model

    async def generate(self, prompt: str, *, json_mode: bool = False, max_tokens: int = 4096) -> str:
        kwargs = {"model": self._model, "messages": [{"role": "user", "content": prompt}], "max_tokens": max_tokens}
        if json_mode:
            kwargs["response_format"] = {"type": "json_object"}
        response = await self._client.chat.completions.create(**kwargs)
        return response.choices[0].message.content or ""
```

- [ ] **Step 5: Implement Ollama provider**

Create `src/job_hunter/llm/ollama.py`:
```python
from __future__ import annotations
import httpx
from job_hunter.llm.base import LLMProvider

class OllamaProvider(LLMProvider):
    def __init__(self, *, model: str = "llama3.1", host: str = "http://localhost:11434", **_):
        self._model = model
        self._host = host.rstrip("/")

    async def generate(self, prompt: str, *, json_mode: bool = False, max_tokens: int = 4096) -> str:
        payload = {"model": self._model, "prompt": prompt, "stream": False,
                   "options": {"num_predict": max_tokens}}
        if json_mode:
            payload["format"] = "json"
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{self._host}/api/generate", json=payload)
            resp.raise_for_status()
            return resp.json().get("response", "")
```

- [ ] **Step 6: Update factory in base.py**

Add `"openai"` and `"ollama"` branches to `get_provider()`. For ollama, pass `host` from `OLLAMA_HOST` env var (default `http://localhost:11434`).

- [ ] **Step 7: Run all tests**

```bash
pytest tests/ -v
```

- [ ] **Step 8: Commit**

```bash
git add src/job_hunter/llm/openai.py src/job_hunter/llm/ollama.py src/job_hunter/llm/base.py tests/test_openai_provider.py tests/test_ollama_provider.py
git commit -m "feat: add OpenAI and Ollama LLM providers"
```

---

## Task 8: CSV/JSON Export + HTML Resume Fallback

**Files:**
- Create: `src/job_hunter/export.py`
- Create: `src/job_hunter/tailor/html_renderer.py`
- Create: `config/resume_template.html`
- Modify: `src/job_hunter/cli.py` (add `export` command)
- Modify: `src/job_hunter/tailor/renderer.py` (dispatch to HTML fallback)
- Test: `tests/test_export.py`, `tests/test_html_renderer.py`

- [ ] **Step 1: Write failing test for CSV export**

```python
# tests/test_export.py

def test_export_csv_writes_file(tmp_path):
    from job_hunter.database import JobDB, Job
    db_path = tmp_path / "test.db"
    db = JobDB(db_path)
    db.upsert_job(Job(url="http://example.com", title="SWE", company="Acme",
                      location="Tokyo", source="indeed", score=8))
    from job_hunter.export import export_csv
    out = tmp_path / "jobs.csv"
    count = export_csv(db, out)
    assert count == 1
    assert out.exists()
    content = out.read_text()
    assert "SWE" in content
    assert "Acme" in content
    db.close()
```

- [ ] **Step 2: Write failing test for HTML renderer**

```python
# tests/test_html_renderer.py

def test_html_render_produces_html(tmp_path):
    from job_hunter.tailor.html_renderer import render_html_resume
    html = render_html_resume(
        name="Jane Doe",
        sections={"experience": "5 years at Acme Corp", "skills": "Python, React"},
    )
    assert "<html" in html
    assert "Jane Doe" in html
    assert "Python, React" in html
```

- [ ] **Step 3: Run tests to verify they fail**

```bash
pytest tests/test_export.py tests/test_html_renderer.py -v
```

- [ ] **Step 4: Implement export.py**

```python
# src/job_hunter/export.py
import csv
import json
from pathlib import Path
from job_hunter.database import JobDB

def export_csv(db: JobDB, output: Path, min_score: int = 0) -> int:
    jobs = [j for s in ("new","enriched","scored","tailored","synced","applied")
            for j in db.get_jobs_by_status(s) if (j.score or 0) >= min_score]
    with open(output, "w", newline="") as f:
        writer = csv.DictWriter(f, fieldnames=["title","company","location","score","url","status"])
        writer.writeheader()
        for j in jobs:
            writer.writerow({"title":j.title,"company":j.company,"location":j.location,
                           "score":j.score,"url":j.url,"status":j.status})
    return len(jobs)

def export_json(db: JobDB, output: Path, min_score: int = 0) -> int:
    jobs = [j for s in ("new","enriched","scored","tailored","synced","applied")
            for j in db.get_jobs_by_status(s) if (j.score or 0) >= min_score]
    data = [{"title":j.title,"company":j.company,"location":j.location,
             "score":j.score,"url":j.url,"status":j.status} for j in jobs]
    output.write_text(json.dumps(data, indent=2))
    return len(data)
```

- [ ] **Step 5: Implement html_renderer.py**

Create `src/job_hunter/tailor/html_renderer.py` with `render_html_resume()` that uses Jinja2 to render `config/resume_template.html`. Create the HTML template with professional print-media CSS.

- [ ] **Step 6: Update renderer.py to dispatch to HTML fallback**

In `render_latex_to_pdf`, if `_find_compiler()` returns None, try HTML fallback:
```python
if not compiler:
    try:
        from job_hunter.tailor.html_renderer import render_to_pdf as html_render
        return html_render(preamble, tailored_body, output_dir, job_url)
    except ImportError:
        logger.error("No renderer available. Install pdflatex or weasyprint.")
        return None
```

- [ ] **Step 7: Add `export` command to CLI**

```python
@cli.group()
def export():
    """Export jobs to CSV or JSON."""
    pass

@export.command()
@click.option("--output", "-o", required=True, type=click.Path())
@click.option("--min-score", default=0, type=int)
@click.pass_context
def csv(ctx, output, min_score):
    """Export jobs to CSV."""
    ...

@export.command()
@click.option("--output", "-o", required=True, type=click.Path())
@click.option("--min-score", default=0, type=int)
@click.pass_context
def json(ctx, output, min_score):
    """Export jobs to JSON."""
    ...
```

- [ ] **Step 8: Run all tests**

```bash
pytest tests/ -v
```

- [ ] **Step 9: Commit**

```bash
git add src/job_hunter/export.py src/job_hunter/tailor/html_renderer.py config/resume_template.html src/job_hunter/cli.py src/job_hunter/tailor/renderer.py tests/test_export.py tests/test_html_renderer.py
git commit -m "feat: add CSV/JSON export and HTML resume fallback"
```

---

## Task 9: GitHub Actions CI

**Files:**
- Create: `.github/workflows/ci.yml`

- [ ] **Step 1: Create CI workflow**

```yaml
# .github/workflows/ci.yml
name: CI

on:
  push:
    branches: [main]
  pull_request:

jobs:
  test:
    runs-on: ubuntu-latest
    strategy:
      matrix:
        python-version: ["3.11", "3.12", "3.13"]
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: ${{ matrix.python-version }}
      - run: pip install -e ".[dev,gemini]"
      - run: ruff check src/ tests/
      - run: ruff format --check src/ tests/
      - run: pytest tests/ -v --tb=short
```

- [ ] **Step 2: Run tests locally to verify they pass**

```bash
ruff check src/ tests/
ruff format --check src/ tests/
pytest tests/ -v
```

Fix any failures before pushing CI.

- [ ] **Step 3: Fix any ruff lint/format issues**

```bash
ruff check --fix src/ tests/
ruff format src/ tests/
```

- [ ] **Step 4: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: add GitHub Actions for lint + test on Python 3.11-3.13"
```

---

## Task 10: Documentation + Final Polish

**Files:**
- Create: `docs/getting-started.md`, `docs/configuration.md`, `docs/architecture.md`, `docs/llm-providers.md`, `docs/adding-job-boards.md`, `docs/adding-ats-strategies.md`, `docs/autoresearch.md`, `docs/faq.md`
- Move: `docs/plans/` → `docs/design/`

- [ ] **Step 1: Move docs/plans to docs/design**

```bash
git mv docs/plans docs/design
```

- [ ] **Step 2: Write getting-started.md**

Two paths:
1. Quickest (Ollama) — no API keys
2. Full pipeline (Gemini/OpenAI) — with API key

Step-by-step from install to first results.

- [ ] **Step 3: Write configuration.md**

Every config file explained: `profile.json`, `.env`, `searches.yaml`, `employers.yaml`, `sites.yaml`. All env vars. XDG path conventions.

- [ ] **Step 4: Write architecture.md**

Pipeline ASCII diagram. Module map. Data flow. Extension points (scrapers, LLM providers, ATS strategies).

- [ ] **Step 5: Write llm-providers.md**

Setup guide for each: Gemini (get API key from AI Studio), OpenAI (get key from platform.openai.com), Claude (get key from console.anthropic.com), Ollama (install and pull model).

- [ ] **Step 6: Write adding-job-boards.md**

Concrete tutorial: create file, implement interface, register, test.

- [ ] **Step 7: Write adding-ats-strategies.md**

Same pattern: create strategy file, implement `FormStrategy` ABC, register in strategies map.

- [ ] **Step 8: Write autoresearch.md**

Explain the Karpathy-style deep research engine, `program.md` steering, loop mode, keep/discard logic.

- [ ] **Step 9: Write faq.md**

Common issues: TokyoDev 403s, rate limiting, pdflatex installation, Ollama connection errors.

- [ ] **Step 10: Update hunt doctor with enhanced checks**

Add to `doctor` command in `cli.py`:
- LLM connectivity: try `get_provider()` and report if reachable
- Resume renderer: check `shutil.which("pdflatex")`, try `import weasyprint`
- Notion token: if set, try `notion.users.me()` and report validity
- Show config and data directory paths

- [ ] **Step 11: Generate requirements.txt**

```bash
pip freeze > requirements.txt
```

Review and remove dev-only or system packages. This must happen after all dependency changes (Tasks 2, 7, 8).

- [ ] **Step 12: Test clean install flow**

From a fresh virtual environment:
```bash
python -m venv /tmp/test-job-hunter
source /tmp/test-job-hunter/bin/activate
pip install -e ".[all]"
hunt init
hunt doctor
hunt --version
```

Also test minimal install:
```bash
pip install -e ".[dev]"
pytest tests/ -v
```

- [ ] **Step 13: Final commit and tag**

```bash
git add docs/ src/job_hunter/cli.py requirements.txt
git commit -m "docs: add comprehensive documentation for v0.1.0 release"
git tag -a v0.1.0 -m "Initial public release"
git push origin main --tags
```
