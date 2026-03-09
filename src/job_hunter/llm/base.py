from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    @abstractmethod
    async def generate(
        self, prompt: str, *, json_mode: bool = False, max_tokens: int = 4096
    ) -> str: ...


def get_provider(provider_name: str, *, api_key: str, model: str) -> LLMProvider:
    if provider_name == "gemini":
        from job_hunter.llm.gemini import GeminiProvider

        return GeminiProvider(api_key=api_key, model=model)
    elif provider_name == "claude":
        from job_hunter.llm.claude import ClaudeProvider

        return ClaudeProvider(api_key=api_key, model=model)
    else:
        raise ValueError(f"Unknown LLM provider: {provider_name}")
