# Phase 2: Enrich — Design Document

**Date:** 2026-03-10
**Status:** Approved

---

## Goal

Take raw job URLs from Phase 1 and extract full structured data: description, apply URL, salary, visa sponsorship, remote policy, tech stack, seniority, contract type, team size, and benefits. Use a 3-tier cascade to minimize LLM cost, with raw text fallback flagged for low quality.

---

## 3-Tier Extraction Cascade

### Tier 1: JSON-LD (zero cost)
- Parse `<script type="application/ld+json">` tags
- Find `@type: "JobPosting"` (including nested `@graph`)
- Extract `description`, `directApply`/`applicationContact` URL
- ~60% of major job boards have this

### Tier 2: CSS Selectors (zero cost)
- 20 curated description selectors (`#job-description`, `.ashby-job-posting-description`, etc.)
- 13 apply URL selectors (`a[href*='apply']`, `a[href*='greenhouse.io']`, etc.)
- Fallback: scan all `<a>` tags for text containing "apply"
- ~25% additional coverage

### Tier 3: LLM Extraction (1 Gemini call)
- Strip nav/header/footer/script/style noise
- Truncate to 30k chars
- Send to Gemini requesting structured JSON with all fields
- No budget caps — Gemini Pro subscription

### Tier 4: Raw Text Fallback
- If all tiers fail, strip HTML tags and store raw page text as description
- Set `enrichment_raw = True` flag so user knows it's low quality
- Still gives the scorer something to work with

---

## Smart Rate Limiting

- **Per-domain throttle:** max 5 requests/min to the same domain
- **Cross-domain parallel:** blast through different domains concurrently
- **429 backoff:** exponential retry (2s → 4s → 8s → 16s) on rate limit responses
- **Timeout:** 30s per request, skip after 2 retries on timeout

---

## JS Rendering Strategy

- **Default:** httpx static fetch (fast, ~0.5s)
- **Playwright fallback:** only for known JS-heavy domains
- **JS domain allowlist** (configurable in code):
  - `lever.co`
  - `greenhouse.io`
  - `ashby.io`
  - `jobs.smartrecruiters.com`
  - `boards.eu.greenhouse.io`
  - `myworkdayjobs.com` (some pages)
- If httpx returns description < 100 chars for an allowlisted domain, re-fetch with Playwright

---

## New Database Columns

| Column | Type | Purpose |
|--------|------|---------|
| `visa_sponsorship` | BOOLEAN | Whether visa sponsorship is mentioned |
| `remote_policy` | TEXT | remote / hybrid / onsite / unknown |
| `tech_stack` | TEXT | Comma-separated technologies |
| `seniority` | TEXT | junior / mid / senior / lead / staff / unknown |
| `contract_type` | TEXT | full-time / contract / part-time / internship / unknown |
| `team_size` | TEXT | Raw text if mentioned |
| `benefits` | TEXT | Key benefits mentioned |
| `enrichment_raw` | BOOLEAN | True if fallback raw text was used instead of structured extraction |

---

## Concurrency Model

- asyncio semaphore per domain (max 5 concurrent per domain)
- Global concurrency limit of 20 simultaneous requests
- Progress bar via `rich.progress`
- Upsert to DB after each job completes (crash-safe)
- Domain extracted from job URL for throttle grouping

---

## CLI Command

```bash
hunt enrich                    # Enrich all jobs where description IS NULL
hunt enrich --limit 100        # Process max 100 jobs
hunt enrich --tier1-only       # Skip LLM tier (dry run, zero cost)
```

---

## Structured Extraction Prompt (Tier 3)

When LLM is needed, extract all fields in one call:

```
Extract job details from this page. Return JSON only:
{
  "full_description": "...",
  "application_url": "..." or null,
  "visa_sponsorship": true/false/null,
  "remote_policy": "remote"/"hybrid"/"onsite"/null,
  "tech_stack": ["Python", "React", ...] or [],
  "seniority": "junior"/"mid"/"senior"/"lead"/"staff"/null,
  "contract_type": "full-time"/"contract"/"part-time"/"internship"/null,
  "team_size": "..." or null,
  "benefits": "..." or null
}
```

---

## Implementation Tasks

1. **2.1** — Expand Job dataclass + DB schema with new columns
2. **2.2** — Smart rate limiter (per-domain throttle + semaphore)
3. **2.3** — Tier 1 & 2 extractors (JSON-LD + CSS) + structured field parsing
4. **2.4** — Tier 3 LLM extractor + raw text fallback
5. **2.5** — JS domain allowlist + Playwright integration
6. **2.6** — `enrich_job()` orchestrator + concurrent runner
7. **2.7** — `hunt enrich` CLI command + progress bar
