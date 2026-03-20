# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/), and this project adheres to [Semantic Versioning](https://semver.org/).

## [0.1.0] - 2026-03-20

### Added

- **Discover**: scrape jobs from Indeed, LinkedIn, Glassdoor, ZipRecruiter, Google Jobs (via JobSpy), TokyoDev, JapanDev, GaijinPot, and Workday employer portals
- **Enrich**: 3-tier cascade (direct fetch, proxy, LLM) to extract full job descriptions
- **Score**: rule-based pre-filter + multi-criteria LLM scoring against user profile
- **Tailor**: per-job LaTeX resume generation with strict/normal/lenient validation
- **Cover Letter**: LLM-generated targeted cover letters with PDF rendering
- **Sync**: two-way Notion integration with optional Google Drive PDF upload (beta)
- **Apply**: browser automation for Workday, Greenhouse, Lever, Ashby, Indeed, and Japan boards
- **AutoResearch**: Karpathy-style deep research on companies and roles
- **CLI**: `hunt` command with subcommands for each stage plus `run`, `status`, and `doctor`
- Support for Gemini and Claude LLM providers
- SQLite-based local job database with deduplication
- Full pipeline orchestration via `hunt run`
