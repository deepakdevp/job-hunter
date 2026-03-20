from __future__ import annotations

import json
from pathlib import Path

import click
import yaml

from job_hunter.config import get_config_dir, get_data_dir

# Map provider names to their API key env var names
_PROVIDER_KEY_VARS = {
    "gemini": "GEMINI_API_KEY",
    "openai": "OPENAI_API_KEY",
    "claude": "ANTHROPIC_API_KEY",
}

_PROVIDER_DEFAULT_MODELS = {
    "ollama": "llama3.1",
    "gemini": "gemini-2.5-flash",
    "openai": "gpt-4o",
    "claude": "claude-sonnet-4-20250514",
}


def run_init(answers: dict) -> Path:
    """Non-interactive setup: create profile.json, .env, searches.yaml from *answers*.

    Required keys in *answers*:
        config_dir, data_dir, llm_provider, api_key, name, email,
        target_roles (comma-separated), skills (comma-separated).

    Returns the config directory path.
    """
    config_dir = Path(answers["config_dir"])
    data_dir = Path(answers["data_dir"])

    config_dir.mkdir(parents=True, exist_ok=True)
    data_dir.mkdir(parents=True, exist_ok=True)

    # --- profile.json ---
    target_roles = [r.strip() for r in answers["target_roles"].split(",") if r.strip()]
    skills = [s.strip() for s in answers["skills"].split(",") if s.strip()]

    profile = {
        "name": answers["name"],
        "email": answers["email"],
        "phone": "",
        "location": "",
        "preferred_name": answers["name"].split()[0] if answers["name"] else "",
        "website": "",
        "linkedin_url": "",
        "github_url": "",
        "target_role": target_roles[0] if target_roles else "",
        "target_roles": target_roles,
        "work_authorization": "",
        "work_permit_type": "",
        "languages": {"english": "professional"},
        "skills": skills,
        "resume_facts": {
            "companies": [],
            "education": [],
            "metrics": [],
            "certifications": [],
        },
        "eeo_defaults": {
            "gender": "",
            "race": "",
            "veteran_status": "not_a_veteran",
            "disability_status": "no",
        },
    }

    (config_dir / "profile.json").write_text(json.dumps(profile, indent=4) + "\n", encoding="utf-8")

    # --- .env ---
    provider = answers["llm_provider"]
    api_key = answers.get("api_key", "")
    model = _PROVIDER_DEFAULT_MODELS.get(provider, "")

    env_lines = [
        "# LLM Configuration",
        f"LLM_PROVIDER={provider}",
        f"LLM_MODEL={model}",
    ]

    if provider == "ollama":
        env_lines.append("OLLAMA_HOST=http://localhost:11434")
    else:
        key_var = _PROVIDER_KEY_VARS.get(provider, "")
        if key_var:
            env_lines.append(f"{key_var}={api_key}")

    env_lines += [
        "",
        "# Notion Sync (optional)",
        "NOTION_TOKEN=",
        "NOTION_PAGE_ID=",
        "NOTION_DATABASE_ID=",
        "",
        "# Other",
        "CAPSOLVER_API_KEY=",
        "SCORE_THRESHOLD=3",
    ]

    (config_dir / ".env").write_text("\n".join(env_lines) + "\n", encoding="utf-8")

    # --- searches.yaml ---
    first_role = target_roles[0] if target_roles else "software engineer"
    searches = {
        "searches": [
            {
                "query": first_role.lower(),
                "location": "Remote",
                "boards": ["indeed", "linkedin"],
                "max_results": 100,
                "remote_only": True,
            },
            {
                "query": first_role.lower(),
                "location": "United States",
                "boards": ["indeed", "linkedin", "glassdoor"],
                "max_results": 100,
                "remote_only": False,
            },
        ]
    }

    (config_dir / "searches.yaml").write_text(
        yaml.dump(searches, default_flow_style=False, sort_keys=False),
        encoding="utf-8",
    )

    return config_dir


def interactive_init() -> None:
    """Collect answers via Click prompts, then call :func:`run_init`."""
    click.echo("Welcome to Job Hunter setup!\n")

    config_dir = click.prompt(
        "Config directory",
        default=str(get_config_dir()),
        type=str,
    )
    data_dir = click.prompt(
        "Data directory",
        default=str(get_data_dir()),
        type=str,
    )
    llm_provider = click.prompt(
        "LLM provider",
        default="ollama",
        type=click.Choice(["ollama", "gemini", "openai", "claude"], case_sensitive=False),
    )

    api_key = ""
    if llm_provider != "ollama":
        api_key = click.prompt(
            f"API key for {llm_provider}",
            default="",
            show_default=False,
        )

    name = click.prompt("Your full name")
    email = click.prompt("Your email")
    target_roles = click.prompt(
        "Target roles (comma-separated)",
        default="Software Engineer",
    )
    skills = click.prompt(
        "Key skills (comma-separated)",
        default="Python",
    )

    answers = {
        "config_dir": config_dir,
        "data_dir": data_dir,
        "llm_provider": llm_provider,
        "api_key": api_key,
        "name": name,
        "email": email,
        "target_roles": target_roles,
        "skills": skills,
    }

    result_dir = run_init(answers)
    click.echo(f"\nSetup complete! Config written to {result_dir}")
    click.echo("Next steps:")
    click.echo("  1. Edit profile.json to add your full work history")
    click.echo("  2. Edit searches.yaml to customise job search queries")
    click.echo("  3. Run 'hunt doctor' to verify your setup")
