from __future__ import annotations

import json
import os
from dataclasses import dataclass, field
from pathlib import Path

import yaml
from dotenv import load_dotenv


def get_config_dir(override: Path | None = None) -> Path:
    """Resolve config directory: explicit override > XDG > ~/.config/job-hunter."""
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_CONFIG_HOME", "")
    base = Path(xdg) if xdg else Path.home() / ".config"
    return base / "job-hunter"


def get_data_dir(override: Path | None = None) -> Path:
    """Resolve data directory: explicit override > XDG > ~/.local/share/job-hunter."""
    if override:
        return Path(override)
    xdg = os.environ.get("XDG_DATA_HOME", "")
    base = Path(xdg) if xdg else Path.home() / ".local" / "share"
    return base / "job-hunter"


@dataclass
class Config:
    profile: dict
    searches: list[dict]
    gemini_api_key: str
    notion_token: str
    notion_page_id: str
    notion_database_id: str = ""
    anthropic_api_key: str = ""
    capsolver_api_key: str = ""
    llm_provider: str = "gemini"
    llm_model: str = "gemini-2.5-flash"
    score_threshold: int = 3
    validation_mode: str = "normal"
    employers: list[dict] = field(default_factory=list)
    sites_config: dict = field(default_factory=dict)
    config_dir: Path = field(default_factory=get_config_dir)
    data_dir: Path = field(default_factory=get_data_dir)


def load_config(config_dir: Path | None = None, data_dir: Path | None = None) -> Config:
    config_dir = get_config_dir(config_dir)
    data_dir = get_data_dir(data_dir)

    env_path = config_dir / ".env"
    if env_path.exists():
        load_dotenv(env_path, override=True)

    profile_path = config_dir / "profile.json"
    if not profile_path.exists():
        raise FileNotFoundError(f"profile.json not found in {config_dir}")
    profile = json.loads(profile_path.read_text())

    searches_path = config_dir / "searches.yaml"
    searches = []
    if searches_path.exists():
        data = yaml.safe_load(searches_path.read_text()) or {}
        searches = data.get("searches", [])

    employers_path = config_dir / "employers.yaml"
    employers = []
    if employers_path.exists():
        data = yaml.safe_load(employers_path.read_text()) or {}
        employers_raw = data.get("employers", {})
        employers = list(employers_raw.values()) if isinstance(employers_raw, dict) else employers_raw

    sites_path = config_dir / "sites.yaml"
    sites_config = {}
    if sites_path.exists():
        sites_config = yaml.safe_load(sites_path.read_text()) or {}

    return Config(
        profile=profile,
        searches=searches,
        gemini_api_key=os.environ.get("GEMINI_API_KEY", ""),
        notion_token=os.environ.get("NOTION_TOKEN", ""),
        notion_page_id=os.environ.get("NOTION_PAGE_ID", ""),
        notion_database_id=os.environ.get("NOTION_DATABASE_ID", ""),
        anthropic_api_key=os.environ.get("ANTHROPIC_API_KEY", ""),
        capsolver_api_key=os.environ.get("CAPSOLVER_API_KEY", ""),
        llm_provider=os.environ.get("LLM_PROVIDER", "gemini"),
        llm_model=os.environ.get("LLM_MODEL", "gemini-2.5-flash"),
        score_threshold=int(os.environ.get("SCORE_THRESHOLD", "3")),
        validation_mode=os.environ.get("VALIDATION_MODE", "normal"),
        employers=employers,
        sites_config=sites_config,
        config_dir=config_dir,
        data_dir=data_dir,
    )
