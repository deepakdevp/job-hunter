"""Cover letter generation (thin wrapper around LLM)."""

from __future__ import annotations

from src.llm.base import LLMProvider


def generate_cover_letter(llm: LLMProvider, profile_text: str, job: dict) -> str:
    """Generate a cover letter for the given job."""
    return llm.write_cover_letter(
        profile_text=profile_text,
        job_description=job.get("description", "")[:5000],
        job_title=job.get("title", ""),
        company=job.get("company", ""),
    )
