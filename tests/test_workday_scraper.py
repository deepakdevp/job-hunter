import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from job_hunter.discover.workday_scraper import scrape_workday_employer, run_workday_scrapers


MOCK_WORKDAY_RESPONSE = {
    "jobPostings": [
        {
            "title": "Software Engineer",
            "externalPath": "/job/12345",
            "locationsText": "Tokyo, Japan",
            "postedOn": "2026-03-01",
        },
        {
            "title": "Backend Developer",
            "externalPath": "/job/67890",
            "locationsText": "Osaka, Japan",
            "postedOn": "2026-03-02",
        },
        {
            "title": "No Path Job",
            "externalPath": "",
            "locationsText": "Remote",
            "postedOn": "",
        },
    ],
}


@pytest.mark.asyncio
async def test_scrape_workday_employer_parses_jobs():
    employer = {
        "name": "TestCorp",
        "base_url": "https://testcorp.wd5.myworkdayjobs.com",
        "tenant": "testcorp",
        "site_id": "careers",
    }
    mock_response = MagicMock()
    mock_response.json.return_value = MOCK_WORKDAY_RESPONSE
    mock_response.raise_for_status = MagicMock()

    with patch("job_hunter.discover.workday_scraper.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        jobs = await scrape_workday_employer(employer, query="engineer", max_results=10)

    # Should skip the job with empty externalPath
    assert len(jobs) == 2
    assert jobs[0].title == "Software Engineer"
    assert jobs[0].company == "TestCorp"
    assert jobs[0].source == "workday"
    assert "/job/12345" in jobs[0].url
    assert jobs[1].location == "Osaka, Japan"


@pytest.mark.asyncio
async def test_scrape_workday_missing_config():
    employer = {"name": "Bad", "base_url": "", "site_id": ""}
    jobs = await scrape_workday_employer(employer)
    assert jobs == []


@pytest.mark.asyncio
async def test_run_workday_scrapers_aggregates():
    employer1 = {
        "name": "A",
        "base_url": "https://a.wd5.myworkdayjobs.com",
        "tenant": "a",
        "site_id": "careers",
    }
    employer2 = {
        "name": "B",
        "base_url": "https://b.wd5.myworkdayjobs.com",
        "tenant": "b",
        "site_id": "careers",
    }

    mock_response = MagicMock()
    mock_response.json.return_value = {"jobPostings": [
        {"title": "Dev", "externalPath": "/job/1", "locationsText": "Tokyo", "postedOn": ""},
    ]}
    mock_response.raise_for_status = MagicMock()

    with patch("job_hunter.discover.workday_scraper.httpx.AsyncClient") as mock_client_cls:
        mock_client = AsyncMock()
        mock_client.post.return_value = mock_response
        mock_client.__aenter__ = AsyncMock(return_value=mock_client)
        mock_client.__aexit__ = AsyncMock(return_value=False)
        mock_client_cls.return_value = mock_client

        jobs = await run_workday_scrapers([employer1, employer2])

    assert len(jobs) == 2
