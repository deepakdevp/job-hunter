"""Browser session manager for per-domain storageState persistence."""
from __future__ import annotations

import json
import logging
from pathlib import Path

import tldextract

log = logging.getLogger(__name__)


class SessionManager:
    """Manages Playwright browser session state (storageState) per domain.

    Each domain gets its own JSON file under *session_dir*.
    """

    def __init__(self, session_dir: Path) -> None:
        self._dir = session_dir
        self._dir.mkdir(parents=True, exist_ok=True)

    def get_session_path(self, domain: str) -> Path:
        """Return the path for *domain*'s storageState file."""
        return self._dir / f"{domain}.json"

    def has_session(self, domain: str) -> bool:
        """Check whether a saved session exists for *domain*."""
        return self.get_session_path(domain).exists()

    def save_session(self, domain: str, state: dict) -> None:
        """Persist browser *state* for *domain* as JSON."""
        path = self.get_session_path(domain)
        path.write_text(json.dumps(state, indent=2))
        log.debug("Saved session for %s to %s", domain, path)

    def load_session(self, domain: str) -> dict | None:
        """Load a previously saved session for *domain*, or ``None``."""
        path = self.get_session_path(domain)
        if not path.exists():
            return None
        log.debug("Loading session for %s from %s", domain, path)
        return json.loads(path.read_text())

    @staticmethod
    def domain_from_url(url: str) -> str:
        """Extract the registrable domain from *url*.

        Examples::

            >>> SessionManager.domain_from_url("https://company.myworkdayjobs.com/en/jobs/1")
            'myworkdayjobs.com'
        """
        ext = tldextract.extract(url)
        return f"{ext.domain}.{ext.suffix}"
