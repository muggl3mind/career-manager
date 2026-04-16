#!/usr/bin/env python3
"""
Tests for the Stage 1 lifecycle-column migration.

Run: pytest career-manager/evals/tests/test_lifecycle_migration.py -v
"""
from __future__ import annotations

import csv
import importlib.util
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
MIGRATE_SCRIPT = REPO / 'job-search' / 'scripts' / 'ops' / 'migrate_lifecycle_columns.py'


def _load_migrate_module():
    spec = importlib.util.spec_from_file_location('migrate_lifecycle_columns', MIGRATE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    sys.modules['migrate_lifecycle_columns'] = module
    spec.loader.exec_module(module)
    return module


MIG = _load_migrate_module()


def _write_csv(path: Path, fieldnames: list, rows: list) -> None:
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fieldnames)
        w.writeheader()
        w.writerows(rows)


def _read_csv(path: Path) -> tuple:
    with path.open(encoding='utf-8') as f:
        r = csv.DictReader(f)
        fields = list(r.fieldnames)
        rows = list(r)
    return fields, rows


class TestMigrationAddsColumns:
    def test_adds_three_new_columns(self, tmp_path):
        csv_path = tmp_path / 'target.csv'
        _write_csv(csv_path, ['company', 'validation_status', 'llm_evaluated_at'], [
            {'company': 'A', 'validation_status': 'pass', 'llm_evaluated_at': '2026-04-10'},
        ])

        summary = MIG.migrate(csv_path)

        fields, _ = _read_csv(csv_path)
        assert 'lifecycle_state' in fields
        assert 'last_verified_at' in fields
        assert 'watching_run_count' in fields
        assert summary['status'] == 'migrated'

    def test_preserves_existing_column_order(self, tmp_path):
        csv_path = tmp_path / 'target.csv'
        original_fields = ['company', 'website', 'llm_score', 'validation_status', 'llm_evaluated_at']
        _write_csv(csv_path, original_fields, [
            {'company': 'A', 'website': 'a.com', 'llm_score': '80',
             'validation_status': 'pass', 'llm_evaluated_at': '2026-04-10'},
        ])

        MIG.migrate(csv_path)

        fields, _ = _read_csv(csv_path)
        assert fields[:len(original_fields)] == original_fields


class TestMigrationSeedsRows:
    def test_pass_rows_seed_to_active(self, tmp_path):
        csv_path = tmp_path / 'target.csv'
        _write_csv(csv_path, ['company', 'validation_status', 'llm_evaluated_at'], [
            {'company': 'A', 'validation_status': 'pass', 'llm_evaluated_at': '2026-04-10'},
            {'company': 'B', 'validation_status': 'pass', 'llm_evaluated_at': '2026-04-11'},
        ])

        MIG.migrate(csv_path)

        _, rows = _read_csv(csv_path)
        assert all(r['lifecycle_state'] == 'active' for r in rows)

    def test_non_pass_rows_seed_to_watching(self, tmp_path):
        csv_path = tmp_path / 'target.csv'
        _write_csv(csv_path, ['company', 'validation_status', 'llm_evaluated_at'], [
            {'company': 'A', 'validation_status': 'watch_list', 'llm_evaluated_at': '2026-04-10'},
            {'company': 'B', 'validation_status': '', 'llm_evaluated_at': ''},
        ])

        MIG.migrate(csv_path)

        _, rows = _read_csv(csv_path)
        assert all(r['lifecycle_state'] == 'watching' for r in rows)

    def test_last_verified_at_copies_llm_evaluated_at(self, tmp_path):
        csv_path = tmp_path / 'target.csv'
        _write_csv(csv_path, ['company', 'validation_status', 'llm_evaluated_at'], [
            {'company': 'A', 'validation_status': 'pass', 'llm_evaluated_at': '2026-04-10T12:00:00'},
        ])

        MIG.migrate(csv_path)

        _, rows = _read_csv(csv_path)
        assert rows[0]['last_verified_at'] == '2026-04-10T12:00:00'

    def test_watching_run_count_seeds_to_zero(self, tmp_path):
        csv_path = tmp_path / 'target.csv'
        _write_csv(csv_path, ['company', 'validation_status', 'llm_evaluated_at'], [
            {'company': 'A', 'validation_status': 'pass', 'llm_evaluated_at': '2026-04-10'},
            {'company': 'B', 'validation_status': 'watch_list', 'llm_evaluated_at': '2026-04-11'},
        ])

        MIG.migrate(csv_path)

        _, rows = _read_csv(csv_path)
        assert all(r['watching_run_count'] == '0' for r in rows)


class TestMigrationIdempotency:
    def test_second_run_is_noop(self, tmp_path):
        csv_path = tmp_path / 'target.csv'
        _write_csv(csv_path, ['company', 'validation_status', 'llm_evaluated_at'], [
            {'company': 'A', 'validation_status': 'pass', 'llm_evaluated_at': '2026-04-10'},
        ])

        MIG.migrate(csv_path)
        summary = MIG.migrate(csv_path)

        assert summary['status'] == 'already_migrated'

    def test_second_run_does_not_change_data(self, tmp_path):
        csv_path = tmp_path / 'target.csv'
        _write_csv(csv_path, ['company', 'validation_status', 'llm_evaluated_at'], [
            {'company': 'A', 'validation_status': 'pass', 'llm_evaluated_at': '2026-04-10'},
        ])

        MIG.migrate(csv_path)
        _, rows_before = _read_csv(csv_path)

        # Manually flip a value that shouldn't be touched on a re-run
        rows_before[0]['watching_run_count'] = '3'
        _write_csv(csv_path, list(rows_before[0].keys()), rows_before)

        MIG.migrate(csv_path)
        _, rows_after = _read_csv(csv_path)

        assert rows_after[0]['watching_run_count'] == '3'


class TestDryRun:
    def test_dry_run_does_not_write(self, tmp_path):
        csv_path = tmp_path / 'target.csv'
        _write_csv(csv_path, ['company', 'validation_status', 'llm_evaluated_at'], [
            {'company': 'A', 'validation_status': 'pass', 'llm_evaluated_at': '2026-04-10'},
        ])

        MIG.migrate(csv_path, dry_run=True)

        fields, _ = _read_csv(csv_path)
        assert 'lifecycle_state' not in fields

    def test_dry_run_returns_correct_summary(self, tmp_path):
        csv_path = tmp_path / 'target.csv'
        _write_csv(csv_path, ['company', 'validation_status', 'llm_evaluated_at'], [
            {'company': 'A', 'validation_status': 'pass', 'llm_evaluated_at': '2026-04-10'},
            {'company': 'B', 'validation_status': 'watch_list', 'llm_evaluated_at': '2026-04-11'},
        ])

        summary = MIG.migrate(csv_path, dry_run=True)

        assert summary['status'] == 'migrated'
        assert summary['dry_run'] is True
        assert summary['rows'] == 2
        assert summary['state_counts']['active'] == 1
        assert summary['state_counts']['watching'] == 1


class TestMissingFile:
    def test_raises_on_missing_csv(self, tmp_path):
        import pytest
        with pytest.raises(FileNotFoundError):
            MIG.migrate(tmp_path / 'does-not-exist.csv')
