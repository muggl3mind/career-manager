#!/usr/bin/env python3
"""Tests for atomic CSV writes (job-search/scripts/core/csv_io.py).

target-companies.csv and applications.csv are the pipeline's source of
truth. The contract under test: the target file is never touched until
the temp file is complete and os.replace() runs, and on any failure the
old content survives with no temp litter left behind.
"""

import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'core'))

import csv_io
from csv_io import atomic_open, write_csv_atomic, write_csv_rows_atomic

HEADER = ['company', 'role', 'llm_score']
ROWS = [
    {'company': 'Acme Corp', 'role': 'Senior Accountant', 'llm_score': '80'},
    {'company': 'Globex, Inc.', 'role': 'Controller\n(remote)', 'llm_score': ''},
]


def _read_rows(path):
    with path.open(newline='', encoding='utf-8') as f:
        return list(csv.DictReader(f))


def _write_old(path):
    path.write_text('company,role,llm_score\r\nOldCo,Analyst,50\r\n', encoding='utf-8')


def _tmp_litter(directory):
    return [p for p in directory.iterdir() if p.suffix == '.tmp']


# ---------------------------------------------------------------------------
# Content correctness
# ---------------------------------------------------------------------------

def test_write_csv_atomic_round_trips_content(tmp_path):
    target = tmp_path / 'target-companies.csv'
    write_csv_atomic(target, ROWS, HEADER)
    assert _read_rows(target) == ROWS
    assert _tmp_litter(tmp_path) == []


def test_write_csv_atomic_overwrites_existing(tmp_path):
    target = tmp_path / 'target-companies.csv'
    _write_old(target)
    write_csv_atomic(target, ROWS, HEADER)
    assert _read_rows(target) == ROWS


def test_write_csv_atomic_creates_parent_dirs(tmp_path):
    target = tmp_path / 'data' / 'nested' / 'applications.csv'
    write_csv_atomic(target, ROWS, HEADER)
    assert _read_rows(target) == ROWS


def test_write_csv_atomic_ignores_extra_keys_by_default(tmp_path):
    target = tmp_path / 'target-companies.csv'
    rows = [dict(ROWS[0], stray_column='x')]
    write_csv_atomic(target, rows, HEADER)
    assert _read_rows(target) == [ROWS[0]]


def test_write_csv_rows_atomic_round_trips_raw_rows(tmp_path):
    target = tmp_path / 'target-companies.csv'
    raw = [HEADER, ['Acme Corp', 'Senior Accountant', '80']]
    write_csv_rows_atomic(target, raw)
    with target.open(newline='', encoding='utf-8') as f:
        assert list(csv.reader(f)) == raw


# ---------------------------------------------------------------------------
# Atomicity: target untouched until the final replace
# ---------------------------------------------------------------------------

def test_target_untouched_until_replace(tmp_path):
    target = tmp_path / 'target-companies.csv'
    _write_old(target)
    old_bytes = target.read_bytes()

    with atomic_open(target) as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        w.writerows(ROWS)
        f.flush()
        # Mid-write: new data exists only in the temp file.
        assert target.read_bytes() == old_bytes
        assert len(_tmp_litter(tmp_path)) == 1

    # After clean exit: replaced in one step, no litter.
    assert _read_rows(target) == ROWS
    assert _tmp_litter(tmp_path) == []


def test_crash_mid_write_preserves_old_content(tmp_path):
    target = tmp_path / 'target-companies.csv'
    _write_old(target)
    old_bytes = target.read_bytes()

    def exploding_rows():
        yield ROWS[0]
        raise RuntimeError('simulated crash mid-write')

    with pytest.raises(RuntimeError, match='simulated crash'):
        write_csv_atomic(target, exploding_rows(), HEADER)

    assert target.read_bytes() == old_bytes
    assert _tmp_litter(tmp_path) == []


def test_crash_mid_write_with_no_preexisting_file(tmp_path):
    target = tmp_path / 'target-companies.csv'

    def exploding_rows():
        raise RuntimeError('boom')
        yield  # pragma: no cover

    with pytest.raises(RuntimeError):
        write_csv_atomic(target, exploding_rows(), HEADER)

    assert not target.exists()
    assert _tmp_litter(tmp_path) == []


def test_failed_replace_preserves_old_and_cleans_temp(tmp_path, monkeypatch):
    target = tmp_path / 'target-companies.csv'
    _write_old(target)
    old_bytes = target.read_bytes()

    def failing_replace(src, dst):
        raise OSError('simulated replace failure')

    monkeypatch.setattr(csv_io.os, 'replace', failing_replace)
    with pytest.raises(OSError, match='simulated replace failure'):
        write_csv_atomic(target, ROWS, HEADER)

    assert target.read_bytes() == old_bytes
    assert _tmp_litter(tmp_path) == []


def test_extrasaction_raise_leaves_target_untouched(tmp_path):
    target = tmp_path / 'target-companies.csv'
    _write_old(target)
    old_bytes = target.read_bytes()

    rows = [dict(ROWS[0], stray_column='x')]
    with pytest.raises(ValueError):
        write_csv_atomic(target, rows, HEADER, extrasaction='raise')

    assert target.read_bytes() == old_bytes
    assert _tmp_litter(tmp_path) == []


# ---------------------------------------------------------------------------
# Writers are actually routed through csv_io
# ---------------------------------------------------------------------------

def test_known_writers_delegate_to_csv_io():
    """Every script that writes target-companies.csv must import csv_io."""
    scripts = Path(__file__).resolve().parents[2] / 'job-search' / 'scripts'
    writers = [
        scripts / 'core' / 'migrate_csv_columns.py',
        scripts / 'core' / 'target_companies_sync.py',
        scripts / 'ops' / 'merge_research.py',
        scripts / 'ops' / 'discovery_pipeline.py',
        scripts / 'ops' / 'migrate_lifecycle_columns.py',
        scripts / 'ops' / 'monitor_watchlist.py',
        scripts / 'ops' / 'fix_careers_urls.py',
        scripts / 'ops' / 'web_prospecting.py',
        scripts / 'ops' / 'apply_eval_results.py',
    ]
    for path in writers:
        text = path.read_text(encoding='utf-8')
        assert 'from csv_io import' in text, f'{path.name} does not use csv_io'
