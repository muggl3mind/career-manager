"""Tests for generate_dashboard.py: data layer (unchanged) plus the new
JSON-driven rendering layer (build_dashboard_data / build_html)."""
import csv
import json
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, date

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'ops'))
from generate_dashboard import (
    read_target_companies, read_applications, merge_data, get_score, parse_roles,
    classify_staleness, suggested_action, get_section, build_html, compute_stats,
    build_dashboard_data, _merged_to_views,
)


def _extract_embedded_data(html_out: str) -> dict:
    """Pull the JSON blob the client-side renderer consumes out of a rendered page."""
    import re
    match = re.search(
        r'<script type="application/json" id="dashboard-data">(.*?)</script>',
        html_out, re.DOTALL)
    assert match, 'embedded dashboard-data script tag not found'
    return json.loads(match.group(1))


def _write_csv(path: Path, headers: list[str], rows: list[list[str]]):
    """Helper to write a test CSV file."""
    with path.open('w', encoding='utf-8', newline='') as f:
        w = csv.writer(f)
        w.writerow(headers)
        for row in rows:
            w.writerow(row)


class TestGetScore:
    def test_llm_score_primary(self):
        row = {'llm_score': '85', 'numeric_score': '70'}
        assert get_score(row) == 85.0

    def test_missing_score_returns_negative(self):
        row = {'llm_score': ''}
        assert get_score(row) == -1.0

    def test_invalid_value_returns_negative(self):
        row = {'llm_score': 'N/A'}
        assert get_score(row) == -1.0


class TestParseRoles:
    def test_single_role(self):
        assert parse_roles("Staff PM") == (["Staff PM"], 1)

    def test_multiple_roles_returns_first_two_and_count(self):
        roles_str = "Staff PM; Solutions Architect; FDE"
        display, count = parse_roles(roles_str)
        assert display == ["Staff PM", "Solutions Architect"]
        assert count == 3

    def test_empty_string(self):
        assert parse_roles("") == ([], 0)

    def test_whitespace_trimmed(self):
        display, count = parse_roles("  Staff PM ;  FDE  ")
        assert display == ["Staff PM", "FDE"]
        assert count == 2


class TestReadTargetCompanies:
    def test_filters_to_pass_only(self, tmp_path):
        csv_path = tmp_path / 'target-companies.csv'
        _write_csv(csv_path,
            ['company', 'llm_score', 'numeric_score', 'role_family',
             'llm_rationale', 'open_positions', 'validation_status',
             'careers_url', 'role_url', 'source'],
            [
                ['Acme', '90', '', 'Tier 1 AI', 'Great fit', 'PM; FDE', 'pass', '', '', 'web'],
                ['BadCo', '80', '', 'Tier 1 AI', 'OK fit', 'Eng', 'fail', '', '', 'web'],
            ])
        rows = read_target_companies(csv_path)
        assert len(rows) == 1
        assert rows[0]['company'] == 'Acme'

    def test_sorted_by_score_descending(self, tmp_path):
        csv_path = tmp_path / 'target-companies.csv'
        _write_csv(csv_path,
            ['company', 'llm_score', 'numeric_score', 'role_family',
             'llm_rationale', 'open_positions', 'validation_status',
             'careers_url', 'role_url', 'source'],
            [
                ['Low', '60', '', 'Path A', '', '', 'pass', '', '', ''],
                ['High', '90', '', 'Path A', '', '', 'pass', '', '', ''],
                ['Mid', '75', '', 'Path A', '', '', 'pass', '', '', ''],
            ])
        rows = read_target_companies(csv_path)
        names = [r['company'] for r in rows]
        assert names == ['High', 'Mid', 'Low']


class TestReadApplications:
    def test_reads_all_rows(self, tmp_path):
        csv_path = tmp_path / 'applications.csv'
        _write_csv(csv_path,
            ['company', 'role', 'job_url', 'status', 'date_added', 'date_applied',
             'last_contact', 'contact_name', 'contact_email', 'priority', 'notes'],
            [
                ['Acme', 'PM', '', 'applied', '2026-03-01', '2026-03-01', '', '', '', '', ''],
                ['BigCo', 'Eng', '', 'rejected', '2026-02-01', '', '', '', '', '', ''],
            ])
        rows = read_applications(csv_path)
        assert len(rows) == 2

    def test_returns_empty_if_file_missing(self, tmp_path):
        rows = read_applications(tmp_path / 'nonexistent.csv')
        assert rows == []


class TestMergeData:
    def test_merge_adds_application_status(self):
        targets = [
            {'company': 'Acme', 'llm_score': '90', 'role_family': 'AI'},
            {'company': 'BigCo', 'llm_score': '80', 'role_family': 'Finance'},
        ]
        apps = [
            {'company': 'Acme', 'status': 'applied', 'date_added': '2026-03-01',
             'date_applied': '2026-03-01',
             'last_contact': '', 'contact_name': 'Jane', 'contact_email': '',
             'role': 'PM', 'notes': ''},
        ]
        merged = merge_data(targets, apps)
        acme = next(r for r in merged if r['company'] == 'Acme')
        assert acme['app_status'] == 'applied'
        assert acme['contact_name'] == 'Jane'
        assert acme['date_applied'] == '2026-03-01'
        bigco = next(r for r in merged if r['company'] == 'BigCo')
        assert bigco['app_status'] == ''

    def test_case_insensitive_match(self):
        targets = [{'company': '  Acme Corp  ', 'llm_score': '90', 'role_family': 'AI'}]
        apps = [{'company': 'acme corp', 'status': 'applied', 'date_added': '2026-03-01',
                 'date_applied': '',
                 'last_contact': '', 'contact_name': '', 'contact_email': '',
                 'role': '', 'notes': ''}]
        merged = merge_data(targets, apps)
        assert merged[0]['app_status'] == 'applied'


class TestStaleness:
    def test_stale_no_contact(self):
        old_date = (date.today() - timedelta(days=20)).isoformat()
        row = {'date_added': old_date, 'last_contact': '', 'contact_name': ''}
        assert classify_staleness(row) == 'stale'

    def test_recent(self):
        recent_date = (date.today() - timedelta(days=5)).isoformat()
        row = {'date_added': recent_date, 'last_contact': '', 'contact_name': ''}
        assert classify_staleness(row) == 'recent'

    def test_warm_contact_gone_stale(self):
        old_date = (date.today() - timedelta(days=30)).isoformat()
        contact_date = (date.today() - timedelta(days=16)).isoformat()
        row = {'date_added': old_date, 'last_contact': contact_date, 'contact_name': 'Jane'}
        assert classify_staleness(row) == 'warm'

    def test_recent_contact_is_recent(self):
        old_date = (date.today() - timedelta(days=30)).isoformat()
        contact_date = (date.today() - timedelta(days=3)).isoformat()
        row = {'date_added': old_date, 'last_contact': contact_date, 'contact_name': 'Jane'}
        assert classify_staleness(row) == 'recent'

    def test_missing_date_returns_stale(self):
        row = {'date_added': '', 'last_contact': '', 'contact_name': ''}
        assert classify_staleness(row) == 'stale'

    def test_date_applied_used_before_date_added(self):
        old_added = (date.today() - timedelta(days=30)).isoformat()
        recent_applied = (date.today() - timedelta(days=5)).isoformat()
        row = {'date_added': old_added, 'date_applied': recent_applied,
               'last_contact': '', 'contact_name': ''}
        assert classify_staleness(row) == 'recent'

    def test_stale_date_applied(self):
        old_applied = (date.today() - timedelta(days=20)).isoformat()
        row = {'date_added': old_applied, 'date_applied': old_applied,
               'last_contact': '', 'contact_name': ''}
        assert classify_staleness(row) == 'stale'


class TestSuggestedAction:
    def test_stale_no_contact(self):
        row = {'contact_name': '', 'date_added': '2026-01-01', 'last_contact': ''}
        result = suggested_action(row, 'stale')
        assert 'finding a contact' in result.lower()

    def test_stale_with_contact(self):
        row = {'contact_name': 'Jane Doe', 'date_added': '2026-01-01', 'last_contact': ''}
        result = suggested_action(row, 'stale')
        assert 'Jane Doe' in result

    def test_warm(self):
        row = {'contact_name': 'Jane Doe', 'date_added': '2026-01-01', 'last_contact': '2026-02-01'}
        result = suggested_action(row, 'warm')
        assert 'Jane Doe' in result

    def test_recent_no_contact(self):
        row = {'contact_name': '', 'date_added': '2026-03-15', 'last_contact': ''}
        result = suggested_action(row, 'recent')
        assert 'wait' in result.lower()


class TestClassifyForSections:
    def test_applied_goes_to_section1(self):
        assert get_section({'app_status': 'applied'}) == 'followup'

    def test_researching_goes_to_bestfits(self):
        assert get_section({'app_status': 'researching'}) == 'bestfits'

    def test_rejected_goes_to_closed_out(self):
        assert get_section({'app_status': 'rejected'}) == 'closed_out'

    def test_closed_goes_to_closed_out(self):
        assert get_section({'app_status': 'closed'}) == 'closed_out'

    def test_declined_goes_to_closed_out(self):
        assert get_section({'app_status': 'declined'}) == 'closed_out'

    def test_no_fit_goes_to_closed_out(self):
        assert get_section({'app_status': 'no_fit_now'}) == 'closed_out'

    def test_no_status_goes_to_bestfits(self):
        assert get_section({'app_status': ''}) == 'bestfits'


def _views_with_followup(rows):
    return {
        'follow_up': rows, 'best_fits': [], 'worth_exploring': [], 'closed_out': [],
        'stats': {'follow_up': len(rows), 'best_fits': 0, 'worth_exploring': 0,
                   'closed_out': 0, 'total': len(rows)},
    }


class TestFollowupData:
    """build_dashboard_data()'s follow_up records replace the old
    build_followup_cards() HTML string builder — the client renders the cards
    from this JSON, so we assert on the record fields it needs instead."""

    def test_record_has_company_and_score(self):
        rows = [{
            'company': 'Acme', 'llm_score': '90', 'open_positions': 'PM',
            'date_added': '2026-01-01', 'date_applied': '2026-01-01',
            'last_contact': '', 'contact_name': '',
            'app_status': 'applied', 'role_family': 'AI',
            'careers_url': '', 'role_url': '',
        }]
        data = build_dashboard_data(_views_with_followup(rows), full_mode=False)
        rec = data['sections']['follow_up'][0]
        assert rec['company'] == 'Acme'
        assert rec['score'] == 90.0
        assert rec['score_display'] == '90'

    def test_staleness_and_suggested_action_present(self):
        old_date = (date.today() - timedelta(days=20)).isoformat()
        rows = [{
            'company': 'Acme', 'llm_score': '90', 'open_positions': 'PM',
            'date_added': old_date, 'date_applied': old_date,
            'last_contact': '', 'contact_name': '',
            'app_status': 'applied', 'role_family': 'AI',
            'careers_url': '', 'role_url': '',
        }]
        data = build_dashboard_data(_views_with_followup(rows), full_mode=False)
        rec = data['sections']['follow_up'][0]
        assert rec['staleness'] == 'stale'
        assert rec['days_since'] == 20
        assert 'finding a contact' in rec['suggested_action'].lower()

    def test_empty_rows_yields_empty_section(self):
        data = build_dashboard_data(_views_with_followup([]), full_mode=False)
        assert data['sections']['follow_up'] == []
        # The friendly empty-state string is baked into the always-inlined
        # client script and shown whenever this list is empty at render time.
        html_out = build_html([], full_mode=False)
        assert 'No applications to follow up on' in html_out

    def test_contact_name_present(self):
        recent_date = (date.today() - timedelta(days=3)).isoformat()
        rows = [{
            'company': 'Acme', 'llm_score': '90', 'open_positions': 'PM',
            'date_added': recent_date, 'date_applied': recent_date,
            'last_contact': '', 'contact_name': 'Jane Doe',
            'app_status': 'applied', 'role_family': 'AI',
            'careers_url': '', 'role_url': '',
        }]
        data = build_dashboard_data(_views_with_followup(rows), full_mode=False)
        assert data['sections']['follow_up'][0]['contact_name'] == 'Jane Doe'

    def test_days_since_ordering_enables_oldest_first_sort(self):
        """The client sorts follow-up cards by days_since descending (oldest
        first); verify the underlying field is correct for both rows so that
        sort produces the same order the old server-side sort did."""
        old = (date.today() - timedelta(days=30)).isoformat()
        recent = (date.today() - timedelta(days=5)).isoformat()
        rows = [
            {'company': 'Recent', 'llm_score': '90', 'open_positions': '',
             'date_added': recent, 'date_applied': recent,
             'last_contact': '', 'contact_name': '',
             'app_status': 'applied', 'role_family': '', 'careers_url': '', 'role_url': ''},
            {'company': 'Old', 'llm_score': '80', 'open_positions': '',
             'date_added': old, 'date_applied': old,
             'last_contact': '', 'contact_name': '',
             'app_status': 'applied', 'role_family': '', 'careers_url': '', 'role_url': ''},
        ]
        data = build_dashboard_data(_views_with_followup(rows), full_mode=False)
        by_company = {r['company']: r for r in data['sections']['follow_up']}
        assert by_company['Old']['days_since'] > by_company['Recent']['days_since']

    def test_date_applied_empty_falls_back_to_date_added(self):
        old_date = (date.today() - timedelta(days=10)).isoformat()
        rows = [{
            'company': 'NoDates', 'llm_score': '70', 'open_positions': 'PM',
            'date_added': old_date, 'date_applied': '',
            'last_contact': '', 'contact_name': '',
            'app_status': 'applied', 'role_family': 'AI',
            'careers_url': '', 'role_url': '',
        }]
        data = build_dashboard_data(_views_with_followup(rows), full_mode=False)
        assert data['sections']['follow_up'][0]['days_since'] == 10


def _views_with_bestfits(rows):
    return {
        'follow_up': [], 'best_fits': rows, 'worth_exploring': [], 'closed_out': [],
        'stats': {'follow_up': 0, 'best_fits': len(rows), 'worth_exploring': 0,
                   'closed_out': 0, 'total': len(rows)},
    }


class TestBestFitsData:
    """build_dashboard_data()'s best_fits records replace the old
    build_bestfits_section() HTML string builder. Grouping/expand-collapse
    decisions now happen client-side in JS from this data, so these tests
    assert the data is complete and correctly tagged rather than parsing
    generated markup."""

    def _make_row(self, company, score, path, roles='PM'):
        return {
            'company': company, 'llm_score': str(score),
            'role_family': path, 'llm_rationale': 'Good fit for testing',
            'open_positions': roles, 'careers_url': '', 'role_url': '',
            'app_status': '',
        }

    def test_groups_by_path(self):
        rows = [
            self._make_row('A', 90, 'AI'),
            self._make_row('B', 85, 'Finance'),
            self._make_row('C', 80, 'AI'),
        ]
        data = build_dashboard_data(_views_with_bestfits(rows), full_mode=False)
        paths = {r['path'] for r in data['sections']['best_fits']}
        assert paths == {'AI', 'Finance'}

    def test_all_companies_rendered_in_group_no_truncation(self):
        # Unlike the old server-rendered version (which truncated to
        # limit_per_path), the new client-rendered data always carries every
        # row — the client decides how many to show and lets you expand.
        rows = [
            self._make_row('A', 90, 'AI'),
            self._make_row('B', 85, 'AI'),
            self._make_row('C', 80, 'AI'),
            self._make_row('D', 75, 'AI'),
        ]
        data = build_dashboard_data(_views_with_bestfits(rows), full_mode=False)
        companies = {r['company'] for r in data['sections']['best_fits']}
        assert companies == {'A', 'B', 'C', 'D'}

    def test_full_mode_flag_recorded_in_meta(self):
        rows = [self._make_row('A', 90, 'AI')]
        data = build_dashboard_data(_views_with_bestfits(rows), full_mode=True)
        assert data['meta']['full_mode'] is True
        assert data['meta']['title'] == 'Career Dashboard (Full)'
        data = build_dashboard_data(_views_with_bestfits(rows), full_mode=False)
        assert data['meta']['full_mode'] is False
        assert data['meta']['title'] == 'Career Dashboard'

    def test_empty_path_goes_to_other(self):
        rows = [self._make_row('X', 80, '')]
        data = build_dashboard_data(_views_with_bestfits(rows), full_mode=False)
        assert data['sections']['best_fits'][0]['path'] == 'Other'

    def test_rationale_kept_full_for_client_side_truncation(self):
        # Truncation for compact display is now a client-side concern; the
        # JSON payload must carry the full text so detail cards can show it.
        long_rationale = 'A' * 300
        rows = [{
            'company': 'X', 'llm_score': '80', 'role_family': 'AI',
            'llm_rationale': long_rationale, 'open_positions': 'PM',
            'careers_url': '', 'role_url': '', 'app_status': '',
        }]
        data = build_dashboard_data(_views_with_bestfits(rows), full_mode=False)
        assert data['sections']['best_fits'][0]['rationale'] == long_rationale

    def test_empty_rows(self):
        data = build_dashboard_data(_views_with_bestfits([]), full_mode=False)
        assert data['sections']['best_fits'] == []


class TestPipelineData:
    """build_dashboard_data()'s pipeline records replace the old
    build_pipeline_table() HTML string builder."""

    def _make_row(self, company, score, path, status='', date_added='', date_applied=''):
        return {
            'company': company, 'llm_score': str(score), 'role_family': path,
            'open_positions': 'PM; Eng', 'app_status': status,
            'date_added': date_added, 'date_applied': date_applied,
            'careers_url': '', 'role_url': '',
        }

    def _views(self, rows):
        return {
            'follow_up': [], 'best_fits': rows, 'worth_exploring': [], 'closed_out': [],
            'stats': {'follow_up': 0, 'best_fits': len(rows), 'worth_exploring': 0,
                       'closed_out': 0, 'total': len(rows)},
        }

    def test_renders_all_companies(self):
        rows = [
            self._make_row('A', 90, 'AI', 'applied', '2026-03-01'),
            self._make_row('B', 80, 'Finance'),
        ]
        data = build_dashboard_data(self._views(rows), full_mode=False)
        companies = {r['company'] for r in data['sections']['pipeline']}
        assert companies == {'A', 'B'}

    def test_status_badge_applied(self):
        rows = [self._make_row('A', 90, 'AI', 'applied', '2026-03-01')]
        data = build_dashboard_data(self._views(rows), full_mode=False)
        rec = data['sections']['pipeline'][0]
        assert rec['status_class'] == 'status-applied'
        assert rec['status_label'] == 'Applied'

    def test_status_badge_not_applied(self):
        rows = [self._make_row('A', 90, 'AI')]
        data = build_dashboard_data(self._views(rows), full_mode=False)
        assert data['sections']['pipeline'][0]['status_class'] == 'status-not'

    def test_status_badge_rejected(self):
        rows = [self._make_row('A', 90, 'AI', 'rejected', '2026-01-01')]
        data = build_dashboard_data(self._views(rows), full_mode=False)
        rec = data['sections']['pipeline'][0]
        assert rec['status_label'] == 'Rejected'
        assert rec['status_class'] == 'status-rejected'

    def test_paths_list_for_filter_dropdown(self):
        rows = [
            self._make_row('A', 90, 'AI'),
            self._make_row('B', 80, 'Finance'),
        ]
        data = build_dashboard_data(self._views(rows), full_mode=False)
        assert set(data['paths']) == {'AI', 'Finance'}

    def test_roles_full_list_and_count_preserved(self):
        rows = [self._make_row('A', 90, 'AI')]
        rows[0]['open_positions'] = 'PM; Eng; FDE'
        data = build_dashboard_data(self._views(rows), full_mode=False)
        rec = data['sections']['pipeline'][0]
        assert rec['roles'] == ['PM', 'Eng', 'FDE']
        assert rec['role_count'] == 3


class TestBuildFullDashboard:
    def test_contains_all_sections_and_no_external_requests(self, tmp_path):
        targets_path = tmp_path / 'targets.csv'
        apps_path = tmp_path / 'apps.csv'

        _write_csv(targets_path,
            ['company', 'llm_score', 'numeric_score', 'role_family',
             'llm_rationale', 'open_positions', 'validation_status',
             'careers_url', 'role_url', 'source'],
            [
                ['Applied Co', '90', '', 'AI', 'Great', 'PM', 'pass', '', '', 'web'],
                ['Fresh Co', '85', '', 'Finance', 'Good', 'Eng', 'pass', '', '', 'web'],
            ])
        _write_csv(apps_path,
            ['company', 'role', 'job_url', 'status', 'date_added', 'date_applied',
             'last_contact', 'contact_name', 'contact_email', 'priority', 'notes'],
            [['Applied Co', 'PM', '', 'applied', '2026-03-01', '2026-03-01', '', '', '', '', '']])

        targets = read_target_companies(targets_path)
        apps = read_applications(apps_path)
        merged = merge_data(targets, apps)

        html_out = build_html(merged, full_mode=False)

        assert '<!DOCTYPE html>' in html_out
        assert 'Applied' in html_out
        assert 'Best Fits' in html_out
        assert 'Full Pipeline' in html_out
        # Company data now lives in the embedded JSON, not literal HTML markup.
        assert 'Applied Co' in html_out
        assert 'Fresh Co' in html_out

        data = _extract_embedded_data(html_out)
        companies = {r['company'] for r in data['sections']['pipeline']}
        assert companies == {'Applied Co', 'Fresh Co'}

        # Fully self-contained: no <script src=...> / <link href=...> pointed
        # at an external http(s) resource (a bare "http://" can still appear,
        # e.g. the SVG namespace URI used when building charts).
        assert 'script src="http' not in html_out
        assert 'link href="http' not in html_out
        assert 'fonts.googleapis.com' not in html_out
        assert '<script type="application/json" id="dashboard-data">' in html_out

    def test_stats_ribbon_counts(self, tmp_path):
        targets_path = tmp_path / 'targets.csv'
        apps_path = tmp_path / 'apps.csv'

        _write_csv(targets_path,
            ['company', 'llm_score', 'numeric_score', 'role_family',
             'llm_rationale', 'open_positions', 'validation_status',
             'careers_url', 'role_url', 'source'],
            [
                ['A', '90', '', 'AI', '', '', 'pass', '', '', ''],
                ['B', '85', '', 'AI', '', '', 'pass', '', '', ''],
                ['C', '80', '', 'AI', '', '', 'pass', '', '', ''],
            ])
        _write_csv(apps_path,
            ['company', 'role', 'job_url', 'status', 'date_added', 'date_applied',
             'last_contact', 'contact_name', 'contact_email', 'priority', 'notes'],
            [['A', '', '', 'applied', '2026-01-01', '2026-01-01', '', '', '', '', '']])

        targets = read_target_companies(targets_path)
        apps = read_applications(apps_path)
        merged = merge_data(targets, apps)

        html_out = build_html(merged, full_mode=False)
        data = _extract_embedded_data(html_out)

        assert data['stats']['follow_up'] == 1
        assert data['stats']['total'] == 3

    def test_full_mode_includes_all_companies(self, tmp_path):
        targets_path = tmp_path / 'targets.csv'
        _write_csv(targets_path,
            ['company', 'llm_score', 'numeric_score', 'role_family',
             'llm_rationale', 'open_positions', 'validation_status',
             'careers_url', 'role_url', 'source'],
            [['Co' + str(i), str(90 - i), '', 'AI', '', '', 'pass', '', '', '']
             for i in range(5)])

        targets = read_target_companies(targets_path)
        merged = merge_data(targets, [])

        html_out = build_html(merged, full_mode=True)
        data = _extract_embedded_data(html_out)
        assert data['meta']['full_mode'] is True
        companies = {r['company'] for r in data['sections']['best_fits']}
        assert companies == {f'Co{i}' for i in range(5)}

    def test_empty_data_renders_clean_with_no_traceback(self):
        """A fresh checkout with no CSVs at all must still produce a valid,
        self-contained page (no exception, no blank page)."""
        html_out = build_html([], full_mode=False)
        assert '<!DOCTYPE html>' in html_out
        assert 'No applications to follow up on' in html_out
        data = _extract_embedded_data(html_out)
        assert data['sections']['follow_up'] == []
        assert data['sections']['best_fits'] == []
        assert data['stats']['total'] == 0


class TestDisplayGroups:
    def _make_row(self, company, score, path, roles='PM'):
        return {
            'company': company, 'llm_score': str(score),
            'role_family': path, 'llm_rationale': 'Good fit',
            'open_positions': roles, 'careers_url': '', 'role_url': '',
            'app_status': '',
        }

    def _views(self, rows):
        return {
            'follow_up': [], 'best_fits': rows, 'worth_exploring': [], 'closed_out': [],
            'stats': {'follow_up': 0, 'best_fits': len(rows), 'worth_exploring': 0,
                       'closed_out': 0, 'total': len(rows)},
        }

    def test_groups_paths_into_display_groups(self):
        rows = [
            self._make_row('A', 90, 'Path Alpha'),
            self._make_row('B', 85, 'Path Beta'),
            self._make_row('C', 80, 'Path Gamma'),
        ]
        display_groups = {'AI & Tech': ['Path Alpha', 'Path Gamma'], 'Finance': ['Path Beta']}
        data = build_dashboard_data(self._views(rows), full_mode=False, display_groups=display_groups)
        groups = {r['company']: r['group'] for r in data['sections']['best_fits']}
        assert groups['A'] == 'AI & Tech'
        assert groups['C'] == 'AI & Tech'
        assert groups['B'] == 'Finance'

    def test_unmapped_path_goes_to_other(self):
        rows = [
            self._make_row('A', 90, 'Path Alpha'),
            self._make_row('B', 85, 'Unmapped Path'),
        ]
        display_groups = {'AI & Tech': ['Path Alpha']}
        data = build_dashboard_data(self._views(rows), full_mode=False, display_groups=display_groups)
        groups = {r['company']: r['group'] for r in data['sections']['best_fits']}
        assert groups['B'] == 'Other'

    def test_no_display_groups_falls_back_to_path(self):
        rows = [
            self._make_row('A', 90, 'Path Alpha'),
            self._make_row('B', 85, 'Path Beta'),
        ]
        data = build_dashboard_data(self._views(rows), full_mode=False, display_groups=None)
        groups = {r['company']: r['group'] for r in data['sections']['best_fits']}
        assert groups['A'] == 'Path Alpha'
        assert groups['B'] == 'Path Beta'


class TestWatchListSection:
    def test_read_watch_list_filters_correctly(self, tmp_path):
        """read_watch_list_companies returns watch_list rows with score >= 50."""
        import sys as _sys
        _sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'core'))
        from csv_schema import HEADER

        csv_path = tmp_path / "target-companies.csv"
        rows = [
            {"company": "PassCo", "validation_status": "pass", "llm_score": "90"},
            {"company": "HighWatch", "validation_status": "watch_list", "llm_score": "80"},
            {"company": "LowWatch", "validation_status": "watch_list", "llm_score": "30"},
            {"company": "MidWatch", "validation_status": "watch_list", "llm_score": "50"},
        ]
        with csv_path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=HEADER, extrasaction="ignore")
            w.writeheader()
            for r in rows:
                filled = {h: r.get(h, "") for h in HEADER}
                w.writerow(filled)

        from generate_dashboard import read_watch_list_companies
        result = read_watch_list_companies(csv_path)
        names = [r["company"] for r in result]
        assert "HighWatch" in names
        assert "MidWatch" in names
        assert "LowWatch" not in names
        assert "PassCo" not in names
        assert names[0] == "HighWatch"  # sorted by score desc
