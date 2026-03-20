"""Tests for Japan-specific form strategies."""

from __future__ import annotations
import asyncio
from unittest.mock import AsyncMock
from job_hunter.apply.strategies.japan import (
    WantedlyFormFiller,
    GreenFormFiller,
    CareerCrossFormFiller,
)


def test_wantedly_detect():
    filler = WantedlyFormFiller()
    page = AsyncMock()
    page.url = "https://www.wantedly.com/projects/1234"
    assert asyncio.run(filler.detect(page)) is True


def test_wantedly_detect_false():
    filler = WantedlyFormFiller()
    page = AsyncMock()
    page.url = "https://lever.co/jobs/1"
    assert asyncio.run(filler.detect(page)) is False


def test_wantedly_field_selectors():
    filler = WantedlyFormFiller()
    assert "name" in filler.FIELD_SELECTORS or "email" in filler.FIELD_SELECTORS


def test_green_detect():
    filler = GreenFormFiller()
    page = AsyncMock()
    page.url = "https://www.green-japan.com/job/1234"
    assert asyncio.run(filler.detect(page)) is True


def test_green_detect_false():
    filler = GreenFormFiller()
    page = AsyncMock()
    page.url = "https://wantedly.com/projects/1"
    assert asyncio.run(filler.detect(page)) is False


def test_careercross_detect():
    filler = CareerCrossFormFiller()
    page = AsyncMock()
    page.url = "https://www.careercross.com/en/job/detail-1234"
    assert asyncio.run(filler.detect(page)) is True


def test_careercross_detect_false():
    filler = CareerCrossFormFiller()
    page = AsyncMock()
    page.url = "https://green-japan.com/job/1"
    assert asyncio.run(filler.detect(page)) is False
