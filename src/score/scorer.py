"""Score jobs against the user's profile using an LLM."""

from __future__ import annotations

from rich.console import Console
from rich.progress import track

from src.llm.base import LLMProvider

console = Console()


def score_job(llm: LLMProvider, job: dict, profile_text: str) -> tuple[int, str, list[str]]:
    """
    Score a single job.
    Returns (score, summary, keywords).
    """
    description = job.get("description", "")
    if not description:
        description = f"{job.get('title', '')} at {job.get('company', '')}"

    # Cap description to avoid token limits
    description_trimmed = description[:6000]

    score = llm.score_job(description_trimmed, profile_text)
    summary = llm.summarize_job(description_trimmed)
    keywords = llm.extract_keywords(description_trimmed)

    return score, summary, keywords


def score_jobs(
    llm: LLMProvider,
    jobs: list[dict],
    profile_text: str,
    threshold: int = 7,
) -> list[dict]:
    """
    Score all jobs. Modifies jobs in place.
    Returns only jobs that meet or exceed threshold.
    """
    console.print(f"\n[bold]Scoring {len(jobs)} jobs...[/bold]")
    qualified = []

    for job in track(jobs, description="Scoring jobs..."):
        if job.get("score") is not None:
            if job["score"] >= threshold:
                qualified.append(job)
            continue

        try:
            score, summary, keywords = score_job(llm, job, profile_text)
            job["score"] = score
            job["notes"] = summary
            job["tags"] = keywords

            if score >= threshold:
                qualified.append(job)
                console.print(
                    f"  [green]✓[/green] Score {score}/10 — {job.get('title')} @ {job.get('company')}"
                )
            else:
                console.print(
                    f"  [dim]✗ Score {score}/10 — {job.get('title')} @ {job.get('company')}[/dim]"
                )
        except Exception as exc:
            console.print(f"  [red]Error scoring {job.get('title')}: {exc}[/red]")
            job["score"] = 5  # default
            job["notes"] = "Scoring failed"

    console.print(f"\n[bold green]{len(qualified)}/{len(jobs)}[/bold green] jobs above threshold ({threshold}+)")
    return qualified
