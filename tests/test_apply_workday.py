"""Tests for Workday form strategy."""
from __future__ import annotations
import asyncio
from unittest.mock import AsyncMock
import pytest
from job_hunter.apply.strategies.workday import WorkdayFormFiller

@pytest.fixture
def filler():
    return WorkdayFormFiller()

def test_detect_workday_url(filler):
    page = AsyncMock()
    page.url = "https://acme.myworkdayjobs.com/en-US/External/job/1234"
    assert asyncio.run(filler.detect(page)) is True

def test_detect_non_workday(filler):
    page = AsyncMock()
    page.url = "https://greenhouse.io/jobs/1234"
    assert asyncio.run(filler.detect(page)) is False

def test_wizard_step_selectors_defined(filler):
    assert len(filler.STEP_SELECTORS) > 0

def test_next_button_selector(filler):
    assert filler.NEXT_BUTTON is not None

def test_field_selectors_have_required_keys(filler):
    assert "first_name" in filler.FIELD_SELECTORS
    assert "last_name" in filler.FIELD_SELECTORS
    assert "email" in filler.FIELD_SELECTORS
    assert "resume" in filler.FIELD_SELECTORS
