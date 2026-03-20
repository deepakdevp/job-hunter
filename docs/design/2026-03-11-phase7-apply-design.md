# Phase 7: Apply — Design Document

**Date:** 2026-03-11
**Status:** Approved

---

## Goal

Automate job applications using Playwright browser automation. Full auto-submit with dry-run safety. Platform-specific strategies for major ATS systems + Japan boards + generic fallback. LLM-powered unknown field resolution. Session persistence for login-required sites.

---

## Architecture

Strategy pattern — one base `FormFiller` with platform-specific subclasses.

```
src/job_hunter/apply/
├── __init__.py
├── applicant.py        # Orchestrator: open browser, detect platform, delegate
├── session.py          # Session persistence (storageState save/load)
├── strategies/
│   ├── base.py         # BaseFormFiller interface
│   ├── workday.py      # Workday multi-step wizard
│   ├── greenhouse.py   # Greenhouse handler
│   ├── lever.py        # Lever handler
│   ├── ashby.py        # Ashby handler
│   ├── japan.py        # Wantedly, Green, CareerCross handlers
│   └── generic.py      # Generic HTML form detection (fallback)
└── field_mapper.py     # LLM-powered unknown field resolution
```

**Flow:** `hunt apply` → load session → open `apply_url` → detect ATS platform from URL/DOM → delegate to strategy → fill fields → upload PDFs → submit → update DB status to "applied".

---

## Form Filling Strategy

### Interface

```python
class BaseFormFiller:
    async def detect(self, page) -> bool        # Can this strategy handle this page?
    async def fill(self, page, job, profile)     # Fill all form fields
    async def upload_files(self, page, job)      # Upload resume + cover letter
    async def submit(self, page)                 # Click submit
    async def handle_wizard(self, page)          # Navigate multi-step (if applicable)
```

### Platform Detection

Match by URL domain:

| Domain | Strategy |
|--------|----------|
| `myworkdayjobs.com` | Workday (5-step wizard) |
| `boards.greenhouse.io` | Greenhouse |
| `jobs.lever.co` | Lever |
| `jobs.ashbyhq.com` | Ashby |
| `wantedly.com` | Japan (Wantedly) |
| `green-japan.com` | Japan (Green) |
| `careercross.com` | Japan (CareerCross) |
| Everything else | Generic (CSS heuristics) |

### Field Mapping

Profile fields → form fields:
- Name, email, phone, LinkedIn, website → direct fill
- Work authorization, visa → select/radio from profile
- Resume, cover letter → file upload from `resume_path` / `cover_letter_path`
- Unknown fields → LLM generates answer from profile context

### Unknown Field Handling

1. Send field label + context to LLM
2. If LLM confidence is high → auto-fill
3. If LLM confidence is low → pause, show field in terminal, user types answer

### Multi-Step Wizards

- Workday and Greenhouse get hardcoded step sequences (next button selectors, page detection)
- Unknown multi-step forms pause after page 1

---

## Session Persistence

- Sessions stored in `sessions/` directory (in `.gitignore`)
- One `storageState.json` per domain — e.g., `sessions/workday.json`
- `hunt apply --login <domain>` opens browser for manual login, saves session
- Subsequent runs load saved session automatically
- Expired session (login wall detected) → prompt to re-login

---

## Safety & Error Handling

### Guardrails
- Full auto-submit by default
- `--dry-run` flag fills forms without submitting
- Rate limit: 2-second delay between applications in batch mode
- `--limit N` caps batch applications per run

### Application Log
Every submission logged to `output/apply_log.json`:
```json
{"timestamp": "2026-03-11T10:30:00", "url": "...", "company": "Acme", "platform": "workday", "status": "applied", "error": null}
```

### Error Recovery
- Form submit fails → mark job as `apply_failed`, log error
- CAPTCHA detected → pause, open browser to foreground, wait for user to solve, resume
- Unexpected popup/modal → attempt dismiss, if can't → pause for manual intervention
- Network error → retry once, then skip and log

---

## CLI Commands

```
hunt apply --job-url <url>          # Apply to single job
hunt apply --all [--limit N]        # Batch apply to all tailored/synced jobs
hunt apply --login <domain>         # Open browser to save session for a domain
hunt apply --dry-run                # Fill forms but don't submit
```

### Job Eligibility for `--all`
Jobs with status `tailored` or `synced` that have both `resume_path` and `cover_letter_path` set.

### Output per Application
```
[1/5] Software Engineer @ Acme Corp
      URL: https://workday.com/acme/apply
      Platform: Workday
      Resume: output/resumes/acme-corp.pdf
      Cover Letter: output/cover-letters/acme-corp.txt
      Status: ✓ Applied
```

---

## Implementation Tasks

1. **7.1** — Base form filler interface + platform detection
2. **7.2** — Session manager (save/load storageState per domain)
3. **7.3** — Generic form strategy (CSS heuristic field detection + fill)
4. **7.4** — LLM field mapper (unknown field resolution with confidence)
5. **7.5** — Workday strategy (multi-step wizard)
6. **7.6** — Greenhouse + Lever + Ashby strategies
7. **7.7** — Japan strategies (Wantedly, Green, CareerCross)
8. **7.8** — Applicant orchestrator (detect → delegate → submit → log)
9. **7.9** — `hunt apply` CLI command (single, batch, login, dry-run)
