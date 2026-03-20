"""Tests for generic form strategy."""

from __future__ import annotations
import asyncio
from unittest.mock import AsyncMock
import pytest
from job_hunter.apply.strategies.generic import GenericFormFiller


@pytest.fixture
def filler():
    return GenericFormFiller()


@pytest.fixture
def sample_profile():
    return {
        "name": "Test User",
        "email": "test@example.com",
        "phone": "+1234567890",
        "linkedin_url": "https://linkedin.com/in/testuser",
        "website": "https://testuser.dev",
        "location": "Tokyo, Japan",
    }


def test_detect_always_true(filler):
    page = AsyncMock()
    assert asyncio.run(filler.detect(page)) is True


def test_field_mapping_basics(filler, sample_profile):
    mappings = filler._build_field_map(sample_profile)
    assert mappings["name"] == "Test User"
    assert mappings["email"] == "test@example.com"
    assert mappings["phone"] == "+1234567890"


def test_field_mapping_linkedin(filler, sample_profile):
    mappings = filler._build_field_map(sample_profile)
    assert mappings["linkedin"] == "https://linkedin.com/in/testuser"


def test_match_label_email(filler):
    assert filler._match_label_to_key("Email Address") == "email"


def test_match_label_name(filler):
    assert filler._match_label_to_key("Your Full Name") == "name"


def test_match_label_phone(filler):
    assert filler._match_label_to_key("Phone Number") == "phone"


def test_match_label_linkedin(filler):
    assert filler._match_label_to_key("LinkedIn Profile") == "linkedin"


def test_match_label_resume(filler):
    assert filler._match_label_to_key("Upload Resume") == "resume"


def test_match_label_cover_letter(filler):
    assert filler._match_label_to_key("Cover Letter") == "cover_letter"


def test_match_label_unknown(filler):
    assert filler._match_label_to_key("Favorite Color") is None


def test_submit_selectors_exist(filler):
    assert len(filler.SUBMIT_SELECTORS) > 0
