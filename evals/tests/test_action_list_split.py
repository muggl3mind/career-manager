#!/usr/bin/env python3
"""
Tests for dashboard_views.build_active_views — unified best_fits section.

Run: pytest career-manager/evals/tests/test_action_list_split.py -v
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'job-search' / 'scripts' / 'ops'))
sys.path.insert(0, str(REPO / 'job-search' / 'scripts' / 'core'))
sys.path.insert(0, str(REPO / 'scripts'))

from csv_schema import HEADER
from dashboard_views import build_active_views


def _write_target(path: Path, rows: list[dict]) -> None:
    full = []
    for r in rows:
        row = {k: '' for k in HEADER}
        row.update(r)
        full.append(row)
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        w.writerows(full)


def _write_apps(path: Path, rows: list[dict]) -> None:
    fields = ['company', 'status', 'date_added', 'date_applied', 'last_contact',
              'contact_name', 'contact_email', 'role', 'job_url', 'notes']
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r in rows:
            row = {k: '' for k in fields}
            row.update(r)
            w.writerow(row)


def _cfg(min_score=70):
    return {'apply_min_score': min_score, 'watch_min_score': 85, 'watch_max_rows': 20}


class TestSectioning:
    def test_high_score_goes_to_best_fits(self, tmp_path):
        _write_target(tmp_path / 't.csv', [
            {'company': 'A', 'role_url': 'https://a.com/jobs/1',
             'validation_status': 'pass', 'llm_score': '80', 'lifecycle_state': 'active'},
        ])
        _write_apps(tmp_path / 'a.csv', [])
        views = build_active_views(tmp_path / 't.csv', tmp_path / 'a.csv', _cfg())
        assert len(views['best_fits']) == 1

    def test_no_role_url_still_in_best_fits(self, tmp_path):
        _write_target(tmp_path / 't.csv', [
            {'company': 'B', 'role_url': '', 'careers_url': 'https://b.com/',
             'validation_status': 'pass', 'llm_score': '75', 'lifecycle_state': 'active'},
        ])
        _write_apps(tmp_path / 'a.csv', [])
        views = build_active_views(tmp_path / 't.csv', tmp_path / 'a.csv', _cfg())
        assert len(views['best_fits']) == 1

    def test_applied_goes_to_follow_up(self, tmp_path):
        _write_target(tmp_path / 't.csv', [
            {'company': 'C', 'role_url': 'https://c.com/jobs/1',
             'validation_status': 'pass', 'llm_score': '90', 'lifecycle_state': 'active'},
        ])
        _write_apps(tmp_path / 'a.csv', [{'company': 'C', 'status': 'applied'}])
        views = build_active_views(tmp_path / 't.csv', tmp_path / 'a.csv', _cfg())
        assert len(views['follow_up']) == 1
        assert len(views['best_fits']) == 0

    def test_rejected_goes_to_closed_out(self, tmp_path):
        _write_target(tmp_path / 't.csv', [
            {'company': 'D', 'role_url': 'https://d.com/jobs/1',
             'validation_status': 'pass', 'llm_score': '90', 'lifecycle_state': 'active'},
        ])
        _write_apps(tmp_path / 'a.csv', [{'company': 'D', 'status': 'rejected'}])
        views = build_active_views(tmp_path / 't.csv', tmp_path / 'a.csv', _cfg())
        assert len(views['closed_out']) == 1
        assert len(views['best_fits']) == 0


class TestThresholds:
    def test_below_min_goes_to_worth_exploring(self, tmp_path):
        _write_target(tmp_path / 't.csv', [
            {'company': 'A', 'role_url': 'https://a.com/jobs/1',
             'validation_status': 'pass', 'llm_score': '65', 'lifecycle_state': 'active'},
        ])
        _write_apps(tmp_path / 'a.csv', [])
        views = build_active_views(tmp_path / 't.csv', tmp_path / 'a.csv', _cfg())
        assert views['best_fits'] == []
        assert len(views['worth_exploring']) == 1
        assert views['worth_exploring'][0]['company'] == 'A'

    def test_below_explore_min_dropped(self, tmp_path):
        _write_target(tmp_path / 't.csv', [
            {'company': 'A', 'role_url': 'https://a.com/jobs/1',
             'validation_status': 'pass', 'llm_score': '40', 'lifecycle_state': 'active'},
        ])
        _write_apps(tmp_path / 'a.csv', [])
        views = build_active_views(tmp_path / 't.csv', tmp_path / 'a.csv', _cfg())
        assert views['best_fits'] == []
        assert views['worth_exploring'] == []

    def test_custom_threshold_respected(self, tmp_path):
        _write_target(tmp_path / 't.csv', [
            {'company': 'A', 'role_url': 'https://a.com/jobs/1',
             'validation_status': 'pass', 'llm_score': '50', 'lifecycle_state': 'active'},
        ])
        _write_apps(tmp_path / 'a.csv', [])
        views = build_active_views(tmp_path / 't.csv', tmp_path / 'a.csv', _cfg(min_score=50))
        assert len(views['best_fits']) == 1


class TestLifecycleFilter:
    def test_watching_excluded(self, tmp_path):
        _write_target(tmp_path / 't.csv', [
            {'company': 'A', 'role_url': 'https://a.com/jobs/1',
             'validation_status': 'pass', 'llm_score': '90', 'lifecycle_state': 'watching'},
        ])
        _write_apps(tmp_path / 'a.csv', [])
        views = build_active_views(tmp_path / 't.csv', tmp_path / 'a.csv', _cfg())
        assert views['best_fits'] == []

    def test_archived_excluded(self, tmp_path):
        _write_target(tmp_path / 't.csv', [
            {'company': 'A', 'validation_status': 'pass', 'llm_score': '95',
             'lifecycle_state': 'archived'},
        ])
        _write_apps(tmp_path / 'a.csv', [])
        views = build_active_views(tmp_path / 't.csv', tmp_path / 'a.csv', _cfg())
        assert views['best_fits'] == []

    def test_pre_migration_pass_eligible(self, tmp_path):
        _write_target(tmp_path / 't.csv', [
            {'company': 'A', 'role_url': 'https://a.com/jobs/1',
             'validation_status': 'pass', 'llm_score': '80', 'lifecycle_state': ''},
        ])
        _write_apps(tmp_path / 'a.csv', [])
        views = build_active_views(tmp_path / 't.csv', tmp_path / 'a.csv', _cfg())
        assert len(views['best_fits']) == 1

    def test_pre_migration_non_pass_excluded(self, tmp_path):
        _write_target(tmp_path / 't.csv', [
            {'company': 'A', 'validation_status': 'watch_list', 'llm_score': '95',
             'lifecycle_state': ''},
        ])
        _write_apps(tmp_path / 'a.csv', [])
        views = build_active_views(tmp_path / 't.csv', tmp_path / 'a.csv', _cfg())
        assert views['best_fits'] == []


class TestSorting:
    def test_sorted_by_score_desc(self, tmp_path):
        _write_target(tmp_path / 't.csv', [
            {'company': 'Low', 'role_url': 'https://lo/j/1',
             'validation_status': 'pass', 'llm_score': '72', 'lifecycle_state': 'active'},
            {'company': 'High', 'role_url': 'https://hi/j/1',
             'validation_status': 'pass', 'llm_score': '95', 'lifecycle_state': 'active'},
            {'company': 'Mid', 'role_url': 'https://mid/j/1',
             'validation_status': 'pass', 'llm_score': '83', 'lifecycle_state': 'active'},
        ])
        _write_apps(tmp_path / 'a.csv', [])
        views = build_active_views(tmp_path / 't.csv', tmp_path / 'a.csv', _cfg())
        names = [r['company'] for r in views['best_fits']]
        assert names == ['High', 'Mid', 'Low']


class TestApplicationMerge:
    def test_app_status_merged(self, tmp_path):
        _write_target(tmp_path / 't.csv', [
            {'company': 'ACo', 'role_url': 'https://a.com/j/1',
             'validation_status': 'pass', 'llm_score': '80', 'lifecycle_state': 'active'},
        ])
        _write_apps(tmp_path / 'a.csv', [
            {'company': 'ACo', 'status': 'researching', 'date_added': '2026-04-10'}
        ])
        views = build_active_views(tmp_path / 't.csv', tmp_path / 'a.csv', _cfg())
        assert views['best_fits'][0]['app_status'] == 'researching'

    def test_no_app_defaults_to_empty(self, tmp_path):
        _write_target(tmp_path / 't.csv', [
            {'company': 'ACo', 'role_url': 'https://a.com/j/1',
             'validation_status': 'pass', 'llm_score': '80', 'lifecycle_state': 'active'},
        ])
        _write_apps(tmp_path / 'a.csv', [])
        views = build_active_views(tmp_path / 't.csv', tmp_path / 'a.csv', _cfg())
        assert views['best_fits'][0]['app_status'] == ''


class TestStats:
    def test_stats_match(self, tmp_path):
        _write_target(tmp_path / 't.csv', [
            {'company': 'Fit', 'role_url': 'https://f.com/j/1',
             'validation_status': 'pass', 'llm_score': '80', 'lifecycle_state': 'active'},
            {'company': 'Watch', 'role_url': '', 'careers_url': 'https://w.com/',
             'validation_status': 'pass', 'llm_score': '90', 'lifecycle_state': 'active'},
        ])
        _write_apps(tmp_path / 'a.csv', [
            {'company': 'Applied', 'status': 'applied'},
            {'company': 'Rejected', 'status': 'rejected'},
        ])
        views = build_active_views(tmp_path / 't.csv', tmp_path / 'a.csv', _cfg())
        assert views['stats']['best_fits'] == 2
        assert views['stats']['follow_up'] == 1
        assert views['stats']['closed_out'] == 1
        assert views['stats']['total'] == 4
