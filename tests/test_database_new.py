"""Tests for new database features: new Job fields, StoryBankDB, new query methods."""

import json

import pytest

from job_hunter.database import Job, JobDB, StoryBankDB


@pytest.fixture
def db(tmp_path):
    return JobDB(tmp_path / "test.db")


@pytest.fixture
def story_db(tmp_path):
    return StoryBankDB(tmp_path / "test.db")


def _make_job(url="https://example.com/1", **kwargs) -> Job:
    defaults = dict(
        url=url,
        title="Software Engineer",
        company="TestCo",
        location="Tokyo",
        source="indeed",
    )
    defaults.update(kwargs)
    return Job(**defaults)


# --- New Job fields with upsert ---


class TestNewJobFields:
    def test_evaluation_field_roundtrips(self, db):
        eval_data = json.dumps({"archetype": {"primary": "backend"}, "blocks": {}})
        job = _make_job(evaluation=eval_data)
        db.upsert_job(job)
        result = db.get_job("https://example.com/1")
        assert result.evaluation is not None
        assert json.loads(result.evaluation)["archetype"]["primary"] == "backend"

    def test_outreach_field_roundtrips(self, db):
        outreach_data = json.dumps({"targets": [{"role": "peer", "message": "hi"}]})
        job = _make_job(outreach=outreach_data)
        db.upsert_job(job)
        result = db.get_job("https://example.com/1")
        assert result.outreach is not None
        parsed = json.loads(result.outreach)
        assert len(parsed["targets"]) == 1

    def test_research_data_field_roundtrips(self, db):
        research = json.dumps({"company_size": 500, "funding": "Series B"})
        job = _make_job(research_data=research)
        db.upsert_job(job)
        result = db.get_job("https://example.com/1")
        assert result.research_data is not None
        assert json.loads(result.research_data)["company_size"] == 500

    def test_keywords_field_roundtrips(self, db):
        kw = json.dumps({"keywords": ["python", "react"], "coverage_pct": 0.8})
        job = _make_job(keywords=kw)
        db.upsert_job(job)
        result = db.get_job("https://example.com/1")
        assert result.keywords is not None
        assert json.loads(result.keywords)["coverage_pct"] == 0.8

    def test_negotiation_field_roundtrips(self, db):
        neg = json.dumps({"market_data": {"salary_range": {"mid": "10M JPY"}}})
        job = _make_job(negotiation=neg)
        db.upsert_job(job)
        result = db.get_job("https://example.com/1")
        assert result.negotiation is not None
        assert "10M JPY" in result.negotiation

    def test_upsert_preserves_new_fields(self, db):
        job = _make_job(evaluation='{"test": true}')
        db.upsert_job(job)
        # Update another field
        job.score = 8
        db.upsert_job(job)
        result = db.get_job("https://example.com/1")
        assert result.score == 8
        assert result.evaluation == '{"test": true}'


# --- get_unevaluated_jobs ---


class TestGetUnevaluatedJobs:
    def test_returns_scored_without_evaluation(self, db):
        db.upsert_job(_make_job(
            url="https://a.com/1", score=7, description="JD", evaluation=None,
        ))
        db.upsert_job(_make_job(
            url="https://a.com/2", score=8, description="JD",
            evaluation='{"done": true}',
        ))
        result = db.get_unevaluated_jobs(min_score=5)
        assert len(result) == 1
        assert result[0].url == "https://a.com/1"

    def test_filters_by_min_score(self, db):
        db.upsert_job(_make_job(url="https://a.com/1", score=3, description="JD"))
        db.upsert_job(_make_job(url="https://a.com/2", score=7, description="JD"))
        result = db.get_unevaluated_jobs(min_score=5)
        assert len(result) == 1
        assert result[0].url == "https://a.com/2"

    def test_returns_empty_when_all_evaluated(self, db):
        db.upsert_job(_make_job(score=7, description="JD", evaluation='{"a": 1}'))
        result = db.get_unevaluated_jobs(min_score=5)
        assert len(result) == 0


# --- get_evaluated_jobs ---


class TestGetEvaluatedJobs:
    def test_returns_jobs_with_evaluation(self, db):
        db.upsert_job(_make_job(
            url="https://a.com/1", score=7, evaluation='{"done": true}',
        ))
        db.upsert_job(_make_job(url="https://a.com/2", score=8, evaluation=None))
        result = db.get_evaluated_jobs()
        assert len(result) == 1
        assert result[0].url == "https://a.com/1"

    def test_filters_by_min_score(self, db):
        db.upsert_job(_make_job(
            url="https://a.com/1", score=3, evaluation='{"x": 1}',
        ))
        db.upsert_job(_make_job(
            url="https://a.com/2", score=7, evaluation='{"x": 1}',
        ))
        result = db.get_evaluated_jobs(min_score=5)
        assert len(result) == 1
        assert result[0].url == "https://a.com/2"


# --- get_jobs_for_comparison ---


class TestGetJobsForComparison:
    def test_ordering_by_score_descending(self, db):
        for score, url in [(5, "a"), (9, "b"), (7, "c")]:
            db.upsert_job(_make_job(
                url=f"https://ex.com/{url}", score=score,
                evaluation='{"x":1}',
            ))
        result = db.get_jobs_for_comparison(min_score=5)
        scores = [j.score for j in result]
        assert scores == [9, 7, 5]

    def test_respects_limit(self, db):
        for i in range(5):
            db.upsert_job(_make_job(
                url=f"https://ex.com/{i}", score=6, evaluation='{"x":1}',
            ))
        result = db.get_jobs_for_comparison(min_score=5, limit=3)
        assert len(result) == 3

    def test_excludes_unevaluated_jobs(self, db):
        db.upsert_job(_make_job(url="https://a.com/1", score=9, evaluation=None))
        db.upsert_job(_make_job(
            url="https://a.com/2", score=7, evaluation='{"x":1}',
        ))
        result = db.get_jobs_for_comparison(min_score=5)
        assert len(result) == 1
        assert result[0].url == "https://a.com/2"


# --- StoryBankDB ---


class TestStoryBankDB:
    def test_add_story_returns_id(self, story_db):
        story_id = story_db.add_story({
            "title": "Built REST API",
            "theme": "backend",
            "situation": "Needed a scalable API",
            "task": "Design and implement",
            "action": "Used FastAPI with async",
            "result": "Handled 10K req/s",
        })
        assert isinstance(story_id, int)
        assert story_id > 0

    def test_get_stories_returns_all(self, story_db):
        story_db.add_story({"title": "Story 1", "theme": "backend"})
        story_db.add_story({"title": "Story 2", "theme": "frontend"})
        stories = story_db.get_stories()
        assert len(stories) == 2

    def test_search_stories_by_title(self, story_db):
        story_db.add_story({"title": "REST API Design", "theme": "backend"})
        story_db.add_story({"title": "React Component Library", "theme": "frontend"})
        results = story_db.search_stories("REST")
        assert len(results) == 1
        assert results[0]["title"] == "REST API Design"

    def test_search_stories_by_theme(self, story_db):
        story_db.add_story({"title": "Story 1", "theme": "leadership"})
        story_db.add_story({"title": "Story 2", "theme": "technical"})
        results = story_db.search_stories("leadership")
        assert len(results) == 1

    def test_search_stories_by_tags(self, story_db):
        story_db.add_story({
            "title": "Story 1",
            "tags": json.dumps(["python", "api"]),
        })
        results = story_db.search_stories("python")
        assert len(results) == 1

    def test_story_exists_true(self, story_db):
        story_db.add_story({
            "title": "Built API",
            "situation": "At startup X",
        })
        assert story_db.story_exists("Built API", "At startup X") is True

    def test_story_exists_false(self, story_db):
        story_db.add_story({"title": "Built API", "situation": "At startup X"})
        assert story_db.story_exists("Built API", "At startup Y") is False
        assert story_db.story_exists("Other", "At startup X") is False


# --- _migrate_schema idempotency ---


class TestMigrateSchema:
    def test_migrate_is_idempotent(self, tmp_path):
        db_path = tmp_path / "test.db"
        db1 = JobDB(db_path)
        db1.upsert_job(_make_job(evaluation='{"a":1}'))
        db1.close()

        # Open again -- _migrate_schema runs again
        db2 = JobDB(db_path)
        result = db2.get_job("https://example.com/1")
        assert result.evaluation == '{"a":1}'
        db2.close()

        # Third time
        db3 = JobDB(db_path)
        result = db3.get_job("https://example.com/1")
        assert result.evaluation == '{"a":1}'
        db3.close()


# --- get_stats includes evaluation and stories counts ---


class TestGetStatsNew:
    def test_stats_includes_evaluated_count(self, db):
        db.upsert_job(_make_job(url="https://a.com/1", status="scored"))
        db.upsert_job(_make_job(
            url="https://a.com/2", status="scored", evaluation='{"x":1}',
        ))
        stats = db.get_stats()
        assert stats["evaluated"] == 1

    def test_stats_includes_stories_count(self, db):
        # The JobDB also creates the story_bank table
        db.conn.execute(
            "INSERT INTO story_bank (title) VALUES (?)", ("Test Story",)
        )
        db.conn.commit()
        stats = db.get_stats()
        assert stats["stories"] == 1

    def test_stats_zero_when_empty(self, db):
        stats = db.get_stats()
        assert stats["evaluated"] == 0
        assert stats["stories"] == 0
        assert stats["total"] == 0
