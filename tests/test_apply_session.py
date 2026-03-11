"""Tests for apply session manager."""
from __future__ import annotations
import json
import pytest
from job_hunter.apply.session import SessionManager

@pytest.fixture
def session_dir(tmp_path):
    return tmp_path / "sessions"

@pytest.fixture
def manager(session_dir):
    return SessionManager(session_dir)

def test_session_dir_created(session_dir):
    SessionManager(session_dir)
    assert session_dir.exists()

def test_get_session_path(manager, session_dir):
    path = manager.get_session_path("workday")
    assert path == session_dir / "workday.json"

def test_has_session_false(manager):
    assert manager.has_session("workday") is False

def test_has_session_true(manager, session_dir):
    (session_dir / "workday.json").write_text("{}")
    assert manager.has_session("workday") is True

def test_save_session(manager, session_dir):
    state = {"cookies": [{"name": "sid", "value": "abc"}]}
    manager.save_session("greenhouse", state)
    saved = json.loads((session_dir / "greenhouse.json").read_text())
    assert saved == state

def test_load_session(manager, session_dir):
    state = {"cookies": [{"name": "sid", "value": "xyz"}]}
    (session_dir / "lever.json").write_text(json.dumps(state))
    loaded = manager.load_session("lever")
    assert loaded == state

def test_load_session_missing(manager):
    assert manager.load_session("nonexistent") is None

def test_domain_from_url():
    assert SessionManager.domain_from_url("https://company.myworkdayjobs.com/en/jobs/1") == "myworkdayjobs.com"
    assert SessionManager.domain_from_url("https://boards.greenhouse.io/acme/1") == "greenhouse.io"
    assert SessionManager.domain_from_url("https://jobs.lever.co/acme") == "lever.co"
