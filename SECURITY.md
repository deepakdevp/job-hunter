# Security Policy

## Reporting a Vulnerability

If you discover a security vulnerability in job-hunter, please report it responsibly.

**Email:** deepakdevp@gmail.com

Please include:
- A description of the vulnerability
- Steps to reproduce
- Potential impact

I will acknowledge your report within 48 hours and aim to provide a fix or mitigation within 7 days for critical issues.

**Please do not open a public GitHub issue for security vulnerabilities.**

## API Key Handling

job-hunter works with several API keys and tokens. Follow these practices to keep them safe:

- Store all secrets in a `.env` file in your project directory. The `.gitignore` should exclude `.env` files.
- Never commit API keys, tokens, or credentials to version control.
- job-hunter loads secrets via `python-dotenv` at runtime and does not persist them to the database or log files.
- When using the Notion sync or Google Drive integration, ensure your tokens have the minimum required permissions.

### Keys used by job-hunter

| Variable | Purpose |
|----------|---------|
| `GEMINI_API_KEY` | Google Gemini LLM provider |
| `ANTHROPIC_API_KEY` | Anthropic Claude LLM provider |
| `OPENAI_API_KEY` | OpenAI LLM provider |
| `NOTION_TOKEN` | Notion API integration token |
| `NOTION_DATABASE_ID` | Notion database for job tracking |

## Dependencies

- Keep dependencies up to date. Run `pip audit` periodically to check for known vulnerabilities.
- Playwright browser automation runs with user-level permissions. Do not run job-hunter as root.
