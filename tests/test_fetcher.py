import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from job_hunter.enrich.fetcher import fetch_page, _is_js_heavy


def test_is_js_heavy():
    assert _is_js_heavy("https://jobs.lever.co/company/123") is True
    assert _is_js_heavy("https://boards.greenhouse.io/company/jobs/456") is True
    assert _is_js_heavy("https://jobs.ashby.io/company") is True
    assert _is_js_heavy("https://example.com/jobs/123") is False
    assert _is_js_heavy("https://tokyodev.com/jobs/456") is False


@pytest.mark.asyncio
async def test_fetch_page_static():
    with patch("job_hunter.enrich.fetcher._fetch_static", new_callable=AsyncMock) as mock:
        mock.return_value = "<html><body>" + "x" * 6000 + "</body></html>"
        result = await fetch_page("https://example.com/jobs/1")
        assert result is not None
        assert len(result) > 5000


@pytest.mark.asyncio
async def test_fetch_page_js_heavy_triggers_playwright():
    with patch("job_hunter.enrich.fetcher._fetch_static", new_callable=AsyncMock) as mock_static, \
         patch("job_hunter.enrich.fetcher._fetch_with_playwright", new_callable=AsyncMock) as mock_pw:
        # Static returns short content for JS-heavy domain
        mock_static.return_value = "<html><body>Loading...</body></html>"
        mock_pw.return_value = "<html><body>" + "Full content " * 500 + "</body></html>"

        result = await fetch_page("https://jobs.lever.co/company/123")
        mock_pw.assert_called_once()
        assert "Full content" in result


@pytest.mark.asyncio
async def test_fetch_page_static_none():
    with patch("job_hunter.enrich.fetcher._fetch_static", new_callable=AsyncMock) as mock:
        mock.return_value = None
        result = await fetch_page("https://example.com/jobs/1")
        assert result is None
