import json
import pytest
from unittest.mock import AsyncMock
from job_hunter.enrich.detail import (
    extract_from_json_ld,
    extract_description_css,
    extract_with_llm,
    extract_raw_text,
    parse_structured_fields,
)


# --- Tier 1: JSON-LD ---


def test_extract_from_json_ld():
    html = """
    <html><head>
    <script type="application/ld+json">
    {"@type": "JobPosting", "title": "Senior Python Developer",
     "description": "<p>We need a Python developer with 5+ years. Visa sponsorship available. Fully remote position. Health insurance and equity provided.</p>",
     "url": "https://example.com/apply", "directApply": true}
    </script>
    </head><body></body></html>
    """
    result = extract_from_json_ld(html)
    assert result is not None
    assert "Python developer" in result.description
    assert result.tier == "json-ld"
    assert result.apply_url == "https://example.com/apply"
    assert result.visa_sponsorship is True
    assert result.remote_policy == "remote"


def test_extract_from_json_ld_graph():
    html = """
    <html><head>
    <script type="application/ld+json">
    {"@graph": [{"@type": "Organization"}, {"@type": "JobPosting",
     "description": "React engineer needed. On-site in Tokyo."}]}
    </script>
    </head><body></body></html>
    """
    result = extract_from_json_ld(html)
    assert result is not None
    assert "React engineer" in result.description
    assert result.remote_policy == "onsite"


def test_extract_from_json_ld_returns_none_for_no_job():
    html = "<html><head></head><body>No jobs here</body></html>"
    result = extract_from_json_ld(html)
    assert result is None


def test_extract_from_json_ld_no_visa():
    html = """
    <html><head>
    <script type="application/ld+json">
    {"@type": "JobPosting",
     "description": "<p>Software engineer role. Cannot sponsor visa. Must be authorized to work.</p>"}
    </script>
    </head><body></body></html>
    """
    result = extract_from_json_ld(html)
    assert result is not None
    assert result.visa_sponsorship is False


# --- Tier 2: CSS Selectors ---


def test_extract_description_css():
    html = """
    <html><body>
    <h1>Senior Backend Engineer</h1>
    <div id="job-description">
        <p>Looking for a senior engineer with 5+ years experience.
        Must know Python, Django, PostgreSQL, and Docker.
        This is a full-time hybrid role. Team of 8 engineers.</p>
    </div>
    </body></html>
    """
    result = extract_description_css(html)
    assert result is not None
    assert "senior engineer" in result.description
    assert result.tier == "css"
    assert result.seniority == "senior"
    assert "Python" in result.tech_stack
    assert "Django" in result.tech_stack
    assert result.contract_type == "full-time"
    assert result.remote_policy == "hybrid"


def test_extract_description_css_fallback_selectors():
    html = """
    <html><body>
    <div class="job-description">
        <p>Machine learning engineer role. Experience with PyTorch and TensorFlow required.
        We offer health insurance, equity, and flexible hours. Junior to mid level.</p>
    </div>
    </body></html>
    """
    result = extract_description_css(html)
    assert result is not None
    assert "Machine learning" in result.description
    assert "PyTorch" in result.tech_stack
    assert result.benefits is not None
    assert "health insurance" in result.benefits


def test_extract_description_css_with_apply_link():
    html = """
    <html><body>
    <div id="job-description">
        <p>Great role for a developer with React and TypeScript skills.
        This position is fully remote with stock options and PTO.</p>
    </div>
    <a href="https://apply.example.com/job/123">Apply Now</a>
    </body></html>
    """
    result = extract_description_css(html)
    assert result is not None
    assert result.apply_url == "https://apply.example.com/job/123"
    assert result.remote_policy == "remote"


def test_extract_description_css_returns_none_for_short_content():
    html = '<html><body><div id="job-description"><p>Short</p></div></body></html>'
    result = extract_description_css(html)
    assert result is None


# --- Raw text fallback ---


def test_extract_raw_text():
    html = """
    <html>
    <head><style>body{color:red}</style></head>
    <body>
    <nav>Menu stuff</nav>
    <h1>Software Engineer</h1>
    <p>We are looking for a software engineer. Must know Python and AWS.
    Visa sponsorship is available for qualified candidates. This is a contract role.
    Benefits include health insurance and paid time off.</p>
    <footer>Footer content</footer>
    </body></html>
    """
    result = extract_raw_text(html)
    assert result.enrichment_raw is True
    assert result.tier == "raw"
    assert "software engineer" in result.description.lower()
    # Nav/footer/style should be stripped
    assert "Menu stuff" not in result.description
    assert "Footer content" not in result.description
    assert result.visa_sponsorship is True
    assert result.contract_type == "contract"


# --- Structured field parsing ---


def test_parse_structured_fields_tech_stack():
    fields = parse_structured_fields("We use Python, React, PostgreSQL, and Docker in our stack.")
    assert "Python" in fields["tech_stack"]
    assert "React" in fields["tech_stack"]
    assert "PostgreSQL" in fields["tech_stack"]
    assert "Docker" in fields["tech_stack"]


def test_parse_structured_fields_no_duplicates():
    fields = parse_structured_fields("Python Python Python React React")
    python_count = sum(1 for t in fields["tech_stack"] if t.lower() == "python")
    assert python_count == 1


def test_parse_structured_fields_seniority_from_title():
    fields = parse_structured_fields(
        "Some description without seniority keywords.", title="Lead Software Engineer"
    )
    assert fields["seniority"] == "lead"


def test_parse_structured_fields_team_size():
    fields = parse_structured_fields("Join our team of 12 engineers building the next big thing.")
    assert fields["team_size"] is not None
    assert "12" in fields["team_size"]


# --- Tier 3: LLM extraction ---


@pytest.mark.asyncio
async def test_extract_with_llm():
    html = """
    <html><body>
    <nav>Navigation</nav>
    <p>We are hiring a Senior Python Engineer. Must know Django, PostgreSQL, Docker.
    Full-time remote position. Visa sponsorship available. Team of 6 engineers.
    Benefits: health insurance, equity, PTO.</p>
    <footer>Footer</footer>
    </body></html>
    """
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = json.dumps(
        {
            "full_description": "We are hiring a Senior Python Engineer. Must know Django, PostgreSQL, Docker. Full-time remote position. Visa sponsorship available. Team of 6 engineers. Benefits: health insurance, equity, PTO.",
            "application_url": "https://example.com/apply",
            "visa_sponsorship": True,
            "remote_policy": "remote",
            "tech_stack": ["Python", "Django", "PostgreSQL", "Docker"],
            "seniority": "senior",
            "contract_type": "full-time",
            "team_size": "6 engineers",
            "benefits": "health insurance, equity, PTO",
        }
    )

    result = await extract_with_llm(html, mock_llm)
    assert result is not None
    assert result.tier == "ai"
    assert result.visa_sponsorship is True
    assert result.remote_policy == "remote"
    assert "Python" in result.tech_stack
    assert result.seniority == "senior"
    assert result.apply_url == "https://example.com/apply"
    mock_llm.generate.assert_called_once()


@pytest.mark.asyncio
async def test_extract_with_llm_returns_none_on_bad_json():
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = "not valid json"
    result = await extract_with_llm("<html><body>content</body></html>", mock_llm)
    assert result is None


@pytest.mark.asyncio
async def test_extract_with_llm_returns_none_on_short_description():
    mock_llm = AsyncMock()
    mock_llm.generate.return_value = json.dumps({"full_description": "Short"})
    result = await extract_with_llm("<html><body>content</body></html>", mock_llm)
    assert result is None


def test_parse_structured_fields_empty_text():
    fields = parse_structured_fields("")
    assert fields["visa_sponsorship"] is None
    assert fields["remote_policy"] is None
    assert fields["seniority"] is None
    assert fields["contract_type"] is None
    assert fields["tech_stack"] == []
    assert fields["team_size"] is None
    assert fields["benefits"] is None
