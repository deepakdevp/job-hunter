import pytest
from pathlib import Path


@pytest.fixture
def fixtures_dir():
    return Path(__file__).parent / "fixtures"


@pytest.fixture
def sample_profile():
    return {
        "name": "Test User",
        "email": "test@example.com",
        "phone": "+1-555-0100",
        "location": "Tokyo, Japan",
        "target_role": "Software Engineer",
        "skills": ["Python", "TypeScript", "React"],
        "resume_facts": {
            "companies": [
                {
                    "name": "Acme Corp",
                    "title": "Senior Engineer",
                    "dates": "2022-2025",
                    "bullets": ["Built distributed systems", "Led team of 5"],
                }
            ],
            "education": [
                {"school": "MIT", "degree": "BS Computer Science", "year": 2022}
            ],
            "metrics": ["Reduced API latency by 40%", "Led team of 5 engineers"],
            "certifications": [],
        },
    }
