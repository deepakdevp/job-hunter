"""Gemini provider — default free-tier LLM."""

from __future__ import annotations

import google.generativeai as genai

from .base import LLMProvider


class GeminiProvider(LLMProvider):
    """Google Gemini via google-generativeai SDK."""

    def __init__(self, api_key: str, model: str = "gemini-2.0-flash"):
        genai.configure(api_key=api_key)
        self.model_name = model
        self._model = genai.GenerativeModel(model)

    def complete(self, prompt: str, system: str = "", temperature: float = 0.3) -> str:
        full_prompt = f"{system}\n\n{prompt}" if system else prompt
        response = self._model.generate_content(
            full_prompt,
            generation_config=genai.GenerationConfig(temperature=temperature),
        )
        return response.text.strip()
