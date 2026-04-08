"""Tests for the STAR story bank: extraction, deduplication, search."""

import json

import pytest
from unittest.mock import AsyncMock

from job_hunter.database import StoryBankDB
from job_hunter.stories.bank import (
    extract_stories_from_evaluation,
    add_stories_to_bank,
    list_stories,
    search_stories,
    deduplicate_story,
)


def _make_evaluation(stories=None):
    """Build a realistic evaluation dict with interview_prep stories."""
    if stories is None:
        stories = [
            {
                "requirement": "Python experience",
                "title": "REST API at TechCo",
                "situation": "TechCo needed a new API for mobile clients.",
                "task": "Design and implement a REST API.",
                "action": "Built with Django REST Framework and Redis caching.",
                "result": "Handled 10K requests/day with <100ms p99 latency.",
                "reflection": "Learned the importance of caching and proper indexing.",
            },
            {
                "requirement": "Team leadership",
                "title": "Frontend Migration Lead",
                "situation": "Legacy jQuery frontend was unmaintainable.",
                "task": "Lead migration to React.",
                "action": "Planned incremental migration, mentored 3 junior devs.",
                "result": "Completed migration in 4 months, 50% fewer bugs.",
                "reflection": "Incremental migration is safer than big-bang rewrites.",
            },
        ]
    return {
        "version": "1.0",
        "blocks": {
            "interview_prep": {
                "stories": stories,
            },
        },
    }


# --- extract_stories_from_evaluation ---


class TestExtractStories:
    @pytest.mark.asyncio
    async def test_extracts_stories_from_eval(self):
        evaluation = _make_evaluation()
        stories = await extract_stories_from_evaluation(evaluation, "https://example.com/1")
        assert len(stories) == 2
        assert stories[0]["title"] == "REST API at TechCo"
        assert stories[0]["source_job_url"] == "https://example.com/1"

    @pytest.mark.asyncio
    async def test_stories_have_required_fields(self):
        evaluation = _make_evaluation()
        stories = await extract_stories_from_evaluation(evaluation, "https://example.com/1")
        for story in stories:
            assert "title" in story
            assert "theme" in story
            assert "situation" in story
            assert "task" in story
            assert "action" in story
            assert "result" in story
            assert "reflection" in story
            assert "tags" in story
            assert "best_for" in story

    @pytest.mark.asyncio
    async def test_empty_evaluation_returns_empty(self):
        evaluation = {"blocks": {"interview_prep": {"stories": []}}}
        stories = await extract_stories_from_evaluation(evaluation, "https://example.com/1")
        assert stories == []

    @pytest.mark.asyncio
    async def test_missing_blocks_returns_empty(self):
        evaluation = {"blocks": {}}
        stories = await extract_stories_from_evaluation(evaluation, "https://example.com/1")
        assert stories == []

    @pytest.mark.asyncio
    async def test_tags_are_extracted(self):
        evaluation = _make_evaluation()
        stories = await extract_stories_from_evaluation(evaluation, "https://example.com/1")
        # Should have at least one tag from the requirement
        assert len(stories[0]["tags"]) > 0


# --- add_stories_to_bank ---


class TestAddStoriesToBank:
    def test_adds_stories(self, tmp_path):
        db_path = tmp_path / "test.db"
        # Pre-create StoryBankDB to ensure table exists
        sdb = StoryBankDB(db_path)
        sdb.close()

        stories = [
            {
                "title": "API Story",
                "theme": "backend",
                "situation": "Needed API",
                "task": "Build",
                "action": "Built it",
                "result": "Worked",
                "reflection": "Learned",
                "tags": ["python", "api"],
                "best_for": ["backend roles"],
                "source_job_url": "https://example.com/1",
            },
        ]
        added = add_stories_to_bank(db_path, stories)
        assert added == 1

        sdb = StoryBankDB(db_path)
        all_stories = sdb.get_stories()
        sdb.close()
        assert len(all_stories) == 1

    def test_deduplicates_by_title_and_situation(self, tmp_path):
        db_path = tmp_path / "test.db"
        stories = [
            {
                "title": "API Story",
                "situation": "At TechCo",
                "tags": [],
                "best_for": [],
            },
        ]
        added_first = add_stories_to_bank(db_path, stories)
        assert added_first == 1

        # Add again -- should be skipped
        added_second = add_stories_to_bank(db_path, stories)
        assert added_second == 0

        sdb = StoryBankDB(db_path)
        assert len(sdb.get_stories()) == 1
        sdb.close()

    def test_allows_different_stories(self, tmp_path):
        db_path = tmp_path / "test.db"
        stories = [
            {"title": "Story A", "situation": "Context A", "tags": [], "best_for": []},
            {"title": "Story B", "situation": "Context B", "tags": [], "best_for": []},
        ]
        added = add_stories_to_bank(db_path, stories)
        assert added == 2


# --- list_stories ---


class TestListStories:
    def test_groups_by_theme(self, tmp_path):
        db_path = tmp_path / "test.db"
        stories = [
            {"title": "S1", "situation": "X1", "theme": "backend", "tags": [], "best_for": []},
            {"title": "S2", "situation": "X2", "theme": "backend", "tags": [], "best_for": []},
            {"title": "S3", "situation": "X3", "theme": "frontend", "tags": [], "best_for": []},
        ]
        add_stories_to_bank(db_path, stories)

        grouped = list_stories(db_path)
        themes = {g["theme"] for g in grouped}
        assert "backend" in themes
        assert "frontend" in themes

        backend_group = next(g for g in grouped if g["theme"] == "backend")
        assert len(backend_group["stories"]) == 2

    def test_empty_returns_empty(self, tmp_path):
        db_path = tmp_path / "test.db"
        # Create the table
        sdb = StoryBankDB(db_path)
        sdb.close()
        grouped = list_stories(db_path)
        assert grouped == []


# --- search_stories ---


class TestSearchStories:
    def test_finds_by_query(self, tmp_path):
        db_path = tmp_path / "test.db"
        stories = [
            {"title": "REST API Design", "situation": "X", "theme": "backend", "tags": [], "best_for": []},
            {"title": "React Components", "situation": "Y", "theme": "frontend", "tags": [], "best_for": []},
        ]
        add_stories_to_bank(db_path, stories)

        results = search_stories(db_path, "REST")
        assert len(results) == 1
        assert results[0]["title"] == "REST API Design"

    def test_no_results_returns_empty(self, tmp_path):
        db_path = tmp_path / "test.db"
        sdb = StoryBankDB(db_path)
        sdb.close()
        results = search_stories(db_path, "nonexistent")
        assert results == []


# --- deduplicate_story (LLM-based) ---


class TestDeduplicateStory:
    @pytest.mark.asyncio
    async def test_detects_duplicate(self):
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = json.dumps({
            "is_duplicate": True,
            "reason": "Same project described differently",
            "similar_to": 1,
        })
        existing = [
            {
                "title": "Built REST API",
                "situation": "TechCo needed an API",
                "result": "Handled 10K req/day",
            }
        ]
        new_story = {
            "title": "API Development at TechCo",
            "situation": "Company needed REST endpoints",
            "task": "Create API",
            "action": "Used Django",
            "result": "Served 10K requests daily",
        }
        is_dup = await deduplicate_story(existing, new_story, mock_llm)
        assert is_dup is True

    @pytest.mark.asyncio
    async def test_detects_unique(self):
        mock_llm = AsyncMock()
        mock_llm.generate.return_value = json.dumps({
            "is_duplicate": False,
            "reason": "Different project entirely",
            "similar_to": None,
        })
        existing = [{"title": "Built REST API", "situation": "X", "result": "Y"}]
        new_story = {"title": "ML Pipeline", "situation": "Data team needed pipeline", "result": "Reduced training time"}
        is_dup = await deduplicate_story(existing, new_story, mock_llm)
        assert is_dup is False

    @pytest.mark.asyncio
    async def test_empty_existing_returns_false(self):
        mock_llm = AsyncMock()
        new_story = {"title": "Something", "situation": "Context"}
        is_dup = await deduplicate_story([], new_story, mock_llm)
        assert is_dup is False
        # LLM should not be called
        mock_llm.generate.assert_not_called()

    @pytest.mark.asyncio
    async def test_llm_failure_returns_false(self):
        mock_llm = AsyncMock()
        mock_llm.generate.side_effect = Exception("API error")
        existing = [{"title": "X", "situation": "Y", "result": "Z"}]
        new_story = {"title": "A", "situation": "B"}
        is_dup = await deduplicate_story(existing, new_story, mock_llm)
        assert is_dup is False
