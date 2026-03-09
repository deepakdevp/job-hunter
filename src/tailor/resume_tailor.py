"""Tailor resume and cover letter for a specific job."""

from __future__ import annotations

import json
import re
from pathlib import Path

from rich.console import Console

from src.llm.base import LLMProvider
from .validator import validate_tailored

console = Console()


def load_resume_facts(profile_path: Path) -> dict:
    """Load the full profile JSON as resume facts."""
    return json.loads(profile_path.read_text())


def tailor_resume(
    llm: LLMProvider,
    profile: dict,
    job: dict,
    max_retries: int = 2,
) -> dict | None:
    """
    Use LLM to tailor the resume for a specific job.
    Returns the tailored resume as a dict, or None on failure.
    """
    title = job.get("title", "")
    company = job.get("company", "")
    description = job.get("description", "")[:6000]

    if not description:
        description = f"{title} at {company}"

    import json as _json
    profile_str = _json.dumps(profile, indent=2)

    for attempt in range(max_retries + 1):
        try:
            raw = llm.tailor_resume(
                resume_facts=profile_str,
                job_description=description,
                job_title=title,
                company=company,
            )

            result = validate_tailored(profile, raw)
            if result.passed:
                # Parse and return
                text = raw.strip()
                if text.startswith("```"):
                    parts = text.split("```")
                    text = parts[1] if len(parts) > 1 else text
                    if text.startswith("json"):
                        text = text[4:]
                return json.loads(text)
            else:
                console.print(f"  [yellow]Validation failed (attempt {attempt+1}): {result.errors}[/yellow]")
                if attempt == max_retries:
                    console.print("  [red]Using original profile as fallback[/red]")
                    return profile
        except Exception as exc:
            console.print(f"  [red]Tailor error (attempt {attempt+1}): {exc}[/red]")
            if attempt == max_retries:
                return profile

    return profile


def write_cover_letter(
    llm: LLMProvider,
    profile_text: str,
    job: dict,
) -> str:
    """Generate a cover letter for the job."""
    return llm.write_cover_letter(
        profile_text=profile_text,
        job_description=job.get("description", "")[:5000],
        job_title=job.get("title", ""),
        company=job.get("company", ""),
    )
