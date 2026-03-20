# Adding Job Boards

This tutorial walks through adding a new custom scraper to Job Hunter.

## 1. Create the scraper file

Create `src/job_hunter/discover/my_board.py`:

```python
from __future__ import annotations

import logging

from job_hunter.database import Job
from job_hunter.discover.base_scraper import BaseScraper

logger = logging.getLogger(__name__)


class MyBoardScraper(BaseScraper):
    name = "MyBoard"
    base_url = "https://myboard.example.com"

    async def scrape(
        self, query: str = "", location: str = "", max_results: int = 50
    ) -> list[Job]:
        """Scrape MyBoard and return a list of Job objects."""
        jobs: list[Job] = []

        # Fetch the search results page (or API endpoint)
        url = f"{self.base_url}/api/jobs?q={query}&location={location}"
        data = await self._fetch_json(url)

        for item in data[:max_results]:
            jobs.append(
                Job(
                    url=item["url"],
                    title=item["title"],
                    company=item["company"],
                    location=item.get("location", ""),
                    source=self.name,
                )
            )

        logger.info(f"{self.name}: found {len(jobs)} jobs")
        return jobs
```

### Key points

- Extend `BaseScraper` from `discover/base_scraper.py`
- Implement `async scrape()` returning `list[Job]`
- Use `self._fetch(url)` for HTML or `self._fetch_json(url)` for JSON APIs
- The `Job` dataclass requires: `url`, `title`, `company`, `location`, `source`

## 2. Register in searches.yaml

Add your board under `custom_boards`:

```yaml
custom_boards:
  global:
    - name: "MyBoard"
      url: "https://myboard.example.com"
      type: "searchable"
```

## 3. Wire into the discover command

Add your scraper to `cli.py` in the `discover` command, or to `japan_scrapers.py` if it follows that pattern:

```python
from job_hunter.discover.my_board import MyBoardScraper

scraper = MyBoardScraper()
board_jobs = await scraper.scrape(query="software engineer", max_results=50)
all_jobs.extend(board_jobs)
await scraper.close()
```

## 4. Register in sites.yaml (optional)

If the board needs special enrichment handling, add its base URL:

```yaml
base_urls:
  "MyBoard": "https://myboard.example.com"
```

## 5. Test

```bash
# Run discover and check output
hunt discover --skip-jobspy --skip-workday

# Verify jobs landed in the database
hunt status
```

## BaseScraper API

```python
class BaseScraper(ABC):
    name: str                  # display name
    base_url: str              # root URL

    async def scrape(self, query, location, max_results) -> list[Job]: ...
    async def _fetch(self, url: str) -> str:        # returns HTML text
    async def _fetch_json(self, url: str) -> dict:   # returns parsed JSON
    async def close(self): ...                       # close httpx client
```

The base class provides an `httpx.AsyncClient` with sensible defaults (user-agent, redirects, 30s timeout).
