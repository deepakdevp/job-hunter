# Phase 4: Tailor Resume — Design Document

**Date:** 2026-03-10
**Status:** Approved

---

## Goal

Generate a tailored resume PDF for each scored job. LLM rephrases and reorders the user's real resume content to emphasize relevant skills for the specific JD. Strict validation ensures no fabrication or filler. LaTeX → PDF rendering using the user's existing template.

---

## Source of Truth

1. **LaTeX resume** (primary) — parsed into structured sections, stored as `resume_source.tex`
2. **profile.json** (supplementary) — skills, target roles, metrics for validation cross-reference

The LLM sees both but draws primarily from the LaTeX content.

---

## Tailoring Strategy (Moderate)

- Reorder sections and bullet points to prioritize JD-relevant ones
- Rephrase bullet points to match JD language/keywords (~60-70% original wording)
- May merge or split bullets for better emphasis
- Inject missing keywords from JD into existing bullets where truthful
- Never fabricate companies, titles, degrees, certifications, or metrics
- Keep all dates, company names, and education exactly as-is

---

## Validation (Strict Mode Default)

### Always Error (all modes)
- Fabricated companies, titles, degrees, certifications
- LLM self-talk leak phrases (30+)
- Companies/roles not in source resume

### Strict Mode (default)
- Banned filler words (50+) → error, retry with feedback
- LLM judge pass required (1 extra call)
- Section structure must match template

### Banned Filler Words (subset)
"passionate", "spearheaded", "robust", "synergy", "proven track record",
"I am excited", "furthermore", "adept at", "extensive experience",
"proactive", "leveraged", "utilized", "orchestrated", "championed",
"demonstrated", "facilitated", "endeavored", "cutting-edge"

### LLM Leak Phrases
"I am sorry", "here is the corrected", "per your feedback",
"the following resume", "as an AI", "I cannot", "note that"

### Fabrication Detection
- Extract all company names, titles, degrees from generated resume
- Diff against source LaTeX — flag anything not present in original

---

## LaTeX Rendering

- Parse user's LaTeX template to identify section markers and structure
- LLM generates content blocks that slot into the template
- Render with `pdflatex` (or `tectonic` as fallback)
- Output to `output/<job_url_hash>_resume.pdf`

---

## Implementation Tasks

1. **4.1** — Resume parser (extract structured sections from LaTeX)
2. **4.2** — LLM tailoring prompt + response handling
3. **4.3** — Validator (filler words, leak phrases, fabrication detection)
4. **4.4** — LaTeX renderer (template fill + pdflatex)
5. **4.5** — `hunt tailor` CLI command
