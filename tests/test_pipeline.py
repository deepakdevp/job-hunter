"""Tests for the pipeline runner."""

from __future__ import annotations
from unittest.mock import MagicMock, patch
from job_hunter.pipeline import run_pipeline, StageResult, PipelineSummary


def test_stage_result_defaults():
    r = StageResult(name="discover")
    assert r.success is True
    assert r.detail == ""
    assert r.error is None


def test_stage_result_failed():
    r = StageResult(name="enrich", success=False, error="timeout")
    assert r.success is False


def test_pipeline_summary_add():
    s = PipelineSummary()
    s.add(StageResult(name="discover", detail="47 new jobs"))
    assert len(s.stages) == 1


def test_pipeline_summary_all_succeeded_true():
    s = PipelineSummary()
    s.add(StageResult(name="a", detail="ok"))
    s.add(StageResult(name="b", detail="ok"))
    assert s.all_succeeded is True


def test_pipeline_summary_all_succeeded_false():
    s = PipelineSummary()
    s.add(StageResult(name="a"))
    s.add(StageResult(name="b", success=False, error="fail"))
    assert s.all_succeeded is False


@patch("job_hunter.pipeline._run_discover")
@patch("job_hunter.pipeline._run_enrich")
@patch("job_hunter.pipeline._run_score")
@patch("job_hunter.pipeline._run_tailor")
@patch("job_hunter.pipeline._run_sync")
def test_run_pipeline_all_stages(mock_sync, mock_tailor, mock_score, mock_enrich, mock_discover):
    mock_discover.return_value = StageResult(name="Discover", detail="5 jobs")
    mock_enrich.return_value = StageResult(name="Enrich", detail="5/5")
    mock_score.return_value = StageResult(name="Score", detail="3 scored")
    mock_tailor.return_value = StageResult(name="Tailor", detail="3/3")
    mock_sync.return_value = StageResult(name="Sync", detail="3 created")

    summary = run_pipeline(MagicMock(), skip_discover=False, run_apply=False)
    assert len(summary.stages) == 5


@patch("job_hunter.pipeline._run_discover")
@patch("job_hunter.pipeline._run_enrich")
@patch("job_hunter.pipeline._run_score")
@patch("job_hunter.pipeline._run_tailor")
@patch("job_hunter.pipeline._run_sync")
def test_run_pipeline_skip_discover(mock_sync, mock_tailor, mock_score, mock_enrich, mock_discover):
    mock_enrich.return_value = StageResult(name="Enrich", detail="ok")
    mock_score.return_value = StageResult(name="Score", detail="ok")
    mock_tailor.return_value = StageResult(name="Tailor", detail="ok")
    mock_sync.return_value = StageResult(name="Sync", detail="ok")

    summary = run_pipeline(MagicMock(), skip_discover=True, run_apply=False)
    mock_discover.assert_not_called()
    assert len(summary.stages) == 4


@patch("job_hunter.pipeline._run_discover")
@patch("job_hunter.pipeline._run_enrich")
@patch("job_hunter.pipeline._run_score")
@patch("job_hunter.pipeline._run_tailor")
@patch("job_hunter.pipeline._run_sync")
def test_run_pipeline_failure_continues(
    mock_sync, mock_tailor, mock_score, mock_enrich, mock_discover
):
    mock_discover.side_effect = Exception("network error")
    mock_enrich.return_value = StageResult(name="Enrich", detail="3/3")
    mock_score.return_value = StageResult(name="Score", detail="ok")
    mock_tailor.return_value = StageResult(name="Tailor", detail="ok")
    mock_sync.return_value = StageResult(name="Sync", detail="ok")

    summary = run_pipeline(MagicMock(), skip_discover=False, run_apply=False)
    assert len(summary.stages) == 5
    assert summary.stages[0].success is False
    assert summary.stages[1].success is True
