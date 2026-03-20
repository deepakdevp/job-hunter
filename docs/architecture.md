# Architecture

## Pipeline Overview

Job Hunter is an 8-stage pipeline. Each stage reads from and writes to a shared SQLite database. Stages can run individually or be chained with `hunt run`.

```
                        ┌─────────────────────────────┐
                        │     searches.yaml            │
                        │     employers.yaml           │
                        └─────────┬───────────────────┘
                                  │
                    ┌─────────────▼──────────────┐
              1     │         DISCOVER            │  JobSpy + custom scrapers
                    │   jobspy, japan, workday    │  + Workday portals
                    └─────────────┬──────────────┘
                                  │ new Job rows (status=new)
                    ┌─────────────▼──────────────┐
              2     │          ENRICH             │  3-tier: HTTP → BS4 → LLM
                    │   fetcher, detail, runner   │
                    └─────────────┬──────────────┘
                                  │ full descriptions + metadata
                    ┌─────────────▼──────────────┐
              3     │          SCORE              │  pre-filter + LLM scoring
                    │   prefilter, scorer         │  (1-10 scale)
                    └─────────────┬──────────────┘
                                  │ scored (status=scored)
                    ┌─────────────▼──────────────┐
              4     │          TAILOR             │  resume + cover letter
                    │   parser, tailor, renderer  │  per job
                    └─────────────┬──────────────┘
                                  │ PDFs in output/ (status=tailored)
                    ┌─────────────▼──────────────┐
              5     │        NOTION SYNC          │  two-way sync
                    │   client, sync, drive       │
                    └─────────────┬──────────────┘
                                  │ (status=synced)
                    ┌─────────────▼──────────────┐
              6     │          APPLY              │  browser automation
                    │   applicant, strategies/*   │  (Playwright)
                    └─────────────┬──────────────┘
                                  │ (status=applied)
                    ┌─────────────▼──────────────┐
              7     │      DEEP RESEARCH          │  Karpathy-style
                    │   autoresearch/*            │  agentic loops
                    └─────────────┬──────────────┘
                                  │ re-scored with evidence
                    ┌─────────────▼──────────────┐
              8     │         EXPORT              │  CSV / JSON output
                    │   export.py                 │
                    └─────────────────────────────┘
```

## Module Map

```
src/job_hunter/
  cli.py              Click CLI -- all hunt commands
  config.py           Config loader (XDG paths, .env, YAML, JSON)
  database.py         Job dataclass + SQLite CRUD
  pipeline.py         Full pipeline orchestration (hunt run)
  init_wizard.py      Interactive setup (hunt init)
  export.py           CSV/JSON export

  discover/           Stage 1: Job discovery
    base_scraper.py     BaseScraper ABC (httpx client, scrape method)
    jobspy_scraper.py   Indeed/LinkedIn/Glassdoor via python-jobspy
    japan_scrapers.py   TokyoDev, JapanDev, GaijinPot custom scrapers
    workday_scraper.py  Workday REST API scraper
    dedup.py            URL-based deduplication

  enrich/             Stage 2: Description enrichment
    runner.py           3-tier orchestrator (HTTP → BS4 → LLM)
    fetcher.py          HTTP fetching with retry + rate limiting
    detail.py           Structured detail extraction
    rate_limiter.py     Per-domain rate limiter

  score/              Stage 3: Scoring
    prefilter.py        Rule-based pre-filter (zero LLM cost)
    scorer.py           Multi-criteria LLM scoring (1-10)

  tailor/             Stages 4-5: Resume + cover letter
    parser.py           LaTeX resume parser
    tailor.py           LLM resume tailoring
    renderer.py         LaTeX → PDF (pdflatex) or HTML fallback
    cover_letter.py     LLM cover letter generation
    cover_letter_renderer.py  Cover letter → PDF/TXT
    validator.py        Output validation (strict/normal/lenient)

  llm/                LLM provider abstraction
    base.py             LLMProvider ABC + get_provider() factory
    gemini.py           Google Gemini
    openai.py           OpenAI GPT
    claude.py           Anthropic Claude
    ollama.py           Local Ollama

  notion/             Stage 6: Notion sync
    client.py           Notion API wrapper (create DB, upsert pages)
    sync.py             Two-way sync (push jobs, pull status)
    drive_uploader.py   Google Drive PDF upload

  apply/              Stage 7: Auto-apply
    applicant.py        Main orchestrator (login, apply, log)
    session.py          Playwright session persistence
    field_mapper.py     LLM-assisted form field mapping
    strategies/         ATS platform strategies (strategy pattern)
      base.py             BaseFormFiller ABC + detect_platform()
      workday.py          Workday strategy
      greenhouse.py       Greenhouse strategy
      lever.py            Lever strategy
      ashby.py            Ashby strategy
      indeed.py           Indeed strategy
      japan.py            Japan boards (Wantedly, Green, CareerCross)
      generic.py          Fallback for unknown platforms

  autoresearch/       Stage 8: Deep research
    deep_research.py    Karpathy-style iterative research engine
    source_research.py  Source discovery (web search)
    web_tools.py        Web fetching utilities
    resume_audit.py     Resume gap analysis
    score_audit.py      Score explanation with citations
    data_validation.py  Research output validation
```

## Data Flow

```
Job board URL
  → discover: scrape → Job(status=new, title, company, url)
  → enrich:   fetch description → Job(description, tech_stack, visa_sponsorship, ...)
  → score:    pre-filter + LLM → Job(score=1-10, score_reason, status=scored)
  → tailor:   LLM + LaTeX → Job(resume_path, cover_letter_path, status=tailored)
  → sync:     Notion API → Job(notion_page_id, status=synced)
  → apply:    Playwright → Job(status=applied)
```

All state lives in `jobs.db` (SQLite). Each stage reads jobs by status and writes them back with an updated status. This means you can re-run any stage independently.

## Extension Points

### Adding scrapers

Implement `BaseScraper` from `discover/base_scraper.py`. The `scrape()` method returns `list[Job]`. See [Adding Job Boards](adding-job-boards.md).

### Adding LLM providers

Implement `LLMProvider` from `llm/base.py`. Register in `get_provider()`. The only required method is `async generate(prompt, json_mode, max_tokens) -> str`.

### Adding ATS strategies

Implement `BaseFormFiller` from `apply/strategies/base.py`. Add a URL pattern to `PLATFORM_PATTERNS`. See [Adding ATS Strategies](adding-ats-strategies.md).

### Adding export formats

Add a function to `export.py` following the pattern of `export_csv()` and `export_json()`. Wire it up as a subcommand of `hunt export`.
