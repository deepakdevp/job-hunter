"""Tests for job_hunter.notion.client — NotionJobDB."""

from __future__ import annotations

from unittest.mock import patch, MagicMock

import pytest

from job_hunter.database import Job
from job_hunter.notion.client import NotionJobDB, DATABASE_PROPERTIES, DATABASE_TITLE


@pytest.fixture
def mock_client():
    with patch("job_hunter.notion.client.Client") as MockClient:
        instance = MockClient.return_value
        yield instance


@pytest.fixture
def notion(mock_client):
    return NotionJobDB(token="test-token", database_id="db-123")


@pytest.fixture
def sample_job():
    return Job(
        url="https://example.com/job/1",
        title="Software Engineer",
        company="Acme Corp",
        location="Tokyo, Japan",
        source="indeed",
        status="scored",
        score=85,
        score_reason="Good fit",
        salary_min=6000000,
        salary_max=9000000,
        salary_raw="6M-9M JPY",
        posted_date="2026-03-01",
        found_date="2026-03-10",
        tech_stack="Python, React, AWS",
        apply_url="https://example.com/apply/1",
    )


# --- Database creation ---


def test_create_database(mock_client, notion):
    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "new-db-id"}
    mock_response.raise_for_status.return_value = None

    with patch("job_hunter.notion.client.httpx.post", return_value=mock_response) as mock_post:
        db_id = notion.create_database("parent-page-id")

    assert db_id == "new-db-id"
    assert notion.database_id == "new-db-id"
    mock_post.assert_called_once()
    call_kwargs = mock_post.call_args
    assert call_kwargs.kwargs["json"]["properties"] == DATABASE_PROPERTIES


def test_find_existing_database(mock_client, notion):
    mock_client.search.return_value = {
        "results": [
            {
                "id": "existing-db-id",
                "object": "database",
                "title": [{"plain_text": DATABASE_TITLE}],
            }
        ]
    }

    db_id = notion.find_existing_database("parent-page-id")

    assert db_id == "existing-db-id"
    assert notion.database_id == "existing-db-id"


def test_find_existing_database_not_found(mock_client, notion):
    mock_client.search.return_value = {"results": []}

    result = notion.find_existing_database("parent-page-id")

    assert result is None


def test_init_database_finds_existing(mock_client, notion):
    mock_client.search.return_value = {
        "results": [
            {
                "id": "found-id",
                "object": "database",
                "title": [{"plain_text": DATABASE_TITLE}],
            }
        ]
    }

    db_id = notion.init_database("parent-page-id")

    assert db_id == "found-id"


def test_init_database_creates_new(mock_client, notion):
    mock_client.search.return_value = {"results": []}

    mock_response = MagicMock()
    mock_response.json.return_value = {"id": "created-id"}
    mock_response.raise_for_status.return_value = None

    with patch("job_hunter.notion.client.httpx.post", return_value=mock_response):
        db_id = notion.init_database("parent-page-id")

    assert db_id == "created-id"


# --- Page CRUD ---


def test_create_page(mock_client, notion, sample_job):
    mock_client.pages.create.return_value = {"id": "page-123"}

    page_id = notion.create_page(sample_job)

    assert page_id == "page-123"
    call_kwargs = mock_client.pages.create.call_args.kwargs
    assert call_kwargs["parent"] == {"database_id": "db-123"}
    props = call_kwargs["properties"]
    assert props["Job Title"]["title"][0]["text"]["content"] == "Software Engineer"
    assert props["Company"]["rich_text"][0]["text"]["content"] == "Acme Corp"
    assert props["Score"]["number"] == 85
    assert props["Status"]["select"]["name"] == "scored"
    assert props["Job URL"]["url"] == "https://example.com/job/1"


def test_create_page_with_urls(mock_client, notion, sample_job):
    mock_client.pages.create.return_value = {"id": "page-456"}

    notion.create_page(
        sample_job,
        resume_url="https://drive.google.com/resume",
        cover_letter_url="https://drive.google.com/cl",
    )

    props = mock_client.pages.create.call_args.kwargs["properties"]
    assert props["Resume PDF"]["url"] == "https://drive.google.com/resume"
    assert props["Cover Letter"]["url"] == "https://drive.google.com/cl"


def test_create_page_no_database_id():
    with patch("job_hunter.notion.client.Client"):
        n = NotionJobDB(token="test")
        with pytest.raises(ValueError, match="Database ID not set"):
            n.create_page(Job(url="x", title="t", company="c", location="l", source="s"))


def test_update_page(mock_client, notion, sample_job):
    notion.update_page("page-123", sample_job)

    mock_client.pages.update.assert_called_once()
    call_kwargs = mock_client.pages.update.call_args.kwargs
    assert call_kwargs["page_id"] == "page-123"


# --- Pagination ---


def test_get_all_pages_single_page(mock_client, notion):
    mock_client.databases.query.return_value = {
        "results": [{"id": "p1"}, {"id": "p2"}],
        "has_more": False,
    }

    pages = notion.get_all_pages()

    assert len(pages) == 2


def test_get_all_pages_pagination(mock_client, notion):
    mock_client.databases.query.side_effect = [
        {"results": [{"id": "p1"}], "has_more": True, "next_cursor": "cursor-1"},
        {"results": [{"id": "p2"}], "has_more": False},
    ]

    pages = notion.get_all_pages()

    assert len(pages) == 2
    assert mock_client.databases.query.call_count == 2


# --- Page status extraction ---


def test_get_page_status(notion):
    page = {
        "id": "page-1",
        "properties": {
            "Job URL": {"url": "https://example.com/job/1"},
            "Status": {"select": {"name": "applied"}},
        },
    }

    url, status = notion.get_page_status(page)

    assert url == "https://example.com/job/1"
    assert status == "applied"


def test_get_page_status_no_select(notion):
    page = {
        "properties": {
            "Job URL": {"url": "https://example.com/job/2"},
            "Status": {"select": None},
        },
    }

    url, status = notion.get_page_status(page)

    assert status == "new"


# --- Property mapping ---


def test_job_to_properties_tech_stack(notion, sample_job):
    props = notion._job_to_properties(sample_job)

    tags = props["Tags"]["multi_select"]
    tag_names = [t["name"] for t in tags]
    assert "Python" in tag_names
    assert "React" in tag_names
    assert "AWS" in tag_names


def test_job_to_properties_truncates_long_text(notion):
    job = Job(
        url="https://example.com/job/long",
        title="X" * 3000,
        company="Y" * 3000,
        location="Z" * 3000,
        source="indeed",
    )

    props = notion._job_to_properties(job)

    assert len(props["Job Title"]["title"][0]["text"]["content"]) == 2000
    assert len(props["Company"]["rich_text"][0]["text"]["content"]) == 2000


def test_job_to_properties_salary(notion, sample_job):
    props = notion._job_to_properties(sample_job)

    assert props["Salary Min"]["number"] == 6000000
    assert props["Salary Max"]["number"] == 9000000
    assert props["Salary Raw"]["rich_text"][0]["text"]["content"] == "6M-9M JPY"


def test_job_to_properties_dates(notion, sample_job):
    props = notion._job_to_properties(sample_job)

    assert props["Posted Date"]["date"]["start"] == "2026-03-01"
    assert props["Found Date"]["date"]["start"] == "2026-03-10"
