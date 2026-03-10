# Phase 3: Score — Design Document

**Date:** 2026-03-10
**Status:** Approved

---

## Goal

Score enriched jobs 1-10 against the user's profile using a two-pass system: fast pre-filter to reject obvious mismatches (zero LLM cost), then multi-criteria LLM scoring on survivors.

---

## Two-Pass Architecture

### Pass 1: Pre-Filter (No LLM)

Auto-reject jobs that clearly don't match. These get `score=0, status="filtered"`.

**Title matching:**
- Fuzzy match against 17 target roles from profile.json
- Jobs whose title doesn't match any target role are rejected

**Salary floor:**
- If salary is parseable and below 5M JPY, reject
- Unparseable salaries pass through (don't reject on missing data)

**Blocked title keywords:**
- intern, director, VP, chief, head of
- PhD required, PhD preferred
- native Japanese required

**Blocked description keywords:**
- 10+ years, 15+ years
- security clearance required
- US citizens only, EU citizens only

### Pass 2: Multi-Criteria LLM Scoring

Jobs that survive pre-filter are scored by Gemini on 5 dimensions:

| Dimension | Weight | What it measures |
|-----------|--------|-----------------|
| Skills match | 30% | Overlap between user's 28 skills and job requirements |
| Role fit | 20% | Title/responsibilities alignment with 17 target roles |
| Location/remote | 15% | Japan > Europe > Remote > Other |
| Visa/sponsorship | 25% | Visa available, not needed, or explicitly denied |
| Salary fit | 10% | Meets 5M JPY floor, how far above |

**Score reason:** Analytical style — 2 sentences explaining the match with context.

**LLM prompt returns:** JSON with per-dimension scores (1-10), weighted final score, and 2-sentence reason.

---

## Implementation Tasks

1. **3.1** — Pre-filter engine (title matching, salary floor, blocklists)
2. **3.2** — LLM scoring prompt + response parser
3. **3.3** — `hunt score` CLI command + progress bar
