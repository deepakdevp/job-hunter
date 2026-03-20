import pandas as pd
from job_hunter.discover.jobspy_scraper import parse_jobspy_results
from job_hunter.discover.dedup import dedup_jobs
from job_hunter.database import Job


def test_parse_jobspy_results_converts_dataframe():
    df = pd.DataFrame(
        {
            "job_url": ["https://example.com/1", "https://example.com/2"],
            "title": ["SWE", "Backend Dev"],
            "company_name": ["Acme", "Globex"],
            "location": ["Tokyo", "Remote"],
            "site": ["indeed", "linkedin"],
            "description": ["Great job", "Another job"],
            "date_posted": ["2026-03-01", "2026-03-02"],
            "min_amount": [80000, None],
            "max_amount": [120000, None],
            "interval": ["yearly", None],
        }
    )
    jobs = parse_jobspy_results(df)
    assert len(jobs) == 2
    assert jobs[0].title == "SWE"
    assert jobs[0].source == "indeed"
    assert jobs[0].salary_min == 80000
    assert jobs[0].salary_max == 120000
    assert jobs[1].salary_min is None


def test_parse_jobspy_results_skips_nan_urls():
    df = pd.DataFrame(
        {
            "job_url": ["https://example.com/1", float("nan")],
            "title": ["SWE", "Bad"],
            "company_name": ["A", "B"],
            "location": ["T", "T"],
            "site": ["indeed", "indeed"],
            "description": [None, None],
            "date_posted": [None, None],
            "min_amount": [None, None],
            "max_amount": [None, None],
            "interval": [None, None],
        }
    )
    jobs = parse_jobspy_results(df)
    assert len(jobs) == 1


def test_parse_jobspy_results_builds_salary_raw():
    df = pd.DataFrame(
        {
            "job_url": ["https://example.com/1"],
            "title": ["SWE"],
            "company_name": ["A"],
            "location": ["T"],
            "site": ["indeed"],
            "description": [None],
            "date_posted": [None],
            "min_amount": [5000000],
            "max_amount": [8000000],
            "interval": ["yearly"],
        }
    )
    jobs = parse_jobspy_results(df)
    assert "5000000" in jobs[0].salary_raw
    assert "8000000" in jobs[0].salary_raw
    assert "yearly" in jobs[0].salary_raw


def test_dedup_removes_existing_urls():
    jobs = [
        Job(url="https://example.com/1", title="A", company="X", location="Y", source="indeed"),
        Job(url="https://example.com/2", title="B", company="X", location="Y", source="indeed"),
        Job(url="https://example.com/3", title="C", company="X", location="Y", source="indeed"),
    ]
    existing = {"https://example.com/1", "https://example.com/3"}
    deduped = dedup_jobs(jobs, existing)
    assert len(deduped) == 1
    assert deduped[0].url == "https://example.com/2"


def test_dedup_removes_duplicates_within_batch():
    jobs = [
        Job(url="https://example.com/1", title="A", company="X", location="Y", source="indeed"),
        Job(
            url="https://example.com/1", title="A dup", company="X", location="Y", source="linkedin"
        ),
        Job(url="https://example.com/2", title="B", company="X", location="Y", source="indeed"),
    ]
    deduped = dedup_jobs(jobs, set())
    assert len(deduped) == 2


def test_dedup_empty_existing():
    jobs = [
        Job(url="https://example.com/1", title="A", company="X", location="Y", source="indeed"),
    ]
    deduped = dedup_jobs(jobs, set())
    assert len(deduped) == 1
