"""Claude provider — premium optional LLM for high-quality prose."""

from __future__ import annotations

import anthropic

from .base import LLMProvider


class ClaudeProvider(LLMProvider):
    """Anthropic Claude via the official SDK."""

    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    def complete(self, prompt: str, system: str = "", temperature: float = 0.3) -> str:
        kwargs = {
            "model": self.model,
            "max_tokens": 4096,
            "temperature": temperature,
            "messages": [{"role": "user", "content": prompt}],
        }
        if system:
            kwargs["system"] = system

        message = self.client.messages.create(**kwargs)
        return message.content[0].text.strip()
