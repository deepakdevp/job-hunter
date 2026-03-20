# Getting Started

## Prerequisites

- **Python 3.11+**
- **Optional:** TeX Live (for PDF resume rendering; HTML fallback available)
- **Optional:** Playwright (`playwright install chromium`) for auto-apply

## Path 1: Quickest Setup (Ollama -- no API keys)

Ollama runs LLMs locally. Zero cost, no accounts needed.

### 1. Install Ollama and pull a model

```bash
# macOS
brew install ollama
ollama serve &
ollama pull llama3.1

# Linux
curl -fsSL https://ollama.com/install.sh | sh
ollama serve &
ollama pull llama3.1
```

### 2. Install job-hunter

```bash
pip install -e ".[all]"
# or minimal:
pip install -e ".[jobspy]"
```

### 3. Initialize config

```bash
hunt init
```

The wizard creates `~/.config/job-hunter/` with:
- `profile.json` -- your background, skills, target roles
- `.env` -- environment variables
- `searches.yaml` -- job search queries

Set these in your `.env`:

```
LLM_PROVIDER=ollama
LLM_MODEL=llama3.1
```

### 4. Run the pipeline

```bash
hunt discover          # scrape job boards
hunt enrich            # fetch full descriptions
hunt score             # rank against your profile
hunt export csv -o jobs.csv   # export results
```

### 5. Check status anytime

```bash
hunt status            # pipeline statistics
hunt doctor            # verify dependencies
```

## Path 2: Full Pipeline (Gemini/OpenAI API key)

Adds resume tailoring, cover letters, and Notion sync.

### 1. Install with all extras

```bash
pip install -e ".[all]"
```

### 2. Get an API key

Pick one provider (see [LLM Providers](llm-providers.md) for details):

| Provider | Env var | Free tier? |
|----------|---------|------------|
| Gemini   | `GEMINI_API_KEY` | Yes (generous) |
| OpenAI   | `OPENAI_API_KEY` | No |
| Claude   | `ANTHROPIC_API_KEY` | No |

### 3. Configure

```bash
hunt init
```

Edit `~/.config/job-hunter/.env`:

```
LLM_PROVIDER=gemini
LLM_MODEL=gemini-2.5-flash
GEMINI_API_KEY=your-key-here

# Optional: Notion sync
NOTION_TOKEN=secret_xxx
NOTION_PAGE_ID=your-page-id
```

### 4. Run the full pipeline

```bash
hunt discover                  # scrape jobs
hunt enrich                    # fetch descriptions
hunt score                     # LLM scoring
hunt tailor --all              # generate tailored resumes + cover letters
hunt sync init --page-id ID    # create Notion database (once)
hunt sync push                 # push jobs to Notion
```

Or run everything at once:

```bash
hunt run                       # discover -> enrich -> score -> tailor -> sync
```

### 5. Deep research (optional)

```bash
hunt research run              # single-pass research on high-value jobs
hunt research loop             # continuous re-research until Ctrl+C
```

### 6. Auto-apply (optional)

```bash
pip install -e ".[apply]"
playwright install chromium

hunt apply --login indeed.com  # save login session
hunt apply --all --dry-run     # test without submitting
hunt apply --all               # submit applications
```
