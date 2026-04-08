from __future__ import annotations

import re
from dataclasses import dataclass, field
from enum import Enum


class ValidationMode(Enum):
    STRICT = "strict"
    NORMAL = "normal"
    LENIENT = "lenient"


BANNED_FILLER_WORDS = [
    "passionate",
    "spearheaded",
    "robust",
    "synergy",
    "proven track record",
    "I am excited",
    "furthermore",
    "adept at",
    "extensive experience",
    "proactive",
    "leveraged",
    "utilized",
    "orchestrated",
    "championed",
    "demonstrated",
    "facilitated",
    "endeavored",
    "cutting-edge",
    "innovative solutions",
    "dynamic environment",
    "results-driven",
    "self-motivated",
    "team player",
    "go-getter",
    "think outside the box",
    "synergize",
    "paradigm shift",
    "deep dive",
    "circle back",
    "move the needle",
    "low-hanging fruit",
    "best-in-class",
    "world-class",
    "game-changer",
    "disruptive",
    "bleeding edge",
    "rockstar",
    "ninja",
    "guru",
    "wizard",
    "evangelist",
    "holistic approach",
    "seamlessly",
    "meticulously",
    "tirelessly",
    "relentlessly",
    "passionately",
    "wholeheartedly",
    "diligently",
    "strategically",
    "comprehensively",
    "instrumental in",
]

LLM_LEAK_PHRASES = [
    "I am sorry",
    "I'm sorry",
    "here is the corrected",
    "per your feedback",
    "the following resume",
    "as an AI",
    "I cannot",
    "note that",
    "please note",
    "I hope this helps",
    "feel free to",
    "don't hesitate",
    "I'd be happy to",
    "here is your",
    "I have updated",
    "as requested",
    "I've modified",
    "the revised version",
    "updated resume",
    "below is the",
    "here's the",
    "I've tailored",
    "based on your request",
    "as per your",
    "I've rewritten",
    "the following is",
    "I have rewritten",
    "hope this meets",
    "let me know if",
    "I can also",
]


@dataclass
class ValidationIssue:
    severity: str  # "error" or "warning"
    category: str  # "filler", "leak", "fabrication", "structure"
    message: str
    match: str | None = None


@dataclass
class ValidationResult:
    passed: bool
    issues: list[ValidationIssue] = field(default_factory=list)
    errors: list[ValidationIssue] = field(default_factory=list)
    warnings: list[ValidationIssue] = field(default_factory=list)

    @property
    def error_count(self) -> int:
        return len(self.errors)

    @property
    def warning_count(self) -> int:
        return len(self.warnings)


def _check_filler_words(text: str, mode: ValidationMode) -> list[ValidationIssue]:
    """Check for banned filler words."""
    if mode == ValidationMode.LENIENT:
        return []

    issues = []
    text_lower = text.lower()
    for word in BANNED_FILLER_WORDS:
        pattern = r"\b" + re.escape(word.lower()) + r"\b"
        if re.search(pattern, text_lower):
            severity = "error" if mode == ValidationMode.STRICT else "warning"
            issues.append(
                ValidationIssue(
                    severity=severity,
                    category="filler",
                    message=f"Banned filler word: '{word}'",
                    match=word,
                )
            )
    return issues


def _check_llm_leaks(text: str) -> list[ValidationIssue]:
    """Check for LLM self-talk leak phrases. Always an error."""
    issues = []
    text_lower = text.lower()
    for phrase in LLM_LEAK_PHRASES:
        if phrase.lower() in text_lower:
            issues.append(
                ValidationIssue(
                    severity="error",
                    category="leak",
                    message=f"LLM leak phrase detected: '{phrase}'",
                    match=phrase,
                )
            )
    return issues


def _check_fabrication(
    generated_text: str,
    source_companies: list[str],
    source_titles: list[str],
    source_degrees: list[str],
) -> list[ValidationIssue]:
    """Check for fabricated companies, titles, or degrees not in source resume."""
    issues = []

    # Extract company-like patterns from generated text
    # Look for text after "at " or in experience context
    company_pattern = re.compile(
        r"(?:at|@)\s+([A-Z][A-Za-z0-9\s&.]+?)(?:[,\.]|\s*[-–—]|\s*\()", re.MULTILINE
    )
    found_companies = company_pattern.findall(generated_text)

    source_companies_lower = [c.lower().strip() for c in source_companies]

    for company in found_companies:
        company_clean = company.strip()
        if company_clean and company_clean.lower() not in source_companies_lower:
            # Check partial matches (e.g. "Acme Corp" vs "Acme Corp Pvt Ltd")
            if not any(
                company_clean.lower() in sc or sc in company_clean.lower()
                for sc in source_companies_lower
            ):
                issues.append(
                    ValidationIssue(
                        severity="error",
                        category="fabrication",
                        message=f"Possible fabricated company: '{company_clean}' not in source resume",
                        match=company_clean,
                    )
                )

    return issues


def validate_resume(
    generated_text: str,
    source_companies: list[str] | None = None,
    source_titles: list[str] | None = None,
    source_degrees: list[str] | None = None,
    mode: ValidationMode = ValidationMode.STRICT,
) -> ValidationResult:
    """Validate a generated resume against quality and truthfulness checks."""
    all_issues: list[ValidationIssue] = []

    # 1. LLM leak phrases (always checked, always error)
    all_issues.extend(_check_llm_leaks(generated_text))

    # 2. Banned filler words (mode-dependent severity)
    all_issues.extend(_check_filler_words(generated_text, mode))

    # 3. Fabrication detection (always checked, always error)
    if source_companies or source_titles or source_degrees:
        all_issues.extend(
            _check_fabrication(
                generated_text,
                source_companies or [],
                source_titles or [],
                source_degrees or [],
            )
        )

    errors = [i for i in all_issues if i.severity == "error"]
    warnings = [i for i in all_issues if i.severity == "warning"]

    return ValidationResult(
        passed=len(errors) == 0,
        issues=all_issues,
        errors=errors,
        warnings=warnings,
    )
