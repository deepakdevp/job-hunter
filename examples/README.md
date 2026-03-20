# Examples

## japan_pipeline.py

A standalone script that demonstrates how to build a **region-specific** job
hunting pipeline using job-hunter's building blocks.

### What it does

Runs the full pipeline end-to-end for Japan-based job searches:

1. **Discover** -- scrapes Indeed, LinkedIn (via JobSpy), TokyoDev, JapanDev,
   GaijinPot, and Workday employer portals, filtering to Japan locations.
2. **Enrich** -- fetches full job descriptions for newly discovered jobs.
3. **Score** -- scores each job against your `config/profile.json`.
4. **Tailor** -- generates tailored LaTeX resumes for high-scoring jobs.
5. **Sync** -- pushes results to a dedicated "Job Hunter Japan" Notion database.

Between stages, four autoresearch passes run automatically:

- **Source Research** -- validates that employer Workday URLs are still live.
- **Data Validation** -- checks for dead URLs, duplicates, non-Japan jobs, and
  low-quality listings.
- **Score Audit** -- re-checks scores with rule-based and LLM auditors.
- **Resume Audit** -- flags tailored resumes that may need regeneration.

An optional **Deep Research** stage (Karpathy-style iterative web search + LLM)
can be enabled with `--deep-research` or run in a never-stop loop with
`--deep-research-loop`.

### Prerequisites

```bash
pip install -e ".[all]"
```

You also need the following files in `config/`:

| File                     | Purpose                          |
|--------------------------|----------------------------------|
| `profile.json`           | Your skills, experience, prefs   |
| `japan_searches.yaml`    | JobSpy search queries for Japan  |
| `japan_employers.yaml`   | Workday employer portal URLs     |
| `resume.tex`             | Your LaTeX master resume         |
| `.env`                   | API keys and Notion credentials  |

### Usage

```bash
# Full pipeline
python examples/japan_pipeline.py

# Skip stages
python examples/japan_pipeline.py --skip-discover --skip-enrich

# Deep research only
python examples/japan_pipeline.py --deep-research-only

# Never-stop deep research loop (Ctrl+C to stop)
python examples/japan_pipeline.py --deep-research-loop --deep-min-score 6
```

### Adapting for other regions

1. Copy `japan_pipeline.py` to a new file (e.g. `europe_pipeline.py`).
2. Replace the Japan-specific scrapers and location filters with your target
   region's equivalents.
3. Update the config file paths (`japan_searches.yaml` -> `europe_searches.yaml`,
   etc.).
4. Adjust the location keywords in the Workday filter section.
