import pytest
from pathlib import Path
from job_hunter.config import load_config, Config


@pytest.fixture
def config_dir(tmp_path):
    import json
    import yaml

    profile = {
        "name": "Test User",
        "email": "test@example.com",
        "target_role": "Software Engineer",
        "skills": ["Python"],
        "resume_facts": {"companies": [], "education": [], "metrics": []},
    }
    searches = {
        "searches": [
            {"query": "software engineer", "location": "Tokyo", "boards": ["indeed"]}
        ]
    }
    (tmp_path / "profile.json").write_text(json.dumps(profile))
    (tmp_path / "searches.yaml").write_text(yaml.dump(searches))
    env_file = tmp_path / ".env"
    env_file.write_text(
        "GEMINI_API_KEY=test-key\nNOTION_TOKEN=test-token\nNOTION_PAGE_ID=test-page\n"
    )
    return tmp_path


def test_load_config_returns_config_object(config_dir):
    config = load_config(config_dir)
    assert isinstance(config, Config)
    assert config.profile["name"] == "Test User"
    assert config.searches[0]["query"] == "software engineer"
    assert config.gemini_api_key == "test-key"
    assert config.notion_token == "test-token"


def test_load_config_missing_profile_raises(tmp_path):
    with pytest.raises(FileNotFoundError, match="profile.json"):
        load_config(tmp_path)


def test_config_score_threshold_default(config_dir):
    config = load_config(config_dir)
    assert config.score_threshold == 3


def test_config_score_threshold_from_env(config_dir):
    env_file = config_dir / ".env"
    env_file.write_text(
        "GEMINI_API_KEY=k\nNOTION_TOKEN=t\nNOTION_PAGE_ID=p\nSCORE_THRESHOLD=8\n"
    )
    config = load_config(config_dir)
    assert config.score_threshold == 8


def test_config_loads_employers(config_dir):
    import yaml

    employers = {
        "employers": {
            "nvidia": {
                "name": "NVIDIA",
                "tenant": "nvidia",
                "site_id": "NVIDIAExternalCareerSite",
                "base_url": "https://nvidia.wd5.myworkdayjobs.com",
            }
        }
    }
    (config_dir / "employers.yaml").write_text(yaml.dump(employers))
    config = load_config(config_dir)
    assert len(config.employers) == 1
    assert config.employers[0]["name"] == "NVIDIA"


def test_config_loads_sites(config_dir):
    import yaml

    sites = {"blocked": {"sites": ["glassdoor"]}, "blocked_sso": ["accounts.google.com"]}
    (config_dir / "sites.yaml").write_text(yaml.dump(sites))
    config = load_config(config_dir)
    assert "glassdoor" in config.sites_config["blocked"]["sites"]
