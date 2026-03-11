"""Tests for Greenhouse, Lever, and Ashby strategies."""
from __future__ import annotations
import asyncio
from unittest.mock import AsyncMock
import pytest
from job_hunter.apply.strategies.greenhouse import GreenhouseFormFiller
from job_hunter.apply.strategies.lever import LeverFormFiller
from job_hunter.apply.strategies.ashby import AshbyFormFiller

# Greenhouse
@pytest.fixture
def greenhouse():
    return GreenhouseFormFiller()

def test_greenhouse_detect(greenhouse):
    page = AsyncMock()
    page.url = "https://boards.greenhouse.io/acme/jobs/1234"
    assert asyncio.run(greenhouse.detect(page)) is True

def test_greenhouse_detect_false(greenhouse):
    page = AsyncMock()
    page.url = "https://lever.co/jobs/1234"
    assert asyncio.run(greenhouse.detect(page)) is False

def test_greenhouse_field_selectors(greenhouse):
    assert "first_name" in greenhouse.FIELD_SELECTORS
    assert "email" in greenhouse.FIELD_SELECTORS
    assert "resume" in greenhouse.FIELD_SELECTORS

def test_greenhouse_submit(greenhouse):
    assert greenhouse.SUBMIT_BUTTON is not None

# Lever
@pytest.fixture
def lever():
    return LeverFormFiller()

def test_lever_detect(lever):
    page = AsyncMock()
    page.url = "https://jobs.lever.co/acme/abc-123"
    assert asyncio.run(lever.detect(page)) is True

def test_lever_detect_false(lever):
    page = AsyncMock()
    page.url = "https://greenhouse.io/jobs/1234"
    assert asyncio.run(lever.detect(page)) is False

def test_lever_field_selectors(lever):
    assert "name" in lever.FIELD_SELECTORS
    assert "email" in lever.FIELD_SELECTORS
    assert "resume" in lever.FIELD_SELECTORS

# Ashby
@pytest.fixture
def ashby():
    return AshbyFormFiller()

def test_ashby_detect(ashby):
    page = AsyncMock()
    page.url = "https://jobs.ashbyhq.com/acme/1234"
    assert asyncio.run(ashby.detect(page)) is True

def test_ashby_detect_false(ashby):
    page = AsyncMock()
    page.url = "https://lever.co/jobs/1234"
    assert asyncio.run(ashby.detect(page)) is False

def test_ashby_field_selectors(ashby):
    assert "name" in ashby.FIELD_SELECTORS
    assert "email" in ashby.FIELD_SELECTORS
