"""URL-based deduplication for discovered jobs."""

from __future__ import annotations

import hashlib
import re
from pathlib import Path
from urllib.parse import urlparse, urlunparse, parse_qs, urlencode


def normalize_url(url: str) -> str:
    """Normalize a job URL for consistent deduplication."""
    if not url:
        return ""
    try:
        parsed = urlparse(url)
        # Drop tracking params common in job boards
        TRACKING_PARAMS = {"utm_source", "utm_medium", "utm_campaign", "trk", "ref", "refid", "trackingId"}
        params = {k: v for k, v in parse_qs(parsed.query).items() if k not in TRACKING_PARAMS}
        clean = parsed._replace(
            scheme=parsed.scheme.lower(),
            netloc=parsed.netloc.lower(),
            query=urlencode(params, doseq=True),
            fragment="",
        )
        return urlunparse(clean)
    except Exception:
        return url


def url_hash(url: str) -> str:
    return hashlib.sha256(normalize_url(url).encode()).hexdigest()[:16]


class SeenSet:
    """Persistent set of seen job URLs backed by a plain text file."""

    def __init__(self, path: Path):
        self.path = path
        self._hashes: set[str] = set()
        if path.exists():
            self._hashes = set(path.read_text().splitlines())

    def is_seen(self, url: str) -> bool:
        return url_hash(url) in self._hashes

    def mark_seen(self, url: str) -> None:
        h = url_hash(url)
        if h not in self._hashes:
            self._hashes.add(h)
            with self.path.open("a") as f:
                f.write(h + "\n")

    def dedup(self, jobs: list[dict]) -> list[dict]:
        """Return only jobs not seen before, and mark them as seen."""
        new_jobs = []
        for job in jobs:
            url = job.get("job_url", "")
            if not self.is_seen(url):
                new_jobs.append(job)
                self.mark_seen(url)
        return new_jobs
