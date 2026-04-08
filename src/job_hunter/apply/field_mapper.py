"""LLM-powered field mapper for unknown form fields."""

from __future__ import annotations

import json
import logging
from dataclasses import dataclass

logger = logging.getLogger(__name__)

CONFIDENCE_THRESHOLD = 0.7

_FIELD_MAPPER_PROMPT = """\
You are a job application assistant. Given the candidate profile below, answer the form field question as accurately as possible.

Use the "I'm Choosing You" tone: confident without arrogance, proof-first.

## Candidate Profile
- Name: {name}
- Target Role: {target_role}
- Skills: {skills}
- Work Authorization: {work_authorization}
- Current Role: {current_title} at {current_company}

## Evaluation Context (if available)
{evaluation_context}

## Form Field Question
{question}

Respond with JSON only: {{"answer": "<your answer>", "confidence": <0.0-1.0>}}
Set confidence based on how certain you are that the answer is correct given the profile information.
"""


@dataclass
class FieldSuggestion:
    """A suggested answer for a form field."""

    answer: str
    confidence: float

    @property
    def needs_human(self) -> bool:
        """Return True if confidence is below the threshold."""
        return self.confidence < CONFIDENCE_THRESHOLD


class FieldMapper:
    """Uses an LLM to suggest answers for unknown form fields."""

    def __init__(
        self,
        llm,
        profile: dict,
        evaluation_data: dict | None = None,
    ) -> None:
        self._llm = llm
        self._profile = profile
        self._evaluation_data = evaluation_data

    def _build_evaluation_context(self) -> str:
        """Format evaluation data for the field-mapper prompt."""
        if not self._evaluation_data:
            return "No evaluation data available."

        parts: list[str] = []

        # Block B — CV match / proof points
        for key in ("block_b", "cv_match", "proof_points"):
            val = self._evaluation_data.get(key)
            if val:
                parts.append(f"### Proof Points ({key})")
                if isinstance(val, (dict, list)):
                    parts.append(json.dumps(val, indent=2))
                else:
                    parts.append(str(val))

        # Block F — STAR stories for behavioural answers
        for key in ("block_f", "star_stories"):
            val = self._evaluation_data.get(key)
            if val:
                parts.append(f"### STAR Stories ({key})")
                if isinstance(val, (dict, list)):
                    parts.append(json.dumps(val, indent=2))
                else:
                    parts.append(str(val))

        # Block G — pre-drafted answers
        for key in ("block_g", "pre_drafted_answers", "draft_answers"):
            val = self._evaluation_data.get(key)
            if val:
                parts.append(f"### Pre-drafted Answers ({key})")
                if isinstance(val, (dict, list)):
                    parts.append(json.dumps(val, indent=2))
                else:
                    parts.append(str(val))

        return "\n".join(parts) if parts else "No evaluation data available."

    def _build_prompt(self, question: str) -> str:
        """Build a prompt with profile context."""
        resume_facts = self._profile.get("resume_facts", {})
        companies = resume_facts.get("companies", [])
        current = companies[0] if companies else {}

        return _FIELD_MAPPER_PROMPT.format(
            name=self._profile.get("name", ""),
            target_role=self._profile.get("target_role", ""),
            skills=", ".join(self._profile.get("skills", [])),
            work_authorization=self._profile.get("work_authorization", ""),
            current_title=current.get("title", "N/A"),
            current_company=current.get("name", "N/A"),
            evaluation_context=self._build_evaluation_context(),
            question=question,
        )

    async def suggest(self, question: str) -> FieldSuggestion:
        """Call LLM to suggest an answer for the given form field question."""
        try:
            prompt = self._build_prompt(question)
            raw = await self._llm.generate(prompt, json_mode=True)
            data = json.loads(raw)
            return FieldSuggestion(
                answer=str(data.get("answer", "")),
                confidence=float(data.get("confidence", 0.0)),
            )
        except Exception:
            logger.exception("Field mapper failed for question: %s", question)
            return FieldSuggestion(answer="", confidence=0.0)
