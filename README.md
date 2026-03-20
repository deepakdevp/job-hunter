# job-hunter

**AI-powered job hunting pipeline that discovers, scores, tailors resumes, and auto-applies.**

![Python 3.11+](https://img.shields.io/badge/python-3.11%2B-blue)
![License: MIT](https://img.shields.io/badge/license-MIT-green)

---

## Features

job-hunter automates your entire job search through an 8-stage pipeline:

| # | Stage | Description |
|---|-------|-------------|
| 1 | **Discover** | Scrape jobs from Indeed, LinkedIn, TokyoDev, JapanDev, GaijinPot, Workday portals |
| 2 | **Enrich** | Fetch full job descriptions via a 3-tier cascade (direct, proxy, LLM) |
| 3 | **Score** | Pre-filter + multi-criteria LLM scoring against your profile |
| 4 | **Tailor** | Generate per-job tailored LaTeX resumes with validation |
| 5 | **Cover Letter** | Generate targeted cover letters |
| 6 | **Sync** | Two-way sync with Notion for tracking (beta) |
| 7 | **Apply** | Auto-fill application forms on Workday, Greenhouse, Lever, Ashby, Indeed |
| 8 | **AutoResearch** | Karpathy-style deep research on companies and roles |

### Pipeline

```
searches.yaml + profile.json
        |
        v
  +-----------+     +---------+     +-------+     +--------+
  | Discover  | --> | Enrich  | --> | Score | --> | Tailor |
  +-----------+     +---------+     +-------+     +--------+
                                                      |
                                        +-------------+-------------+
                                        v             v             v
                                   +---------+   +-------+   +---------+
                                   |  Sync   |   | Apply |   | Research|
                                   | (Notion)|   | (ATS) |   | (Deep)  |
                                   +---------+   +-------+   +---------+
```

## Quickstart

```bash
# Install with core dependencies
pip install job-hunter

# Or install with all optional extras
pip install "job-hunter[all]"

# Set up your config directory
hunt doctor          # check environment
hunt discover        # scrape job boards
hunt enrich          # fetch full descriptions
hunt score           # score against your profile
hunt tailor --all    # generate tailored resumes
hunt status          # view pipeline statistics
hunt run             # run the full pipeline end-to-end
```

### Configuration

Create these files in your working directory:

- `profile.json` -- your skills, experience, preferences
- `searches.yaml` -- search queries, locations, boards
- `employers.yaml` -- Workday employer portal URLs
- `.env` -- API keys (LLM provider, Notion, etc.)

## Supported Job Boards

| Board | Method | Extra Required |
|-------|--------|----------------|
| Indeed | JobSpy | `jobspy` |
| LinkedIn | JobSpy | `jobspy` |
| Glassdoor | JobSpy | `jobspy` |
| ZipRecruiter | JobSpy | `jobspy` |
| Google Jobs | JobSpy | `jobspy` |
| TokyoDev | Custom scraper | -- |
| JapanDev | Custom scraper | -- |
| GaijinPot | Custom scraper | -- |
| Workday | Custom scraper | -- |

## Supported LLM Providers

| Provider | Extra Required | Environment Variable |
|----------|----------------|---------------------|
| Gemini | `gemini` | `GEMINI_API_KEY` |
| Claude | `claude` | `ANTHROPIC_API_KEY` |
| OpenAI | `openai` | `OPENAI_API_KEY` |
| Ollama | -- | -- (local) |

## Supported ATS Platforms (Auto-Apply)

| Platform | Extra Required |
|----------|----------------|
| Workday | `apply` |
| Greenhouse | `apply` |
| Lever | `apply` |
| Ashby | `apply` |
| Indeed | `apply` |

## Installation Extras

```bash
pip install "job-hunter[gemini]"       # Gemini LLM provider
pip install "job-hunter[claude]"       # Claude LLM provider
pip install "job-hunter[openai]"       # OpenAI LLM provider
pip install "job-hunter[notion]"       # Notion sync
pip install "job-hunter[pdf]"          # PDF resume rendering
pip install "job-hunter[apply]"        # Browser automation for auto-apply
pip install "job-hunter[jobspy]"       # JobSpy job board scraping
pip install "job-hunter[dev]"          # Development dependencies
pip install "job-hunter[all]"          # Everything
```

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md) for development setup, code style, and how to add new scrapers or ATS strategies.

## License

[MIT](LICENSE)
