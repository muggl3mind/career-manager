"""Verify apply_eval_results.py merges per-shard eval files."""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(ROOT / 'job-search' / 'scripts' / 'ops'))
sys.path.insert(0, str(ROOT / 'job-search' / 'scripts' / 'core'))


def _write_target(csv_path: Path) -> None:
    from csv_schema import HEADER
    with csv_path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()


def _make_eval_row(url: str, score: int, company: str = 'ExampleCo') -> dict:
    return {
        'careers_url': url,
        'actual_company': company,
        'path_name': 'AI in Finance / Accounting Tech',
        'scores': {'background_asset': 1, 'ai_central': 1, 'can_influence': 1,
                   'non_traditional_welcome': 1, 'comp_200k_path': 1,
                   'growth_path': 1, 'funding_supports_comp': 1,
                   'problems_exciting': 1, 'culture_public_voice': 1,
                   'global_leverage': 1},
        'total_score': score,
        'fit_summary': f'{company} fit',
        'hard_pass': False,
        'hard_pass_reason': '',
        'red_flags': [],
    }


def test_load_eval_results_merges_shards(tmp_path, monkeypatch):
    import apply_eval_results as aer

    shard1 = [_make_eval_row('https://a.example.com/a', 90, 'AlphaCo')]
    shard2 = [_make_eval_row('https://b.example.com/b', 80, 'BetaCo')]
    shard3 = [_make_eval_row('https://c.example.com/c', 70, 'GammaCo')]
    (tmp_path / 'eval-results-shard-1.json').write_text(json.dumps(shard1))
    (tmp_path / 'eval-results-shard-2.json').write_text(json.dumps(shard2))
    (tmp_path / 'eval-results-shard-3.json').write_text(json.dumps(shard3))

    monkeypatch.setattr(aer, 'EVAL_RESULTS', tmp_path / 'eval-results.json')

    merged = aer._load_eval_results()
    assert len(merged) == 3
    urls = {r['careers_url'] for r in merged}
    assert urls == {'https://a.example.com/a', 'https://b.example.com/b',
                    'https://c.example.com/c'}


def test_shard_duplicate_urls_later_wins(tmp_path, monkeypatch):
    import apply_eval_results as aer

    url = 'https://dup.example.com/r'
    shard1 = [_make_eval_row(url, 60, 'OldVerdict')]
    shard2 = [_make_eval_row(url, 90, 'NewVerdict')]
    (tmp_path / 'eval-results-shard-1.json').write_text(json.dumps(shard1))
    (tmp_path / 'eval-results-shard-2.json').write_text(json.dumps(shard2))

    monkeypatch.setattr(aer, 'EVAL_RESULTS', tmp_path / 'eval-results.json')

    merged = aer._load_eval_results()
    assert len(merged) == 1
    assert merged[0]['total_score'] == 90
    assert merged[0]['actual_company'] == 'NewVerdict'


def test_falls_back_to_single_file_when_no_shards(tmp_path, monkeypatch):
    import apply_eval_results as aer

    rows = [_make_eval_row('https://single.example.com/x', 85)]
    (tmp_path / 'eval-results.json').write_text(json.dumps(rows))

    monkeypatch.setattr(aer, 'EVAL_RESULTS', tmp_path / 'eval-results.json')

    merged = aer._load_eval_results()
    assert len(merged) == 1
    assert merged[0]['careers_url'] == 'https://single.example.com/x'


def test_returns_empty_when_neither_present(tmp_path, monkeypatch):
    import apply_eval_results as aer
    monkeypatch.setattr(aer, 'EVAL_RESULTS', tmp_path / 'eval-results.json')
    assert aer._load_eval_results() == []


def test_apply_cleanup_removes_shard_files(tmp_path, monkeypatch):
    """After a successful apply, shard files are deleted (not left to
    pollute the next run)."""
    import apply_eval_results as aer

    shard1 = [_make_eval_row('https://k.example.com/k', 90, 'KappaCo')]
    (tmp_path / 'eval-results-shard-1.json').write_text(json.dumps(shard1))
    (tmp_path / 'pending-eval-shard-1.json').write_text(json.dumps([{
        'careers_url': 'https://k.example.com/k',
        'title': 'FDE',
        'company': 'KappaCo',
        'location': 'Remote',
        'description': 'Ship agentic AI to finance customers',
        'role_family': 'AI in Finance / Accounting Tech',
        'is_agency': False,
        'source': 'jobspy',
    }]))
    target_csv = tmp_path / 'target-companies.csv'
    raw_csv = tmp_path / 'raw-discovery.csv'
    seen_jobs = tmp_path / 'seen-jobs.json'
    _write_target(target_csv)
    _write_target(raw_csv)

    monkeypatch.setattr(aer, 'DATA', tmp_path)
    monkeypatch.setattr(aer, 'TARGET_CSV', target_csv)
    monkeypatch.setattr(aer, 'RAW_CSV', raw_csv)
    monkeypatch.setattr(aer, 'SEEN_JOBS', seen_jobs)
    monkeypatch.setattr(aer, 'EVAL_RESULTS', tmp_path / 'eval-results.json')
    monkeypatch.setattr(aer, 'PENDING_EVAL', tmp_path / 'pending-eval.json')
    monkeypatch.setattr(aer, '_sync_xlsx', lambda: None)

    rc = aer.cmd_apply(dry_run=False)
    assert rc == 0
    assert not (tmp_path / 'eval-results-shard-1.json').exists()
    assert not (tmp_path / 'pending-eval-shard-1.json').exists()
