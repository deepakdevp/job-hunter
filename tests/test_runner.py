import pytest
from unittest.mock import AsyncMock, patch
from job_hunter.database import Job, JobDB
from job_hunter.enrich.runner import enrich_job, run_enrichment, _apply_enrichment
from job_hunter.enrich.detail import EnrichResult


@pytest.mark.asyncio
async def test_enrich_job_tier1_success():
    html = """
    <html><head>
    <script type="application/ld+json">
    {"@type": "JobPosting", "description": "<p>Python engineer needed with Django and AWS experience.</p>"}
    </script>
    </head><body></body></html>
    """
    with patch("job_hunter.enrich.runner.fetch_page", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = html
        result = await enrich_job("https://example.com/job/1")
        assert result is not None
        assert result.tier == "json-ld"
        assert "Python engineer" in result.description


@pytest.mark.asyncio
async def test_enrich_job_falls_through_to_css():
    html = """
    <html><body>
    <div id="job-description">
        <p>We need a React developer with TypeScript and Node.js experience.
        This is a full-time hybrid role with health insurance.</p>
    </div>
    </body></html>
    """
    with patch("job_hunter.enrich.runner.fetch_page", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = html
        result = await enrich_job("https://example.com/job/2")
        assert result is not None
        assert result.tier == "css"


@pytest.mark.asyncio
async def test_enrich_job_raw_fallback():
    html = (
        "<html><body><p>Some random unstructured content that is long enough to pass the raw text extraction. "
        + "x" * 200
        + "</p></body></html>"
    )
    with patch("job_hunter.enrich.runner.fetch_page", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = html
        result = await enrich_job("https://example.com/job/3")
        assert result is not None
        assert result.tier == "raw"
        assert result.enrichment_raw is True


@pytest.mark.asyncio
async def test_enrich_job_returns_none_on_fetch_failure():
    with patch("job_hunter.enrich.runner.fetch_page", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = None
        result = await enrich_job("https://example.com/job/4")
        assert result is None


def test_apply_enrichment():
    job = Job(
        url="https://example.com/1", title="SWE", company="A", location="Tokyo", source="indeed"
    )
    result = EnrichResult(
        description="Full description here",
        apply_url="https://apply.example.com",
        tier="css",
        visa_sponsorship=True,
        remote_policy="hybrid",
        tech_stack=["Python", "React"],
        seniority="senior",
        contract_type="full-time",
        team_size="team of 10",
        benefits="health insurance, equity",
    )
    updated = _apply_enrichment(job, result)
    assert updated.description == "Full description here"
    assert updated.apply_url == "https://apply.example.com"
    assert updated.enrich_tier == "css"
    assert updated.visa_sponsorship is True
    assert updated.tech_stack == "Python, React"
    assert updated.seniority == "senior"
    assert updated.status == "enriched"


@pytest.mark.asyncio
async def test_run_enrichment(tmp_path):
    db = JobDB(tmp_path / "test.db")
    db.upsert_job(
        Job(
            url="https://example.com/1",
            title="SWE",
            company="A",
            location="Tokyo",
            source="indeed",
            description=None,
        )
    )
    db.upsert_job(
        Job(
            url="https://example.com/2",
            title="FE",
            company="B",
            location="Osaka",
            source="indeed",
            description=None,
        )
    )

    html = """
    <html><head>
    <script type="application/ld+json">
    {"@type": "JobPosting", "description": "<p>A great job with Python and Docker in a remote team.</p>"}
    </script>
    </head><body></body></html>
    """

    with patch("job_hunter.enrich.runner.fetch_page", new_callable=AsyncMock) as mock_fetch:
        mock_fetch.return_value = html
        enriched, total = await run_enrichment(db, limit=10)

    assert total == 2
    assert enriched == 2
    job = db.get_job("https://example.com/1")
    assert job.description is not None
    assert job.enrich_tier == "json-ld"
    assert job.status == "enriched"
    db.close()
