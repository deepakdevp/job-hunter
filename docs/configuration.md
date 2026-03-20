# Configuration

All config lives in `~/.config/job-hunter/` (XDG-compliant). Data goes to `~/.local/share/job-hunter/`.

Override with CLI flags: `hunt --config-dir /path --data-dir /path`.

## Directory Layout

```
~/.config/job-hunter/          # XDG_CONFIG_HOME/job-hunter
  profile.json                 # your background and preferences
  .env                         # API keys and settings
  searches.yaml                # job search queries
  employers.yaml               # Workday employer portals
  sites.yaml                   # site registry (blocked sites, SSO domains)
  resume.tex                   # LaTeX resume template
  resume_template.html         # HTML resume template (fallback)
  deep_research_program.md     # autoresearch steering file

~/.local/share/job-hunter/     # XDG_DATA_HOME/job-hunter
  jobs.db                      # SQLite database
  output/                      # generated resumes, cover letters, logs
  sessions/                    # Playwright browser sessions
```

## profile.json

Your professional background. Used for scoring, tailoring, and auto-apply.

```json
{
    "name": "Your Name",
    "email": "your.email@example.com",
    "phone": "+1234567890",
    "location": "City, Country",
    "preferred_name": "YourName",
    "website": "https://yoursite.dev/",
    "linkedin_url": "https://www.linkedin.com/in/your-profile/",
    "github_url": "https://github.com/your-username",
    "target_role": "Software Engineer",
    "target_roles": ["Software Engineer", "Full Stack Developer"],
    "work_authorization": "visa_required",
    "work_permit_type": "needs_sponsorship",
    "languages": {
        "english": "professional"
    },
    "skills": ["Python", "TypeScript", "React"],
    "resume_facts": {
        "companies": [
            {
                "name": "Example Corp",
                "title": "Software Engineer",
                "dates": "Jan 2022 - Present",
                "location": "City, Country",
                "bullets": ["Built feature X that improved metric Y by Z%"],
                "tech_stack": ["Python", "React"]
            }
        ],
        "education": [
            {
                "school": "University Name",
                "degree": "Bachelor of Science, Computer Science",
                "year": 2020,
                "location": "City, Country"
            }
        ],
        "metrics": ["Improved performance by X%"],
        "certifications": []
    },
    "eeo_defaults": {
        "gender": "",
        "race": "",
        "veteran_status": "not_a_veteran",
        "disability_status": "no"
    }
}
```

Key fields:
- **target_roles** -- list of roles you want. Used by the scorer.
- **work_authorization** -- `authorized`, `visa_required`, or `visa_holder`
- **resume_facts** -- structured work history. The tailor uses this to pick relevant bullets.
- **eeo_defaults** -- auto-filled in EEO forms during apply stage.

## .env

Environment variables loaded at startup.

```bash
# LLM provider (gemini | openai | claude | ollama)
LLM_PROVIDER=gemini
LLM_MODEL=gemini-2.5-flash

# API keys (only the one matching LLM_PROVIDER is needed)
GEMINI_API_KEY=
OPENAI_API_KEY=
ANTHROPIC_API_KEY=

# Notion sync
NOTION_TOKEN=
NOTION_PAGE_ID=
NOTION_DATABASE_ID=

# Scoring
SCORE_THRESHOLD=3

# Validation mode for tailoring (strict | normal | lenient)
VALIDATION_MODE=normal

# Optional
CAPSOLVER_API_KEY=            # CAPTCHA solving for auto-apply
```

## searches.yaml

Defines what jobs to search for and where.

```yaml
searches:
  - query: "software engineer"
    location: "Tokyo, Japan"
    boards: ["indeed", "linkedin", "glassdoor"]
    max_results: 100
    remote_only: false

  - query: "AI engineer remote"
    location: "Remote"
    boards: ["indeed", "linkedin"]
    max_results: 50
    remote_only: true
    distance_km: 50         # optional radius filter

custom_boards:
  japan:
    - name: "TokyoDev"
      url: "https://www.tokyodev.com/jobs"
      type: "searchable"
  europe:
    - name: "Welcome to the Jungle"
      url: "https://www.welcometothejungle.com"
      type: "searchable"
  global:
    - name: "Remotive"
      url: "https://remotive.com"
      type: "searchable"
```

Fields per search:
- **query** (required) -- search string
- **location** -- location filter
- **boards** -- list of `indeed`, `linkedin`, `glassdoor`, `google`, `zip_recruiter`
- **max_results** -- cap per search (default 100)
- **remote_only** -- only return remote jobs
- **distance_km** -- radius from location

## employers.yaml

Workday employer portals to scrape directly.

```yaml
employers:
  nvidia:
    name: "NVIDIA"
    tenant: "nvidia"
    site_id: "NVIDIAExternalCareerSite"
    base_url: "https://nvidia.wd5.myworkdayjobs.com"
    region: "global"

  rakuten:
    name: "Rakuten"
    tenant: "rakuten"
    site_id: "RakutenInc"
    base_url: "https://rakuten.wd1.myworkdayjobs.com"
    region: "japan"
```

The URL pattern is `https://[tenant].wd[N].myworkdayjobs.com/[site_id]`. Find it by visiting a company's careers page and looking for Workday redirect URLs.

## sites.yaml

Controls enrichment behavior: which sites to block, SSO domains to skip, and base URLs for custom boards.

```yaml
manual_ats:
  - "ibegin.tcsapps.com"

blocked:
  sites: ["glassdoor", "google", "accenture"]
  url_patterns: ["%glassdoor%", "%google.com/about/careers%"]

blocked_sso:
  - "accounts.google.com"
  - "login.microsoftonline.com"
  - "okta.com"

base_urls:
  "TokyoDev": "https://www.tokyodev.com"
  "Japan Dev": "https://japan-dev.com"
```

## XDG Path Conventions

Job Hunter follows the [XDG Base Directory Specification](https://specifications.freedesktop.org/basedir-spec/latest/):

| Purpose | Default path | Override env var |
|---------|-------------|-----------------|
| Config  | `~/.config/job-hunter` | `XDG_CONFIG_HOME` |
| Data    | `~/.local/share/job-hunter` | `XDG_DATA_HOME` |

You can also override per-invocation:

```bash
hunt --config-dir ./my-config --data-dir ./my-data discover
```
