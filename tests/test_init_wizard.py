import json

import pytest
import yaml

from job_hunter.init_wizard import run_init


@pytest.fixture
def answers(tmp_path):
    return {
        "config_dir": str(tmp_path / "config"),
        "data_dir": str(tmp_path / "data"),
        "llm_provider": "gemini",
        "api_key": "test-gemini-key",  # pragma: allowlist secret
        "name": "Jane Doe",
        "email": "jane@example.com",
        "target_roles": "Software Engineer, Backend Developer",
        "skills": "Python, Go, PostgreSQL",
    }


def test_init_creates_profile_json(answers):
    config_dir = run_init(answers)
    profile_path = config_dir / "profile.json"
    assert profile_path.exists()

    profile = json.loads(profile_path.read_text())
    assert profile["name"] == "Jane Doe"
    assert profile["email"] == "jane@example.com"
    assert profile["target_roles"] == ["Software Engineer", "Backend Developer"]
    assert profile["target_role"] == "Software Engineer"
    assert profile["skills"] == ["Python", "Go", "PostgreSQL"]
    assert "resume_facts" in profile
    assert "eeo_defaults" in profile


def test_init_creates_env_file(answers):
    config_dir = run_init(answers)
    env_path = config_dir / ".env"
    assert env_path.exists()

    content = env_path.read_text()
    assert "LLM_PROVIDER=" in content
    assert "GEMINI_API_KEY=test-gemini-key" in content
    assert "SCORE_THRESHOLD=3" in content


def test_init_creates_searches_yaml(answers):
    config_dir = run_init(answers)
    searches_path = config_dir / "searches.yaml"
    assert searches_path.exists()

    data = yaml.safe_load(searches_path.read_text())
    assert "searches" in data
    assert len(data["searches"]) >= 1
    assert data["searches"][0]["query"] == "software engineer"


def test_init_env_has_correct_provider(answers):
    # Test gemini provider
    config_dir = run_init(answers)
    content = (config_dir / ".env").read_text()
    assert "LLM_PROVIDER=gemini" in content
    assert "GEMINI_API_KEY=test-gemini-key" in content

    # Test ollama provider (no API key line expected)
    answers["llm_provider"] = "ollama"
    answers["api_key"] = ""
    answers["config_dir"] = str(config_dir.parent / "config2")
    config_dir2 = run_init(answers)
    content2 = (config_dir2 / ".env").read_text()
    assert "LLM_PROVIDER=ollama" in content2
    assert "OLLAMA_HOST=http://localhost:11434" in content2
    # ollama should not have a GEMINI/OPENAI/ANTHROPIC key line
    assert "GEMINI_API_KEY" not in content2
