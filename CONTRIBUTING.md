# Contributing to job-hunter

Thanks for your interest in contributing! This guide covers development setup, code style, and how to extend the project.

## Development Setup

```bash
# Clone the repo
git clone https://github.com/deepakdevp/job-hunter.git
cd job-hunter

# Create a virtual environment
python -m venv .venv
source .venv/bin/activate

# Install in editable mode with dev extras
pip install -e ".[dev,all]"

# Install playwright browsers (needed for apply stage)
playwright install chromium
```

## Code Style

We use **ruff** for linting and formatting:

```bash
ruff check src/ tests/         # lint
ruff format src/ tests/         # format
```

Configuration is in `pyproject.toml`:
- Target: Python 3.11
- Line length: 100

Please run `ruff check` and `ruff format` before opening a PR.

## Running Tests

```bash
pytest                          # run all tests
pytest tests/test_score.py      # run a specific test file
pytest -x                       # stop on first failure
```

## PR Process

1. Fork the repo and create a feature branch from `main`.
2. Make your changes with tests where applicable.
3. Run `ruff check` and `ruff format` to ensure code style compliance.
4. Run `pytest` to confirm all tests pass.
5. Open a pull request with a clear description of what changed and why.

## How to Add a New Scraper

Job board scrapers live in `src/job_hunter/discover/`.

1. Create a new file or add to an existing one (e.g., `japan_scrapers.py` for Japan boards).
2. Subclass or follow the pattern in `base_scraper.py`.
3. Return a list of `Job` dataclass instances with at minimum: `url`, `title`, `company`, `source`.
4. Wire your scraper into the `discover` CLI command in `src/job_hunter/cli.py`.
5. Add tests in `tests/`.

## How to Add an ATS Strategy

ATS form-filling strategies live in `src/job_hunter/apply/strategies/`.

The project uses the **strategy pattern** -- each ATS platform has its own class:

1. Create a new file (e.g., `myplatform.py`) in `src/job_hunter/apply/strategies/`.
2. Subclass `FormFiller` from `base.py` and implement `fill_and_submit()`.
3. Add a URL-matching regex to `PLATFORM_PATTERNS` in `base.py` so `detect_platform()` routes to your strategy.
4. Add tests in `tests/`.

Example skeleton:

```python
from job_hunter.apply.strategies.base import FormFiller, FillResult

class MyPlatformFiller(FormFiller):
    async def fill_and_submit(self, page, job, profile) -> FillResult:
        # Navigate, fill fields, optionally submit
        ...
        return FillResult(success=True, fields_filled=10)
```

## How to Add an LLM Provider

LLM providers live in `src/job_hunter/llm/`.

1. Create a new file (e.g., `openai.py`).
2. Subclass `LLMProvider` from `base.py` and implement `generate()`.
3. Register the provider name in `get_provider()` in `base.py`.
4. If the provider needs a new dependency, add it as an optional extra in `pyproject.toml`.
