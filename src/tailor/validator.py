"""Validate that LLM-tailored resumes don't fabricate facts."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass


@dataclass
class ValidationResult:
    passed: bool
    errors: list[str]

    def __bool__(self) -> bool:
        return self.passed


def _extract_companies(resume: dict) -> set[str]:
    companies = set()
    for exp in resume.get("experience", []):
        if c := exp.get("company"):
            companies.add(c.strip().lower())
    for edu in resume.get("education", []):
        if s := edu.get("school"):
            companies.add(s.strip().lower())
    return companies


def _extract_dates(resume: dict) -> list[str]:
    dates = []
    for exp in resume.get("experience", []):
        dates.append(exp.get("start", ""))
        dates.append(exp.get("end", ""))
    for edu in resume.get("education", []):
        dates.append(exp.get("year", ""))
    return [d for d in dates if d]


def validate_tailored(original: dict, tailored_text: str) -> ValidationResult:
    """
    Compare tailored resume (JSON string from LLM) against original facts.
    Returns ValidationResult with any fabrication errors found.
    """
    errors = []

    # Parse tailored JSON
    try:
        # Strip markdown code fences
        text = tailored_text.strip()
        if text.startswith("```"):
            parts = text.split("```")
            text = parts[1] if len(parts) > 1 else text
            if text.startswith("json"):
                text = text[4:]
        tailored = json.loads(text)
    except json.JSONDecodeError as exc:
        return ValidationResult(passed=False, errors=[f"LLM returned invalid JSON: {exc}"])

    # Check: no new companies
    orig_companies = _extract_companies(original)
    tail_companies = _extract_companies(tailored)
    new_companies = tail_companies - orig_companies
    if new_companies:
        errors.append(f"Fabricated companies/schools: {new_companies}")

    # Check: experience count matches
    orig_exp = original.get("experience", [])
    tail_exp = tailored.get("experience", [])
    if len(tail_exp) != len(orig_exp):
        errors.append(
            f"Experience count changed: {len(orig_exp)} → {len(tail_exp)}"
        )

    # Check: education count matches
    orig_edu = original.get("education", [])
    tail_edu = tailored.get("education", [])
    if len(tail_edu) != len(orig_edu):
        errors.append(
            f"Education count changed: {len(orig_edu)} → {len(tail_edu)}"
        )

    # Check: dates haven't changed
    for i, (orig, tail) in enumerate(zip(orig_exp, tail_exp)):
        if orig.get("start") and orig["start"] != tail.get("start"):
            errors.append(
                f"Start date changed for exp[{i}]: {orig['start']} → {tail.get('start')}"
            )
        if orig.get("end") and orig["end"] != tail.get("end"):
            errors.append(
                f"End date changed for exp[{i}]: {orig['end']} → {tail.get('end')}"
            )

    return ValidationResult(passed=len(errors) == 0, errors=errors)
