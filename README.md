# Job Hunter

AI-powered job hunting CLI with Notion integration. Scrapes job boards, scores jobs against your profile, generates tailored resumes, and lets you apply with one command.

**Key principle: Human-in-the-loop. No mass auto-apply. Quality over quantity.**

---

## Features

- **Discover** — Scrapes LinkedIn, Indeed, Glassdoor, GaijinPot, JREC-IN, and more
- **Score** — AI rates each job 1-10 against your profile (Gemini free tier = $0)
- **Tailor** — Generates ATS-optimized resume + cover letter per job, never fabricates
- **Notion dashboard** — All jobs tracked in Notion with score, status, and tailored docs
- **Apply** — Playwright auto-fills application forms; you review and submit

---

## Quick Start

### 1. Install

```bash
pip install -e ".[jobspy]"
playwright install chromium
```

### 2. Setup

```bash
cp .env.example .env
# Fill in NOTION_TOKEN and GEMINI_API_KEY in .env

hunt init
# Copies config templates; edit them next

cp config/profile.example.json config/profile.json
cp config/searches.example.yaml config/searches.yaml
# Edit both files with your info
```

### 3. Run

```bash
# Full pipeline (discover → score → tailor → sync to Notion)
hunt run

# Or step by step:
hunt discover     # scrape job boards
hunt enrich       # fetch full descriptions
hunt score        # AI rate each job
hunt tailor --all # generate tailored resumes for top jobs
hunt sync         # push to Notion
```

### 4. Apply

Review jobs in Notion, then apply to the ones you like:

```bash
hunt apply <job-url-suffix>
# Opens browser, auto-fills form, you confirm and submit
```

---

## Configuration

### `config/profile.json`

Your resume facts. The LLM **only rephrases** existing content — it never invents companies, dates, or metrics.

```json
{
  "name": "Jane Smith",
  "email": "jane@example.com",
  "experience": [
    {
      "title": "Senior Engineer",
      "company": "Acme Corp",
      "start": "2021-03",
      "end": "Present",
      "bullets": ["Led migration of..."]
    }
  ]
}
```

### `config/searches.yaml`

```yaml
platforms: [linkedin, indeed, glassdoor, gaijinpot]
score_threshold: 7
queries:
  - search_term: "Senior Python Engineer"
    location: "Remote"
    country: "USA"
```

### `.env`

```
NOTION_TOKEN=secret_...
NOTION_DATABASE_ID=...
GEMINI_API_KEY=...
LLM_PROVIDER=gemini
LLM_MODEL=gemini-2.0-flash
```

---

## Cron Setup

```bash
# Run daily at 8 AM
0 8 * * * cd /path/to/job-hunter && hunt run --daily >> ~/.job-hunter/daily.log 2>&1
```

---

## CLI Reference

```
hunt init              Setup wizard
hunt discover          Scrape all platforms
hunt enrich            Fetch full job descriptions
hunt score             AI score all jobs
hunt tailor [id]       Tailor resume + cover letter for a job
hunt tailor --all      Tailor all jobs above threshold
hunt apply [id]        Open browser, auto-fill application
hunt sync              Push jobs to Notion
hunt status            Show pipeline stats
hunt run               Full pipeline (discover→enrich→score→tailor→sync)
hunt run --daily       Same, quiet mode for cron
```

---

## Architecture

```
python-jobspy          LinkedIn, Indeed, Glassdoor, Google, ZipRecruiter
Custom scrapers        GaijinPot, JREC-IN (robots.txt compliant)
    ↓
Deduplication          URL-hash based, persistent across runs
    ↓
Enrichment             Fetch full JD (JSON-LD → CSS → text fallback)
    ↓
Scoring                LLM rates fit 1-10, extracts keywords, writes summary
    ↓
Tailoring              LLM rewrites resume bullets to match JD keywords
    ↓
Validation             Diff against original facts — no fabrication allowed
    ↓
Rendering              Jinja2 → HTML → WeasyPrint → ATS-safe PDF
    ↓
Notion sync            Create/update job pages with all metadata
    ↓
Apply (manual)         Playwright auto-fills forms; user confirms submit
```

---

## Cost

| Component | Cost |
|-----------|------|
| Gemini 2.5 Flash (default LLM) | **Free** (1,500 req/day) |
| Notion API | **Free** |
| All scrapers | **Free** |
| Claude Sonnet (optional) | ~$3/1M tokens |
| **Total** | **$0** |

---

## Stack

- **Python 3.11+** — CLI, all logic
- **Click + Rich** — CLI framework + beautiful output
- **python-jobspy** — Western job board scraping
- **Requests + BeautifulSoup** — Japanese board scraping
- **google-generativeai / anthropic** — LLM backends
- **notion-client** — Notion API
- **Jinja2 + WeasyPrint** — PDF resume rendering
- **Playwright** — Browser automation for applying
