# Phase 6: Notion Sync — Design Document

**Date:** 2026-03-11
**Status:** Approved

---

## Goal

Sync jobs to Notion as the primary dashboard. Auto-create database with 18 columns. Two-way sync (manual trigger): push new jobs + pull status changes back. Upload resume/cover letter PDFs to Google Drive, store shareable links in Notion.

---

## Notion Database

### Auto-Creation
- `hunt notion init` creates database under a specified parent page
- If "Job Hunter" database already exists, connect to it
- Store database ID in `.env` as `NOTION_DATABASE_ID`

### Schema (18 columns)
| Column | Notion Type | Source |
|--------|------------|--------|
| Job Title | title | job.title |
| Company | rich_text | job.company |
| Location | rich_text | job.location |
| Score | number | job.score |
| Score Reason | rich_text | job.score_reason |
| Status | select | job.status |
| Job URL | url | job.url |
| Apply URL | url | job.apply_url |
| Source | select | job.source |
| Salary Min | number | job.salary_min |
| Salary Max | number | job.salary_max |
| Salary Raw | rich_text | job.salary_raw |
| Posted Date | date | job.posted_date |
| Found Date | date | job.found_date |
| Resume PDF | url | Google Drive link |
| Cover Letter | url | Google Drive link |
| Tags | multi_select | job.tech_stack (split) |
| Notes | rich_text | job.score_reason (detailed) |

---

## Google Drive Upload

- Use `google-api-python-client` to upload PDFs to a "Job Hunter" folder
- Create folder if it doesn't exist
- Set file permissions to "anyone with link can view"
- Store shareable link in Notion URL field
- Requires Google OAuth credentials (service account or OAuth2)

---

## Two-Way Sync (Manual)

### Push (`hunt sync push`)
- Push all new/updated jobs to Notion
- Create new pages for jobs not yet in Notion
- Update existing pages for jobs with changed data
- Upload PDFs to Drive, store links

### Pull (`hunt sync pull`)
- Read all pages from Notion database
- Pull back Status field changes to local DB
- Match by URL (primary key)

---

## Implementation Tasks

1. **6.1** — Notion client (create DB, create/update pages)
2. **6.2** — Google Drive uploader (upload PDFs, get shareable links)
3. **6.3** — Push sync (local → Notion + Drive)
4. **6.4** — Pull sync (Notion → local status)
5. **6.5** — `hunt sync` CLI commands
