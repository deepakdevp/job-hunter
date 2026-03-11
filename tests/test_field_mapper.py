"""Tests for LLM-powered field mapper."""
from __future__ import annotations
import json
from unittest.mock import AsyncMock
import pytest
from job_hunter.apply.field_mapper import FieldMapper, FieldSuggestion, CONFIDENCE_THRESHOLD

@pytest.fixture
def sample_profile():
    return {
        "name": "Test User",
        "skills": ["Python", "React"],
        "target_role": "Software Engineer",
        "work_authorization": "visa_required",
        "resume_facts": {
            "companies": [{"name": "Acme", "title": "SDE 2"}],
        },
    }

@pytest.fixture
def mock_llm():
    return AsyncMock()

@pytest.mark.asyncio
async def test_map_high_confidence(mock_llm, sample_profile):
    mock_llm.generate.return_value = json.dumps({"answer": "Yes", "confidence": 0.95})
    mapper = FieldMapper(mock_llm, sample_profile)
    result = await mapper.suggest("Are you authorized to work in Japan?")
    assert result.answer == "Yes"
    assert result.confidence >= 0.9
    assert result.needs_human is False

@pytest.mark.asyncio
async def test_map_low_confidence(mock_llm, sample_profile):
    mock_llm.generate.return_value = json.dumps({"answer": "Maybe", "confidence": 0.3})
    mapper = FieldMapper(mock_llm, sample_profile)
    result = await mapper.suggest("What is your expected salary?")
    assert result.confidence < 0.5
    assert result.needs_human is True

@pytest.mark.asyncio
async def test_map_llm_error(mock_llm, sample_profile):
    mock_llm.generate.side_effect = Exception("LLM unavailable")
    mapper = FieldMapper(mock_llm, sample_profile)
    result = await mapper.suggest("Some question")
    assert result.answer == ""
    assert result.needs_human is True

def test_field_suggestion_needs_human_threshold():
    high = FieldSuggestion(answer="Yes", confidence=0.9)
    assert high.needs_human is False
    low = FieldSuggestion(answer="Maybe", confidence=0.4)
    assert low.needs_human is True

@pytest.mark.asyncio
async def test_prompt_includes_profile_context(mock_llm, sample_profile):
    mock_llm.generate.return_value = json.dumps({"answer": "test", "confidence": 0.8})
    mapper = FieldMapper(mock_llm, sample_profile)
    await mapper.suggest("Why do you want this job?")
    prompt = mock_llm.generate.call_args[0][0]
    assert "Test User" in prompt
    assert "Python" in prompt
