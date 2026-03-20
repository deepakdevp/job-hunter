import pytest
from job_hunter.database import JobDB, Job


@pytest.fixture
def db(tmp_path):
    return JobDB(tmp_path / "test.db")


def test_insert_and_get_job(db):
    job = Job(
        url="https://example.com/job/123",
        title="Software Engineer",
        company="Acme",
        location="Tokyo",
        source="indeed",
    )
    db.upsert_job(job)
    result = db.get_job("https://example.com/job/123")
    assert result is not None
    assert result.title == "Software Engineer"
    assert result.company == "Acme"


def test_upsert_updates_existing(db):
    job = Job(
        url="https://example.com/1", title="SWE", company="A", location="Tokyo", source="indeed"
    )
    db.upsert_job(job)
    job.score = 8
    job.score_reason = "Great match"
    db.upsert_job(job)
    result = db.get_job("https://example.com/1")
    assert result.score == 8


def test_dedup_returns_true_for_existing(db):
    job = Job(
        url="https://example.com/1", title="SWE", company="A", location="Tokyo", source="indeed"
    )
    db.upsert_job(job)
    assert db.exists("https://example.com/1") is True
    assert db.exists("https://example.com/2") is False


def test_get_jobs_by_status(db):
    for i in range(5):
        job = Job(
            url=f"https://example.com/{i}",
            title=f"Job {i}",
            company="A",
            location="Tokyo",
            source="indeed",
            status="new",
        )
        db.upsert_job(job)
    db.update_status("https://example.com/0", "scored")
    new_jobs = db.get_jobs_by_status("new")
    assert len(new_jobs) == 4


def test_get_unenriched_jobs(db):
    job = Job(
        url="https://example.com/1",
        title="SWE",
        company="A",
        location="Tokyo",
        source="indeed",
        description=None,
    )
    db.upsert_job(job)
    unenriched = db.get_unenriched_jobs()
    assert len(unenriched) == 1


def test_get_unscored_jobs(db):
    job = Job(
        url="https://example.com/1",
        title="SWE",
        company="A",
        location="Tokyo",
        source="indeed",
        description="Full JD here",
        score=None,
    )
    db.upsert_job(job)
    unscored = db.get_unscored_jobs()
    assert len(unscored) == 1


def test_get_all_urls(db):
    for i in range(3):
        db.upsert_job(
            Job(url=f"https://example.com/{i}", title="J", company="A", location="T", source="i")
        )
    urls = db.get_all_urls()
    assert len(urls) == 3
    assert "https://example.com/0" in urls


def test_get_stats(db):
    db.upsert_job(
        Job(url="https://a.com/1", title="J", company="A", location="T", source="i", status="new")
    )
    db.upsert_job(
        Job(
            url="https://a.com/2", title="J", company="A", location="T", source="i", status="scored"
        )
    )
    stats = db.get_stats()
    assert stats["new"] == 1
    assert stats["scored"] == 1
    assert stats["total"] == 2
