"""Tests for path coverage check logic."""
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'ops'))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'core'))


def test_coverage_counts_by_normalized_path():
    from run_pipeline import compute_path_coverage
    rows = [
        {"role_family": "Accounting Software / Fintech SaaS", "validation_status": "pass"},
        {"role_family": "Accounting Software / Fintech SaaS", "validation_status": "pass"},
        {"role_family": "domain operations & Alternative Investments", "validation_status": "pass"},
        {"role_family": "", "validation_status": "pass"},
    ]
    coverage = compute_path_coverage(rows)
    assert coverage.get("Accounting Software / Fintech SaaS", 0) == 2
    assert coverage.get("domain operations & Alternative Investments", 0) == 1
    assert "Uncategorized" in coverage


def test_coverage_flags_thin_paths():
    from run_pipeline import find_thin_paths
    coverage = {"Path A": 14, "Path B": 5, "Path C": 8}
    thin = find_thin_paths(coverage, threshold=8)
    assert "Path B" in thin
    assert "Path A" not in thin
    assert "Path C" not in thin
