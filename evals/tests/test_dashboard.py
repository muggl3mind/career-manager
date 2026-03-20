"""Tests for generate_dashboard.py data layer."""
import csv
import sys
import tempfile
from pathlib import Path
from datetime import datetime, timedelta, date

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'ops'))
from generate_dashboard import (
    read_target_companies, read_applications, merge_data, get_score, parse_roles,
    classify_staleness, suggested_action, get_section, build_followup_cards,
    build_bestfits_section, build_pipeline_table, build_html, compute_stats
)


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


class TestBuildFollowupCards:
    def test_renders_company_name(self):
        rows = [{
            'company': 'Acme', 'llm_score': '90', 'open_positions': 'PM',
            'date_added': '2026-01-01', 'date_applied': '2026-01-01',
            'last_contact': '', 'contact_name': '',
            'app_status': 'applied', 'role_family': 'AI',
            'careers_url': '', 'role_url': '',
        }]
        html_out = build_followup_cards(rows)
        assert 'Acme' in html_out

    def test_shows_stale_border_class(self):
        old_date = (date.today() - timedelta(days=20)).isoformat()
        rows = [{
            'company': 'Acme', 'llm_score': '90', 'open_positions': 'PM',
            'date_added': old_date, 'date_applied': old_date,
            'last_contact': '', 'contact_name': '',
            'app_status': 'applied', 'role_family': 'AI',
            'careers_url': '', 'role_url': '',
        }]
        html_out = build_followup_cards(rows)
        assert 'stale' in html_out

    def test_shows_days_since_applied(self):
        old_date = (date.today() - timedelta(days=20)).isoformat()
        rows = [{
            'company': 'Acme', 'llm_score': '90', 'open_positions': 'PM',
            'date_added': old_date, 'date_applied': old_date,
            'last_contact': '', 'contact_name': '',
            'app_status': 'applied', 'role_family': 'AI',
            'careers_url': '', 'role_url': '',
        }]
        html_out = build_followup_cards(rows)
        assert '20 days' in html_out

    def test_empty_rows_shows_placeholder(self):
        html_out = build_followup_cards([])
        assert 'No applications to follow up on' in html_out

    def test_contact_name_shown(self):
        recent_date = (date.today() - timedelta(days=3)).isoformat()
        rows = [{
            'company': 'Acme', 'llm_score': '90', 'open_positions': 'PM',
            'date_added': recent_date, 'date_applied': recent_date,
            'last_contact': '', 'contact_name': 'Jane Doe',
            'app_status': 'applied', 'role_family': 'AI',
            'careers_url': '', 'role_url': '',
        }]
        html_out = build_followup_cards(rows)
        assert 'Jane Doe' in html_out

    def test_sorted_by_staleness_oldest_first(self):
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
        html_out = build_followup_cards(rows)
        old_pos = html_out.index('Old')
        recent_pos = html_out.index('Recent')
        assert old_pos < recent_pos

    def test_date_applied_empty_falls_back_to_date_added(self):
        old_date = (date.today() - timedelta(days=10)).isoformat()
        rows = [{
            'company': 'NoDates', 'llm_score': '70', 'open_positions': 'PM',
            'date_added': old_date, 'date_applied': '',
            'last_contact': '', 'contact_name': '',
            'app_status': 'applied', 'role_family': 'AI',
            'careers_url': '', 'role_url': '',
        }]
        html_out = build_followup_cards(rows)
        assert '10 days' in html_out


class TestBuildBestFits:
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
        html_out = build_bestfits_section(rows, limit_per_path=3)
        assert 'AI' in html_out
        assert 'Finance' in html_out

    def test_all_companies_rendered_in_collapsed_group(self):
        rows = [
            self._make_row('A', 90, 'AI'),
            self._make_row('B', 85, 'AI'),
            self._make_row('C', 80, 'AI'),
            self._make_row('D', 75, 'AI'),
        ]
        html_out = build_bestfits_section(rows, limit_per_path=3)
        # All companies rendered (inside collapsed path group)
        assert 'A' in html_out
        assert 'B' in html_out
        assert 'C' in html_out
        assert 'D' in html_out
        # Path groups are collapsed by default
        assert 'display:none' in html_out

    def test_expand_all_toggle_present(self):
        rows = [self._make_row('A', 90, 'AI')]
        html_out = build_bestfits_section(rows, limit_per_path=3)
        assert 'Expand All' in html_out

    def test_paths_ordered_by_highest_score(self):
        rows = [
            self._make_row('Low', 60, 'Finance'),
            self._make_row('High', 95, 'AI'),
        ]
        html_out = build_bestfits_section(rows, limit_per_path=3)
        ai_pos = html_out.index('AI')
        fin_pos = html_out.index('Finance')
        assert ai_pos < fin_pos

    def test_empty_path_goes_to_other(self):
        rows = [self._make_row('X', 80, '')]
        html_out = build_bestfits_section(rows, limit_per_path=3)
        assert 'Other' in html_out

    def test_rationale_truncated_at_200(self):
        long_rationale = 'A' * 300
        rows = [{
            'company': 'X', 'llm_score': '80', 'role_family': 'AI',
            'llm_rationale': long_rationale, 'open_positions': 'PM',
            'careers_url': '', 'role_url': '', 'app_status': '',
        }]
        html_out = build_bestfits_section(rows, limit_per_path=3)
        assert long_rationale not in html_out
        assert '...' in html_out

    def test_empty_rows(self):
        html_out = build_bestfits_section([], limit_per_path=3)
        assert html_out.strip()


class TestBuildPipelineTable:
    def _make_row(self, company, score, path, status='', date_added='', date_applied=''):
        return {
            'company': company, 'llm_score': str(score), 'role_family': path,
            'open_positions': 'PM; Eng', 'app_status': status,
            'date_added': date_added, 'date_applied': date_applied,
            'careers_url': '', 'role_url': '',
        }

    def test_renders_all_companies(self):
        rows = [
            self._make_row('A', 90, 'AI', 'applied', '2026-03-01'),
            self._make_row('B', 80, 'Finance'),
        ]
        html_out = build_pipeline_table(rows)
        assert 'A' in html_out
        assert 'B' in html_out

    def test_status_badge_applied(self):
        rows = [self._make_row('A', 90, 'AI', 'applied', '2026-03-01')]
        html_out = build_pipeline_table(rows)
        assert 'status-applied' in html_out
        assert 'Applied' in html_out

    def test_status_badge_not_applied(self):
        rows = [self._make_row('A', 90, 'AI')]
        html_out = build_pipeline_table(rows)
        assert 'status-not' in html_out

    def test_status_badge_rejected(self):
        rows = [self._make_row('A', 90, 'AI', 'rejected', '2026-01-01')]
        html_out = build_pipeline_table(rows)
        assert 'Rejected' in html_out

    def test_has_filter_controls(self):
        rows = [self._make_row('A', 90, 'AI')]
        html_out = build_pipeline_table(rows)
        assert 'search' in html_out.lower() or 'Search' in html_out
        assert 'select' in html_out.lower()

    def test_roles_consolidated(self):
        rows = [self._make_row('A', 90, 'AI')]
        rows[0]['open_positions'] = 'PM; Eng; FDE'
        html_out = build_pipeline_table(rows)
        assert '+1' in html_out


class TestBuildFullDashboard:
    def test_contains_all_three_sections(self, tmp_path):
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
        assert 'Applied Co' in html_out
        assert 'Fresh Co' in html_out

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

        assert '>1<' in html_out  # Applied count
        assert '>3<' in html_out  # Total count

    def test_full_mode_shows_all_in_bestfits(self, tmp_path):
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
        assert 'class="show-more"' not in html_out
