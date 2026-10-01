#!/usr/bin/env python3
"""Tests for null-vs-0 score separation and confidence persistence.

Finding H2: an honest zero score (0 yes of 5+ evaluated dimensions) was
written as an empty cell, and unscored (needs_research) companies were
dropped from the merge entirely, making them invisible. The write path
must keep the two states distinct: '' means "not scored", '0' is a real
verdict.

Finding M9: llm_dimensions_evaluated was collected from agents and then
thrown away. It now lives in the CSV schema and is persisted by every
merge script, so a 90-on-10-dimensions is distinguishable from a
90-on-5-dimensions.
"""

import csv
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CORE = REPO / 'job-search' / 'scripts' / 'core'
OPS = REPO / 'job-search' / 'scripts' / 'ops'
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(OPS))

from csv_schema import HEADER
from merge_validation import DEFAULT_DIMENSION_KEYS
from scoring import NEEDS_RESEARCH_FLAG

DIMS = sorted(DEFAULT_DIMENSION_KEYS)


def _scores(yes=0, no=0):
    assert yes + no <= len(DIMS)
    d = {}
    for key in DIMS[:yes]:
        d[key] = 1
    for key in DIMS[yes:yes + no]:
        d[key] = 0
    return d


def _write_target_csv(path, rows):
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=HEADER, extrasaction='ignore')
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, '') for k in HEADER})


def _read_rows(path):
    with path.open() as f:
        return list(csv.DictReader(f))


EXISTING = {
    'company': 'ExistingCo',
    'careers_url': 'https://existing.example/careers',
    'validation_status': 'pass',
    'llm_score': '70',
    'lifecycle_state': 'active',
    'watching_run_count': '0',
}


def test_schema_has_dimensions_evaluated_column():
    assert 'llm_dimensions_evaluated' in HEADER


@pytest.fixture
def eval_env(tmp_path, monkeypatch):
    import apply_eval_results as aer

    data = tmp_path / 'data'
    data.mkdir()
    monkeypatch.setattr(aer, 'DATA', data)
    monkeypatch.setattr(aer, 'TARGET_CSV', data / 'target-companies.csv')
    monkeypatch.setattr(aer, 'RAW_CSV', data / 'raw-discovery.csv')
    monkeypatch.setattr(aer, 'SEEN_JOBS', data / 'seen-jobs.json')
    monkeypatch.setattr(aer, 'EVAL_RESULTS', data / 'eval-results.json')
    monkeypatch.setattr(aer, 'PENDING_EVAL', data / 'pending-eval.json')
    _write_target_csv(data / 'target-companies.csv', [EXISTING])
    return aer, data


class TestApplyEvalResults:
    def test_honest_zero_stored_as_zero_not_empty(self, eval_env):
        """The H2 follow-up: 0 yes of 5 evaluated is a real verdict and
        must be stored as 0, not conflated with "not scored"."""
        aer, data = eval_env
        (data / 'eval-results.json').write_text(json.dumps([{
            'careers_url': 'https://existing.example/careers',
            'total_score': 0,
            'scores': _scores(yes=0, no=5),
            'fit_summary': 'fails every evaluable dimension',
        }]))

        rc = aer.cmd_apply(dry_run=False)
        assert rc == 0

        rows = {r['company']: r for r in _read_rows(data / 'target-companies.csv')}
        row = rows['ExistingCo']
        assert row['llm_score'] == '0'
        assert row['llm_dimensions_evaluated'] == '5'
        assert NEEDS_RESEARCH_FLAG not in row['llm_flags']
        assert row['llm_evaluated_at']

    def test_needs_research_stored_as_empty_with_flag(self, eval_env):
        aer, data = eval_env
        (data / 'eval-results.json').write_text(json.dumps([{
            'careers_url': 'https://existing.example/careers',
            'total_score': 0,
            'scores': _scores(yes=2, no=1),  # only 3 evaluated: below minimum
            'fit_summary': 'thin job description',
        }]))

        aer.cmd_apply(dry_run=False)

        rows = {r['company']: r for r in _read_rows(data / 'target-companies.csv')}
        row = rows['ExistingCo']
        assert row['llm_score'] == ''
        assert NEEDS_RESEARCH_FLAG in row['llm_flags']
        assert row['llm_dimensions_evaluated'] == '3'

    def test_new_job_with_honest_zero_is_added_not_dropped(self, eval_env):
        """Previously `if not total: continue` silently dropped 0-scored
        new jobs; they must be visible in the CSV."""
        aer, data = eval_env
        url = 'https://zero.example/careers'
        (data / 'eval-results.json').write_text(json.dumps([{
            'careers_url': url,
            'total_score': 0,
            'scores': _scores(yes=0, no=6),
            'fit_summary': 'poor fit but evaluated',
        }]))
        (data / 'pending-eval.json').write_text(json.dumps([
            {'careers_url': url, 'company': 'ZeroCo', 'title': 'Analyst'},
        ]))

        aer.cmd_apply(dry_run=False)

        rows = {r['company']: r for r in _read_rows(data / 'target-companies.csv')}
        assert 'ZeroCo' in rows
        assert rows['ZeroCo']['llm_score'] == '0'
        assert rows['ZeroCo']['llm_dimensions_evaluated'] == '6'

    def test_new_unscored_job_visible_with_needs_research(self, eval_env):
        aer, data = eval_env
        url = 'https://unknown.example/careers'
        (data / 'eval-results.json').write_text(json.dumps([{
            'careers_url': url,
            'total_score': 0,
            'scores': _scores(yes=1, no=1),  # 2 evaluated: needs_research
            'fit_summary': 'not enough information',
        }]))
        (data / 'pending-eval.json').write_text(json.dumps([
            {'careers_url': url, 'company': 'MysteryCo', 'title': 'PM'},
        ]))

        aer.cmd_apply(dry_run=False)

        rows = {r['company']: r for r in _read_rows(data / 'target-companies.csv')}
        assert 'MysteryCo' in rows
        assert rows['MysteryCo']['llm_score'] == ''
        assert NEEDS_RESEARCH_FLAG in rows['MysteryCo']['llm_flags']

    def test_seen_jobs_cache_distinguishes_zero_from_unscored(self, eval_env):
        aer, data = eval_env
        (data / 'eval-results.json').write_text(json.dumps([{
            'careers_url': 'https://existing.example/careers',
            'total_score': 0,
            'scores': _scores(yes=0, no=5),
        }]))
        aer.cmd_apply(dry_run=False)
        seen = json.loads((data / 'seen-jobs.json').read_text())
        entry = seen['https://existing.example/careers']
        assert entry['llm_score'] == '0'
        assert entry['llm_dimensions_evaluated'] == '5'


class TestWebProspectingMerge:
    def test_dimensions_persisted_and_zero_score_dated(self, tmp_path):
        import web_prospecting as wp

        _write_target_csv(tmp_path / 'target-companies.csv', [])
        results = [
            {
                'company': 'StrongCo',
                'llm_score': 90,
                'llm_dimensions_evaluated': 10,
                'prospect_status': 'active_role',
                'open_positions': 'PM',
            },
            {
                'company': 'ZeroCo',
                'llm_score': 0,
                'llm_dimensions_evaluated': 5,
                'prospect_status': 'active_role',
                'open_positions': 'PM',
            },
        ]
        rc = wp._do_merge(results, tmp_path, dry_run=False)
        assert rc == 0

        rows = {r['company']: r for r in _read_rows(tmp_path / 'target-companies.csv')}
        assert rows['StrongCo']['llm_dimensions_evaluated'] == '10'
        assert rows['ZeroCo']['llm_score'] == '0'
        assert rows['ZeroCo']['llm_dimensions_evaluated'] == '5'
        # An honest zero is a dated evaluation (H2: previously the
        # timestamp was only written for truthy scores).
        assert rows['ZeroCo']['llm_evaluated_at']


class TestMonitorMerge:
    def test_dimensions_persisted_on_update(self, tmp_path, monkeypatch):
        import monitor_watchlist as mw

        data = tmp_path / 'data'
        data.mkdir()
        monkeypatch.setattr(mw, 'DATA', data)
        monkeypatch.setattr(mw, 'TARGET_CSV', data / 'target-companies.csv')
        monkeypatch.setattr(mw, 'SEEN_COMPANIES', data / 'seen-companies.json')
        monkeypatch.setattr(mw, 'MONITOR_CONTEXT', data / 'monitor-context.json')
        monkeypatch.setattr(mw, 'MONITOR_RESULTS', data / 'monitor-results.json')
        _write_target_csv(data / 'target-companies.csv', [EXISTING])
        (data / 'monitor-results.json').write_text(json.dumps([{
            'company': 'ExistingCo',
            'status': 'active_role',
            'open_positions': 'PM',
            'llm_score': 87,
            'llm_dimensions_evaluated': 8,
        }]))

        rc = mw.cmd_merge(dry_run=False)
        assert rc == 0

        rows = {r['company']: r for r in _read_rows(data / 'target-companies.csv')}
        assert rows['ExistingCo']['llm_score'] == '87'
        assert rows['ExistingCo']['llm_dimensions_evaluated'] == '8'
