#!/usr/bin/env python3
"""Tests for the pending-eval shard export (plan item 15a/15c).

One eval agent used to be handed the full pending batch, hundreds of
jobs in bad weeks. Batches above EVAL_SHARD_SIZE now also export
pending-eval-shard-N.json work units of at most EVAL_SHARD_SIZE jobs.
The legacy pending-eval.json keeps the full array in every case because
apply_eval_results.py reads it for job metadata, and small batches keep
producing only that file so existing flows are untouched.

Also pins the compact (no indent) agent-facing JSON.
"""

import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
OPS = REPO / 'job-search' / 'scripts' / 'ops'
sys.path.insert(0, str(OPS))

import evaluate_jobs


def _jobs(n: int) -> list:
    return [
        {
            'careers_url': f'https://example.com/job-{i}',
            'company': f'Company {i}',
            'open_positions': 'Engineer',
            'location_detected': 'Remote',
            'notes': '',
            'source': 'jobspy',
        }
        for i in range(n)
    ]


@pytest.fixture
def eval_paths(tmp_path, monkeypatch):
    seen_path = tmp_path / 'seen-jobs.json'
    pending_path = tmp_path / 'pending-eval.json'
    monkeypatch.setattr(evaluate_jobs, 'SEEN_JOBS', seen_path)
    monkeypatch.setattr(evaluate_jobs, 'PENDING_EVAL', pending_path)
    return seen_path, pending_path


def _shards(tmp_path: Path) -> list:
    return sorted(tmp_path.glob('pending-eval-shard-*.json'))


class TestSmallBatchLegacy:
    def test_small_batch_writes_only_legacy_file(self, eval_paths, tmp_path):
        _, pending_path = eval_paths
        evaluate_jobs.export_pending(_jobs(3), dry_run=False, verbose=False)

        assert pending_path.exists()
        assert _shards(tmp_path) == []
        urls = [p['careers_url'] for p in json.loads(pending_path.read_text())]
        assert urls == [f'https://example.com/job-{i}' for i in range(3)]

    def test_batch_at_shard_size_stays_single_file(self, eval_paths, tmp_path):
        _, pending_path = eval_paths
        evaluate_jobs.export_pending(
            _jobs(5), dry_run=False, verbose=False, shard_size=5)

        assert pending_path.exists()
        assert _shards(tmp_path) == []

    def test_default_shard_size_is_40(self):
        assert evaluate_jobs.EVAL_SHARD_SIZE == 40


class TestShardedBatch:
    def test_large_batch_writes_shards_plus_legacy(self, eval_paths, tmp_path):
        _, pending_path = eval_paths
        evaluate_jobs.export_pending(
            _jobs(10), dry_run=False, verbose=False, shard_size=4)

        names = [p.name for p in _shards(tmp_path)]
        assert names == [
            'pending-eval-shard-1.json',
            'pending-eval-shard-2.json',
            'pending-eval-shard-3.json',
        ]
        sizes = [len(json.loads(p.read_text())) for p in _shards(tmp_path)]
        assert sizes == [4, 4, 2]
        # Legacy file still carries the full array for apply_eval_results.
        assert len(json.loads(pending_path.read_text())) == 10

    def test_shards_preserve_batch_order_and_cover_everything(self, eval_paths, tmp_path):
        _, pending_path = eval_paths
        evaluate_jobs.export_pending(
            _jobs(9), dry_run=False, verbose=False, shard_size=4)

        legacy_urls = [p['careers_url'] for p in json.loads(pending_path.read_text())]
        shard_urls = []
        for path in _shards(tmp_path):
            shard_urls.extend(p['careers_url'] for p in json.loads(path.read_text()))
        assert shard_urls == legacy_urls

    def test_one_over_shard_size_makes_two_shards(self, eval_paths, tmp_path):
        evaluate_jobs.export_pending(
            _jobs(5), dry_run=False, verbose=False, shard_size=4)
        sizes = [len(json.loads(p.read_text())) for p in _shards(tmp_path)]
        assert sizes == [4, 1]

    def test_write_pending_export_returns_shard_paths(self, eval_paths, tmp_path):
        _, pending_path = eval_paths
        pending = [{'careers_url': f'u{i}'} for i in range(6)]
        written = evaluate_jobs.write_pending_export(pending, shard_size=3)
        assert [p.name for p in written] == [
            'pending-eval-shard-1.json', 'pending-eval-shard-2.json']

        written = evaluate_jobs.write_pending_export(pending[:2], shard_size=3)
        assert written == [pending_path]


class TestStaleShardCleanup:
    def test_small_batch_removes_stale_shards(self, eval_paths, tmp_path):
        stale = tmp_path / 'pending-eval-shard-7.json'
        stale.write_text('[]')

        evaluate_jobs.export_pending(_jobs(2), dry_run=False, verbose=False)
        assert not stale.exists()

    def test_reshard_removes_extra_old_shards(self, eval_paths, tmp_path):
        evaluate_jobs.export_pending(
            _jobs(12), dry_run=False, verbose=False, shard_size=3)
        assert len(_shards(tmp_path)) == 4

        evaluate_jobs.export_pending(
            _jobs(5), dry_run=False, verbose=False, shard_size=3)
        assert [p.name for p in _shards(tmp_path)] == [
            'pending-eval-shard-1.json', 'pending-eval-shard-2.json']

    def test_empty_pending_clears_shards(self, eval_paths, tmp_path):
        stale = tmp_path / 'pending-eval-shard-1.json'
        stale.write_text('[]')

        evaluate_jobs.export_pending([], dry_run=False, verbose=False)
        assert not stale.exists()

    def test_dry_run_touches_nothing(self, eval_paths, tmp_path):
        _, pending_path = eval_paths
        stale = tmp_path / 'pending-eval-shard-1.json'
        stale.write_text('[]')

        evaluate_jobs.export_pending(
            _jobs(10), dry_run=True, verbose=False, shard_size=4)
        assert not pending_path.exists()
        assert stale.exists()
        assert stale.read_text() == '[]'


class TestCompactJson:
    def test_exports_have_no_indentation(self, eval_paths, tmp_path):
        _, pending_path = eval_paths
        evaluate_jobs.export_pending(
            _jobs(6), dry_run=False, verbose=False, shard_size=4)

        for path in [pending_path, *_shards(tmp_path)]:
            assert '\n' not in path.read_text(encoding='utf-8')
