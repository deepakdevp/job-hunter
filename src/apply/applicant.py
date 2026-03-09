"""Playwright-based application form filler."""

from __future__ import annotations

import json
from pathlib import Path

from rich.console import Console

console = Console()

SESSION_DIR = Path.home() / ".job-hunter" / "sessions"


def get_session_path(domain: str) -> Path:
    SESSION_DIR.mkdir(parents=True, exist_ok=True)
    return SESSION_DIR / f"{domain.replace('.', '_')}.json"


async def apply_to_job(
    job: dict,
    profile: dict,
    resume_pdf: Path,
    cover_letter_pdf: Path | None = None,
) -> bool:
    """
    Open a browser and attempt to fill out the job application.
    Pauses for CAPTCHA and final user confirmation.
    Returns True if application was submitted.
    """
    from playwright.async_api import async_playwright
    from urllib.parse import urlparse

    apply_url = job.get("apply_url") or job.get("job_url", "")
    if not apply_url:
        console.print("[red]No apply URL found for this job.[/red]")
        return False

    domain = urlparse(apply_url).netloc
    session_path = get_session_path(domain)

    async with async_playwright() as p:
        # Load existing session if available
        context_kwargs = {}
        if session_path.exists():
            context_kwargs["storage_state"] = str(session_path)

        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context(**context_kwargs)
        page = await context.new_page()

        console.print(f"\n[bold]Opening: {apply_url}[/bold]")
        await page.goto(apply_url, wait_until="domcontentloaded", timeout=30000)

        # --- Basic field filling heuristics ---
        # Name field
        await _try_fill(page, ['input[name*="name"]', 'input[placeholder*="name" i]'], profile.get("name", ""))

        # Email
        await _try_fill(page, ['input[type="email"]', 'input[name*="email"]'], profile.get("email", ""))

        # Phone
        await _try_fill(page, ['input[type="tel"]', 'input[name*="phone"]'], profile.get("phone", ""))

        # LinkedIn
        await _try_fill(page, ['input[name*="linkedin"]', 'input[placeholder*="linkedin" i]'], profile.get("linkedin", ""))

        # Resume upload
        resume_inputs = await page.query_selector_all('input[type="file"]')
        if resume_inputs and resume_pdf.exists():
            try:
                await resume_inputs[0].set_input_files(str(resume_pdf))
                console.print(f"  [green]✓[/green] Uploaded resume: {resume_pdf.name}")
            except Exception as exc:
                console.print(f"  [yellow]Resume upload failed: {exc}[/yellow]")

        # Cover letter upload (second file input if available)
        if len(resume_inputs) > 1 and cover_letter_pdf and cover_letter_pdf.exists():
            try:
                await resume_inputs[1].set_input_files(str(cover_letter_pdf))
                console.print(f"  [green]✓[/green] Uploaded cover letter: {cover_letter_pdf.name}")
            except Exception as exc:
                console.print(f"  [yellow]Cover letter upload failed: {exc}[/yellow]")

        # Save session
        await context.storage_state(path=str(session_path))

        console.print(
            "\n[bold yellow]PAUSED — Please review the form, solve any CAPTCHA, "
            "and press ENTER here when ready to confirm submission...[/bold yellow]"
        )
        input()

        console.print("[bold yellow]Did you submit the application? (y/n)[/bold yellow] ", end="")
        submitted = input().strip().lower() == "y"

        await context.close()
        await browser.close()

    return submitted


async def _try_fill(page, selectors: list[str], value: str) -> None:
    """Try each selector until one works."""
    if not value:
        return
    for selector in selectors:
        try:
            el = await page.query_selector(selector)
            if el:
                await el.fill(value)
                return
        except Exception:
            continue


def apply_sync(job: dict, profile: dict, resume_pdf: Path, cover_letter_pdf: Path | None = None) -> bool:
    """Synchronous wrapper for apply_to_job."""
    import asyncio
    return asyncio.run(apply_to_job(job, profile, resume_pdf, cover_letter_pdf))
