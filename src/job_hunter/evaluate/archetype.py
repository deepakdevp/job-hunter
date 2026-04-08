from __future__ import annotations

import json
import logging

logger = logging.getLogger(__name__)

ARCHETYPES: dict[str, dict] = {
    "full_stack": {
        "name": "Full-Stack Engineer",
        "keywords": [
            "full-stack", "fullstack", "full stack", "frontend and backend",
            "react", "node", "next.js", "django", "rails", "end-to-end",
            "web application", "SPA", "REST API", "GraphQL",
        ],
        "proof_priorities": [
            "frontend frameworks", "backend APIs", "database design",
            "deployment pipelines", "end-to-end feature delivery",
        ],
        "framing": (
            "A versatile engineer who ships complete features from database "
            "schema to polished UI, reducing handoff overhead and accelerating delivery."
        ),
    },
    "backend": {
        "name": "Backend / Platform Engineer",
        "keywords": [
            "backend", "back-end", "server-side", "microservices", "API",
            "distributed systems", "scalability", "infrastructure",
            "kubernetes", "docker", "cloud architecture", "data pipeline",
        ],
        "proof_priorities": [
            "system design", "API architecture", "database optimization",
            "cloud infrastructure", "performance tuning",
        ],
        "framing": (
            "A systems-oriented engineer who builds reliable, scalable backend "
            "services that handle real-world traffic and complexity."
        ),
    },
    "frontend": {
        "name": "Frontend / UI Engineer",
        "keywords": [
            "frontend", "front-end", "UI", "UX", "react", "vue", "angular",
            "CSS", "design system", "component library", "accessibility",
            "responsive", "web performance", "TypeScript",
        ],
        "proof_priorities": [
            "component architecture", "design system implementation",
            "performance optimization", "accessibility", "user experience",
        ],
        "framing": (
            "A frontend specialist who translates designs into performant, "
            "accessible interfaces that users genuinely enjoy."
        ),
    },
    "ai_ml": {
        "name": "AI / ML Engineer",
        "keywords": [
            "machine learning", "deep learning", "NLP", "computer vision",
            "model training", "fine-tuning", "MLOps", "PyTorch", "TensorFlow",
            "data science", "feature engineering", "model deployment",
        ],
        "proof_priorities": [
            "model development", "training pipelines", "evaluation metrics",
            "production ML systems", "data processing at scale",
        ],
        "framing": (
            "An ML engineer who bridges research and production, delivering "
            "models that solve real business problems at scale."
        ),
    },
    "agentic_ai": {
        "name": "Agentic AI / LLM Engineer",
        "keywords": [
            "LLM", "large language model", "RAG", "retrieval augmented",
            "langchain", "llamaindex", "vector database", "embeddings",
            "prompt engineering", "AI agent", "agentic", "MCP",
            "tool use", "function calling", "chatbot", "copilot",
        ],
        "proof_priorities": [
            "RAG pipelines", "LLM integration", "prompt engineering",
            "vector search", "agent orchestration", "tool/function calling",
        ],
        "framing": (
            "An AI engineer who builds production LLM-powered systems — RAG "
            "pipelines, agents, and tool-using copilots — that deliver real value."
        ),
    },
    "ai_transformation_lead": {
        "name": "AI Transformation Lead",
        "keywords": [
            "AI transformation", "digital transformation", "AI strategy",
            "change management", "AI adoption", "enterprise AI",
            "AI roadmap", "cross-functional", "stakeholder", "POC to production",
            "AI governance", "responsible AI",
        ],
        "proof_priorities": [
            "AI strategy development", "stakeholder alignment",
            "POC to production delivery", "team leadership",
            "cross-functional collaboration", "measurable business impact",
        ],
        "framing": (
            "A technical leader who drives enterprise AI adoption — from strategy "
            "and stakeholder buy-in to production deployment and measurable ROI."
        ),
    },
}

_ARCHETYPE_DETECTION_PROMPT = """You are a job-role classification expert.

Given the job description and title below, classify the role into one or two of these archetypes:
{archetype_list}

Analyze the JD carefully. Pick the PRIMARY archetype that best fits. If the role is clearly a hybrid (e.g., full-stack + AI), also pick a SECONDARY archetype. If it is not a hybrid, set secondary to null.

Rate your confidence from 0.0 to 1.0.

## Job Title
{job_title}

## Job Description (truncated)
{job_description}

Return JSON only:
{{
  "primary": "<archetype_key>",
  "secondary": "<archetype_key or null>",
  "confidence": <0.0-1.0>
}}

IMPORTANT: archetype_key MUST be one of: {archetype_keys}
"""


async def detect_archetype(
    job_description: str, job_title: str, llm
) -> dict:
    """Classify a job into one or two archetypes using LLM.

    Returns: {"primary": str, "secondary": str|None, "confidence": float}
    """
    archetype_list = "\n".join(
        f"- {key}: {info['name']} — {info['framing']}"
        for key, info in ARCHETYPES.items()
    )
    archetype_keys = ", ".join(ARCHETYPES.keys())
    jd_truncated = (job_description or "")[:4000]

    prompt = _ARCHETYPE_DETECTION_PROMPT.format(
        archetype_list=archetype_list,
        archetype_keys=archetype_keys,
        job_title=job_title or "Unknown",
        job_description=jd_truncated,
    )

    try:
        response = await llm.generate(prompt, json_mode=True)
        data = json.loads(response)

        primary = data.get("primary", "full_stack")
        if primary not in ARCHETYPES:
            primary = "full_stack"

        secondary = data.get("secondary")
        if secondary is not None and secondary not in ARCHETYPES:
            secondary = None

        confidence = float(data.get("confidence", 0.5))
        confidence = max(0.0, min(1.0, confidence))

        return {
            "primary": primary,
            "secondary": secondary,
            "confidence": confidence,
        }
    except Exception as e:
        logger.warning(f"Archetype detection failed, defaulting to full_stack: {e}")
        return {"primary": "full_stack", "secondary": None, "confidence": 0.0}
