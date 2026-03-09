"""Abstract LLM interface — swap providers without changing callers."""

from __future__ import annotations

from abc import ABC, abstractmethod


class LLMProvider(ABC):
    """Base class for all LLM backends."""

    @abstractmethod
    def complete(self, prompt: str, system: str = "", temperature: float = 0.3) -> str:
        """Send a prompt and return the response text."""

    def score_job(self, job_description: str, profile_text: str) -> int:
        """Score job fitness 1-10. Returns integer."""
        system = (
            "You are a career advisor. Score how well a job matches a candidate's profile. "
            "Respond with ONLY a single integer from 1 to 10. No explanation."
        )
        prompt = (
            f"CANDIDATE PROFILE:\n{profile_text}\n\n"
            f"JOB DESCRIPTION:\n{job_description}\n\n"
            "Score (1-10):"
        )
        result = self.complete(prompt, system=system, temperature=0.1)
        try:
            return max(1, min(10, int(result.strip())))
        except ValueError:
            # Try to extract first digit
            for char in result:
                if char.isdigit():
                    return max(1, min(10, int(char)))
            return 5

    def tailor_resume(
        self,
        resume_facts: dict,
        job_description: str,
        job_title: str,
        company: str,
    ) -> str:
        """Return a tailored resume as JSON matching resume_facts schema."""
        system = (
            "You are an expert resume writer specializing in ATS optimization. "
            "Your job: rewrite the candidate's resume to maximize keyword match with the job description. "
            "Rules:\n"
            "- NEVER invent new companies, job titles, dates, or metrics\n"
            "- ONLY rephrase existing bullets to use JD keywords\n"
            "- Reorder skills/bullets to prioritize most relevant ones\n"
            "- Mirror exact phrases from the JD where possible\n"
            "- Return valid JSON matching the input schema exactly"
        )
        prompt = (
            f"TARGET JOB: {job_title} at {company}\n\n"
            f"JOB DESCRIPTION:\n{job_description}\n\n"
            f"CANDIDATE RESUME FACTS (JSON):\n{resume_facts}\n\n"
            "Return the tailored resume as JSON with the same structure. "
            "Only modify bullet text and skills ordering. Do not add or remove entries."
        )
        return self.complete(prompt, system=system, temperature=0.4)

    def write_cover_letter(
        self,
        profile_text: str,
        job_description: str,
        job_title: str,
        company: str,
    ) -> str:
        """Return a cover letter as plain text."""
        system = (
            "You are an expert cover letter writer. Write concise, compelling cover letters "
            "that are professional, personalized, and ATS-friendly. 3 paragraphs max."
        )
        prompt = (
            f"Write a cover letter for:\n"
            f"Position: {job_title}\nCompany: {company}\n\n"
            f"JOB DESCRIPTION:\n{job_description}\n\n"
            f"CANDIDATE PROFILE:\n{profile_text}\n\n"
            "Write the cover letter body only (no 'Dear...' header needed, no signature block)."
        )
        return self.complete(prompt, system=system, temperature=0.6)

    def summarize_job(self, job_description: str) -> str:
        """Return a 2-3 sentence summary of the job for Notion notes."""
        system = "Summarize job postings concisely. Focus on role, tech stack, and key requirements."
        prompt = f"Summarize this job in 2-3 sentences:\n\n{job_description}"
        return self.complete(prompt, system=system, temperature=0.2)

    def extract_keywords(self, job_description: str) -> list[str]:
        """Extract top 10 relevant skill/tech keywords from a JD."""
        system = (
            "Extract skill and technology keywords from job descriptions. "
            "Return a JSON array of strings. 10 items max. No explanation."
        )
        prompt = f"Extract top keywords from:\n\n{job_description}\n\nReturn JSON array:"
        result = self.complete(prompt, system=system, temperature=0.1)
        import json
        try:
            # Strip markdown code fences if present
            text = result.strip()
            if text.startswith("```"):
                text = text.split("```")[1]
                if text.startswith("json"):
                    text = text[4:]
            return json.loads(text)
        except (json.JSONDecodeError, IndexError):
            return []
