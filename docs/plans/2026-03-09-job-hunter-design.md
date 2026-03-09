# Job Hunter — Design Document

**Date:** 2026-03-09
**Status:** Approved — Implementation in progress

---

## Project Goal

Build a Python CLI tool that:
1. Scrapes job platforms (LinkedIn, Indeed, Glassdoor, Japanese boards)
2. Scores jobs against user's profile using an LLM
3. Stores everything in a Notion database with ratings
4. Creates an ATS-tailored resume + cover letter per job
5. Has a manual "Apply" command — user reviews and triggers only when satisfied
6. Runs daily via cron

**Key principle:** Human-in-the-loop. No mass auto-apply. Quality over quantity.

---

## Architecture

```
job-hunter/
├── src/
│   ├── cli.py                  # Click CLI (hunt discover/tailor/apply/status)
│   ├── config.py               # Load .env, profile, searches config
│   ├── discover/
│   │   ├── jobspy_scraper.py   # python-jobspy wrapper
│   │   ├── japan_scraper.py    # Custom scrapers for JP sites
│   │   └── dedup.py            # URL-based deduplication
│   ├── enrich/
│   │   └── description.py      # Fetch full JD
│   ├── score/
│   │   └── scorer.py           # LLM scores job 1-10 against profile
│   ├── tailor/
│   │   ├── resume_tailor.py    # LLM rewrites resume per job
│   │   ├── cover_letter.py     # LLM generates cover letter
│   │   ├── validator.py        # Ensures no fabrication
│   │   └── renderer.py         # Jinja2 + WeasyPrint → PDF
│   ├── apply/
│   │   └── applicant.py        # Playwright form filler
│   ├── notion/
│   │   ├── client.py           # Notion API wrapper
│   │   ├── database.py         # Create/manage job tracking DB
│   │   └── sync.py             # Push jobs to Notion, update status
│   └── llm/
│       ├── base.py             # Abstract LLM interface
│       ├── gemini.py           # Gemini provider (default, free)
│       └── claude.py           # Claude provider (optional, premium)
├── templates/
│   └── resume.html             # ATS-safe resume template
├── config/
│   ├── profile.json            # User profile + resume_facts
│   ├── searches.yaml           # Search queries, titles, locations, boards
│   └── sites.yaml              # Japanese/custom site configs
├── .env                        # API keys
├── pyproject.toml
└── README.md
```

---

## Notion Database Schema

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
| Notes | rich_text | AI summary or user notes |
| Tags | multi_select | Skills/keywords matched |

---

## CLI Commands

```bash
hunt init              # Setup wizard: profile, resume, API keys, Notion
hunt discover          # Scrape all configured platforms
hunt enrich            # Fetch full descriptions for discovered jobs
hunt score             # AI score all unscored jobs
hunt tailor [job-id]   # Generate tailored resume + cover letter
hunt tailor --all      # Tailor all jobs above score threshold
hunt apply [job-id]    # Open browser, auto-fill application form
hunt status            # Show pipeline stats
hunt run               # Run discover → enrich → score → tailor pipeline
hunt run --daily       # Same as run, designed for cron
```

---

## Tech Stack

| Component | Technology | Cost |
|-----------|-----------|------|
| Language | Python 3.11+ | Free |
| CLI | Click | Free |
| Job scraping (Western) | python-jobspy | Free |
| Job scraping (Japan) | Requests + BeautifulSoup | Free |
| LLM (default) | Gemini 2.5 Flash free tier | Free |
| LLM (premium) | Claude Sonnet 4.6 | ~$3/1M tokens |
| Database/Dashboard | Notion API + notion-client | Free |
| Resume rendering | Jinja2 + WeasyPrint | Free |
| Browser automation | Playwright | Free |
| Scheduling | System cron | Free |

**Total cost: $0** (with Gemini free tier)

---

## Data Flow

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
   ├── Read tailored resume + cover letter previews
   ├── Mark status as "Reviewing" or skip
   └── When ready → run: hunt apply [job-id]

3. MANUAL APPLY: hunt apply [job-id]
   ├── Playwright opens browser
   ├── Auto-fills form fields from profile
   ├── Uploads tailored resume + cover letter
   ├── Pauses at CAPTCHA for user
   ├── User confirms final submit
   └── Updates Notion status → "Applied"
```
