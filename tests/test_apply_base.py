"""Tests for apply strategy base + platform detection."""
from __future__ import annotations
import pytest
from job_hunter.apply.strategies.base import BaseFormFiller, FillResult, detect_platform

def test_detect_workday():
    assert detect_platform("https://company.myworkdayjobs.com/en-US/jobs/1234") == "workday"

def test_detect_greenhouse():
    assert detect_platform("https://boards.greenhouse.io/company/jobs/1234") == "greenhouse"

def test_detect_lever():
    assert detect_platform("https://jobs.lever.co/company/1234") == "lever"

def test_detect_ashby():
    assert detect_platform("https://jobs.ashbyhq.com/company/1234") == "ashby"

def test_detect_wantedly():
    assert detect_platform("https://www.wantedly.com/projects/1234") == "wantedly"

def test_detect_green_japan():
    assert detect_platform("https://www.green-japan.com/job/1234") == "green"

def test_detect_careercross():
    assert detect_platform("https://www.careercross.com/en/job/detail-1234") == "careercross"

def test_detect_generic_fallback():
    assert detect_platform("https://randomcompany.com/careers/apply") == "generic"

def test_base_form_filler_is_abstract():
    with pytest.raises(TypeError):
        BaseFormFiller()

def test_fill_result_defaults():
    r = FillResult(success=True)
    assert r.fields_filled == 0
    assert r.fields_skipped == 0
    assert r.error is None
