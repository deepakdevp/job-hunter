from __future__ import annotations

import anthropic

from job_hunter.llm.base import LLMProvider


class ClaudeProvider(LLMProvider):
    def __init__(self, api_key: str, model: str = "claude-sonnet-4-6"):
        self.client = anthropic.Anthropic(api_key=api_key)
        self.model = model

    async def generate(
        self, prompt: str, *, json_mode: bool = False, max_tokens: int = 4096
    ) -> str:
        system = ""
        if json_mode:
            system = "Respond with valid JSON only. No markdown, no explanation."

        message = self.client.messages.create(
            model=self.model,
            max_tokens=max_tokens,
            system=system if system else anthropic.NOT_GIVEN,
            messages=[{"role": "user", "content": prompt}],
        )
        return message.content[0].text
