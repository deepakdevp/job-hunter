"""Deep autoresearch engine — Karpathy-style agentic research loops.

Faithful to github.com/karpathy/autoresearch patterns:
- program.md steering file: natural language research directives
- Never-stop loop: runs until Ctrl+C, iterating on low-confidence results
- Keep/discard: only persist score changes with sufficient evidence quality
- Append-only TSV log: status (keep/discard/skip/crash), confidence, citations
- Time-budgeted research: per-job wall-clock limit, not fixed rounds
- Company cache: avoid redundant research across jobs in same run

For each high-value job, runs iterative LLM + web search cycles:
1. Company Research: culture, engineering blog, glassdoor, visa history
2. Visa Verification: check USCIS H1B data, company career pages, immigration forums
3. Evidence-Based Re-Scoring: re-score with gathered evidence
4. Resume Optimization: generate → critique → refine loop
"""

from __future__ import annotations

import asyncio
import csv
import json
import logging
import re
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from job_hunter.autoresearch.web_tools import web_search, fetch_page_text
from job_hunter.database import Job, JobDB

logger = logging.getLogger(__name__)

# ── Caches (persist across loop iterations) ────────────────────────────────
_company_cache: dict[str, dict] = {}
_visa_cache: dict[str, dict] = {}

# Companies to skip (not researchable)
_SKIP_COMPANIES = {"unknown", "", "n/a", "none", "null", "confidential"}

# Track researched jobs + their confidence (for loop re-research)
_research_history: dict[str, dict] = {}  # url -> {confidence, iteration, score}


# ── Steering: program.md ───────────────────────────────────────────────────


def load_program(program_path: Path | None = None) -> str:
    """Load research steering directives from program.md (Karpathy pattern).

    The program.md file is the human-agent interface. Humans edit this
    file to steer research priorities without touching code.
    """
    if program_path is None:
        # Default locations
        for p in [
            Path("config/deep_research_program.md"),
            Path("deep_research_program.md"),
        ]:
            if p.exists():
                program_path = p
                break

    if program_path and program_path.exists():
        text = program_path.read_text()
        logger.info(f"Loaded research program from {program_path}")
        return text

    logger.info("No program.md found — using default research directives")
    return ""


def _parse_program_config(program_text: str) -> dict:
    """Extract actionable config from program.md text."""
    config = {
        "time_budget_per_job": 120,  # seconds
        "max_company_rounds": 3,
        "max_visa_rounds": 2,
        "keep_threshold": "MEDIUM",  # minimum confidence to keep
        "min_citations": 2,
    }

    # Parse time budget
    m = re.search(r"Time budget per job[:\s]*(\d+)\s*seconds", program_text, re.IGNORECASE)
    if m:
        config["time_budget_per_job"] = int(m.group(1))

    # Parse max rounds
    m = re.search(r"Max search rounds[:\s]*(\d+)\s*for company", program_text, re.IGNORECASE)
    if m:
        config["max_company_rounds"] = int(m.group(1))

    m = re.search(r"(\d+)\s*for visa", program_text, re.IGNORECASE)
    if m:
        config["max_visa_rounds"] = int(m.group(1))

    return config


# ── Utility functions ──────────────────────────────────────────────────────


def _extract_company_from_jd(description: str, title: str = "") -> str | None:
    """Try to extract company name from job description text."""
    if not description:
        return None

    desc = description[:2000]

    patterns = [
        r"(?:about|join|at)\s+([A-Z][A-Za-z0-9\s&.]+?)(?:\s*(?:is|,|\.|!|\n))",
        r"([A-Z][A-Za-z0-9\s&.]+?)\s+is\s+(?:hiring|looking|seeking|a\s+(?:leading|global|innovative))",
        r"(?:company|employer|organization):\s*([A-Za-z0-9\s&.]+)",
        r"(?:work(?:ing)?\s+(?:at|for))\s+([A-Z][A-Za-z0-9\s&.]+?)(?:\s*[,.\n!])",
    ]

    for pattern in patterns:
        match = re.search(pattern, desc)
        if match:
            name = match.group(1).strip()
            if len(name) >= 3 and len(name) <= 50 and name.lower() not in _SKIP_COMPANIES:
                if not any(
                    w in name.lower()
                    for w in ("the team", "our company", "the company", "this role")
                ):
                    return name

    return None


def _repair_json(text: str) -> dict:
    """Attempt to parse JSON, with aggressive repair for LLM truncation."""
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)

    try:
        return json.loads(text)
    except json.JSONDecodeError:
        pass

    cleaned = re.sub(r",\s*([}\]])", r"\1", text)
    try:
        return json.loads(cleaned)
    except json.JSONDecodeError:
        pass

    start = text.find("{")
    if start < 0:
        raise ValueError(f"No JSON object found in: {text[:200]}")

    content = text[start:]

    for end_pattern in [
        r'((?:true|false|null|\d+(?:\.\d+)?|"[^"]*"))\s*[,}\]]',
    ]:
        for m in reversed(list(re.finditer(end_pattern, content))):
            candidate = content[: m.end()]
            open_braces = candidate.count("{") - candidate.count("}")
            open_brackets = candidate.count("[") - candidate.count("]")
            candidate = candidate.rstrip().rstrip(",")
            candidate += "]" * max(0, open_brackets) + "}" * max(0, open_braces)
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                continue

    # Last resort: extract individual key-value pairs
    pairs = re.findall(r'"(\w+)"\s*:\s*("(?:[^"\\]|\\.)*"|\d+(?:\.\d+)?|true|false|null)', content)
    if pairs:
        obj = {}
        for key, val in pairs:
            try:
                obj[key] = json.loads(val)
            except json.JSONDecodeError:
                obj[key] = val.strip('"')
        if obj:
            return obj

    raise ValueError(f"Could not parse JSON from LLM response: {text[:200]}")


# ── Research prompts ───────────────────────────────────────────────────────

_COMPANY_RESEARCH_PROMPT = """You are a thorough company researcher helping a job seeker evaluate {company}.

## Research Program (steering directives)
{program}

## What we know so far
{prior_evidence}

## New web search results
{search_results}

## Research goals
1. What does {company} do? (1-2 sentences)
2. Engineering culture: tech blog, open source, stack, team size
3. Japan office: where, how big, what teams, recent hires
4. Visa/sponsorship: any evidence they sponsor work visas in Japan?
5. Compensation: any salary data for this role level in Japan?
6. Red flags: layoffs, hiring freezes, bad glassdoor reviews

## Instructions
- Cite specific URLs for claims
- Mark confidence: HIGH (direct evidence), MEDIUM (inferred), LOW (guessing)
- List 2-3 follow-up searches that would fill gaps

Return JSON:
{{
  "company_summary": "...",
  "engineering_culture": "...",
  "japan_office": "...",
  "visa_evidence": "...",
  "compensation_data": "...",
  "red_flags": "...",
  "confidence": {{"overall": "HIGH/MEDIUM/LOW", "visa": "HIGH/MEDIUM/LOW"}},
  "citations": ["url1", "url2"],
  "follow_up_searches": ["query1", "query2", "query3"]
}}"""

_VISA_VERIFICATION_PROMPT = """You are verifying whether {company} sponsors work visas in Japan.

## Research Program (steering directives)
{program}

## Evidence gathered so far
{evidence}

## New search results about visa/sponsorship
{search_results}

## Verification criteria
- CONFIRMED: Career page says "visa sponsorship" or "relocation support", OR USCIS data shows H1B sponsors, OR immigration forum confirms
- LIKELY: English-only JD in Japan, international team mentioned, global company with known sponsorship
- UNLIKELY: Japanese-only JD, small local company, no evidence
- DENIED: Explicitly says "no visa sponsorship" or "Japanese language required (N1)"

Return JSON:
{{
  "visa_status": "CONFIRMED/LIKELY/UNLIKELY/DENIED",
  "evidence_summary": "...",
  "citations": ["url1", "url2"],
  "confidence": 0.0-1.0,
  "follow_up_searches": ["query1"]
}}"""

_EVIDENCE_RESCORE_PROMPT = """You are re-scoring a job with deep research evidence. Be strict and evidence-based.

## Research Program (steering directives)
{program}

## Job
- Title: {title}
- Company: {company}
- Location: {location}
- Original score: {original_score}/10
- Original reason: {original_reason}

## Deep Research Evidence
{evidence}

## Candidate Profile
- Target roles: {target_roles}
- Skills: {skills}

## Scoring Rules (evidence-based)
1. visa_sponsorship (50%):
   - CONFIRMED visa sponsorship = 10
   - LIKELY (English JD, international company) = 7
   - UNLIKELY = 3
   - DENIED or Japanese-only JD = 0
2. role_fit (30%): Based on actual JD requirements + company research
3. skills_match (20%): Based on confirmed tech stack from research

Return JSON:
{{
  "visa_sponsorship": 0-10,
  "role_fit": 0-10,
  "skills_match": 0-10,
  "final_score": 1-10,
  "reason": "2-3 sentences with citations",
  "score_change_explanation": "why score changed from original",
  "evidence_quality": "HIGH/MEDIUM/LOW"
}}"""

_RESUME_CRITIQUE_PROMPT = """You are a harsh resume critic. The candidate is applying to {company} for {title} in Japan.

## Research about this company/role
{company_research}

## Current resume text
{resume_text}

## Job description
{jd}

## Critique
1. Does the resume highlight skills that match THIS specific role's confirmed requirements?
2. Does it mention experience relevant to the company's actual tech stack?
3. Are there any claims that don't match the candidate's real background?
4. What's missing that would make this resume stronger for THIS specific role?
5. Score the resume 1-10 for this specific application.

Return JSON:
{{
  "score": 1-10,
  "strengths": ["..."],
  "weaknesses": ["..."],
  "missing": ["..."],
  "specific_improvements": ["actionable suggestion 1", "actionable suggestion 2"],
  "should_regenerate": true/false
}}"""


# ── Data structures ────────────────────────────────────────────────────────


@dataclass
class ResearchEvidence:
    """Accumulated evidence from research loops."""

    company_info: dict = field(default_factory=dict)
    visa_info: dict = field(default_factory=dict)
    rescore_info: dict = field(default_factory=dict)
    resume_critique: dict = field(default_factory=dict)
    all_citations: list[str] = field(default_factory=list)
    search_queries_used: list[str] = field(default_factory=list)
    total_searches: int = 0
    total_pages_fetched: int = 0
    total_llm_calls: int = 0
    research_time_seconds: float = 0.0
    status: str = "pending"  # keep, discard, skip, crash

    @property
    def confidence(self) -> str:
        """Overall research confidence."""
        if self.rescore_info.get("evidence_quality"):
            return self.rescore_info["evidence_quality"]
        visa_conf = self.visa_info.get("confidence", 0)
        if isinstance(visa_conf, (int, float)) and visa_conf >= 0.8:
            return "HIGH"
        company_conf = self.company_info.get("confidence", {})
        if isinstance(company_conf, dict) and company_conf.get("overall") == "HIGH":
            return "HIGH"
        if isinstance(visa_conf, (int, float)) and visa_conf >= 0.5:
            return "MEDIUM"
        return "LOW"

    @property
    def citation_count(self) -> int:
        return len(set(self.all_citations))

    def summary(self) -> str:
        parts = []
        if self.company_info:
            parts.append(f"Company: {self.company_info.get('company_summary', 'N/A')}")
        if self.visa_info:
            parts.append(
                f"Visa: {self.visa_info.get('visa_status', 'N/A')} "
                f"(conf={self.visa_info.get('confidence', '?')})"
            )
        if self.rescore_info:
            parts.append(f"Re-scored: {self.rescore_info.get('final_score', '?')}/10")
        parts.append(
            f"[{self.status}|{self.confidence}|{self.total_searches} searches, "
            f"{self.total_llm_calls} LLM, {self.research_time_seconds:.0f}s]"
        )
        return " | ".join(parts)


# ── Core research functions ────────────────────────────────────────────────


async def _do_searches(queries: list[str], max_results: int = 3) -> tuple[str, list[str]]:
    """Run multiple web searches, fetch top pages, return formatted results + citations."""
    all_results = []
    citations = []

    for query in queries:
        results = await web_search(query, max_results=max_results)
        for r in results:
            all_results.append(f"- [{r['title']}]({r['url']}): {r['snippet']}")
            citations.append(r["url"])

            # Fetch page text for top result only (to save time)
            if r == results[0] and r["url"]:
                page_text = await fetch_page_text(r["url"], max_chars=3000)
                if page_text:
                    all_results.append(f"  Page content: {page_text[:1500]}")

        await asyncio.sleep(1)

    formatted = "\n".join(all_results) if all_results else "No results found."
    return formatted, citations


def _append_results_log(log_path: Path, row: dict):
    """Append a single result row to TSV log (Karpathy pattern: append-only, never versioned)."""
    exists = log_path.exists()
    with open(log_path, "a", newline="") as f:
        writer = csv.DictWriter(
            f,
            fieldnames=[
                "timestamp",
                "company",
                "title",
                "old_score",
                "new_score",
                "status",
                "confidence",
                "visa_status",
                "citations",
                "searches",
                "llm_calls",
                "time_secs",
            ],
            delimiter="\t",
        )
        if not exists:
            writer.writeheader()
        writer.writerow(row)


def _should_keep(evidence: ResearchEvidence, old_score: int, new_score: int, config: dict) -> bool:
    """Karpathy keep/discard decision: only keep changes backed by evidence.

    Like autoresearch's val_bpb comparison — if the new score isn't backed
    by sufficient evidence, discard it (revert to old score).
    """
    if new_score == old_score:
        return True  # No change, nothing to decide

    confidence = evidence.confidence

    # Confidence threshold from program.md
    threshold = config.get("keep_threshold", "MEDIUM")
    confidence_levels = {"HIGH": 3, "MEDIUM": 2, "LOW": 1}
    if confidence_levels.get(confidence, 0) < confidence_levels.get(threshold, 2):
        logger.info(f"  DISCARD: confidence {confidence} below threshold {threshold}")
        return False

    # Must have at least N citations
    min_citations = config.get("min_citations", 2)
    if evidence.citation_count < min_citations:
        logger.info(f"  DISCARD: only {evidence.citation_count} citations (need {min_citations})")
        return False

    return True


async def research_company(
    job: Job,
    llm,
    program: str = "",
    max_rounds: int = 3,
    time_limit: float = 60,
) -> dict:
    """Iterative company research loop with time budget.

    Uses cache to avoid re-researching the same company.
    Stops on HIGH confidence OR time limit, whichever comes first.
    """
    company = job.company
    cache_key = company.lower().strip()
    if cache_key in _company_cache:
        logger.info(f"  Company cache hit: {company}")
        return _company_cache[cache_key]

    start = time.time()
    evidence_parts = []
    all_citations = []
    search_count = 0
    llm_count = 0
    result = {}

    initial_queries = [
        f"{company} engineering blog tech stack",
        f"{company} Japan office Tokyo hiring",
        f"{company} glassdoor reviews engineering",
    ]

    follow_up_queries = []
    for round_num in range(max_rounds):
        # Time budget check (Karpathy pattern: fixed time, not fixed rounds)
        if time.time() - start > time_limit:
            logger.info(
                f"  Company research: time limit ({time_limit}s) reached after {round_num} rounds"
            )
            break

        queries = initial_queries if round_num == 0 else follow_up_queries
        search_results, citations = await _do_searches(queries, max_results=3)
        search_count += len(queries)
        all_citations.extend(citations)

        prior = "\n".join(evidence_parts) if evidence_parts else "No prior evidence yet."

        prompt = _COMPANY_RESEARCH_PROMPT.format(
            company=company,
            program=program[:500] if program else "No steering directives.",
            prior_evidence=prior,
            search_results=search_results,
        )

        try:
            response = await llm.generate(prompt, json_mode=True, max_tokens=2048)
            llm_count += 1
            result = _repair_json(response)
            evidence_parts.append(json.dumps(result, indent=2))

            follow_up_queries = result.get("follow_up_searches", [])
            if not follow_up_queries:
                break

            # Early stopping on HIGH confidence (Karpathy: stop when metric stabilizes)
            if result.get("confidence", {}).get("overall") == "HIGH":
                logger.info(f"  Company research: HIGH confidence after round {round_num + 1}")
                break

        except Exception as e:
            logger.warning(f"Company research LLM call failed (round {round_num + 1}): {e}")
            break

    out = {
        "result": result,
        "citations": all_citations,
        "search_count": search_count,
        "llm_count": llm_count,
    }
    _company_cache[cache_key] = out
    return out


async def verify_visa(
    job: Job,
    company_evidence: dict,
    llm,
    program: str = "",
    max_rounds: int = 2,
    time_limit: float = 40,
) -> dict:
    """Verify visa sponsorship with targeted searches and time budget."""
    company = job.company
    cache_key = company.lower().strip()
    if cache_key in _visa_cache:
        logger.info(f"  Visa cache hit: {company}")
        return _visa_cache[cache_key]

    start = time.time()
    all_citations = []
    search_count = 0
    llm_count = 0

    visa_queries = [
        f"{company} visa sponsorship Japan work permit",
        f"{company} careers Japan relocation",
        f"{company} H1B visa sponsor",
    ]

    evidence = json.dumps(company_evidence, indent=2)[:2000]
    result = {}

    follow_up_queries = []
    for round_num in range(max_rounds):
        if time.time() - start > time_limit:
            logger.info(f"  Visa verification: time limit ({time_limit}s) reached")
            break

        queries = visa_queries if round_num == 0 else follow_up_queries
        search_results, citations = await _do_searches(queries, max_results=3)
        search_count += len(queries)
        all_citations.extend(citations)

        prompt = _VISA_VERIFICATION_PROMPT.format(
            company=company,
            program=program[:500] if program else "No steering directives.",
            evidence=evidence,
            search_results=search_results,
        )

        try:
            response = await llm.generate(prompt, json_mode=True, max_tokens=2048)
            llm_count += 1
            result = _repair_json(response)
            evidence = json.dumps(result, indent=2)

            follow_up_queries = result.get("follow_up_searches", [])
            if not follow_up_queries:
                break

            # Early stopping on high confidence
            if result.get("confidence", 0) >= 0.8:
                break

        except Exception as e:
            logger.warning(f"Visa verification LLM call failed (round {round_num + 1}): {e}")
            break

    out = {
        "result": result,
        "citations": all_citations,
        "search_count": search_count,
        "llm_count": llm_count,
    }
    _visa_cache[cache_key] = out
    return out


async def evidence_rescore(
    job: Job,
    evidence: ResearchEvidence,
    profile: dict,
    llm,
    program: str = "",
) -> dict:
    """Re-score job using accumulated evidence."""
    evidence_text = evidence.summary()
    if evidence.company_info:
        evidence_text += (
            f"\n\nCompany research:\n{json.dumps(evidence.company_info, indent=2)[:2000]}"
        )
    if evidence.visa_info:
        evidence_text += (
            f"\n\nVisa verification:\n{json.dumps(evidence.visa_info, indent=2)[:1000]}"
        )

    prompt = _EVIDENCE_RESCORE_PROMPT.format(
        title=job.title,
        company=job.company,
        location=job.location,
        original_score=job.score,
        original_reason=job.score_reason or "None",
        evidence=evidence_text,
        target_roles=", ".join(profile.get("target_roles", [])),
        skills=", ".join(profile.get("skills", [])),
        program=program[:500] if program else "No steering directives.",
    )

    try:
        response = await llm.generate(prompt, json_mode=True, max_tokens=2048)
        return _repair_json(response)
    except Exception as e:
        logger.warning(f"Evidence re-scoring failed for {job.url}: {e}")
        return {}


async def critique_resume(
    job: Job,
    resume_text: str,
    company_research: dict,
    llm,
) -> dict:
    """Critique existing resume against deep research findings."""
    prompt = _RESUME_CRITIQUE_PROMPT.format(
        company=job.company,
        title=job.title,
        company_research=json.dumps(company_research, indent=2)[:2000],
        resume_text=resume_text[:3000],
        jd=(job.description or "")[:2000],
    )

    try:
        response = await llm.generate(prompt, json_mode=True, max_tokens=2048)
        return _repair_json(response)
    except Exception as e:
        logger.warning(f"Resume critique failed for {job.url}: {e}")
        return {}


# ── Main deep research orchestrator ────────────────────────────────────────


async def deep_research_job(
    job: Job,
    profile: dict,
    llm,
    program: str = "",
    config: dict | None = None,
) -> ResearchEvidence:
    """Run full deep research pipeline on a single job.

    Time-budgeted: each phase has its own time limit derived from
    the per-job budget in program.md config.
    """
    cfg = config or {}
    time_budget = cfg.get("time_budget_per_job", 120)
    max_company_rounds = cfg.get("max_company_rounds", 3)
    max_visa_rounds = cfg.get("max_visa_rounds", 2)

    start = time.time()
    evidence = ResearchEvidence()

    # Phase 1: Company Research (iterative, time-budgeted)
    logger.info(f"  [1/4] Researching {job.company}...")
    company_result = await research_company(
        job,
        llm,
        program=program,
        max_rounds=max_company_rounds,
        time_limit=time_budget * 0.4,  # 40% of budget for company research
    )
    evidence.company_info = company_result.get("result", {})
    evidence.all_citations.extend(company_result.get("citations", []))
    evidence.total_searches += company_result.get("search_count", 0)
    evidence.total_llm_calls += company_result.get("llm_count", 0)

    # Phase 2: Visa Verification (iterative, time-budgeted)
    logger.info(f"  [2/4] Verifying visa for {job.company}...")
    visa_result = await verify_visa(
        job,
        evidence.company_info,
        llm,
        program=program,
        max_rounds=max_visa_rounds,
        time_limit=time_budget * 0.3,  # 30% of budget for visa
    )
    evidence.visa_info = visa_result.get("result", {})
    evidence.all_citations.extend(visa_result.get("citations", []))
    evidence.total_searches += visa_result.get("search_count", 0)
    evidence.total_llm_calls += visa_result.get("llm_count", 0)

    # Phase 3: Evidence-Based Re-Scoring
    logger.info("  [3/4] Re-scoring with evidence...")
    rescore = await evidence_rescore(job, evidence, profile, llm, program=program)
    evidence.rescore_info = rescore
    evidence.total_llm_calls += 1

    # Phase 4: Resume Critique (if resume exists)
    if job.resume_path and Path(job.resume_path).exists():
        logger.info("  [4/4] Critiquing resume...")
        from job_hunter.autoresearch.resume_audit import extract_text_from_pdf

        resume_text = extract_text_from_pdf(job.resume_path)
        if resume_text:
            critique = await critique_resume(job, resume_text, evidence.company_info, llm)
            evidence.resume_critique = critique
            evidence.total_llm_calls += 1
    else:
        logger.info("  [4/4] No resume to critique, skipping")

    evidence.research_time_seconds = time.time() - start
    return evidence


async def run_deep_research(
    db: JobDB,
    profile: dict,
    llm,
    min_score: int = 5,
    max_jobs: int = 50,
    log_dir: Path | None = None,
    program_path: Path | None = None,
    on_progress=None,
    on_job_complete=None,
) -> dict:
    """Run deep autoresearch on all high-value jobs (single pass).

    Karpathy-style: sequential experiments, keep/discard decisions,
    append-only results log, company cache, time budgets.
    """
    # Load steering directives (Karpathy's program.md pattern)
    program = load_program(program_path)
    config = _parse_program_config(program)

    if log_dir is None:
        log_dir = Path(db.db_path).parent
    results_log = log_dir / "deep_research_results.tsv"

    # Get candidates
    candidates = []
    for status in ("synced", "tailored", "scored"):
        candidates.extend(db.get_jobs_by_status(status))

    # Extract company names from JD for "Unknown" jobs
    unknowns = [
        j
        for j in candidates
        if (j.company or "").strip().lower() in _SKIP_COMPANIES and j.description
    ]
    if unknowns:
        logger.info(f"Extracting company names from {len(unknowns)} 'Unknown' jobs...")
        for j in unknowns:
            extracted = _extract_company_from_jd(j.description, j.title)
            if not extracted and llm:
                try:
                    resp = await llm.generate(
                        f"What company is hiring for this job? Return ONLY the company name, nothing else.\n\n"
                        f"Title: {j.title}\nDescription: {(j.description or '')[:1000]}",
                        max_tokens=50,
                    )
                    name = resp.strip().strip('"').strip("'").strip()
                    if name and len(name) <= 50 and name.lower() not in _SKIP_COMPANIES:
                        extracted = name
                except Exception:
                    pass
            if extracted:
                j.company = extracted
                db.upsert_job(j)
                logger.info(f"  → {j.title[:40]}: {extracted}")

    # Filter and sort
    candidates = [
        j
        for j in candidates
        if (j.score or 0) >= min_score and (j.company or "").strip().lower() not in _SKIP_COMPANIES
    ]
    candidates.sort(key=lambda j: j.score or 0, reverse=True)
    candidates = candidates[:max_jobs]

    total = len(candidates)
    results = {
        "total_researched": 0,
        "scores_changed": 0,
        "scores_increased": 0,
        "scores_decreased": 0,
        "kept": 0,
        "discarded": 0,
        "resumes_flagged": 0,
        "total_web_searches": 0,
        "total_llm_calls": 0,
        "total_time_seconds": 0,
        "per_job": [],
    }

    start = time.time()

    for i, job in enumerate(candidates):
        status = "crash"
        evidence = ResearchEvidence()

        try:
            logger.info(f"\n{'=' * 60}")
            logger.info(f"Deep research [{i + 1}/{total}]: {job.title} @ {job.company}")
            logger.info(f"  Current score: {job.score}/10 | Status: {job.status}")

            evidence = await deep_research_job(job, profile, llm, program=program, config=config)
            results["total_researched"] += 1
            results["total_web_searches"] += evidence.total_searches
            results["total_llm_calls"] += evidence.total_llm_calls

            # Keep/discard decision (Karpathy pattern)
            old_score = job.score
            new_score = old_score

            if evidence.rescore_info.get("final_score"):
                new_score = int(evidence.rescore_info["final_score"])
                new_score = max(1, min(10, new_score))

            keep = _should_keep(evidence, old_score, new_score, config)

            if keep and new_score != old_score:
                # KEEP: apply the score change
                status = "keep"
                results["scores_changed"] += 1
                results["kept"] += 1
                if new_score > old_score:
                    results["scores_increased"] += 1
                else:
                    results["scores_decreased"] += 1

                reason = evidence.rescore_info.get("reason", "")
                change_why = evidence.rescore_info.get("score_change_explanation", "")
                job.score = new_score
                job.score_reason = (
                    f"[DEEP-AR: {old_score}→{new_score}] {reason}\nChange: {change_why}"
                )

                visa_status = evidence.visa_info.get("visa_status", "")
                if visa_status == "CONFIRMED":
                    job.visa_sponsorship = True
                elif visa_status == "DENIED":
                    job.visa_sponsorship = False

                db.upsert_job(job)
                logger.info(f"  KEEP: {old_score} → {new_score} ({evidence.confidence} confidence)")
                evidence.status = "keep"

            elif not keep and new_score != old_score:
                # DISCARD: revert to old score (Karpathy: git reset --hard)
                status = "discard"
                results["discarded"] += 1
                logger.info(
                    f"  DISCARD: {old_score} → {new_score} reverted (insufficient evidence)"
                )
                new_score = old_score  # Revert
                evidence.status = "discard"
            else:
                status = "skip"
                evidence.status = "skip"
                logger.info(f"  SKIP: score unchanged at {old_score}")

            # Track for loop re-research
            _research_history[job.url] = {
                "confidence": evidence.confidence,
                "iteration": _research_history.get(job.url, {}).get("iteration", 0) + 1,
                "score": job.score,
                "status": status,
            }

            # Flag resumes that need regeneration
            if evidence.resume_critique.get("should_regenerate"):
                results["resumes_flagged"] += 1

            # Per-job summary
            results["per_job"].append(
                {
                    "title": job.title[:50],
                    "company": job.company,
                    "old_score": old_score,
                    "new_score": job.score,
                    "status": status,
                    "confidence": evidence.confidence,
                    "visa_status": evidence.visa_info.get("visa_status", "UNKNOWN"),
                    "research_time": round(evidence.research_time_seconds, 1),
                    "searches": evidence.total_searches,
                    "llm_calls": evidence.total_llm_calls,
                    "citations": evidence.citation_count,
                }
            )

            if on_job_complete:
                on_job_complete(job, evidence)

        except Exception as e:
            logger.error(f"Deep research failed for {job.title} @ {job.company}: {e}")
            evidence.status = "crash"

        # Append to TSV log — every result, whether kept or discarded (Karpathy pattern)
        _append_results_log(
            results_log,
            {
                "timestamp": datetime.now().isoformat(),
                "company": job.company,
                "title": job.title[:50],
                "old_score": old_score if "old_score" in dir() else job.score,
                "new_score": job.score,
                "status": status,
                "confidence": evidence.confidence,
                "visa_status": evidence.visa_info.get("visa_status", "UNKNOWN"),
                "citations": evidence.citation_count,
                "searches": evidence.total_searches,
                "llm_calls": evidence.total_llm_calls,
                "time_secs": round(evidence.research_time_seconds, 1),
            },
        )

        if on_progress:
            on_progress(i + 1, total)

        await asyncio.sleep(2)

    results["total_time_seconds"] = round(time.time() - start, 1)

    logger.info(f"\n{'=' * 60}")
    logger.info(
        f"Deep Research Complete: {results['total_researched']} jobs, "
        f"{results['scores_changed']} scores changed "
        f"(kept={results['kept']}, discarded={results['discarded']}), "
        f"{results['total_time_seconds']}s total"
    )

    return results


async def run_deep_research_loop(
    db: JobDB,
    profile: dict,
    llm,
    min_score: int = 5,
    max_jobs: int = 50,
    log_dir: Path | None = None,
    program_path: Path | None = None,
    on_progress=None,
    on_job_complete=None,
    on_iteration_complete=None,
) -> dict:
    """Never-stop deep research loop (Karpathy pattern).

    Runs until interrupted (Ctrl+C). Each iteration:
    1. Processes all jobs above min_score
    2. Re-researches jobs with LOW confidence from previous iterations
    3. Skips jobs already at HIGH confidence
    4. Clears company/visa caches between iterations to get fresh data
    5. Logs everything to TSV

    NEVER STOP. Do NOT pause. Loop until the human interrupts.
    """
    iteration = 0
    cumulative_results = {
        "iterations": 0,
        "total_researched": 0,
        "total_kept": 0,
        "total_discarded": 0,
        "total_time_seconds": 0,
    }

    try:
        while True:
            iteration += 1
            logger.info(f"\n{'#' * 60}")
            logger.info(f"# LOOP ITERATION {iteration}")
            logger.info(f"{'#' * 60}")

            # Reload program.md each iteration (human may have edited it)
            program = load_program(program_path)
            _parse_program_config(program)  # validate config (result used implicitly)

            # On iterations > 1, only research LOW-confidence or un-researched jobs
            if iteration > 1:
                # Clear caches to get fresh search results
                _company_cache.clear()
                _visa_cache.clear()
                logger.info("Cleared caches for fresh research round")

            # Get candidates, filtering out HIGH-confidence already-researched
            candidates = []
            for status in ("synced", "tailored", "scored"):
                candidates.extend(db.get_jobs_by_status(status))

            candidates = [
                j
                for j in candidates
                if (j.score or 0) >= min_score
                and (j.company or "").strip().lower() not in _SKIP_COMPANIES
            ]

            if iteration > 1:
                # Filter: skip HIGH confidence, re-research LOW
                pre_count = len(candidates)
                candidates = [
                    j
                    for j in candidates
                    if _research_history.get(j.url, {}).get("confidence") != "HIGH"
                ]
                skipped = pre_count - len(candidates)
                if skipped:
                    logger.info(f"Skipping {skipped} HIGH-confidence jobs from previous iteration")

            if not candidates:
                logger.info("No more jobs to research. Waiting 60s before next scan...")
                await asyncio.sleep(60)
                continue

            candidates.sort(key=lambda j: j.score or 0, reverse=True)
            candidates = candidates[:max_jobs]

            # Run single pass
            iter_results = await run_deep_research(
                db,
                profile,
                llm,
                min_score=min_score,
                max_jobs=max_jobs,
                log_dir=log_dir,
                program_path=program_path,
                on_progress=on_progress,
                on_job_complete=on_job_complete,
            )

            cumulative_results["iterations"] = iteration
            cumulative_results["total_researched"] += iter_results["total_researched"]
            cumulative_results["total_kept"] += iter_results.get("kept", 0)
            cumulative_results["total_discarded"] += iter_results.get("discarded", 0)
            cumulative_results["total_time_seconds"] += iter_results["total_time_seconds"]

            if on_iteration_complete:
                on_iteration_complete(iteration, iter_results)

            # If no LOW confidence jobs remain, wait longer
            low_conf_count = sum(
                1 for h in _research_history.values() if h.get("confidence") == "LOW"
            )
            if low_conf_count == 0:
                logger.info("All jobs at MEDIUM/HIGH confidence. Waiting 300s...")
                await asyncio.sleep(300)
            else:
                logger.info(f"{low_conf_count} LOW-confidence jobs — re-researching in 30s...")
                await asyncio.sleep(30)

    except (KeyboardInterrupt, asyncio.CancelledError):
        logger.info(f"\nLoop interrupted after {iteration} iterations")

    return cumulative_results


# ── Structured company research (6-axis) ──────────────────────────────────

_STRUCTURED_RESEARCH_PROMPT = """You are an expert company researcher producing structured intelligence for a job candidate.

## Job
- Title: {title}
- Company: {company}
- Location: {location}
- Description (truncated): {description}

## Candidate Profile
- Target roles: {target_roles}
- Skills: {skills}
- Years of experience: {yoe}
- Experience highlights: {experience_highlights}

## Evaluation Data (if available)
{evaluation_data}

## Instructions
Produce a 6-axis structured research report. For each axis, provide findings and a confidence level (HIGH/MEDIUM/LOW). HIGH means you have strong knowledge, MEDIUM means reasonable inference, LOW means speculative.

### Axis 1: AI/Tech Strategy
What AI/ML products does {company} build? Engineering blog? Published papers or conference talks? Known tech stack?

### Axis 2: Recent Moves (last 6 months)
Hiring waves, acquisitions, product launches, funding rounds, leadership changes, layoffs, pivots.

### Axis 3: Engineering Culture
Deploy cadence (daily/weekly/monthly), mono-repo vs multi-repo, primary languages/frameworks, remote-first vs office-first, Glassdoor/Blind sentiment summary.

### Axis 4: Probable Challenges
Scaling issues, reliability/cost/latency problems, tech debt, migrations in progress, pain points from employee reviews.

### Axis 5: Competitive Positioning
Main competitors, moat/differentiation, market position, growth trajectory.

### Axis 6: Candidate Angle
What unique value does THIS specific candidate bring? Which resume projects are most relevant? What interview story should they lead with? What gaps should they proactively address?

Return JSON:
{{
  "ai_tech_strategy": {{
    "findings": "...",
    "products": ["..."],
    "tech_stack": ["..."],
    "confidence": "HIGH/MEDIUM/LOW"
  }},
  "recent_moves": {{
    "findings": "...",
    "events": ["..."],
    "confidence": "HIGH/MEDIUM/LOW"
  }},
  "engineering_culture": {{
    "findings": "...",
    "deploy_cadence": "...",
    "repo_structure": "...",
    "languages": ["..."],
    "remote_policy": "...",
    "sentiment": "...",
    "confidence": "HIGH/MEDIUM/LOW"
  }},
  "probable_challenges": {{
    "findings": "...",
    "challenges": ["..."],
    "confidence": "HIGH/MEDIUM/LOW"
  }},
  "competitive_positioning": {{
    "findings": "...",
    "competitors": ["..."],
    "moat": "...",
    "confidence": "HIGH/MEDIUM/LOW"
  }},
  "candidate_angle": {{
    "findings": "...",
    "unique_value": "...",
    "relevant_projects": ["..."],
    "lead_story": "...",
    "gaps_to_address": ["..."],
    "confidence": "HIGH/MEDIUM/LOW"
  }}
}}"""


async def research_company_structured(job: Job, profile: dict, llm) -> dict:
    """Produce 6-axis structured company research for a job.

    Axes:
    1. ai_tech_strategy - products, blog, papers, stack
    2. recent_moves - hiring, acquisitions, launches, funding (last 6 months)
    3. engineering_culture - deploy cadence, repo, languages, remote, sentiment
    4. probable_challenges - scaling, reliability, migrations, pain points
    5. competitive_positioning - competitors, moat, differentiation
    6. candidate_angle - unique value, relevant projects, interview story

    If the job has evaluation data, it is used for axis 6 (candidate_angle).
    The result is stored in job.research_data.

    Args:
        job: Job to research.
        profile: Candidate profile dict.
        llm: LLM provider instance.

    Returns:
        Structured research dict with 6 axes.
    """
    # Build evaluation context for candidate_angle axis
    evaluation_data = "No evaluation data available."
    if job.evaluation:
        try:
            eval_dict = json.loads(job.evaluation)
            # Extract relevant blocks for candidate angle
            blocks = eval_dict.get("blocks", {})
            eval_parts = []
            cv_match = blocks.get("cv_match", {})
            if cv_match and "error" not in cv_match:
                eval_parts.append(f"CV Match: {json.dumps(cv_match)[:800]}")
            personalization = blocks.get("personalization", {})
            if personalization and "error" not in personalization:
                eval_parts.append(f"Personalization: {json.dumps(personalization)[:800]}")
            level_strategy = blocks.get("level_strategy", {})
            if level_strategy and "error" not in level_strategy:
                eval_parts.append(f"Level Strategy: {json.dumps(level_strategy)[:400]}")
            if eval_parts:
                evaluation_data = "\n".join(eval_parts)
        except (json.JSONDecodeError, TypeError):
            pass

    # Build experience highlights
    experience_highlights = ""
    if profile.get("experience"):
        highlights = profile["experience"]
        if isinstance(highlights, list):
            highlights = "; ".join(
                str(e.get("title", "") + " at " + str(e.get("company", "")))
                if isinstance(e, dict)
                else str(e)
                for e in highlights[:5]
            )
        experience_highlights = str(highlights)[:500]

    prompt = _STRUCTURED_RESEARCH_PROMPT.format(
        title=job.title,
        company=job.company,
        location=job.location or "Not specified",
        description=(job.description or "")[:2000],
        target_roles=", ".join(profile.get("target_roles", []))[:200],
        skills=", ".join(profile.get("skills", []))[:300],
        yoe=profile.get("years_of_experience", "Not specified"),
        experience_highlights=experience_highlights or "Not provided",
        evaluation_data=evaluation_data[:2000],
    )

    try:
        response = await llm.generate(prompt, json_mode=True, max_tokens=4096)
        result = _repair_json(response)

        # Validate axes exist with at least findings and confidence
        required_axes = [
            "ai_tech_strategy",
            "recent_moves",
            "engineering_culture",
            "probable_challenges",
            "competitive_positioning",
            "candidate_angle",
        ]
        for axis in required_axes:
            if axis not in result:
                result[axis] = {
                    "findings": "No data available",
                    "confidence": "LOW",
                }
            elif not isinstance(result[axis], dict):
                result[axis] = {
                    "findings": str(result[axis]),
                    "confidence": "LOW",
                }
            else:
                result[axis].setdefault("findings", "No data available")
                result[axis].setdefault("confidence", "LOW")

        # Store in job.research_data
        job.research_data = json.dumps(result)

        logger.info(
            f"Structured research complete for {job.title} at {job.company} "
            f"({sum(1 for a in required_axes if result[a].get('confidence') == 'HIGH')}/6 HIGH confidence)"
        )
        return result

    except Exception as e:
        logger.error(f"Structured research failed for {job.url}: {e}")
        error_result = {
            axis: {"findings": "Research failed", "confidence": "LOW", "error": str(e)}
            for axis in [
                "ai_tech_strategy",
                "recent_moves",
                "engineering_culture",
                "probable_challenges",
                "competitive_positioning",
                "candidate_angle",
            ]
        }
        return error_result
