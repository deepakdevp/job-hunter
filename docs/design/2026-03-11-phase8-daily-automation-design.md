# Phase 8: Daily Automation — Design Document

**Date:** 2026-03-11
**Status:** Approved

---

## Goal

Single `hunt run` command that chains the full pipeline: discover → enrich → score → tailor → sync push. Optional `--apply` flag adds auto-apply at the end. Best-effort error handling — each stage runs regardless of prior stage failures. Terminal summary table at the end.

---

## CLI Commands

```
hunt run                    # Full pipeline (discover → sync push)
hunt run --apply            # Full pipeline + auto-apply
hunt run --skip-discover    # Skip discover, start from enrich
hunt run --dry-run          # Passes --dry-run to apply stage (if --apply)
```

---

## Pipeline Flow

| Step | Stage | Input Status | Action |
|------|-------|-------------|--------|
| 1 | Discover | — | Scrape new jobs into DB |
| 2 | Enrich | new | Fetch full JDs |
| 3 | Score | enriched | Pre-filter + LLM score |
| 4 | Tailor | scored (>= threshold) | Resume + cover letter |
| 5 | Sync Push | scored/tailored/synced | Push to Notion + Drive |
| 6 | Apply | tailored/synced | Auto-submit (only with --apply) |

Each stage is wrapped in try/except. On failure: log error, print warning, continue to next stage.

---

## Error Handling

Best-effort continuation. Each stage operates on whatever jobs exist in the DB at that point, regardless of whether prior stages succeeded or failed in this run. The pipeline is idempotent — running it again picks up where it left off.

---

## Summary Table

Printed at the end of `hunt run`:

```
┌──────────────────────────────────────┐
│           Run Summary                │
├──────────┬───────────────────────────┤
│ Stage    │ Result                    │
├──────────┼───────────────────────────┤
│ Discover │ 47 new jobs              │
│ Enrich   │ 42/47 enriched           │
│ Score    │ 18 scored, 24 filtered   │
│ Tailor   │ 15/18 tailored           │
│ Sync     │ 15 created, 3 updated    │
│ Apply    │ skipped (use --apply)    │
└──────────┴───────────────────────────┘
```

---

## Cron Usage

No built-in scheduler. Use system cron:

```
0 8 * * * cd /path/to/project && hunt run >> output/cron.log 2>&1
```

---

## Implementation Tasks

1. **8.1** — Pipeline runner function (chain stages, best-effort error handling)
2. **8.2** — Summary table (collect results from each stage, print Rich table)
3. **8.3** — `hunt run` CLI command (--apply, --skip-discover, --dry-run)
