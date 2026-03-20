from __future__ import annotations

import json
import logging
import re
from dataclasses import dataclass, field

from bs4 import BeautifulSoup

logger = logging.getLogger(__name__)

DESCRIPTION_SELECTORS = [
    "#job-description",
    "[data-testid='job-description']",
    ".job-description",
    ".jobsearch-JobComponent-description",
    ".ashby-job-posting-description",
    ".job-details",
    "[class*='job-description']",
    "[class*='jobDescription']",
    ".description__text",
    ".posting-requirements",
    "[role='main'] article",
    ".job__description",
    ".job-posting-content",
    "#jobDescriptionText",
    ".jobs-description",
    ".job_description",
    "[data-automation='jobDescription']",
    ".content-section",
    "article.job-posting",
    "main .content",
]

APPLY_SELECTORS = [
    "a[href*='apply']",
    "a.apply-button",
    "a.ashby-job-posting-apply-button",
    "#grnhse_app a[href*='apply']",
    "a[data-testid='apply-button']",
    "a[class*='apply']",
    "button[class*='apply']",
    "a[href*='lever.co']",
    "a[href*='greenhouse.io']",
    "a[href*='workday']",
    "a[href*='smartrecruiters']",
    "a[href*='icims']",
    "a[href*='taleo']",
]

# Patterns for structured field extraction from description text
_VISA_PATTERNS = [
    re.compile(r"visa\s+sponsor", re.IGNORECASE),
    re.compile(r"sponsor.*visa", re.IGNORECASE),
    re.compile(r"work\s+permit\s+(assist|support|sponsor)", re.IGNORECASE),
    re.compile(r"immigration\s+support", re.IGNORECASE),
    re.compile(r"relocation\s+(support|assist|package)", re.IGNORECASE),
]

_NO_VISA_PATTERNS = [
    re.compile(r"no\s+visa\s+sponsor", re.IGNORECASE),
    re.compile(r"cannot\s+sponsor", re.IGNORECASE),
    re.compile(r"will\s+not\s+sponsor", re.IGNORECASE),
    re.compile(r"must\s+(be|have)\s+(authorized|eligible|right)", re.IGNORECASE),
]

_REMOTE_PATTERNS = {
    "remote": re.compile(
        r"\b(fully\s+remote|100%\s+remote|remote\s+only|remote\s+position|remote\s+work)\b",
        re.IGNORECASE,
    ),
    "hybrid": re.compile(
        r"\b(hybrid|flexible\s+work|partially\s+remote|remote.*office|office.*remote)\b",
        re.IGNORECASE,
    ),
    "onsite": re.compile(
        r"\b(on[\s-]?site|in[\s-]?office|office[\s-]?based|in[\s-]?person)\b", re.IGNORECASE
    ),
}

_SENIORITY_PATTERNS = {
    "intern": re.compile(r"\b(intern|internship)\b", re.IGNORECASE),
    "junior": re.compile(r"\b(junior|entry[\s-]?level|new\s+grad|associate)\b", re.IGNORECASE),
    "mid": re.compile(r"\b(mid[\s-]?level|intermediate|mid[\s-]?senior)\b", re.IGNORECASE),
    "senior": re.compile(r"\b(senior|sr\.?|experienced)\b", re.IGNORECASE),
    "lead": re.compile(r"\b(lead|principal|staff)\b", re.IGNORECASE),
    "manager": re.compile(r"\b(manager|director|head\s+of|vp\b|vice\s+president)\b", re.IGNORECASE),
}

_CONTRACT_PATTERNS = {
    "full-time": re.compile(r"\b(full[\s-]?time|permanent|FTE)\b", re.IGNORECASE),
    "contract": re.compile(r"\b(contract|freelance|consulting|temporary)\b", re.IGNORECASE),
    "part-time": re.compile(r"\b(part[\s-]?time)\b", re.IGNORECASE),
    "internship": re.compile(r"\b(internship|intern\b)", re.IGNORECASE),
}

_TECH_KEYWORDS = [
    "Python",
    "JavaScript",
    "TypeScript",
    "Java",
    "Go",
    "Rust",
    "C\\+\\+",
    "C#",
    "Ruby",
    "PHP",
    "Swift",
    "Kotlin",
    "React",
    "Vue",
    "Angular",
    "Next\\.js",
    "Node\\.js",
    "Django",
    "Flask",
    "FastAPI",
    "Spring",
    "Rails",
    "AWS",
    "GCP",
    "Azure",
    "Docker",
    "Kubernetes",
    "Terraform",
    "PostgreSQL",
    "MySQL",
    "MongoDB",
    "Redis",
    "Elasticsearch",
    "GraphQL",
    "REST",
    "gRPC",
    "TensorFlow",
    "PyTorch",
    "LangChain",
    "OpenAI",
    "Git",
    "CI/CD",
    "Jenkins",
    "GitHub Actions",
    "Linux",
    "Nginx",
    "Apache",
]

_TECH_PATTERN = re.compile(
    r"\b(" + "|".join(_TECH_KEYWORDS) + r")\b",
    re.IGNORECASE,
)


@dataclass
class EnrichResult:
    description: str
    apply_url: str | None = None
    tier: str = "unknown"
    visa_sponsorship: bool | None = None
    remote_policy: str | None = None
    tech_stack: list[str] = field(default_factory=list)
    seniority: str | None = None
    contract_type: str | None = None
    team_size: str | None = None
    benefits: str | None = None
    enrichment_raw: bool = False


def parse_structured_fields(text: str, title: str = "") -> dict:
    """Extract structured fields from description + title text."""
    combined = f"{title}\n{text}"
    result: dict = {}

    # Visa sponsorship
    no_visa = any(p.search(combined) for p in _NO_VISA_PATTERNS)
    has_visa = any(p.search(combined) for p in _VISA_PATTERNS)
    if no_visa:
        result["visa_sponsorship"] = False
    elif has_visa:
        result["visa_sponsorship"] = True
    else:
        result["visa_sponsorship"] = None

    # Remote policy
    result["remote_policy"] = None
    for policy, pattern in _REMOTE_PATTERNS.items():
        if pattern.search(combined):
            result["remote_policy"] = policy
            break

    # Seniority (check title first, then description)
    result["seniority"] = None
    for level, pattern in _SENIORITY_PATTERNS.items():
        if pattern.search(title):
            result["seniority"] = level
            break
    if not result["seniority"]:
        for level, pattern in _SENIORITY_PATTERNS.items():
            if pattern.search(text):
                result["seniority"] = level
                break

    # Contract type
    result["contract_type"] = None
    for ctype, pattern in _CONTRACT_PATTERNS.items():
        if pattern.search(combined):
            result["contract_type"] = ctype
            break

    # Tech stack
    matches = _TECH_PATTERN.findall(combined)
    seen = set()
    tech_stack = []
    for m in matches:
        normalized = m.strip()
        if normalized.lower() not in seen:
            seen.add(normalized.lower())
            tech_stack.append(normalized)
    result["tech_stack"] = tech_stack

    # Team size
    team_match = re.search(
        r"team\s+(?:of\s+)?(\d+[\s\-to]+\d+|\d+\+?)\s*(people|engineers|developers|members)?",
        combined,
        re.IGNORECASE,
    )
    result["team_size"] = team_match.group(0).strip() if team_match else None

    # Benefits (simple keyword extraction)
    benefit_keywords = [
        "health insurance",
        "dental",
        "vision",
        "401k",
        "pension",
        "stock options",
        "equity",
        "RSU",
        "bonus",
        "PTO",
        "paid time off",
        "vacation",
        "parental leave",
        "remote work",
        "flexible hours",
        "gym",
        "education budget",
        "learning budget",
        "conference",
        "relocation",
        "commuter",
        "lunch",
        "snacks",
        "child care",
    ]
    found_benefits = []
    for kw in benefit_keywords:
        if re.search(re.escape(kw), combined, re.IGNORECASE):
            found_benefits.append(kw)
    result["benefits"] = ", ".join(found_benefits) if found_benefits else None

    return result


def extract_from_json_ld(html: str) -> EnrichResult | None:
    """Tier 1: Extract job posting from JSON-LD structured data."""
    soup = BeautifulSoup(html, "html.parser")
    scripts = soup.find_all("script", type="application/ld+json")

    for script in scripts:
        try:
            data = json.loads(script.string or "")
        except (json.JSONDecodeError, TypeError):
            continue

        posting = _find_job_posting(data)
        if posting and posting.get("description"):
            desc_html = posting["description"]
            description = BeautifulSoup(desc_html, "html.parser").get_text(
                separator="\n", strip=True
            )
            apply_url = None
            if posting.get("url"):
                apply_url = posting["url"]
            elif isinstance(posting.get("applicationContact"), dict):
                apply_url = posting["applicationContact"].get("url")

            title = posting.get("title", "")
            fields = parse_structured_fields(description, title)

            return EnrichResult(
                description=description,
                apply_url=apply_url,
                tier="json-ld",
                **fields,
            )

    return None


def _find_job_posting(data) -> dict | None:
    """Recursively find JobPosting in JSON-LD data."""
    if isinstance(data, dict):
        if data.get("@type") == "JobPosting":
            return data
        if "@graph" in data:
            for item in data["@graph"]:
                result = _find_job_posting(item)
                if result:
                    return result
    elif isinstance(data, list):
        for item in data:
            result = _find_job_posting(item)
            if result:
                return result
    return None


def extract_description_css(html: str) -> EnrichResult | None:
    """Tier 2: Extract job description using CSS selectors."""
    soup = BeautifulSoup(html, "html.parser")
    description = None
    apply_url = None

    for selector in DESCRIPTION_SELECTORS:
        try:
            el = soup.select_one(selector)
        except Exception:
            continue
        if el:
            text = el.get_text(separator="\n", strip=True)
            if len(text) > 100:
                description = text
                break

    for selector in APPLY_SELECTORS:
        try:
            el = soup.select_one(selector)
        except Exception:
            continue
        if el and el.get("href"):
            apply_url = el["href"]
            break

    if not apply_url:
        for a in soup.find_all("a", href=True):
            if re.search(r"apply", a.get_text(), re.IGNORECASE):
                apply_url = a["href"]
                break

    if description:
        # Extract title from page
        title_el = soup.find("h1")
        title = title_el.get_text(strip=True) if title_el else ""
        fields = parse_structured_fields(description, title)
        return EnrichResult(description=description, apply_url=apply_url, tier="css", **fields)
    return None


_LLM_EXTRACTION_PROMPT = """Extract job details from this page content. Return JSON only with these fields:
{{
  "full_description": "the complete job description text",
  "application_url": "direct apply URL or null",
  "visa_sponsorship": true/false/null,
  "remote_policy": "remote"/"hybrid"/"onsite"/null,
  "tech_stack": ["Python", "React", ...] or [],
  "seniority": "junior"/"mid"/"senior"/"lead"/"staff"/null,
  "contract_type": "full-time"/"contract"/"part-time"/"internship"/null,
  "team_size": "text if mentioned" or null,
  "benefits": "comma-separated benefits" or null
}}

Page content:
{text}"""


async def extract_with_llm(html: str, llm) -> EnrichResult | None:
    """Tier 3: Use LLM to extract structured job data from messy HTML."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["nav", "header", "footer", "script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)[:30000]

    prompt = _LLM_EXTRACTION_PROMPT.format(text=text)

    try:
        response = await llm.generate(prompt, json_mode=True)
        data = json.loads(response)
        desc = data.get("full_description", "")
        if not desc or len(desc) < 50:
            return None

        tech = data.get("tech_stack", [])
        if isinstance(tech, str):
            tech = [t.strip() for t in tech.split(",") if t.strip()]

        return EnrichResult(
            description=desc,
            apply_url=data.get("application_url"),
            tier="ai",
            visa_sponsorship=data.get("visa_sponsorship"),
            remote_policy=data.get("remote_policy"),
            tech_stack=tech,
            seniority=data.get("seniority"),
            contract_type=data.get("contract_type"),
            team_size=data.get("team_size"),
            benefits=data.get("benefits"),
        )
    except (json.JSONDecodeError, Exception) as e:
        logger.warning(f"LLM extraction failed: {e}")

    return None


def extract_raw_text(html: str) -> EnrichResult:
    """Tier 4 fallback: Strip HTML and return raw text, flagged as low quality."""
    soup = BeautifulSoup(html, "html.parser")
    for tag in soup.find_all(["nav", "header", "footer", "script", "style"]):
        tag.decompose()
    text = soup.get_text(separator="\n", strip=True)
    # Truncate to reasonable size
    text = text[:10000] if len(text) > 10000 else text

    title_el = soup.find("h1")
    title = title_el.get_text(strip=True) if title_el else ""
    fields = parse_structured_fields(text, title)

    return EnrichResult(
        description=text,
        tier="raw",
        enrichment_raw=True,
        **fields,
    )
