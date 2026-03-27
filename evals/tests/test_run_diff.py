"""Tests for cross-run consistency diff."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'ops'))


def test_diff_detects_new_companies():
    from run_pipeline import compute_run_diff
    previous = {"companies": {"OldCo": {"score": 70, "path": "A"}}}
    current = {"OldCo": {"score": 70, "path": "A"}, "NewCo": {"score": 80, "path": "B"}}
    diff = compute_run_diff(previous, current)
    assert "NewCo" in diff["added"]
    assert len(diff["removed"]) == 0


def test_diff_detects_removed_high_score():
    from run_pipeline import compute_run_diff
    previous = {"companies": {"GoneCo": {"score": 75, "path": "A"}, "StayCo": {"score": 60, "path": "B"}}}
    current = {"StayCo": {"score": 60, "path": "B"}}
    diff = compute_run_diff(previous, current)
    assert "GoneCo" in diff["removed"]


def test_diff_detects_score_change():
    from run_pipeline import compute_run_diff
    previous = {"companies": {"Co": {"score": 50, "path": "A"}}}
    current = {"Co": {"score": 70, "path": "A"}}
    diff = compute_run_diff(previous, current)
    assert len(diff["score_changes"]) == 1
    assert diff["score_changes"][0]["company"] == "Co"


def test_diff_ignores_small_score_change():
    from run_pipeline import compute_run_diff
    previous = {"companies": {"Co": {"score": 50, "path": "A"}}}
    current = {"Co": {"score": 55, "path": "A"}}
    diff = compute_run_diff(previous, current)
    assert len(diff["score_changes"]) == 0


def test_first_run_no_snapshot(tmp_path):
    from run_pipeline import load_snapshot
    result = load_snapshot(tmp_path / "nonexistent.json")
    assert result is None
