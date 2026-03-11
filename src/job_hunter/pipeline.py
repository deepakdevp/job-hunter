"""Pipeline runner with best-effort stage chaining."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from pathlib import Path

logger = logging.getLogger(__name__)


@dataclass
class StageResult:
    """Result of a single pipeline stage."""

    name: str
    success: bool = True
    detail: str = ""
    error: str | None = None


class PipelineSummary:
    """Aggregated results from a full pipeline run."""

    def __init__(self) -> None:
        self.stages: list[StageResult] = []

    def add(self, result: StageResult) -> None:
        """Append a stage result."""
        self.stages.append(result)

    @property
    def all_succeeded(self) -> bool:
        """Return True if every stage succeeded."""
        return all(s.success for s in self.stages)


# ---------------------------------------------------------------------------
# Stage wrapper functions — each imports lazily so pipeline.py doesn't fail
# if optional dependencies are missing.
# ---------------------------------------------------------------------------


def _run_discover(config_dir: Path) -> StageResult:
    from job_hunter.discover import run as discover_run

    result = discover_run(config_dir)
    return StageResult(name="Discover", detail=str(result))


def _run_enrich(config_dir: Path) -> StageResult:
    from job_hunter.enrich import run as enrich_run

    result = enrich_run(config_dir)
    return StageResult(name="Enrich", detail=str(result))


def _run_score(config_dir: Path) -> StageResult:
    from job_hunter.score import run as score_run

    result = score_run(config_dir)
    return StageResult(name="Score", detail=str(result))


def _run_tailor(config_dir: Path) -> StageResult:
    from job_hunter.tailor import run as tailor_run

    result = tailor_run(config_dir)
    return StageResult(name="Tailor", detail=str(result))


def _run_sync(config_dir: Path) -> StageResult:
    from job_hunter.notion import push as sync_push

    result = sync_push(config_dir)
    return StageResult(name="Sync", detail=str(result))


def _run_apply(config_dir: Path, *, dry_run: bool = False) -> StageResult:
    from job_hunter.apply import run as apply_run

    result = apply_run(config_dir, dry_run=dry_run)
    return StageResult(name="Apply", detail=str(result))


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_pipeline(
    config_dir: Path,
    *,
    skip_discover: bool = False,
    run_apply: bool = False,
    dry_run: bool = False,
) -> PipelineSummary:
    """Execute the full job-hunter pipeline with best-effort stage chaining.

    Each stage runs in order. If a stage raises an exception the error is
    logged, a failed ``StageResult`` is recorded, and the pipeline continues
    with the next stage.
    """
    stages: list[tuple[str, object]] = []

    if not skip_discover:
        stages.append(("Discover", lambda cd: _run_discover(cd)))

    stages.append(("Enrich", lambda cd: _run_enrich(cd)))
    stages.append(("Score", lambda cd: _run_score(cd)))
    stages.append(("Tailor", lambda cd: _run_tailor(cd)))
    stages.append(("Sync", lambda cd: _run_sync(cd)))

    if run_apply:
        stages.append(("Apply", lambda cd: _run_apply(cd, dry_run=dry_run)))

    summary = PipelineSummary()

    for name, stage_fn in stages:
        try:
            result = stage_fn(config_dir)
            summary.add(result)
            logger.info("Stage %s completed: %s", name, result.detail)
        except Exception as exc:
            logger.error("Stage %s failed: %s", name, exc)
            summary.add(
                StageResult(name=name, success=False, error=str(exc)),
            )

    return summary
