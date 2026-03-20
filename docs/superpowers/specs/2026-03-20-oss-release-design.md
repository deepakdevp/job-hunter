# job-hunter OSS Release Design

> Turn job-hunter from a personal tool into a proper open-source project that
> technical job seekers can install and use, and contributors can extend.

**Target audience:** Developers/engineers who can run CLI tools + contributors who want to add scrapers/strategies.
**Timeline:** 2 weeks. Launch as v0.1.0.
**Approach:** Solid Launch — security cleanup + repo essentials + key architecture fixes in one batch.
**Codebase:** 86 Python files (57 source + 29 test), ~11.4K LOC total.

---

## 1. Security Cleanup & Git History Rewrite

### Problem

Real secrets and PII are committed throughout git history:
- Gemini API key in `config/.env`
- Notion token in `.env`
- Personal data (name, email, phone, LinkedIn) in `config/profile.json`
- 15MB of SQLite databases with scraped job data
- 600+ generated resume PDFs with personal content
- Browser session tokens in `config/sessions/`

### Solution

Use `git filter-repo` to purge from all commits:

**Files to remove from history:**
- `config/.env`, `.env`
- `config/profile.json`
- `config/japan_jobs.db`, `config/jobs.db`
- `config/japan_output/`, `config/output/`
- `config/sessions/`
- `config/.japan_notion_db_id`
- `config/deep_research_results.tsv`
- `config/deep_research_program.md`

**Files to keep (sanitized):**
- `config/profile.json.example` — template with fake "Jane Doe" data
- `.env.example` — all vars documented, no real values
- `config/searches.yaml`, `config/employers.yaml`, `config/japan_employers.yaml` — public job board configs
- `config/resume.tex` — sanitized to "Jane Doe" example content
- `config/sites.yaml`

**Post-rewrite actions:**
1. Rotate Gemini API key and Notion token immediately
2. Force-push rewritten history
3. Add `detect-secrets` pre-commit hook to block future leaks
4. Run `detect-secrets scan > .secrets.baseline` and commit baseline

### Updated .gitignore

```
# Secrets & personal data
.env
config/.env
config/profile.json
config/*.db
config/output/
config/japan_output/
config/sessions/
config/deep_research_results.tsv
config/deep_research_program.md
config/.japan_notion_db_id

# Python
__pycache__/
*.pyc
*.egg-info/
dist/
build/
.venv/
.pytest_cache/
.ruff_cache/

# Generated
*.pdf
```

---

## 2. Repository Essentials

### LICENSE

MIT — standard for developer tools, maximum adoption.

### README.md

Structure:
1. **Hero line:** "AI-powered job hunting pipeline that discovers, scores, tailors resumes, and auto-applies."
2. **Features:** Bullet list of 8 pipeline stages
3. **Quickstart (5 min):** `pip install` → `hunt init` → `hunt discover` → `hunt score` → `hunt status`
4. **Pipeline architecture:** ASCII diagram showing discover → enrich → score → tailor → sync → apply
5. **Configuration:** Brief overview, link to docs
6. **Supported job boards:** Table (Indeed, LinkedIn, TokyoDev, JapanDev, GaijinPot, Workday 20+ employers)
7. **Supported LLM providers:** Table (Gemini, OpenAI, Claude, Ollama)
8. **Contributing:** Link to CONTRIBUTING.md
9. **License:** MIT

### CONTRIBUTING.md

- Dev setup instructions
- How to run tests
- PR process and code style (ruff)
- How to add a scraper
- How to add an ATS strategy

### CLAUDE.md

Project structure overview, key patterns (strategy pattern for ATS, LLM provider abstraction, pipeline stages), common commands, test conventions.

### CHANGELOG.md

Start with `v0.1.0 - Initial public release` documenting current feature set.

### pyproject.toml updates

- Description, author, URLs (homepage, repository, issues)
- Classifiers (Development Status, License, Python versions)

---

## 3. Developer Experience

### Dependency Pinning

Generate `requirements.txt` with exact versions from current working environment. Keep `pyproject.toml` with `>=` for flexibility. Ship both for reproducibility.

### CI/CD (GitHub Actions)

```yaml
# .github/workflows/ci.yml
triggers: push to main, PRs
matrix: Python 3.11, 3.12, 3.13
steps: install deps → ruff lint → ruff format check → pytest
```

No type-checking (mypy) initially — retroactive typing of 54 files is out of scope.

### `hunt init` Setup Wizard

Interactive CLI that creates the user's config:

```
$ hunt init
Welcome to job-hunter! Let's set up your config.

Where to store config? [~/.config/job-hunter]:
LLM provider (gemini/openai/ollama) [ollama]:
API key (skip for ollama) []:
Full name: Jane Doe
Email: jane@example.com
Target roles (comma-separated): Software Engineer, AI Engineer
Skills (comma-separated): Python, React, TypeScript
→ Created profile.json
→ Created .env
→ Created searches.yaml (default job searches)
→ Run 'hunt discover' to find your first jobs!
```

Generates `profile.json`, `.env`, and default `searches.yaml`. Removes the "copy example files and hand-edit" friction.

### Docker

**Deferred to v0.2.** Docker for a tool needing texlive, Playwright browsers, and Ollama is a support burden. The incomplete container would generate issues from users expecting end-to-end functionality. Ship Docker when we can test it properly.

For v0.1, document "install from pip" and "install from source" paths only.

### Optional Dependencies

Restructure `pyproject.toml` so users only install what they need:

```toml
[project.optional-dependencies]
jobspy = ["python-jobspy>=1.1"]
claude = ["anthropic>=0.30"]
openai = ["openai>=1.0"]
notion = ["notion-client>=2.0"]
pdf = ["weasyprint>=62"]
apply = ["playwright>=1.40"]
all = ["job-hunter[jobspy,claude,openai,notion,pdf,apply]"]
```

Core install (`pip install job-hunter`) gives: discover + score + export. No heavy system deps needed.
Full install (`pip install job-hunter[all]`) gives everything.

Remove the unused `crawlee` optional dependency — it is dead code.

### System Dependencies Documentation

Clear install instructions for optional deps:
- texlive (LaTeX resumes — optional, HTML fallback available)
- `playwright install` (for JS-rendered job pages)
- Ollama (for local LLM)
- Cairo/Pango (for weasyprint HTML→PDF — only if not using LaTeX)

### SECURITY.md

Add a `SECURITY.md` with:
- Vulnerability reporting instructions (email, not public issues)
- Note that job-hunter handles API keys, browser sessions, and personal data
- Guidance on keeping `.env` and `profile.json` out of version control

---

## 4. Architecture Fixes

### 4a. LLM Provider Expansion

Existing abstraction is clean: `llm/base.py` → `LLMProvider` ABC with `generate()`.
Three providers already exist: `gemini.py`, `claude.py`, and the factory in `base.py`.

**Existing bug to fix first:** The `Config` dataclass has `gemini_api_key` as the only API key field, and all call sites in `cli.py` and `pipeline.py` pass `config.gemini_api_key` regardless of provider. This means `LLM_PROVIDER=claude` would pass the Gemini key to Claude.

**Refactor (prerequisite, ~half day):**
1. Replace `Config.gemini_api_key` with generic `Config.llm_api_key` (resolved from `GEMINI_API_KEY`, `OPENAI_API_KEY`, or `ANTHROPIC_API_KEY` based on `LLM_PROVIDER`)
2. Update all 12+ call sites in `cli.py` and `pipeline.py`
3. Add `anthropic` as optional dependency in `pyproject.toml` (`[claude]` extra)

**Add two new providers:**
- `llm/openai.py` — using `openai` SDK. Supports GPT-4o, GPT-4o-mini.
- `llm/ollama.py` — using `httpx` to hit `localhost:11434/api/generate`. No SDK dependency. Supports any pulled model.

**Update `get_provider()` factory** to support `"openai"` and `"ollama"` (alongside existing `"gemini"` and `"claude"`).

**Config via env vars:**
```
LLM_PROVIDER=ollama
LLM_MODEL=llama3.1
GEMINI_API_KEY=...         # for gemini
OPENAI_API_KEY=sk-...      # for openai
ANTHROPIC_API_KEY=sk-ant-... # for claude
OLLAMA_HOST=http://localhost:11434  # for ollama
```

**README LLM table:** Gemini, OpenAI, Claude, Ollama (local).

### 4b. CSV/JSON Export

New `hunt export` command:
```
hunt export csv --output jobs.csv
hunt export csv --min-score 5 --output top-jobs.csv
hunt export json --output jobs.json
```

Simple: query DB, write with Python's `csv`/`json` modules. ~50 lines. No new dependencies.

### 4c. HTML→PDF Resume Fallback

Current: LLM generates LaTeX → `pdflatex` renders PDF.

New flow:
1. LLM generates resume content (same as today)
2. If `pdflatex` available → LaTeX path (best quality)
3. If not → Jinja2 HTML template + weasyprint → PDF (weasyprint is an optional `[pdf]` dep)

**Work involved (budget full day):**
- Design `config/resume_template.html` — professional Jinja2 template with print-media CSS
- Add parallel render path in `tailor/renderer.py` (HTML branch alongside LaTeX)
- `hunt doctor` reports which renderer is available
- If neither pdflatex nor weasyprint: generate Markdown resume as last-resort fallback

### 4d. Refactor run_japan.py

`run_japan.py` is 684 lines with significant autoresearch functionality (source research, data validation, score audit, resume audit, deep research loop) that does not exist in the current `hunt run` / `pipeline.py`.

**Scope decision:** Autoresearch is included in v0.1 — it's a key differentiator. The refactor:

1. Move autoresearch stage orchestration from `run_japan.py` into `pipeline.py` (the core stages: source research, data validation, score audit, resume audit)
2. Deep research (`--deep-research`, `--deep-research-loop`) becomes a `hunt research` CLI command
3. Move `run_japan.py` → `examples/japan_pipeline.py` with explanatory comments showing how to compose a custom regional pipeline (this script remains functional as a standalone runner)
4. Add `examples/README.md` explaining the example
5. `hunt run` reads from user's config dir, no hardcoded paths

### 4e. Config Location (XDG)

Current: everything in `config/` next to source code.

New defaults:
```
Config: ~/.config/job-hunter/
  profile.json, .env, searches.yaml, employers.yaml

Data: ~/.local/share/job-hunter/
  jobs.db, output/, sessions/, deep_research_results.tsv
```

`hunt init` creates these. `--config-dir` flag overrides. `hunt doctor` shows current paths.

---

## 5. Documentation

```
docs/
├── getting-started.md        # Install → init → first run (5 min)
├── configuration.md          # Every config file, all env vars
├── architecture.md           # Pipeline stages, data flow, module map
├── llm-providers.md          # Setup for Gemini, OpenAI, Ollama
├── adding-job-boards.md      # Tutorial: write a new scraper
├── adding-ats-strategies.md  # Tutorial: add a form-fill strategy
├── autoresearch.md           # Deep research engine, program.md steering
├── faq.md                    # Common issues (rate limits, 403s, pdflatex)
└── design/                   # Existing phase design docs (renamed from plans/)
```

**getting-started.md** covers three paths:
1. **Quickest (Ollama):** Zero API keys. Install → init → discover → score → export csv.
2. **Full pipeline (Gemini/OpenAI):** With API key. Adds tailor → sync notion.
3. **Docker:** `docker compose run job-hunter init` for one-command setup.

**architecture.md** includes:
- ASCII pipeline diagram
- Module map (which file does what)
- Data flow: URL → Job DB → enriched → scored → tailored → synced
- Extension points: scrapers, LLM providers, ATS strategies

**adding-job-boards.md** — concrete tutorial:
1. Create `src/job_hunter/discover/my_board.py`
2. Implement `scrape(query, location) → list[Job]`
3. Register in `config/sites.yaml`
4. Run `hunt discover`

---

## 6. Testing & Quality

**Existing tests:** 29 test files. Verify all pass, fix any failures.

**CI enforcement:** All tests + ruff lint + ruff format must pass on PRs.

**`hunt doctor` enhancements:**
- LLM provider connectivity check
- Resume renderer check (pdflatex vs weasyprint)
- Notion token validity (if configured)
- System dependency versions

---

## 7. Prerequisites

Before starting the 2-week clock:
- **Verify Phase 6 (Notion sync) completion.** The CLI has sync commands wired up and `notion/sync.py` + `notion/client.py` exist. Confirm `hunt sync push` and `hunt sync pull` work end-to-end, or explicitly mark Notion sync as "beta" in docs.

## 8. Two-Week Execution Plan

### Week 1: Clean & Essential

| Day | Work |
|-----|------|
| 1 | `git filter-repo` to purge secrets/PII/DBs/PDFs from history. Rotate all API keys. Fix `.gitignore`. Add `detect-secrets` pre-commit hook + scan baseline. |
| 2 | LICENSE (MIT), README.md, CONTRIBUTING.md, CLAUDE.md, CHANGELOG.md, SECURITY.md. Update `pyproject.toml` metadata. Restructure optional deps (`[jobspy]`, `[claude]`, `[openai]`, `[notion]`, `[pdf]`, `[apply]`, `[all]`). Remove dead `crawlee` extra. |
| 3 | XDG config paths: refactor `config.py` default paths, update all `config_dir` / DB path references (~15 call sites in `cli.py`, `pipeline.py`). Sanitize `config/resume.tex` to "Jane Doe" example. |
| 4 | `hunt init` setup wizard: interactive CLI creating `profile.json`, `.env`, default `searches.yaml` in XDG config dir. |
| 5 | Refactor `run_japan.py` → `examples/japan_pipeline.py`. Move autoresearch stages into `pipeline.py`. Add `hunt research` CLI command for deep research. Pin deps, generate lock file. |

### Week 2: Features & Docs

| Day | Work |
|-----|------|
| 6 | LLM refactor: replace `Config.gemini_api_key` with provider-aware key resolution. Update all 12+ call sites. Add `anthropic` as `[claude]` optional dep. |
| 7 | `llm/openai.py` + `llm/ollama.py`. Update `get_provider()` factory. Test with real calls. |
| 8 | `hunt export` (CSV/JSON). HTML→PDF resume fallback: Jinja2 template + weasyprint + print CSS. Markdown last-resort fallback. `hunt doctor` enhancements. |
| 9 | GitHub Actions CI (lint + test, Python 3.11/3.12/3.13). Run full test suite, fix failures. |
| 10 | All documentation: getting-started, configuration, architecture, llm-providers, adding-job-boards, adding-ats-strategies, autoresearch, faq. Final polish: test clean install flow. Tag v0.1.0. Push public. |

### Explicitly NOT in Scope

- Web dashboard
- Google Sheets sync
- Plugin/extension system
- Additional resume templates (ship 1 LaTeX + 1 HTML)
- New job board scrapers
- mypy type checking
- Docker (deferred to v0.2)
- PyPI publishing (install from GitHub for v0.1, PyPI for v0.2)
