from __future__ import annotations

import asyncio
import logging

from google import genai

from job_hunter.llm.base import LLMProvider

logger = logging.getLogger(__name__)


class GeminiProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "gemini-2.5-flash"):
        self.client = genai.Client(api_key=api_key)
        self.model = model
        self._retry_delays = [10, 20, 40, 60, 60]

    async def generate(
        self, prompt: str, *, json_mode: bool = False, max_tokens: int = 4096
    ) -> str:
        config = {"max_output_tokens": max_tokens}
        if json_mode:
            config["response_mime_type"] = "application/json"

        last_error = None
        for attempt, delay in enumerate(self._retry_delays):
            try:
                response = self.client.models.generate_content(
                    model=self.model,
                    contents=prompt,
                    config=config,
                )
                return response.text
            except Exception as e:
                last_error = e
                if "429" in str(e) or "ResourceExhausted" in type(e).__name__:
                    logger.warning(f"Rate limited (attempt {attempt + 1}), waiting {delay}s")
                    await asyncio.sleep(delay)
                    continue
                raise

        raise RuntimeError(f"Failed after {len(self._retry_delays)} retries: {last_error}")
