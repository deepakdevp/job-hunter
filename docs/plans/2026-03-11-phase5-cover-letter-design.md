# Phase 5: Cover Letter — Design Document

**Date:** 2026-03-11
**Status:** Approved

---

## Goal

Generate human-sounding, personalized cover letters for each scored job. Professional but warm tone. No LLM traces. Output both LaTeX PDF (matching resume style) and plain text (for paste fields).

---

## Tone & Style

- Professional but warm — genuine interest, not corporate-speak
- Contractions allowed, short paragraphs, natural flow
- No filler words (same banned list as resume validator)
- No LLM leak phrases
- Reads like a real person wrote it, not a template

## Humanizer Rules

The LLM prompt enforces:
- Vary sentence length (mix short and long)
- Use specific details from the JD (team name, product, tech)
- Reference specific personal experience (not generic "extensive experience")
- Avoid starting consecutive sentences with "I"
- No bullet points — prose only
- Keep under 275 words (strict mode)
- One small imperfection is fine (a dash, parenthetical aside, em-dash)

---

## Output

- **LaTeX PDF** — Uses a simple letter template matching resume font/style
- **Plain text** — `.txt` file, no formatting, ready for copy-paste
- Stored in `output/<hash>_cover_letter.pdf` and `output/<hash>_cover_letter.txt`
- `cover_letter_path` stored in DB

---

## Validation

Same strict validator as resume (filler words, LLM leaks). Plus:
- Word count check (max 275 strict, 300 normal, unchecked lenient)
- Must mention the company name
- Must mention at least one specific skill from the JD

---

## Implementation Tasks

1. **5.1** — Cover letter generator (LLM prompt + humanizer rules)
2. **5.2** — Cover letter renderer (LaTeX PDF + plain text)
3. **5.3** — `hunt tailor` integration (cover letter generated alongside resume)
