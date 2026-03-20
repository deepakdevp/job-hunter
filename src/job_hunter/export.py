from __future__ import annotations

import csv
import json
from pathlib import Path

from job_hunter.database import JobDB


def export_csv(db: JobDB, output: Path, min_score: int = 0) -> int:
    """Export jobs to a CSV file. Returns number of jobs exported."""
    jobs = []
    for status in ("new", "enriched", "scored", "tailored", "synced", "applied"):
        for j in db.get_jobs_by_status(status):
            if (j.score or 0) >= min_score:
                jobs.append(j)

    with open(output, "w", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "title",
                "company",
                "location",
                "score",
                "url",
                "status",
                "visa_sponsorship",
            ],
        )
        writer.writeheader()
        for j in jobs:
            writer.writerow(
                {
                    "title": j.title,
                    "company": j.company,
                    "location": j.location,
                    "score": j.score,
                    "url": j.url,
                    "status": j.status,
                    "visa_sponsorship": j.visa_sponsorship,
                }
            )
    return len(jobs)


def export_json(db: JobDB, output: Path, min_score: int = 0) -> int:
    """Export jobs to a JSON file. Returns number of jobs exported."""
    jobs = []
    for status in ("new", "enriched", "scored", "tailored", "synced", "applied"):
        for j in db.get_jobs_by_status(status):
            if (j.score or 0) >= min_score:
                jobs.append(j)

    data = [
        {
            "title": j.title,
            "company": j.company,
            "location": j.location,
            "score": j.score,
            "url": j.url,
            "status": j.status,
            "visa_sponsorship": j.visa_sponsorship,
        }
        for j in jobs
    ]
    output.write_text(json.dumps(data, indent=2))
    return len(data)
