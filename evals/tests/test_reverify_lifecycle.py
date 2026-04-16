#!/usr/bin/env python3
"""
Tests for Stage 4 — re-verify pass and lifecycle state transitions.

Covers the _apply_lifecycle_transition helper which owns the state machine:
  active_role           → active (verified)
  no_change + reachable → active (no change)
  no_change + fetch_empty → watching (incremented; archived if grace exceeded)
  watch_list            → watching (role closed; archived if grace exceeded)

Run: pytest career-manager/evals/tests/test_reverify_lifecycle.py -v
"""
from __future__ import annotations

import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'job-search' / 'scripts' / 'core'))
sys.path.insert(0, str(REPO / 'job-search' / 'scripts' / 'ops'))

# Provide a dummy search-config.json before importing monitor_watchlist,
# because the module loads config at import time.
_DUMMY_CFG = REPO / 'job-search' / 'data' / 'search-config.json'

import monitor_watchlist as MW  # noqa: E402

NOW = '2026-04-15T12:00:00+00:00'


def _active_row(watching_count: int = 0) -> dict:
    return {
        'company': 'ACo',
        'lifecycle_state': 'active',
        'last_verified_at': '2026-04-01T00:00:00+00:00',
        'watching_run_count': str(watching_count),
    }


def _watching_row(watching_count: int) -> dict:
    return {
        'company': 'BCo',
        'lifecycle_state': 'watching',
        'last_verified_at': '2026-03-20T00:00:00+00:00',
        'watching_run_count': str(watching_count),
    }


class TestActiveRole:
    def test_active_role_keeps_active(self):
        row = _active_row()
        state = MW._apply_lifecycle_transition(
            row, {'status': 'active_role'}, archive_grace_runs=2, now_ts=NOW)
        assert state == 'active'
        assert row['lifecycle_state'] == 'active'
        assert row['last_verified_at'] == NOW
        assert row['watching_run_count'] == '0'

    def test_active_role_recovers_watching_company(self):
        """Company was in watching from last run; this run confirms role → back to active."""
        row = _watching_row(watching_count=1)
        state = MW._apply_lifecycle_transition(
            row, {'status': 'active_role'}, archive_grace_runs=2, now_ts=NOW)
        assert state == 'active'
        assert row['lifecycle_state'] == 'active'
        assert row['watching_run_count'] == '0'
        assert row['last_verified_at'] == NOW


class TestNoChange:
    def test_no_change_reachable_stays_active(self):
        row = _active_row()
        state = MW._apply_lifecycle_transition(
            row, {'status': 'no_change', 'llm_flags': ''},
            archive_grace_runs=2, now_ts=NOW)
        assert state == 'active'
        assert row['lifecycle_state'] == 'active'
        assert row['last_verified_at'] == NOW
        assert row['watching_run_count'] == '0'

    def test_no_change_fetch_empty_flips_to_watching(self):
        row = _active_row()
        state = MW._apply_lifecycle_transition(
            row, {'status': 'no_change', 'llm_flags': 'fetch_empty'},
            archive_grace_runs=2, now_ts=NOW)
        assert state == 'watching'
        assert row['lifecycle_state'] == 'watching'
        assert row['watching_run_count'] == '1'
        # last_verified_at NOT updated
        assert row['last_verified_at'] == '2026-04-01T00:00:00+00:00'

    def test_no_change_fetch_empty_preserves_last_verified(self):
        """Rate-limited rows must not look freshly verified."""
        row = _active_row()
        original = row['last_verified_at']
        MW._apply_lifecycle_transition(
            row, {'status': 'no_change', 'llm_flags': 'fetch_empty|other'},
            archive_grace_runs=2, now_ts=NOW)
        assert row['last_verified_at'] == original


class TestWatchList:
    def test_watch_list_flips_active_to_watching(self):
        row = _active_row()
        state = MW._apply_lifecycle_transition(
            row, {'status': 'watch_list'}, archive_grace_runs=2, now_ts=NOW)
        assert state == 'watching'
        assert row['lifecycle_state'] == 'watching'
        assert row['watching_run_count'] == '1'
        assert row['last_verified_at'] == '2026-04-01T00:00:00+00:00'

    def test_watch_list_increments_watching_count(self):
        row = _watching_row(watching_count=1)
        state = MW._apply_lifecycle_transition(
            row, {'status': 'watch_list'}, archive_grace_runs=3, now_ts=NOW)
        assert state == 'watching'
        assert row['watching_run_count'] == '2'


class TestArchival:
    def test_watching_count_at_grace_archives(self):
        row = _watching_row(watching_count=1)
        state = MW._apply_lifecycle_transition(
            row, {'status': 'watch_list'}, archive_grace_runs=2, now_ts=NOW)
        assert state == 'archived'
        assert row['lifecycle_state'] == 'archived'
        assert row['watching_run_count'] == '2'

    def test_watching_count_above_grace_archives(self):
        row = _watching_row(watching_count=5)
        state = MW._apply_lifecycle_transition(
            row, {'status': 'watch_list'}, archive_grace_runs=2, now_ts=NOW)
        assert state == 'archived'

    def test_archived_row_can_recover_on_active_role(self):
        """If somehow an archived row gets re-verified with active_role, it recovers."""
        row = {
            'company': 'ZCo',
            'lifecycle_state': 'archived',
            'last_verified_at': '2026-02-01T00:00:00+00:00',
            'watching_run_count': '3',
        }
        state = MW._apply_lifecycle_transition(
            row, {'status': 'active_role'}, archive_grace_runs=2, now_ts=NOW)
        assert state == 'active'
        assert row['watching_run_count'] == '0'

    def test_fetch_empty_eventually_archives(self):
        """Persistent unreachable pages eventually archive."""
        row = _active_row()
        MW._apply_lifecycle_transition(
            row, {'status': 'no_change', 'llm_flags': 'fetch_empty'},
            archive_grace_runs=2, now_ts=NOW)
        assert row['lifecycle_state'] == 'watching'
        MW._apply_lifecycle_transition(
            row, {'status': 'no_change', 'llm_flags': 'fetch_empty'},
            archive_grace_runs=2, now_ts=NOW)
        assert row['lifecycle_state'] == 'archived'
        assert row['watching_run_count'] == '2'


class TestEdgeCases:
    def test_missing_watching_run_count_treated_as_zero(self):
        row = {'company': 'XCo', 'lifecycle_state': 'active'}
        state = MW._apply_lifecycle_transition(
            row, {'status': 'watch_list'}, archive_grace_runs=2, now_ts=NOW)
        assert state == 'watching'
        assert row['watching_run_count'] == '1'

    def test_invalid_watching_run_count_treated_as_zero(self):
        row = {'company': 'XCo', 'lifecycle_state': 'active', 'watching_run_count': 'bogus'}
        state = MW._apply_lifecycle_transition(
            row, {'status': 'watch_list'}, archive_grace_runs=2, now_ts=NOW)
        assert state == 'watching'
        assert row['watching_run_count'] == '1'

    def test_missing_status_defaults_to_no_change(self):
        row = _active_row()
        state = MW._apply_lifecycle_transition(
            row, {}, archive_grace_runs=2, now_ts=NOW)
        # No status → no_change, reachable → stays active
        assert state == 'active'
        assert row['last_verified_at'] == NOW
