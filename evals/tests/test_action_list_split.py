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
from dashboard_views import aggregate_display_rows, build_active_views
from opportunities import opportunities_from_targets


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


class TestCompanyAggregation:
    def test_multiple_open_roles_at_same_company_collapse_to_one_best_fit_row(self, tmp_path):
        _write_target(tmp_path / 't.csv', [
            {'company': 'OpenAI',
             'careers_url': 'https://openai.com/careers',
             'open_positions': 'Solutions Architect; Accounting Manager',
             'validation_status': 'pass',
             'llm_score': '95',
             'lifecycle_state': 'active'},
        ])
        _write_apps(tmp_path / 'a.csv', [])
        views = build_active_views(tmp_path / 't.csv', tmp_path / 'a.csv', _cfg())

        assert len(views['best_fits']) == 1
        assert views['best_fits'][0]['company'] == 'OpenAI'
        assert views['best_fits'][0]['open_positions'] == 'Accounting Manager; Solutions Architect'

    def test_multiple_applied_roles_at_same_company_collapse_to_one_follow_up_row(self, tmp_path):
        _write_target(tmp_path / 't.csv', [
            {'company': 'Basis',
             'careers_url': 'https://jobs.ashbyhq.com/basis-ai',
             'open_positions': 'Deployed Strategist; Implementation Manager',
             'validation_status': 'pass',
             'llm_score': '88',
             'lifecycle_state': 'active'},
        ])
        _write_apps(tmp_path / 'a.csv', [
            {'company': 'Basis',
             'role': 'Deployed Strategist',
             'job_url': 'https://jobs.ashbyhq.com/basis-ai',
             'status': 'applied'},
            {'company': 'Basis',
             'role': 'Implementation Manager',
             'job_url': 'https://jobs.ashbyhq.com/basis-ai',
             'status': 'applied'},
        ])
        views = build_active_views(tmp_path / 't.csv', tmp_path / 'a.csv', _cfg())

        assert len(views['follow_up']) == 1
        assert views['follow_up'][0]['company'] == 'Basis'
        assert views['follow_up'][0]['open_positions'] == 'Deployed Strategist; Implementation Manager'
        assert views['follow_up'][0]['apply_url'] == 'https://jobs.ashbyhq.com/basis-ai'

    def test_consolidated_company_row_keeps_source_link_fallback(self, tmp_path):
        _write_target(tmp_path / 't.csv', [
            {'company': 'Anthropic',
             'careers_url': 'https://www.linkedin.com/jobs/view/4322460009',
             'role_url': 'https://job-boards.greenhouse.io/anthropic/jobs/4985877008',
             'open_positions': 'Finance Systems, Head of AI & Innovation; Senior Manager, Corporate Accounting Operations',
             'validation_status': 'pass',
             'llm_score': '92',
             'lifecycle_state': 'active'},
        ])
        _write_apps(tmp_path / 'a.csv', [])
        views = build_active_views(tmp_path / 't.csv', tmp_path / 'a.csv', _cfg())

        assert len(views['best_fits']) == 1
        assert views['best_fits'][0]['apply_url'] == 'https://job-boards.greenhouse.io/anthropic/jobs/4985877008'

    def test_full_pipeline_display_collapses_company_across_sections(self):
        rows = [
            {'company': 'OpenAI',
             'open_positions': 'Forward Deployed Engineer',
             'app_status': 'applied',
             'apply_url': 'https://openai.com/applied'},
            {'company': 'OpenAI',
             'open_positions': 'Manager, AI Success Engineers',
             'app_status': '',
             'source_key': 'https://openai.com/careers'},
        ]

        display_rows = aggregate_display_rows(rows)

        assert len(display_rows) == 1
        assert display_rows[0]['open_positions'] == 'Forward Deployed Engineer; Manager, AI Success Engineers'
        assert display_rows[0]['apply_url'] == 'https://openai.com/applied'


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

    def test_rejected_role_does_not_close_new_role_at_same_company(self, tmp_path):
        _write_target(tmp_path / 't.csv', [
            {'company': 'Anthropic',
             'careers_url': 'https://www.anthropic.com/careers',
             'role_url': 'https://job-boards.greenhouse.io/anthropic/jobs/4985877008',
             'open_positions': 'Forward Deployed Engineer; Solutions Architect, Applied AI',
             'validation_status': 'pass',
             'llm_score': '94',
             'lifecycle_state': 'active'},
        ])
        _write_apps(tmp_path / 'a.csv', [
            {'company': 'Anthropic',
             'role': 'Forward Deployed Engineer',
             'job_url': 'https://job-boards.greenhouse.io/anthropic/jobs/4985877008?gh_src=LinkedIn',
             'status': 'rejected'},
        ])
        views = build_active_views(tmp_path / 't.csv', tmp_path / 'a.csv', _cfg())
        best_names = [r['company'] for r in views['best_fits']]
        closed_roles = [r['open_positions'] for r in views['closed_out']]

        assert 'Anthropic' in best_names
        assert views['best_fits'][0]['open_positions'] == 'Solutions Architect, Applied AI'
        assert 'Forward Deployed Engineer' in closed_roles

    def test_applied_role_does_not_hide_other_open_roles_at_same_company(self, tmp_path):
        _write_target(tmp_path / 't.csv', [
            {'company': 'OpenAI',
             'careers_url': 'https://openai.com/careers/search',
             'role_url': 'https://openai.com/careers/forward-deployed-engineer-nyc/',
             'open_positions': 'Forward Deployed Engineer; Solutions Engineer, Financial Services',
             'validation_status': 'pass',
             'llm_score': '95',
             'lifecycle_state': 'active'},
        ])
        _write_apps(tmp_path / 'a.csv', [
            {'company': 'OpenAI',
             'role': 'Forward Deployed Engineer',
             'job_url': 'https://openai.com/careers/forward-deployed-engineer-nyc/',
             'status': 'applied'},
        ])
        views = build_active_views(tmp_path / 't.csv', tmp_path / 'a.csv', _cfg())
        best_roles = [r['open_positions'] for r in views['best_fits']]
        follow_roles = [r['open_positions'] for r in views['follow_up']]

        assert 'Solutions Engineer, Financial Services' in best_roles
        assert 'Forward Deployed Engineer' in follow_roles

    def test_multi_role_row_does_not_reuse_specific_job_url_for_other_roles(self, tmp_path):
        row = {k: '' for k in HEADER}
        row.update({
            'company': 'OpenAI',
            'careers_url': 'https://www.linkedin.com/jobs/view/1234567890',
            'role_url': 'https://openai.com/careers/forward-deployed-engineer-nyc/',
            'open_positions': 'Forward Deployed Engineer; Accounting Manager',
            'validation_status': 'pass',
            'llm_score': '95',
            'lifecycle_state': 'active',
        })
        opportunities = opportunities_from_targets([row])
        by_role = {r['role_title']: r for r in opportunities}

        assert by_role['Forward Deployed Engineer']['apply_url'] == 'https://openai.com/careers/forward-deployed-engineer-nyc/'
        assert by_role['Accounting Manager']['apply_url'] == ''
        assert by_role['Accounting Manager']['role_url'] == ''


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
