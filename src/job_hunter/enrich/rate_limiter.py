from __future__ import annotations

import asyncio
import time
from collections import defaultdict
from urllib.parse import urlparse


class DomainRateLimiter:
    """Per-domain rate limiter with global concurrency cap.

    - Max `per_domain` concurrent requests to the same domain
    - Max `global_limit` concurrent requests total
    - Tracks request timestamps for rate limiting (max `max_per_minute` per domain per minute)
    - Exponential backoff on 429 responses
    """

    def __init__(
        self,
        per_domain: int = 5,
        global_limit: int = 20,
        max_per_minute: int = 5,
    ):
        self.per_domain = per_domain
        self.max_per_minute = max_per_minute
        self._global_semaphore = asyncio.Semaphore(global_limit)
        self._domain_semaphores: dict[str, asyncio.Semaphore] = defaultdict(
            lambda: asyncio.Semaphore(per_domain)
        )
        self._domain_timestamps: dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    @staticmethod
    def extract_domain(url: str) -> str:
        parsed = urlparse(url)
        return parsed.netloc or parsed.hostname or "unknown"

    async def acquire(self, url: str):
        """Acquire rate limit slot for a URL's domain."""
        domain = self.extract_domain(url)

        await self._global_semaphore.acquire()

        await self._domain_semaphores[domain].acquire()

        # Enforce per-minute rate limit
        async with self._lock:
            now = time.monotonic()
            timestamps = self._domain_timestamps[domain]
            # Remove timestamps older than 60s
            self._domain_timestamps[domain] = [t for t in timestamps if now - t < 60]
            timestamps = self._domain_timestamps[domain]

            if len(timestamps) >= self.max_per_minute:
                # Wait until the oldest timestamp expires
                wait_time = 60 - (now - timestamps[0])
                if wait_time > 0:
                    await asyncio.sleep(wait_time)
                self._domain_timestamps[domain] = self._domain_timestamps[domain][1:]

            self._domain_timestamps[domain].append(time.monotonic())

    def release(self, url: str):
        """Release rate limit slot."""
        domain = self.extract_domain(url)
        self._domain_semaphores[domain].release()
        self._global_semaphore.release()

    async def backoff_429(self, url: str, attempt: int):
        """Exponential backoff for 429 responses."""
        delay = min(2 ** (attempt + 1), 60)
        await asyncio.sleep(delay)
