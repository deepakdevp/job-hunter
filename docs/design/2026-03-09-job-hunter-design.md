# Job Hunter — Design Document

**Date:** 2026-03-09
**Status:** Approved

---

## Goal

A Python CLI that automates the grunt work of job searching while keeping humans in control of the final decision. Runs daily, finds jobs, scores them, tailors your resume, pushes everything to Notion. You review, you click apply.

---

## Architecture Overview

```
                    ┌──────────────┐
                    │  DAILY CRON   │
                    │  hunt run     │
                    └──────┬───────┘
                           │
     ┌─────────────────────┼─────────────────────┐
     ▼                     ▼                     ▼
┌──────────┐       ┌────────────┐       ┌──────────────┐
│ JobSpy   │       │  Workday   │       │   Custom     │
│ LinkedIn │       │  48+ portals│      │   Scrapers   │
│ Indeed   │       │  (registry)│       │  GaijinPot   │
│ Glassdoor│       │            │       │  Daijob      │
│ ZipRecr  │       │            │       │  JREC-IN     │
│ Google   │       │            │       │  (your list) │
└────┬─────┘       └─────┬──────┘       └──────┬───────┘
     │                   │                     │
     └─────────────────┬─┘─────────────────────┘
                       ▼
              ┌─────────────────┐
              │  Dedup (by URL) │
              │  vs Notion DB   │
              └────────┬────────┘
                       ▼
              ┌─────────────────┐
              │  Enrich         │  3-tier cascade:
              │  (full JD)      │  JSON-LD → CSS → AI
              └────────┬────────┘
                       ▼
              ┌─────────────────┐
              │  Score          │  Gemini 2.5 Flash
              │  1-10 + reason  │  + 2-sentence WHY
              └────────┬────────┘
                       ▼
              ┌─────────────────┐
              │  Tailor         │  Resume + Cover Letter
              │  + Validate     │  Diff vs resume_facts
              │  + Render PDF   │  Jinja2 + WeasyPrint
              └────────┬────────┘
                       ▼
              ┌─────────────────┐
              │  Notion Sync    │  Push jobs + PDFs
              │  Status: "New"  │
              └────────┬────────┘
                       │
                YOU REVIEW IN NOTION
                       │
                       ▼
              ┌─────────────────┐
              │  hunt apply     │  Playwright auto-fill
              │  (you confirm)  │  Pauses at CAPTCHA
              └─────────────────┘
```

---

## Project Structure

```
job-hunter/
├── src/job_hunter/
│   ├── __init__.py
│   ├── cli.py                      # Click CLI entry point
│   ├── config.py                   # Load .env, profile, searches
│   ├── database.py                 # Local SQLite for job queue + dedup cache
│   │
│   ├── discover/
│   │   ├── __init__.py
│   │   ├── jobspy_scraper.py       # python-jobspy (LinkedIn, Indeed, Glassdoor, Google, ZipRecruiter)
│   │   ├── workday_scraper.py      # Workday employer portal scraper
│   │   ├── japan_scraper.py        # Crawlee scrapers (GaijinPot, Daijob, JREC-IN)
│   │   ├── custom_scraper.py       # Base class for user-added site scrapers
│   │   └── dedup.py                # URL-based dedup against Notion + local DB
│   │
│   ├── enrich/
│   │   ├── __init__.py
│   │   └── detail.py               # 3-tier JD extraction (JSON-LD → CSS → AI)
│   │                                # Stolen pattern from ApplyPilot
│   │
│   ├── score/
│   │   ├── __init__.py
│   │   └── scorer.py               # LLM scores job 1-10 + 2-sentence explanation
│   │
│   ├── tailor/
│   │   ├── __init__.py
│   │   ├── resume_tailor.py        # LLM rewrites resume per job (never fabricates)
│   │   ├── cover_letter.py         # LLM generates targeted cover letter
│   │   ├── validator.py            # 3-mode validation (strict/normal/lenient)
│   │   │                           # Stolen pattern from ApplyPilot:
│   │   │                           #   - Banned filler words (50+)
│   │   │                           #   - LLM self-talk leak detection (30+)
│   │   │                           #   - Fabrication watchlist
│   │   │                           #   - Structural diff vs resume_facts
│   │   └── renderer.py             # Jinja2 + WeasyPrint → PDF
│   │
│   ├── apply/
│   │   ├── __init__.py
│   │   └── applicant.py            # Playwright form filler + Stagehand fallback
│   │
│   ├── notion/
│   │   ├── __init__.py
│   │   ├── client.py               # Notion API wrapper (notion-client SDK)
│   │   ├── database.py             # Create/manage job tracking DB
│   │   └── sync.py                 # Push jobs, update status, upload PDFs
│   │
│   └── llm/
│       ├── __init__.py
│       ├── base.py                 # Abstract LLM interface
│       ├── gemini.py               # Gemini provider (default, free tier)
│       └── claude.py               # Claude provider (optional, premium)
│
├── templates/
│   ├── resume_clean.html           # ATS-safe resume template (single column)
│   ├── resume_modern.html          # Slightly styled ATS-safe template
│   └── cover_letter.html           # Cover letter template
│
├── config/
│   ├── profile.json                # User profile + resume_facts (master truth)
│   ├── searches.yaml               # Search queries, titles, locations, boards
│   ├── employers.yaml              # Workday employer registry (stolen from ApplyPilot, expanded)
│   ├── sites.yaml                  # Site configs: blocked, SSO, base URLs, custom sites
│   └── searches.example.yaml       # Example search config
│
├── .env.example                    # Template for API keys
├── pyproject.toml
└── README.md
```

---

## Stolen from ApplyPilot (with improvements)

### 1. Workday Employer Registry (`employers.yaml`)

ApplyPilot ships 48 pre-configured Workday portals (Canadian banks, pension funds, tech companies, consulting firms). Each entry has `name`, `tenant`, `site_id`, `base_url`.

**Our improvements:**
- Ship their 48 as a starting point
- Add Japanese/international employers (Rakuten, Sony, Fujitsu, NTT, etc.)
- Add a `hunt employers add <company>` CLI command to discover and register new Workday tenants
- Tag employers by region for filtered searches

### 2. 3-Tier JD Extraction Cascade (`enrich/detail.py`)

ApplyPilot's approach is excellent and we adopt it directly:

**Tier 1 — JSON-LD** (zero LLM cost)
- Parse `<script type="application/ld+json">` tags
- Look for `@type: "JobPosting"` (including nested `@graph`)
- Extract `description` + resolve apply URL from `directApply`/`applicationContact`

**Tier 2 — CSS Selectors** (zero LLM cost)
- 20 curated description selectors: `#job-description`, `[data-testid="job-description"]`, `.ashby-job-posting-description`, `[role="main"] article`, etc.
- 13 apply URL selectors: `a[href*="apply"]`, `.ashby-job-posting-apply-button`, `#grnhse_app a[href*="apply"]`, etc.
- Fallback: scan all `<a>` tags for text containing "apply"

**Tier 3 — LLM Extraction** (1 LLM call)
- Strip nav/header/footer noise, truncate to 30k chars
- Send to LLM requesting `{full_description, application_url}`

**Our improvement:** Cache Tier 3 results in local SQLite so re-runs don't burn LLM tokens on already-enriched jobs.

### 3. Validation Strictness Modes (`tailor/validator.py`)

Three modes via `--validation` flag:

| Check | `strict` | `normal` (default) | `lenient` |
|-------|----------|---------------------|-----------|
| Fabricated companies/skills | error | error | error |
| LLM self-talk in output | error | error | error |
| Banned filler words (50+) | error → retry | warning only | ignored |
| LLM judge pass required | yes | best-effort | skipped |
| Cover letter word limit | 250 hard | 275 soft | not checked |
| Section structure check | strict | flexible variants | minimal |

**Banned words list** (from ApplyPilot, 50+ entries): "passionate", "spearheaded", "robust", "synergy", "proven track record", "I am excited", "furthermore", "adept at", "extensive experience", "proactive", etc.

**LLM leak phrases** (30+ entries): "I am sorry", "here is the corrected", "per your feedback", "the following resume", etc.

**Fabrication detection:** Diff generated resume against `resume_facts.json` — flag any company, title, degree, or certification not in the master file.

**Our improvement:** `lenient` recommended for Gemini free tier (saves 1 API call per job by skipping LLM judge).

### 4. Blocked Sites & SSO Registry (`sites.yaml`)

From ApplyPilot:
- **Blocked sites:** glassdoor (scraping issues), google careers, accenture, workopolis
- **Blocked SSO:** accounts.google.com, login.microsoftonline.com, okta.com, auth0.com
- **Manual ATS:** ibegin.tcsapps.com (unsolvable CAPTCHA)
- **Base URLs:** 16 sources for relative URL resolution

**Our improvement:** Add Japanese-specific blocked/manual entries as we discover them.

---

## Notion Database Schema

| Column | Type | Purpose |
|--------|------|---------|
| Job Title | title | Role name |
| Company | rich_text | Employer |
| Location | rich_text | City / Remote / Japan |
| Score | number | AI fit score 1-10 |
| Score Reason | rich_text | 2-sentence explanation of WHY |
| Status | select | `New` / `Reviewing` / `Tailored` / `Applied` / `Phone Screen` / `Interview` / `Offer` / `Rejected` |
| Job URL | url | Original posting |
| Apply URL | url | Direct application link |
| Source | select | LinkedIn / Indeed / GaijinPot / Daijob / Workday / etc. |
| Salary Min | number | Parsed minimum (for filtering) |
| Salary Max | number | Parsed maximum (for filtering) |
| Salary Raw | rich_text | Original salary text |
| Posted Date | date | When job was posted |
| Found Date | date | When we discovered it |
| Resume PDF | files | Tailored resume |
| Cover Letter | files | Generated cover letter |
| Tags | multi_select | Matched skills/keywords |
| Notes | rich_text | AI summary or user notes |
| Enrich Tier | select | `json-ld` / `css` / `ai` / `failed` |

---

## CLI Commands

```bash
# Setup
hunt init                    # Interactive wizard: profile, resume, API keys, Notion
hunt doctor                  # Pre-flight check of all dependencies

# Pipeline (run individually or all at once)
hunt discover                # Scrape all configured platforms
hunt enrich                  # Fetch full JDs (3-tier cascade)
hunt score                   # AI score all unscored jobs
hunt tailor [job-id]         # Tailored resume + cover letter for one job
hunt tailor --all            # Tailor all jobs above score threshold
hunt apply [job-id]          # Playwright auto-fill, you confirm submit

# Daily automation
hunt run                     # Full pipeline: discover → enrich → score → tailor → sync
hunt run --daily             # Same, optimized for cron (skip already-seen)
hunt run --workers 4         # Parallel discovery/enrichment

# Options
hunt run --min-score 8       # Override score threshold (default: 7)
hunt run --validation lenient  # Skip LLM judge (saves API calls)
hunt run --dry-run           # Preview without writing to Notion

# Utilities
hunt status                  # Pipeline stats (discovered, scored, tailored, applied)
hunt employers add <url>     # Register a new Workday employer
hunt employers list          # Show all Workday employers
```

---

## Data Flow (Daily)

```
06:00  CRON: hunt run --daily
         │
         ├─ Discover → scrape all platforms → ~100-500 raw jobs
         ├─ Dedup → check URLs against Notion DB → ~50-200 new jobs
         ├─ Enrich → 3-tier cascade → full JDs (Tier 1: ~60%, Tier 2: ~25%, Tier 3: ~15%)
         ├─ Score → Gemini rates each 1-10 + 2-sentence reason
         ├─ Filter → only score >= 7 → ~10-30 qualified jobs
         ├─ Tailor → resume PDF + cover letter per job
         ├─ Validate → strict/normal/lenient check (no fabrication)
         └─ Sync → push to Notion with status "New"

08:00  YOU: Open Notion
         │
         ├─ Browse jobs sorted by Score (descending)
         ├─ Read Score Reason — understand why AI liked it
         ├─ Review tailored resume PDF — tweak if needed
         ├─ Filter by Salary Min/Max, Location, Tags
         ├─ Set status → "Reviewing" for interesting ones
         └─ Skip or archive low-interest ones

WHEN READY: hunt apply <job-id>
         │
         ├─ Playwright opens Chrome
         ├─ Loads saved session (storageState)
         ├─ Auto-fills form from profile.json
         ├─ Uploads tailored resume + cover letter PDFs
         ├─ Stagehand fallback for unfamiliar form layouts
         ├─ Pauses at CAPTCHA → you solve manually
         ├─ You confirm final submit
         └─ Updates Notion → status "Applied"
```

---

## Tech Stack

| Component | Technology | Cost |
|-----------|-----------|------|
| Language | Python 3.11+ | $0 |
| CLI framework | Click | $0 |
| Job scraping (major boards) | python-jobspy | $0 |
| Job scraping (Workday) | Custom scraper + employers.yaml | $0 |
| Job scraping (Japan) | Crawlee + Playwright | $0 |
| JD enrichment | 3-tier cascade (JSON-LD/CSS/AI) | $0 (Tier 1-2), minimal (Tier 3) |
| LLM (default) | Gemini 2.5 Flash free tier (1,500 req/day) | $0 |
| LLM (premium) | Claude Sonnet 4.6 (optional) | ~$3/1M tokens |
| Database/Dashboard | Notion API + notion-client | $0 |
| Local cache | SQLite | $0 |
| Resume rendering | Jinja2 + WeasyPrint | $0 |
| Browser automation | Playwright | $0 |
| AI form filling | Stagehand (fallback) | $0 |
| Scheduling | macOS launchd / cron | $0 |
| **Total** | | **$0** |

---

## Key Design Decisions

1. **Human-in-the-loop** — You review every job, you approve every application. No mass auto-apply.
2. **Notion as UI** — No custom dashboard. Notion is your tracker, filter, sorter, and review tool.
3. **resume_facts pattern** — Structured JSON of real experience. LLM reorganizes but never fabricates.
4. **3-tier enrichment** — JSON-LD → CSS → AI cascade minimizes LLM cost (85% of jobs enriched free).
5. **3-mode validation** — strict/normal/lenient. Catch hallucinations always, adjust filler strictness by tier.
6. **Pluggable LLM** — Abstract interface. Gemini free default, swap to Claude/OpenAI anytime.
7. **Pluggable scrapers** — Add new sites by dropping an adapter into `discover/`.
8. **Score + reason** — Not just a number. 2-sentence explanation so you understand the AI's judgment.
9. **Salary parsing** — Min/max numbers for Notion filtering, not just raw text.
10. **Local SQLite cache** — Dedup, enrichment cache, apply queue. Survives across runs.

---

## What We Do Better Than ApplyPilot

| Area | ApplyPilot | Job Hunter |
|------|-----------|------------|
| Control | Autonomous mass-apply | Human reviews + approves |
| Dashboard | SQLite + CLI status | Notion (sort, filter, kanban) |
| Score transparency | Number only | Number + 2-sentence reason |
| Salary intelligence | Raw text | Parsed min/max for filtering |
| Application tracking | Applied/Failed binary | Full pipeline: New → Interview → Offer |
| Auto-apply cost | Claude Code CLI ($$$) | Playwright direct ($0) |
| Japanese boards | None | GaijinPot, Daijob, JREC-IN |
| Enrichment caching | Re-fetches every run | SQLite cache, skip enriched jobs |
| Resume templates | Plain text output | 2-3 ATS-safe HTML/CSS templates |
