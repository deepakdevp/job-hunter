"""LLM factory — create the right provider from config."""

from __future__ import annotations

from .base import LLMProvider


def create_llm(provider: str, model: str, gemini_key: str = "", anthropic_key: str = "") -> LLMProvider:
    """Return an LLMProvider instance based on config."""
    if provider == "gemini":
        if not gemini_key:
            raise ValueError("GEMINI_API_KEY is required when LLM_PROVIDER=gemini")
        from .gemini import GeminiProvider
        return GeminiProvider(api_key=gemini_key, model=model)
    elif provider == "claude":
        if not anthropic_key:
            raise ValueError("ANTHROPIC_API_KEY is required when LLM_PROVIDER=claude")
        from .claude import ClaudeProvider
        return ClaudeProvider(api_key=anthropic_key, model=model)
    else:
        raise ValueError(f"Unknown LLM provider: {provider!r}. Choose 'gemini' or 'claude'.")
