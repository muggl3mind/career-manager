"""Monitor export context (Phase 3, item 15).

Pins:
  - cadence gate: companies verified fewer than N days ago are skipped,
    companies with an in-flight application are always included
  - protocol text emitted once per batch (check_instructions map at the
    top level, never copied into checklist rows)
  - search_locations embedded so monitor agents never read search-config.json
  - agent-facing export is compact JSON (no indent)
"""
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'ops'))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'core'))

from csv_schema import HEADER  # noqa: E402
import monitor_watchlist as mw  # noqa: E402


def _days_ago(n: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=n)).strftime('%Y-%m-%d')


def _row(company, last_checked, **overrides):
    row = {
        'company': company,
        'website': f'{company.lower()}.com',
        'careers_url': f'https://{company.lower()}.com/careers',
        'last_checked': last_checked,
        'validation_status': 'pass',
        'open_positions': 'Some Role',
        'lifecycle_state': 'active',
        'last_verified_at': '',
        'watching_run_count': '0',
        'llm_flags': '',
    }
    row.update(overrides)
    return row


def _setup(tmp_path, monkeypatch, target_rows, app_rows=(), seen=None):
    with (tmp_path / 'target-companies.csv').open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=HEADER, extrasaction='ignore')
        w.writeheader()
        w.writerows(target_rows)
    apps = tmp_path / 'applications.csv'
    with apps.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=['company', 'role', 'status', 'job_url'])
        w.writeheader()
        w.writerows(app_rows)
    (tmp_path / 'seen-companies.json').write_text(json.dumps(seen or {}))

    monkeypatch.setattr(mw, 'TARGET_CSV', tmp_path / 'target-companies.csv')
    monkeypatch.setattr(mw, 'APPLICATIONS_CSV', apps)
    monkeypatch.setattr(mw, 'SEEN_COMPANIES', tmp_path / 'seen-companies.json')
    monkeypatch.setattr(mw, 'MONITOR_CONTEXT', tmp_path / 'monitor-context.json')
    monkeypatch.setattr(mw, 'MONITOR_RESULTS', tmp_path / 'monitor-results.json')


def _export(tmp_path, **kwargs):
    assert mw.cmd_export(**kwargs) == 0
    return json.loads((tmp_path / 'monitor-context.json').read_text(encoding='utf-8'))


def _companies(context):
    return {c['company'] for c in context['checklist']}


class TestCadenceGate:
    def test_recently_verified_company_skipped(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, [
            _row('FreshCo', _days_ago(1)),
            _row('StaleCo', _days_ago(10)),
        ])
        ctx = _export(tmp_path, stale_days=7)
        assert _companies(ctx) == {'StaleCo'}
        assert ctx['recently_verified_skipped'] == 1
        assert ctx['min_recheck_days'] == 7

    def test_never_checked_company_included(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, [_row('NewCo', '')])
        ctx = _export(tmp_path, stale_days=7)
        assert _companies(ctx) == {'NewCo'}

    def test_applied_company_always_included(self, tmp_path, monkeypatch):
        _setup(
            tmp_path, monkeypatch,
            [_row('AppliedCo', _days_ago(1)), _row('InterviewCo', _days_ago(1))],
            app_rows=[
                {'company': 'AppliedCo', 'role': 'PM', 'status': 'applied', 'job_url': ''},
                {'company': 'InterviewCo', 'role': 'PM', 'status': 'interviewing', 'job_url': ''},
            ],
        )
        ctx = _export(tmp_path, stale_days=7)
        assert _companies(ctx) == {'AppliedCo', 'InterviewCo'}
        assert ctx['recently_verified_skipped'] == 0

    def test_researching_status_does_not_bypass_gate(self, tmp_path, monkeypatch):
        _setup(
            tmp_path, monkeypatch,
            [_row('ResearchCo', _days_ago(1))],
            app_rows=[{'company': 'ResearchCo', 'role': 'PM', 'status': 'researching', 'job_url': ''}],
        )
        ctx = _export(tmp_path, stale_days=7)
        assert _companies(ctx) == set()
        assert ctx['recently_verified_skipped'] == 1

    def test_config_default_used_when_no_cli_value(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, [
            _row('SixDaysCo', _days_ago(6)),
            _row('TwoDaysCo', _days_ago(2)),
        ])
        monkeypatch.setattr(
            mw, '_pipeline_cfg',
            lambda key, default=None: {'pipeline.monitor.min_recheck_days': 5}.get(key, default),
        )
        ctx = _export(tmp_path)
        assert _companies(ctx) == {'SixDaysCo'}
        assert ctx['min_recheck_days'] == 5

    def test_module_default_used_when_config_missing(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, [_row('AnyCo', _days_ago(999))])
        monkeypatch.setattr(mw, '_pipeline_cfg', lambda key, default=None: default)
        ctx = _export(tmp_path)
        assert ctx['min_recheck_days'] == mw.DEFAULT_MIN_RECHECK_DAYS

    def test_archived_still_skipped(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, [
            _row('GoneCo', _days_ago(30), lifecycle_state='archived'),
        ])
        ctx = _export(tmp_path, stale_days=7)
        assert _companies(ctx) == set()
        assert ctx['archived_skipped'] == 1


class TestBatchProtocolText:
    def test_check_instructions_emitted_once_not_per_row(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mw, 'PATH_CHECK_INSTRUCTIONS', {5: 'Path five protocol'})
        seen = {
            'alphaco': {'company': 'AlphaCo', 'path': 5, 'last_checked': _days_ago(10)},
            'betaco': {'company': 'BetaCo', 'path': 5, 'last_checked': _days_ago(10)},
        }
        _setup(tmp_path, monkeypatch, [_row('GammaCo', _days_ago(10))], seen=seen)
        ctx = _export(tmp_path, stale_days=7)

        assert len(ctx['checklist']) == 3
        for row in ctx['checklist']:
            assert 'check_instructions' not in row

        assert ctx['check_instructions']['5'] == 'Path five protocol'
        assert ctx['check_instructions']['default'] == mw.DEFAULT_CHECK_INSTRUCTION

        raw = (tmp_path / 'monitor-context.json').read_text(encoding='utf-8')
        assert raw.count('Path five protocol') == 1

    def test_instructions_reference_the_map(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, [_row('AnyCo', _days_ago(10))])
        ctx = _export(tmp_path, stale_days=7)
        assert 'check_instructions' in ctx['instructions']
        assert '"default"' in ctx['instructions']


class TestSearchLocations:
    def test_search_locations_embedded(self, tmp_path, monkeypatch):
        monkeypatch.setattr(mw, 'SEARCH_LOCATIONS', ['Mars', 'Remote'])
        _setup(tmp_path, monkeypatch, [_row('AnyCo', _days_ago(10))])
        ctx = _export(tmp_path, stale_days=7)
        assert ctx['search_locations'] == ['Mars', 'Remote']
        assert 'search_locations' in ctx['instructions']


class TestCompactExport:
    def test_context_json_has_no_indentation(self, tmp_path, monkeypatch):
        _setup(tmp_path, monkeypatch, [_row('AnyCo', _days_ago(10))])
        _export(tmp_path, stale_days=7)
        raw = (tmp_path / 'monitor-context.json').read_text(encoding='utf-8')
        assert '\n' not in raw


class TestFetchEmptyRetryUnderGate:
    """fetch_empty rows stay stale so the next monitor export retries them."""

    def test_fetch_empty_company_appears_in_next_export(self, tmp_path, monkeypatch):
        old_checked = _days_ago(30)
        old_seen_ts = (
            datetime.now(timezone.utc) - timedelta(days=30)
        ).isoformat()
        seen = {
            'retryco': {
                'company': 'RetryCo',
                'website': 'retryco.com',
                'last_checked': old_seen_ts,
                'first_seen': old_seen_ts,
                'prospect_status': 'watch_list',
                'path': 1,
            }
        }
        _setup(
            tmp_path,
            monkeypatch,
            [_row('RetryCo', old_checked, website='retryco.com')],
            seen=seen,
        )
        monkeypatch.setattr(mw, '_sync_xlsx', lambda: None)

        first = _export(tmp_path, stale_days=7)
        assert _companies(first) == {'RetryCo'}

        (tmp_path / 'monitor-results.json').write_text(json.dumps([
            {
                'company': 'RetryCo',
                'website': 'retryco.com',
                'careers_url': 'https://retryco.com/careers',
                'status': 'no_change',
                'llm_flags': 'fetch_empty',
            }
        ]), encoding='utf-8')

        assert mw.cmd_merge() == 0
        updated_seen = json.loads(
            (tmp_path / 'seen-companies.json').read_text(encoding='utf-8')
        )
        assert updated_seen['retryco']['last_checked'] == old_seen_ts

        second = _export(tmp_path, stale_days=7)
        assert _companies(second) == {'RetryCo'}
