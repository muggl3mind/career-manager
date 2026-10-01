"""Role-level score tests.

A company row holds one llm_score, and the newest evaluation of ANY of its
roles overwrote it. In the 2026-10-01 run, a weak "AI Engineer 4" posting
(50) replaced Capital One's "Staff AI Engineer" score (80), and every
Capital One role then displayed 50.

Each role now carries its own score from seen-jobs.json, and a company
ranks by its best role. Roles with no per-role evaluation (web-prospecting
finds) fall back to the company score. Ties in score rank the
better-evidenced role first (more dimensions assessed).
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
sys.path.insert(0, str(REPO / 'job-search' / 'scripts' / 'ops'))
sys.path.insert(0, str(REPO / 'job-search' / 'scripts' / 'core'))
sys.path.insert(0, str(REPO / 'scripts'))

from csv_schema import HEADER
from dashboard_views import aggregate_display_rows, build_active_views
from opportunities import (
    company_best_scores,
    load_role_scores,
    opportunities_from_targets,
    target_row_to_opportunities,
)


def _seen(path: Path, entries: list[dict]) -> Path:
    data = {}
    for i, e in enumerate(entries):
        row = {'llm_hard_pass': 'false', 'llm_dimensions_evaluated': '6',
               'llm_rationale': '', 'llm_flags': ''}
        row.update(e)
        data[e.get('url', f'https://jobs.example/{i}')] = row
    path.write_text(json.dumps(data), encoding='utf-8')
    return path


def _target(**overrides) -> dict:
    row = {k: '' for k in HEADER}
    row.update({
        'company': 'Capital One',
        'open_positions': 'Staff AI Engineer; AI Engineer 4 (LLM Gateway)',
        'llm_score': '50',
        'llm_dimensions_evaluated': '6',
        'llm_rationale': 'company-level rationale',
        'validation_status': 'pass',
        'lifecycle_state': 'active',
        'role_family': 'AI Product Manager (Financial Services)',
    })
    row.update(overrides)
    return row


def _write_target(path: Path, rows: list[dict]) -> None:
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()
        w.writerows(rows)


def _by_title(opps: list[dict]) -> dict:
    return {o['role_title']: o for o in opps}


class TestLoadRoleScores:
    def test_duplicate_titles_keep_the_higher_score(self, tmp_path):
        p = _seen(tmp_path / 'seen-jobs.json', [
            {'company': 'Acme', 'title': 'FDE', 'llm_score': '60'},
            {'company': 'Acme', 'title': 'FDE', 'llm_score': '85'},
        ])
        scores = load_role_scores(p)
        assert scores[('acme', 'fde')]['llm_score'] == '85'

    def test_missing_file_is_empty(self, tmp_path):
        assert load_role_scores(tmp_path / 'nope.json') == {}


class TestPerRoleScores:
    def test_each_role_gets_its_own_score(self, tmp_path):
        scores = load_role_scores(_seen(tmp_path / 's.json', [
            {'company': 'Capital One', 'title': 'Staff AI Engineer', 'llm_score': '80',
             'llm_dimensions_evaluated': '8', 'llm_rationale': 'strong'},
            {'company': 'Capital One', 'title': 'AI Engineer 4 (LLM Gateway)', 'llm_score': '50'},
        ]))
        opps = _by_title(target_row_to_opportunities(_target(), scores))
        assert opps['Staff AI Engineer']['llm_score'] == '80'
        assert opps['Staff AI Engineer']['llm_dimensions_evaluated'] == '8'
        assert opps['Staff AI Engineer']['fit_summary'] == 'strong'
        assert opps['AI Engineer 4 (LLM Gateway)']['llm_score'] == '50'

    def test_unscored_role_falls_back_to_company_score(self, tmp_path):
        opps = _by_title(target_row_to_opportunities(
            _target(open_positions='Deployment Strategist'), {}))
        assert opps['Deployment Strategist']['llm_score'] == '50'
        assert opps['Deployment Strategist']['fit_summary'] == 'company-level rationale'

    def test_annotated_title_matches_its_evaluation(self, tmp_path):
        scores = load_role_scores(_seen(tmp_path / 's.json', [
            {'company': 'campfire', 'title': 'Accounting Solutions Consultant', 'llm_score': '83'},
        ]))
        row = _target(company='campfire',
                      open_positions='Accounting Solutions Consultant (SF, $180K-$250K)')
        opps = target_row_to_opportunities(row, scores)
        assert opps[0]['llm_score'] == '83'

    def test_hard_passed_role_is_dropped(self, tmp_path):
        scores = load_role_scores(_seen(tmp_path / 's.json', [
            {'company': 'Capital One', 'title': 'AI Engineer 4 (LLM Gateway)',
             'llm_score': '0', 'llm_hard_pass': 'true'},
        ]))
        titles = [o['role_title'] for o in target_row_to_opportunities(_target(), scores)]
        assert titles == ['Staff AI Engineer']

    def test_role_annotated_as_excluded_is_dropped(self):
        row = _target(company='Ramp',
                      open_positions='Product Manager | Tax (excluded, tax-core role); Solutions Consultant')
        titles = [o['role_title'] for o in target_row_to_opportunities(row, {})]
        assert titles == ['Solutions Consultant']


class TestCompanyRollup:
    def test_company_best_scores_use_best_role(self, tmp_path):
        scores = load_role_scores(_seen(tmp_path / 's.json', [
            {'company': 'Capital One', 'title': 'Staff AI Engineer', 'llm_score': '80'},
            {'company': 'Capital One', 'title': 'AI Engineer 4 (LLM Gateway)', 'llm_score': '50'},
        ]))
        assert company_best_scores([_target()], scores) == {'Capital One': 80}

    def test_company_without_roles_keeps_its_score(self):
        row = _target(company='Quiet Co', open_positions='', role_family='', careers_url='')
        assert company_best_scores([row], {}) == {'Quiet Co': 50}

    def test_dashboard_shows_best_role_score(self, tmp_path):
        target_csv = tmp_path / 'target-companies.csv'
        _write_target(target_csv, [_target()])
        _seen(tmp_path / 'seen-jobs.json', [
            {'company': 'Capital One', 'title': 'Staff AI Engineer', 'llm_score': '80'},
            {'company': 'Capital One', 'title': 'AI Engineer 4 (LLM Gateway)', 'llm_score': '50'},
        ])
        views = build_active_views(target_csv, tmp_path / 'apps.csv')
        assert [(r['company'], r['llm_score']) for r in views['best_fits']] == [('Capital One', '80')]


class TestEvidenceTiebreak:
    def test_equal_scores_keep_the_better_evidenced_role(self):
        rows = [
            {'company': 'Acme', 'llm_score': '100', 'llm_dimensions_evaluated': '5', 'open_positions': 'A'},
            {'company': 'Acme', 'llm_score': '100', 'llm_dimensions_evaluated': '9', 'open_positions': 'B'},
        ]
        [agg] = aggregate_display_rows(rows)
        assert agg['llm_dimensions_evaluated'] == '9'

    def test_best_fits_rank_ties_by_evidence(self, tmp_path):
        target_csv = tmp_path / 'target-companies.csv'
        _write_target(target_csv, [
            _target(company='Thin', open_positions='PM', llm_score='100', llm_dimensions_evaluated='5'),
            _target(company='Solid', open_positions='PM', llm_score='100', llm_dimensions_evaluated='9'),
        ])
        views = build_active_views(target_csv, tmp_path / 'apps.csv')
        assert [r['company'] for r in views['best_fits']] == ['Solid', 'Thin']

    def test_opportunities_carry_dimension_count(self):
        [opp] = opportunities_from_targets([_target(open_positions='PM')])
        assert opp['llm_dimensions_evaluated'] == '6'


class TestDashboardRecord:
    def test_record_exposes_dimension_count(self):
        from generate_dashboard import _row_record
        rec = _row_record({'company': 'Acme', 'llm_score': '83', 'llm_dimensions_evaluated': '6'}, 'best_fits')
        assert rec['dims'] == 6

    def test_record_without_dimension_count(self):
        from generate_dashboard import _row_record
        rec = _row_record({'company': 'Acme', 'llm_score': '83'}, 'best_fits')
        assert rec['dims'] is None


class TestOneSectionPerCompany:
    def test_company_with_mixed_role_scores_appears_once(self, tmp_path):
        target_csv = tmp_path / 'target-companies.csv'
        _write_target(target_csv, [_target()])
        _seen(tmp_path / 'seen-jobs.json', [
            {'company': 'Capital One', 'title': 'Staff AI Engineer', 'llm_score': '80'},
            {'company': 'Capital One', 'title': 'AI Engineer 4 (LLM Gateway)', 'llm_score': '55'},
        ])
        views = build_active_views(target_csv, tmp_path / 'apps.csv')
        assert [r['company'] for r in views['best_fits']] == ['Capital One']
        assert views['worth_exploring'] == []
        assert 'AI Engineer 4 (LLM Gateway)' in views['best_fits'][0]['open_positions']
