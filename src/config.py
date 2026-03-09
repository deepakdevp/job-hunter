"""Configuration loader — reads .env, profile.json, searches.yaml."""

from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

import yaml
from dotenv import load_dotenv

# Project root is one level above src/
ROOT = Path(__file__).parent.parent
CONFIG_DIR = ROOT / "config"
OUTPUT_DIR = ROOT / "output"


def _require_env(key: str) -> str:
    value = os.environ.get(key)
    if not value:
        raise EnvironmentError(
            f"Missing required environment variable: {key}\n"
            f"Add it to your .env file or export it before running hunt."
        )
    return value


@dataclass
class Profile:
    name: str
    email: str
    phone: str
    location: str
    linkedin: str
    github: str
    website: str
    summary: str
    skills: list[str]
    languages: list[str]
    experience: list[dict[str, Any]]
    education: list[dict[str, Any]]
    projects: list[dict[str, Any]]
    certifications: list[dict[str, Any]]

    @classmethod
    def load(cls, path: Path | None = None) -> "Profile":
        path = path or CONFIG_DIR / "profile.json"
        if not path.exists():
            raise FileNotFoundError(
                f"Profile not found at {path}. Run `hunt init` to create one."
            )
        data = json.loads(path.read_text())
        return cls(
            name=data.get("name", ""),
            email=data.get("email", ""),
            phone=data.get("phone", ""),
            location=data.get("location", ""),
            linkedin=data.get("linkedin", ""),
            github=data.get("github", ""),
            website=data.get("website", ""),
            summary=data.get("summary", ""),
            skills=data.get("skills", []),
            languages=data.get("languages", []),
            experience=data.get("experience", []),
            education=data.get("education", []),
            projects=data.get("projects", []),
            certifications=data.get("certifications", []),
        )

    def as_text(self) -> str:
        """Return a plain-text summary of the profile for LLM prompts."""
        lines = [
            f"Name: {self.name}",
            f"Location: {self.location}",
            f"Summary: {self.summary}",
            f"Skills: {', '.join(self.skills)}",
            f"Languages: {', '.join(self.languages)}",
        ]
        for exp in self.experience:
            lines.append(
                f"\nExperience: {exp.get('title')} at {exp.get('company')} "
                f"({exp.get('start')} – {exp.get('end', 'Present')})"
            )
            for bullet in exp.get("bullets", []):
                lines.append(f"  - {bullet}")
        for edu in self.education:
            lines.append(
                f"\nEducation: {edu.get('degree')} at {edu.get('school')} ({edu.get('year')})"
            )
        return "\n".join(lines)


@dataclass
class SearchConfig:
    platforms: list[str]
    queries: list[dict[str, Any]]
    score_threshold: int = 7
    results_per_query: int = 50
    hours_old: int = 24

    @classmethod
    def load(cls, path: Path | None = None) -> "SearchConfig":
        path = path or CONFIG_DIR / "searches.yaml"
        if not path.exists():
            raise FileNotFoundError(
                f"Searches config not found at {path}. Run `hunt init` to create one."
            )
        data = yaml.safe_load(path.read_text())
        return cls(
            platforms=data.get("platforms", ["linkedin", "indeed"]),
            queries=data.get("queries", []),
            score_threshold=data.get("score_threshold", 7),
            results_per_query=data.get("results_per_query", 50),
            hours_old=data.get("hours_old", 24),
        )


@dataclass
class AppConfig:
    # API keys
    notion_token: str
    notion_database_id: str
    gemini_api_key: str
    anthropic_api_key: str

    # Paths
    root: Path = field(default_factory=lambda: ROOT)
    config_dir: Path = field(default_factory=lambda: CONFIG_DIR)
    output_dir: Path = field(default_factory=lambda: OUTPUT_DIR)

    # LLM settings
    llm_provider: str = "gemini"
    llm_model: str = "gemini-2.0-flash"

    # Profile and searches (lazy-loaded)
    _profile: Profile | None = field(default=None, repr=False)
    _searches: SearchConfig | None = field(default=None, repr=False)

    @classmethod
    def load(cls) -> "AppConfig":
        load_dotenv(ROOT / ".env")
        return cls(
            notion_token=_require_env("NOTION_TOKEN"),
            notion_database_id=os.environ.get("NOTION_DATABASE_ID", ""),
            gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
            anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
            llm_provider=os.environ.get("LLM_PROVIDER", "gemini"),
            llm_model=os.environ.get("LLM_MODEL", "gemini-2.0-flash"),
        )

    @property
    def profile(self) -> Profile:
        if self._profile is None:
            self._profile = Profile.load()
        return self._profile

    @property
    def searches(self) -> SearchConfig:
        if self._searches is None:
            self._searches = SearchConfig.load()
        return self._searches
