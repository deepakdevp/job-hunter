# Job Hunter — Session Context (for continuing in claude.ai)

> Drop this entire file into a new claude.ai conversation to resume where we left off.

## Project Goal

Build **Job Hunter** — a Python CLI tool that:
1. Scrapes job platforms the user specifies (LinkedIn, Japanese/international boards)
2. Finds relevant jobs, scores them against the user's profile
3. Stores everything in a Notion database with ratings
4. Creates an ATS-tailored resume per job
5. Has a manual "Apply" button — user clicks only when they approve the match
6. Runs daily via cron to find new posts

**Key principle:** Human-in-the-loop. No mass auto-apply. Quality over quantity.

---

## Research Completed (4 areas)

### 1. Notion API

- **Create databases programmatically:** Yes, via `POST /v1/databases`
- **URL property for "Apply" link:** Fully supported
- **Button property:** NOT available via API (UI-only). Use URL property instead.
- **Rate limit:** 3 requests/second (plenty for job tracking)
- **Best Python SDK:** `notion-client` (pip install notion-client) — official community port
- **Update properties:** Yes, e.g., mark job as "Applied" via `PATCH /v1/pages/{page_id}`
- **API version note:** 2025-09-03 introduced Data Sources model; older tutorials may be outdated

### 2. Job Scraping

**For major Western boards:**
- **python-jobspy** (v1.1.82) — supports LinkedIn, Indeed, Glassdoor, Google, ZipRecruiter
- LinkedIn caps at ~10 pages per IP; mobile proxies get ~85% account survival
- Indeed has no rate limiting — most reliable scraper
- All boards cap at ~1,000 jobs per search query
- Install with `--no-deps` due to numpy pin conflict

**For Japanese job portals:**
- **No APIs exist** for GaijinPot, Daijob, JREC-IN
- Use **Crawlee + Playwright** for JS-heavy sites, **Requests + BeautifulSoup** for server-rendered (JREC-IN)
- Japanese sites have lighter anti-bot than LinkedIn
- Handle encoding: UTF-8 throughout, some sites use shift_JIS/EUC-JP
- Conservative rate: 1 request per 5-10 seconds
- Always check robots.txt

**Architecture:**
```
python-jobspy (LinkedIn, Indeed, Glassdoor, Google, ZipRecruiter)
    +-- Proxy pool (mobile for LinkedIn, datacenter OK for Indeed)
Custom Crawlee+Playwright scrapers (GaijinPot, Daijob, JREC-IN, etc.)
    +-- Per-site adapters with robots.txt compliance
    v
Unified data pipeline → dedup → Notion
```

### 3. ATS Resume Tailoring

**ATS-friendly rules:**
- Single-column, standard fonts, no tables/graphics
- .docx for best parsing; plain PDF acceptable
- Standard section headings: "Professional Experience", "Education", "Skills"
- Mirror exact phrases from job posting (3-5 keyword matches minimum)
- Quantify 60-70% of bullet points

**Architecture:**
1. Store master `resume_facts.json` — structured truth (companies, projects, metrics, skills)
2. Parse JD → extract required skills, keywords, seniority signals
3. LLM rewrites resume: reorder, rephrase, inject keywords. **Never fabricate.**
4. Validate: diff against resume_facts to ensure no new companies/titles/dates invented
5. Render: Jinja2 template → HTML → WeasyPrint → PDF

**LLM recommendation:**
- **Gemini 2.5 Flash free tier** — 1,500 req/day, $0 cost, good quality for keyword optimization
- **Claude Sonnet 4.6** — best prose quality, use as optional second-pass for senior roles
- Abstract LLM behind interface to swap models easily

**PDF stack:** Jinja2 + WeasyPrint (HTML/CSS → PDF, far easier than ReportLab)

### 4. Auto-Apply (Browser Automation)

**Playwright is the winner** over Selenium/Puppeteer:
- Auto-wait eliminates flakiness
- Browser contexts for isolated sessions
- `storageState()` for session persistence (login once, reuse)

**Hybrid approach (80/20):**
- 80% Playwright scripts for deterministic steps (fill name, email, upload resume)
- 20% Stagehand `act()`/`extract()` for unfamiliar form layouts and screening questions
- Pure LLM navigation is 7x slower and 4x more expensive

**CAPTCHA:** For human-in-the-loop system, just pause and let user solve manually. No service costs.

**Success rates:** Tailored applications get 78% higher response rate than generic. Quality > quantity.

---

## Design Decision: Approach 1 — Full Python CLI + Notion (Recommended)

**Why this approach:**
- Zero cost (Gemini free tier + Notion free plan)
- Full local control, cron-able for daily runs
- Notion IS the dashboard — no need to build a UI
- Human-in-the-loop = safe, no ToS violations from mass auto-apply

**Rejected alternatives:**
- Web app (Next.js + Supabase) — overengineered for 1 user
- Hybrid CLI + web dashboard — two systems to maintain

---

## Proposed Architecture (NEEDS APPROVAL)

```
job-hunter/
├── src/
│   ├── cli.py              # Click CLI (hunt discover/tailor/apply/status)
│   ├── config.py            # Load .env, profile, searches config
│   ├── discover/
│   │   ├── jobspy_scraper.py    # python-jobspy wrapper
│   │   ├── japan_scraper.py     # Custom Crawlee scrapers for JP sites
│   │   └── dedup.py             # URL-based deduplication
│   ├── enrich/
│   │   └── description.py       # Fetch full JD (JSON-LD → CSS → AI extraction)
│   ├── score/
│   │   └── scorer.py            # LLM scores job 1-10 against profile
│   ├── tailor/
│   │   ├── resume_tailor.py     # LLM rewrites resume per job
│   │   ├── cover_letter.py      # LLM generates cover letter
│   │   ├── validator.py         # Ensures no fabrication
│   │   └── renderer.py          # Jinja2 + WeasyPrint → PDF
│   ├── apply/
│   │   └── applicant.py         # Playwright form filler
│   ├── notion/
│   │   ├── client.py            # Notion API wrapper
│   │   ├── database.py          # Create/manage job tracking DB
│   │   └── sync.py              # Push jobs to Notion, update status
│   └── llm/
│       ├── base.py              # Abstract LLM interface
│       ├── gemini.py            # Gemini provider (default, free)
│       └── claude.py            # Claude provider (optional, premium)
├── templates/
│   └── resume.html              # ATS-safe resume template
├── config/
│   ├── profile.json             # User profile + resume_facts
│   ├── searches.yaml            # Search queries, titles, locations, boards
│   └── sites.yaml               # Japanese/custom site configs
├── .env                         # API keys (GEMINI_API_KEY, NOTION_TOKEN)
├── pyproject.toml
└── README.md
```

### Notion Database Schema

| Column | Type | Purpose |
|--------|------|---------|
| Job Title | title | Job name |
| Company | rich_text | Employer |
| Location | rich_text | City/remote |
| Score | number | AI fit score 1-10 |
| Status | select | New / Reviewing / Tailored / Applied / Rejected / Interview |
| Job URL | url | Link to original posting |
| Apply URL | url | Direct application link |
| Source | select | LinkedIn / Indeed / GaijinPot / etc. |
| Salary | rich_text | Compensation if listed |
| Posted Date | date | When job was posted |
| Found Date | date | When we discovered it |
| Resume PDF | files | Tailored resume attachment |
| Cover Letter | files | Generated cover letter |
| Notes | rich_text | AI summary or user notes |
| Tags | multi_select | Skills/keywords matched |

### CLI Commands

```bash
hunt init              # Setup wizard: profile, resume, API keys, Notion
hunt discover          # Scrape all configured platforms
hunt enrich            # Fetch full descriptions for discovered jobs
hunt score             # AI score all unscored jobs
hunt tailor [job-id]   # Generate tailored resume + cover letter for a job
hunt tailor --all      # Tailor all jobs above score threshold
hunt apply [job-id]    # Open browser, auto-fill application form
hunt status            # Show pipeline stats
hunt run               # Run discover → enrich → score → tailor pipeline
hunt run --daily       # Same as run, designed for cron
```

### Data Flow

```
1. DAILY CRON: hunt run --daily
   ├── Discover: scrape all platforms → new jobs
   ├── Enrich: fetch full JDs
   ├── Score: AI rates each job 1-10
   ├── Filter: only jobs >= threshold (default 7)
   ├── Tailor: generate resume + cover letter per job
   └── Sync: push everything to Notion DB

2. USER REVIEWS in Notion:
   ├── Browse jobs sorted by score
   ├── Read tailored resume + cover letter
   ├── Mark status as "Reviewing" or skip
   └── When ready → click Apply URL or run:

3. MANUAL APPLY: hunt apply [job-id]
   ├── Playwright opens browser
   ├── Loads saved session (storageState)
   ├── Auto-fills form fields from profile
   ├── Uploads tailored resume + cover letter
   ├── Pauses at CAPTCHA for user
   ├── User confirms final submit
   └── Updates Notion status → "Applied"
```

### Tech Stack

| Component | Technology | Cost |
|-----------|-----------|------|
| Language | Python 3.11+ | Free |
| CLI framework | Click | Free |
| Job scraping (Western) | python-jobspy | Free |
| Job scraping (Japan) | Crawlee + Playwright | Free |
| LLM (default) | Gemini 2.5 Flash free tier | Free |
| LLM (premium, optional) | Claude Sonnet 4.6 | ~$3/1M tokens |
| Database/Dashboard | Notion API + notion-client | Free |
| Resume rendering | Jinja2 + WeasyPrint | Free |
| Browser automation | Playwright | Free |
| AI form filling | Stagehand (fallback) | Free |
| Scheduling | System cron / launchd | Free |

**Total cost: $0** (with Gemini free tier)

---

## Status: Design presented, awaiting user approval

Next steps after approval:
1. Write design doc to `docs/plans/2026-03-09-job-hunter-design.md`
2. Create implementation plan (writing-plans skill)
3. Scaffold project and start building
