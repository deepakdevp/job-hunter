# FAQ

## TokyoDev returns 403 errors

TokyoDev rate-limits scrapers aggressively. Solutions:

- Reduce `max_results` for TokyoDev searches
- Add a delay between requests (the Japan scraper does this automatically)
- Skip Japan boards temporarily: `hunt discover --skip-japan`
- Use a different IP if you have been blocked (wait a few hours)

## "pdflatex not found" when tailoring resumes

The LaTeX renderer needs `pdflatex` on your PATH.

**Install TeX Live:**

```bash
# macOS
brew install --cask mactex-no-gui
# or lighter:
brew install basictex

# Ubuntu/Debian
sudo apt install texlive-latex-base texlive-fonts-recommended

# Fedora
sudo dnf install texlive-scheme-basic
```

**Alternative:** Job Hunter falls back to HTML rendering via WeasyPrint if pdflatex is not found. Install it with:

```bash
pip install -e ".[pdf]"
```

## Ollama "connection refused"

Ollama must be running as a background server before you use it.

```bash
# Start the server
ollama serve &

# Verify it is running
curl http://localhost:11434/api/tags
```

If you installed Ollama via the macOS app, it starts automatically. If installed via `brew`, you need to run `ollama serve` manually.

Also ensure you have pulled a model:

```bash
ollama pull llama3.1
```

## Notion sync errors

Common causes:

1. **Expired token:** Notion integration tokens do not expire, but if you regenerated one, update `NOTION_TOKEN` in `.env`.

2. **Wrong database ID:** After `hunt sync init`, copy the printed `NOTION_DATABASE_ID` into `.env`. The page ID and database ID are different.

3. **Missing permissions:** Go to the Notion page, click "..." > "Connections" > add your integration. The integration must have access to the parent page.

4. **Rate limiting:** Notion's API has a 3 requests/second limit. Job Hunter handles this with retry logic, but very large syncs may hit it. Run `hunt sync push` again -- it is idempotent.

## "No unenriched jobs found" after discover

This means all discovered jobs have already been enriched. Check with:

```bash
hunt status
```

If you want to re-enrich, the jobs need to be in `new` status. This is by design -- enrichment is expensive and should not repeat.

## Scoring takes a long time

The scorer first runs a rule-based pre-filter (zero LLM cost) to eliminate obvious mismatches, then sends remaining jobs to the LLM. If you have many jobs:

- Use `--limit` on `hunt enrich` to process in batches
- Use Gemini (fastest and cheapest for bulk scoring)
- Use Ollama if you want zero cost (slower but free)

## Auto-apply says "no eligible jobs"

Jobs must be in `tailored` or `synced` status to be eligible for apply. Run the full pipeline first:

```bash
hunt discover
hunt enrich
hunt score
hunt tailor --all
hunt apply --all --dry-run
```

Also check that the job has a valid `apply_url`. Some scraped jobs only have a listing URL, not a direct application link.

## How do I reset and start over?

Delete the data directory:

```bash
rm -rf ~/.local/share/job-hunter/jobs.db
```

Your config in `~/.config/job-hunter/` is preserved. Run `hunt discover` to start fresh.

## Browser sessions for auto-apply

Some sites (Indeed, LinkedIn) require login. Save a session first:

```bash
hunt apply --login indeed.com
```

This opens a Chromium window. Log in manually, then close the window. The session is saved to `~/.local/share/job-hunter/sessions/` and reused for future applications.
