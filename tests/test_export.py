import csv
import json

import pytest

from job_hunter.database import JobDB, Job
from job_hunter.export import export_csv, export_json


@pytest.fixture
def db(tmp_path):
    database = JobDB(tmp_path / "test.db")
    # Seed some jobs with different statuses and scores
    jobs = [
        Job(
            url="https://a.com/1",
            title="SWE",
            company="Acme",
            location="Tokyo",
            source="indeed",
            status="scored",
            score=8,
            visa_sponsorship=True,
        ),
        Job(
            url="https://a.com/2",
            title="PM",
            company="Beta",
            location="SF",
            source="linkedin",
            status="new",
            score=3,
            visa_sponsorship=False,
        ),
        Job(
            url="https://a.com/3",
            title="DevOps",
            company="Gamma",
            location="London",
            source="indeed",
            status="tailored",
            score=6,
            visa_sponsorship=None,
        ),
        Job(
            url="https://a.com/4",
            title="Designer",
            company="Delta",
            location="Remote",
            source="glassdoor",
            status="rejected",
            score=2,
        ),  # rejected — not exported
    ]
    for j in jobs:
        database.upsert_job(j)
    yield database
    database.close()


def test_export_csv_all(db, tmp_path):
    out = tmp_path / "jobs.csv"
    count = export_csv(db, out)
    assert count == 3  # rejected status is excluded
    with open(out) as f:
        reader = list(csv.DictReader(f))
    assert len(reader) == 3
    titles = {r["title"] for r in reader}
    assert "SWE" in titles
    assert "Designer" not in titles


def test_export_csv_min_score(db, tmp_path):
    out = tmp_path / "jobs.csv"
    count = export_csv(db, out, min_score=5)
    assert count == 2  # score 8 and 6


def test_export_csv_fieldnames(db, tmp_path):
    out = tmp_path / "jobs.csv"
    export_csv(db, out)
    with open(out) as f:
        reader = csv.DictReader(f)
        assert reader.fieldnames == [
            "title",
            "company",
            "location",
            "score",
            "url",
            "status",
            "visa_sponsorship",
        ]


def test_export_json_all(db, tmp_path):
    out = tmp_path / "jobs.json"
    count = export_json(db, out)
    assert count == 3
    data = json.loads(out.read_text())
    assert len(data) == 3
    assert all("title" in item for item in data)


def test_export_json_min_score(db, tmp_path):
    out = tmp_path / "jobs.json"
    count = export_json(db, out, min_score=7)
    assert count == 1
    data = json.loads(out.read_text())
    assert data[0]["title"] == "SWE"
    assert data[0]["score"] == 8


def test_export_empty_db(tmp_path):
    db = JobDB(tmp_path / "empty.db")

    csv_out = tmp_path / "empty.csv"
    assert export_csv(db, csv_out) == 0
    with open(csv_out) as f:
        reader = list(csv.DictReader(f))
    assert reader == []

    json_out = tmp_path / "empty.json"
    assert export_json(db, json_out) == 0
    assert json.loads(json_out.read_text()) == []

    db.close()


def test_export_json_pretty_printed(db, tmp_path):
    out = tmp_path / "jobs.json"
    export_json(db, out)
    raw = out.read_text()
    # indent=2 means there should be newlines and spaces
    assert "\n" in raw
    assert "  " in raw
