#!/usr/bin/env python3
"""Tests for the seen-jobs eval cache: TTL and hard-pass handling.

Finding H4: hard-passed jobs resurrected into the active list through the
eval cache, while NEW hard-passes were never cached at all and got
re-evaluated (and re-billed) on every run. Both directions are pinned here.

Finding H5: cached verdicts had no TTL, so a job re-posted at the same URL
kept its old score forever. Verdicts now expire after
EVAL_CACHE_TTL_DAYS and the job returns to the pending-eval queue.
"""

import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CORE = REPO / 'job-search' / 'scripts' / 'core'
OPS = REPO / 'job-search' / 'scripts' / 'ops'
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(OPS))

import evaluate_jobs


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _job(url: str, company: str = 'Acme') -> dict:
    return {
        'careers_url': url,
        'company': company,
        'open_positions': 'Engineer',
        'location_detected': 'Remote',
        'notes': '',
        'source': 'jobspy',
    }


def _cached(score, evaluated_at: str, hard_pass: str = 'false', **extra) -> dict:
    entry = {
        'first_seen': evaluated_at,
        'llm_score': score,
        'llm_dimensions_evaluated': 8,
        'role_family': 'Path Alpha',
        'llm_rationale': 'cached rationale',
        'llm_flags': '',
        'llm_hard_pass': hard_pass,
        'llm_hard_pass_reason': 'agency spam' if hard_pass == 'true' else '',
        'llm_evaluated_at': evaluated_at,
    }
    entry.update(extra)
    return entry


@pytest.fixture
def eval_paths(tmp_path, monkeypatch):
    seen_path = tmp_path / 'seen-jobs.json'
    pending_path = tmp_path / 'pending-eval.json'
    monkeypatch.setattr(evaluate_jobs, 'SEEN_JOBS', seen_path)
    monkeypatch.setattr(evaluate_jobs, 'PENDING_EVAL', pending_path)
    return seen_path, pending_path


class TestHardPassSkipList:
    def test_cached_hard_pass_never_resurrects(self, eval_paths):
        """H4 direction 1: a fresh cached hard-pass is skipped entirely.

        It must appear neither in the scored list (which feeds the
        target CSV) nor in pending-eval (no re-evaluation)."""
        seen_path, pending_path = eval_paths
        url = 'https://spam.example/job'
        seen_path.write_text(json.dumps({
            url: _cached('', _now().isoformat(), hard_pass='true'),
        }))

        scored, all_jobs = evaluate_jobs.export_pending(
            [_job(url)], dry_run=False, verbose=False,
        )

        assert scored == []
        assert not pending_path.exists()

    def test_cached_scored_job_restored(self, eval_paths):
        seen_path, pending_path = eval_paths
        url = 'https://good.example/job'
        seen_path.write_text(json.dumps({
            url: _cached(87, _now().isoformat()),
        }))

        scored, _ = evaluate_jobs.export_pending(
            [_job(url)], dry_run=False, verbose=False,
        )

        assert len(scored) == 1
        assert scored[0]['llm_score'] == 87
        # Finding M9: confidence is restored from the cache too.
        assert scored[0]['llm_dimensions_evaluated'] == 8
        assert not pending_path.exists()


class TestCacheTTL:
    def test_expired_verdict_goes_back_to_pending(self, eval_paths):
        """H5: a verdict older than the TTL is re-evaluated, not trusted."""
        seen_path, pending_path = eval_paths
        url = 'https://reposted.example/job'
        stale = (_now() - timedelta(days=evaluate_jobs.EVAL_CACHE_TTL_DAYS + 1)).isoformat()
        seen_path.write_text(json.dumps({url: _cached(88, stale)}))

        scored, _ = evaluate_jobs.export_pending(
            [_job(url)], dry_run=False, verbose=False,
        )

        assert scored == []
        pending = json.loads(pending_path.read_text())
        assert [p['careers_url'] for p in pending] == [url]

    def test_expired_hard_pass_is_re_evaluated(self, eval_paths):
        """An expired hard-pass also returns to pending: the posting may
        have changed, so the exclusion gets a fresh look after the TTL."""
        seen_path, pending_path = eval_paths
        url = 'https://old-spam.example/job'
        stale = (_now() - timedelta(days=evaluate_jobs.EVAL_CACHE_TTL_DAYS + 1)).isoformat()
        seen_path.write_text(json.dumps({
            url: _cached('', stale, hard_pass='true'),
        }))

        scored, _ = evaluate_jobs.export_pending(
            [_job(url)], dry_run=False, verbose=False,
        )

        assert scored == []
        pending = json.loads(pending_path.read_text())
        assert [p['careers_url'] for p in pending] == [url]

    def test_fresh_verdict_within_ttl_is_cached(self, eval_paths):
        seen_path, pending_path = eval_paths
        url = 'https://fresh.example/job'
        fresh = (_now() - timedelta(days=evaluate_jobs.EVAL_CACHE_TTL_DAYS - 1)).isoformat()
        seen_path.write_text(json.dumps({url: _cached(75, fresh)}))

        scored, _ = evaluate_jobs.export_pending(
            [_job(url)], dry_run=False, verbose=False,
        )

        assert len(scored) == 1
        assert not pending_path.exists()

    def test_unparseable_timestamp_treated_as_stale(self, eval_paths):
        seen_path, pending_path = eval_paths
        url = 'https://broken.example/job'
        entry = _cached(75, 'not-a-timestamp')
        entry['first_seen'] = 'also-not-a-timestamp'
        seen_path.write_text(json.dumps({url: entry}))

        scored, _ = evaluate_jobs.export_pending(
            [_job(url)], dry_run=False, verbose=False,
        )

        assert scored == []
        assert pending_path.exists()


class TestNewHardPassesCached:
    """H4 direction 2: apply_eval_results must cache new hard-passes so
    they are not re-evaluated on every subsequent run."""

    @pytest.fixture
    def apply_env(self, tmp_path, monkeypatch):
        import apply_eval_results as aer

        data = tmp_path / 'data'
        data.mkdir()
        monkeypatch.setattr(aer, 'DATA', data)
        monkeypatch.setattr(aer, 'TARGET_CSV', data / 'target-companies.csv')
        monkeypatch.setattr(aer, 'RAW_CSV', data / 'raw-discovery.csv')
        monkeypatch.setattr(aer, 'SEEN_JOBS', data / 'seen-jobs.json')
        monkeypatch.setattr(aer, 'EVAL_RESULTS', data / 'eval-results.json')
        monkeypatch.setattr(aer, 'PENDING_EVAL', data / 'pending-eval.json')
        with (data / 'target-companies.csv').open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=aer.HEADER)
            w.writeheader()
        return aer, data

    def test_new_hard_pass_written_to_seen_jobs(self, apply_env):
        aer, data = apply_env
        url = 'https://agency.example/job'
        results = [{
            'careers_url': url,
            'total_score': 0,
            'scores': {},
            'fit_summary': '',
            'hard_pass': True,
            'hard_pass_reason': 'recruiting agency',
            'red_flags': [],
        }]
        (data / 'eval-results.json').write_text(json.dumps(results))
        (data / 'pending-eval.json').write_text(json.dumps([
            {'careers_url': url, 'company': 'AgencyCo', 'title': 'Ghost role'},
        ]))

        rc = aer.cmd_apply(dry_run=False)
        assert rc == 0

        seen = json.loads((data / 'seen-jobs.json').read_text())
        assert url in seen
        assert seen[url]['llm_hard_pass'] == 'true'
        assert seen[url]['llm_hard_pass_reason'] == 'recruiting agency'
        assert seen[url]['llm_evaluated_at']

        # And the hard-passed job never lands in the target CSV.
        with (data / 'target-companies.csv').open() as f:
            rows = list(csv.DictReader(f))
        assert all(r['careers_url'] != url for r in rows)

    def test_round_trip_hard_pass_not_re_evaluated(self, apply_env, eval_paths):
        """Full loop: apply caches the hard-pass, the next discovery run
        neither rescores nor re-pends the same URL."""
        aer, data = apply_env
        seen_path, pending_path = eval_paths
        url = 'https://agency.example/job'
        (data / 'eval-results.json').write_text(json.dumps([{
            'careers_url': url,
            'total_score': 0,
            'scores': {},
            'hard_pass': True,
            'hard_pass_reason': 'recruiting agency',
        }]))
        aer.cmd_apply(dry_run=False)

        # Point evaluate_jobs at the cache apply just wrote.
        seen_path.write_text((data / 'seen-jobs.json').read_text())
        scored, _ = evaluate_jobs.export_pending(
            [_job(url, company='AgencyCo')], dry_run=False, verbose=False,
        )
        assert scored == []
        assert not pending_path.exists()


class TestProspectingSkipList:
    """H4 company direction: prospecting must never re-surface a
    hard-passed company. seen-jobs.json is the durable source because
    discovery_pipeline.py rewrites raw-discovery.csv every run."""

    def test_hard_pass_company_read_from_seen_jobs(self, tmp_path):
        import web_prospecting
        (tmp_path / 'seen-jobs.json').write_text(json.dumps({
            'https://spam.example/job': _cached(
                '', _now().isoformat(), hard_pass='true', company='Spam Agency'),
            'https://good.example/job': _cached(
                87, _now().isoformat(), company='GoodCo'),
        }))
        entries = web_prospecting._hard_pass_skip_entries(tmp_path)
        assert 'spam agency' in entries
        assert 'goodco' not in entries

    def test_skip_survives_raw_discovery_wipe(self, tmp_path):
        """Regression: the skip list used to come only from
        raw-discovery.csv, which discovery wipes; an absent or empty
        raw CSV must not empty the skip list."""
        import web_prospecting
        (tmp_path / 'seen-jobs.json').write_text(json.dumps({
            'https://spam.example/job': _cached(
                '', _now().isoformat(), hard_pass='true', company='Spam Agency'),
        }))
        (tmp_path / 'raw-discovery.csv').write_text('company,website,llm_hard_pass,exclusion_reason\n')
        entries = web_prospecting._hard_pass_skip_entries(tmp_path)
        assert 'spam agency' in entries

    def test_raw_discovery_rows_still_honored(self, tmp_path):
        import web_prospecting
        (tmp_path / 'raw-discovery.csv').write_text(
            'company,website,llm_hard_pass,exclusion_reason\n'
            'Staffing LLC,staffing.example,,llm_hard_pass\n'
        )
        entries = web_prospecting._hard_pass_skip_entries(tmp_path)
        assert 'staffing llc' in entries
        assert 'staffing.example' in entries
