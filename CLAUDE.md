# CLAUDE.md

## Project Overview

job-hunter is an AI-powered CLI tool that automates the full job search lifecycle: discovering jobs, enriching descriptions, scoring against your profile, deep evaluation with interview prep, generating tailored resumes and cover letters, LinkedIn outreach, syncing to Notion, and auto-applying via browser automation.

## Commands

```bash
# Development
pip install -e ".[dev,all]"          # install in editable mode
ruff check src/ tests/                # lint
ruff format src/ tests/               # format
pytest                                # run tests
pytest -x                             # stop on first failure

# Core Pipeline
hunt discover                         # scrape job boards
hunt enrich                           # fetch full job descriptions
hunt score                            # score jobs against profile
hunt evaluate --all                   # deep evaluation with interview prep
hunt tailor --all                     # generate tailored resumes
hunt apply --job-url URL              # apply to a specific job
hunt apply --all --dry-run            # dry-run batch apply
hunt run                              # full pipeline (discover->enrich->score->evaluate->tailor->sync)
hunt status                           # show pipeline stats
hunt doctor                           # check environment

# Evaluation & Intelligence
hunt evaluate --job-url URL           # deep-evaluate a specific job (blocks A-G)
hunt compare --min-score 5            # compare top jobs across 10 dimensions
hunt negotiate --job-url URL          # negotiation scripts + comp intelligence
hunt outreach --job-url URL           # LinkedIn outreach messages (3-sentence, <300 chars)

# Interview & Career
hunt stories list                     # list STAR+R story bank by theme
hunt stories search "conflict"        # search stories by keyword
hunt stories add --title T --theme T  # manually add a story
hunt evaluate-project "RAG chatbot"   # score a project idea (BUILD/SKIP/PIVOT)
hunt evaluate-training "AWS cert"     # evaluate a course/cert (DO/SKIP/TIMEBOX)

# Notion Sync
hunt sync init --page-id ID           # initialize Notion database
hunt sync push                        # push jobs to Notion
hunt sync pull                        # pull status from Notion

# Export
hunt export csv -o jobs.csv           # export to CSV
hunt export json -o jobs.json         # export to JSON
```

## Project Structure

```
src/job_hunter/
  cli.py              # Click CLI entry point (hunt command)
  config.py            # Config loader (profile.json, searches.yaml, .env)
  database.py          # SQLite Job database
  pipeline.py          # Full pipeline orchestration

  discover/            # Stage 1: Job discovery
    base_scraper.py    # Base scraper interface
    jobspy_scraper.py  # Indeed/LinkedIn/Glassdoor via python-jobspy
    japan_scrapers.py  # TokyoDev, JapanDev, GaijinPot custom scrapers
    workday_scraper.py # Workday employer portal scraper
    dedup.py           # URL-based deduplication

  enrich/              # Stage 2: JD enrichment
    runner.py          # 3-tier enrichment orchestrator
    fetcher.py         # HTTP fetching with retry
    detail.py          # Detail extraction
    rate_limiter.py    # Rate limiting

  score/               # Stage 3: Scoring
    prefilter.py       # Rule-based pre-filter (zero LLM cost)
    scorer.py          # Multi-criteria LLM scoring

  tailor/              # Stage 4-5: Resume + cover letter
    parser.py          # LaTeX resume parser
    tailor.py          # LLM resume tailoring
    renderer.py        # LaTeX -> PDF rendering
    cover_letter.py    # Cover letter generation
    cover_letter_renderer.py
    validator.py       # Output validation (strict/normal/lenient)

  llm/                 # LLM provider abstraction
    base.py            # ABC LLMProvider + get_provider() factory
    gemini.py          # Google Gemini
    claude.py          # Anthropic Claude

  notion/              # Stage 6: Notion sync
    client.py          # Notion API wrapper
    sync.py            # Two-way sync logic
    drive_uploader.py  # Google Drive PDF upload

  apply/               # Stage 7: Auto-apply
    applicant.py       # Main applicant orchestrator
    session.py         # Playwright session management
    field_mapper.py    # LLM-assisted field mapping
    strategies/        # ATS platform strategies (strategy pattern)
      base.py          # FormFiller ABC + detect_platform()
      workday.py
      greenhouse.py
      lever.py
      ashby.py
      indeed.py
      japan.py
      generic.py

  evaluate/            # Stage 3.5: Deep offer evaluation
    archetype.py       # Role archetype detection (6 archetypes)
    blocks.py          # Evaluation blocks A-G generators
    engine.py          # Evaluation orchestrator + markdown report
    compare.py         # Multi-offer comparison (10 dimensions)
    project.py         # Portfolio project evaluator (BUILD/SKIP/PIVOT)
    training.py        # Course/cert evaluator (DO/SKIP/TIMEBOX)

  stories/             # Interview story bank
    bank.py            # STAR+R story extraction, dedup, search

  outreach/            # LinkedIn outreach generation
    generator.py       # 3-sentence messages (<300 chars)

  negotiate/           # Negotiation intelligence
    intelligence.py    # Comp data + word-for-word scripts

  autoresearch/        # Stage 8: Deep research
    deep_research.py   # Karpathy-style iterative + 6-axis structured research
    source_research.py # Source discovery
    web_tools.py       # Web fetching utilities
    resume_audit.py    # Resume gap analysis
    score_audit.py     # Score explanation
    data_validation.py # Research output validation

tests/                 # pytest test suite (418 tests)
config/                # User config templates
```

## Key Patterns

- **Strategy pattern** for ATS form filling: each platform (Workday, Greenhouse, Lever, Ashby, Indeed) has its own `FormFiller` subclass in `apply/strategies/`. `detect_platform()` in `base.py` routes URLs to the correct strategy via regex matching.

- **ABC for LLM providers**: `LLMProvider` in `llm/base.py` defines the interface. `get_provider()` is the factory. Providers are lazy-imported to avoid requiring all SDKs.

- **Pipeline stages are independent**: each stage reads from and writes to the SQLite database (`database.py`). Stages can be run individually or chained via `hunt run`.

- **Lazy imports**: optional dependencies (jobspy, notion-client, google-genai, playwright, weasyprint) are imported inside functions, not at module level. This allows the CLI to work with only core deps installed.

## Important Files

- `src/job_hunter/cli.py` -- all CLI commands
- `src/job_hunter/database.py` -- Job dataclass, SQLite operations, StoryBankDB
- `src/job_hunter/llm/base.py` -- LLM provider ABC and factory
- `src/job_hunter/evaluate/engine.py` -- deep evaluation orchestrator
- `src/job_hunter/evaluate/archetype.py` -- 6 role archetypes + detection
- `src/job_hunter/apply/strategies/base.py` -- ATS strategy ABC and platform detection
- `src/job_hunter/config.py` -- configuration loading
- `pyproject.toml` -- dependencies and build config

## Ethical Guardrails

- NEVER submit application without user confirmation (non-dry-run requires `confirm_submit=True`)
- NEVER invent experience or metrics in any generated content
- NEVER share phone number in auto-generated outreach messages
- Weak match warning when score < 3: "consider skipping unless specific reason"
- Quality over speed: fewer high-score applications > blast all scored jobs
- All generated content matches JD language (English by default)
