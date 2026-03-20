from __future__ import annotations

import os

import httpx

from job_hunter.llm.base import LLMProvider


class OllamaProvider(LLMProvider):
    def __init__(self, *, model: str = "llama3.1", host: str | None = None, **_: object):
        self._model = model
        self._host = (host or os.environ.get("OLLAMA_HOST", "http://localhost:11434")).rstrip("/")

    async def generate(
        self, prompt: str, *, json_mode: bool = False, max_tokens: int = 4096
    ) -> str:
        payload: dict = {
            "model": self._model,
            "prompt": prompt,
            "stream": False,
            "options": {"num_predict": max_tokens},
        }
        if json_mode:
            payload["format"] = "json"
        async with httpx.AsyncClient(timeout=120) as client:
            resp = await client.post(f"{self._host}/api/generate", json=payload)
            resp.raise_for_status()
            return resp.json().get("response", "")
