#!/usr/bin/env python3
"""
Tests for the scoring gate: unscored jobs must not appear in target-companies.csv.
"""

import csv
import json
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

BASE = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(BASE / 'scripts' / 'ops'))
sys.path.insert(0, str(BASE / 'scripts' / 'core'))

from csv_schema import HEADER


# ---------------------------------------------------------------------------
# Test 1: export_pending returns (scored, all) with correct split
# ---------------------------------------------------------------------------

def test_unscored_jobs_not_in_scored_list(tmp_path):
    """Jobs without cached LLM scores must NOT appear in the scored list."""
    # Set up a temporary seen-jobs.json with one cached entry
    seen_jobs = {
        'https://example.com/job-scored': {
            'llm_score': 78,
            'role_family': 'AI Engineering',
            'llm_rationale': 'Good fit',
            'llm_flags': '',
            'llm_hard_pass': 'false',
            'llm_hard_pass_reason': '',
            'llm_evaluated_at': '2026-03-20T00:00:00Z',
        }
    }
    seen_path = tmp_path / 'seen-jobs.json'
    seen_path.write_text(json.dumps(seen_jobs))

    pending_path = tmp_path / 'pending-eval.json'

    jobs = [
        {
            'careers_url': 'https://example.com/job-scored',
            'company': 'ScoredCo',
            'open_positions': 'ML Engineer',
            'location_detected': 'New York',
            'notes': '',
            'source': 'jobspy',
        },
        {
            'careers_url': 'https://example.com/job-unscored',
            'company': 'UnscoredCo',
            'open_positions': 'Data Scientist',
            'location_detected': 'Remote',
            'notes': '',
            'source': 'jobspy',
        },
    ]

    # Patch file paths used by evaluate_jobs
    import evaluate_jobs
    original_seen = evaluate_jobs.SEEN_JOBS
    original_pending = evaluate_jobs.PENDING_EVAL
    evaluate_jobs.SEEN_JOBS = seen_path
    evaluate_jobs.PENDING_EVAL = pending_path

    try:
        scored, all_jobs = evaluate_jobs.export_pending(jobs, dry_run=False, verbose=False)
    finally:
        evaluate_jobs.SEEN_JOBS = original_seen
        evaluate_jobs.PENDING_EVAL = original_pending

    # Scored list should only contain the cached job
    assert len(scored) == 1
    assert scored[0]['company'] == 'ScoredCo'
    assert scored[0]['llm_score'] == 78

    # All jobs list should contain both
    assert len(all_jobs) == 2

    # Pending file should contain only the unscored job
    assert pending_path.exists()
    pending = json.loads(pending_path.read_text())
    assert len(pending) == 1
    assert pending[0]['company'] == 'UnscoredCo'


# ---------------------------------------------------------------------------
# Test 2: apply_eval_results adds new rows to target CSV
# ---------------------------------------------------------------------------

def test_apply_eval_adds_new_rows(tmp_path):
    """Eval results for jobs not in target CSV must be ADDED as new rows."""
    # Create a minimal target CSV with one existing row
    target_csv = tmp_path / 'target-companies.csv'
    existing_row = {h: '' for h in HEADER}
    existing_row.update({
        'rank': '1',
        'company': 'ExistingCo',
        'careers_url': 'https://existing.com/job',
        'llm_score': '80',
        'open_positions': 'Engineer',
        'source': 'jobspy',
        'validation_status': 'pass',
    })
    with target_csv.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        w.writerow(existing_row)

    # Create eval-results.json with one existing update + one NEW job
    eval_results = [
        {
            'careers_url': 'https://existing.com/job',
            'total_score': 85,
            'scores': {'technical': 40, 'domain': 45},
            'fit_summary': 'Updated fit',
            'red_flags': [],
            'hard_pass': False,
            'path_name': 'AI Engineering',
        },
        {
            'careers_url': 'https://newjob.com/apply',
            'total_score': 72,
            'scores': {'technical': 35, 'domain': 37},
            'fit_summary': 'New job fit',
            'red_flags': ['no funding info'],
            'hard_pass': False,
            'path_name': 'Data Engineering',
        },
    ]
    eval_path = tmp_path / 'eval-results.json'
    eval_path.write_text(json.dumps(eval_results))

    # Create pending-eval.json with metadata for the new job
    pending_eval = [
        {
            'careers_url': 'https://newjob.com/apply',
            'title': 'Data Engineer',
            'company': 'NewCo',
            'location': 'San Francisco',
            'source': 'indeed',
            'role_family': 'Data Engineering',
        }
    ]
    pending_path = tmp_path / 'pending-eval.json'
    pending_path.write_text(json.dumps(pending_eval))

    # Create empty raw CSV
    raw_csv = tmp_path / 'raw-discovery.csv'
    with raw_csv.open('w', newline='') as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()

    # Create empty seen-jobs.json
    seen_path = tmp_path / 'seen-jobs.json'
    seen_path.write_text('{}')

    # Patch apply_eval_results paths and run
    import apply_eval_results
    orig = {
        'TARGET_CSV': apply_eval_results.TARGET_CSV,
        'RAW_CSV': apply_eval_results.RAW_CSV,
        'SEEN_JOBS': apply_eval_results.SEEN_JOBS,
        'EVAL_RESULTS': apply_eval_results.EVAL_RESULTS,
        'PENDING_EVAL': apply_eval_results.PENDING_EVAL,
    }
    apply_eval_results.TARGET_CSV = target_csv
    apply_eval_results.RAW_CSV = raw_csv
    apply_eval_results.SEEN_JOBS = seen_path
    apply_eval_results.EVAL_RESULTS = eval_path
    apply_eval_results.PENDING_EVAL = pending_path

    try:
        with patch('sys.argv', ['apply_eval_results.py']):
            ret = apply_eval_results.main()
    finally:
        for k, v in orig.items():
            setattr(apply_eval_results, k, v)

    assert ret == 0

    # Read the target CSV and verify
    with target_csv.open() as f:
        rows = list(csv.DictReader(f))

    urls = {r['careers_url'] for r in rows}
    assert 'https://existing.com/job' in urls, "Existing row should still be present"
    assert 'https://newjob.com/apply' in urls, "New job should have been added"

    # Check the new row has correct data
    new_row = [r for r in rows if r['careers_url'] == 'https://newjob.com/apply'][0]
    assert new_row['company'] == 'NewCo'
    assert new_row['llm_score'] == '72'
    assert new_row['open_positions'] == 'Data Engineer'
    assert new_row['source'] == 'indeed'
    assert new_row['llm_rationale'] == 'New job fit'

    # Check existing row was updated
    existing = [r for r in rows if r['careers_url'] == 'https://existing.com/job'][0]
    assert existing['llm_score'] == '85'


if __name__ == '__main__':
    pytest.main([__file__, '-v'])
