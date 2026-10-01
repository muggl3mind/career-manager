#!/usr/bin/env python3
"""Tests for merge-time validation of agent self-reported scores.

Findings C2: merges previously trusted self-reported totals with zero
validation, so {"total_score": 97, "scores": {}} merged cleanly and became
the day's top action. These tests pin the new behavior: recompute from
dimension data via the canonical scoring module, range-check values,
validate dimension keys against the rubric, quarantine garbage.
"""

import csv
import json
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[2]
CORE = REPO / 'job-search' / 'scripts' / 'core'
OPS = REPO / 'job-search' / 'scripts' / 'ops'
sys.path.insert(0, str(CORE))
sys.path.insert(0, str(OPS))

from merge_validation import (
    DEFAULT_DIMENSION_KEYS,
    REASON_INSUFFICIENT_DIMENSIONS,
    REASON_INVALID_DIMENSION_VALUE,
    REASON_INVALID_DIMENSIONS_EVALUATED,
    REASON_INVALID_SCORE,
    REASON_SCORE_DIMENSION_MISMATCH,
    REASON_SCORE_OUT_OF_RANGE,
    REASON_UNKNOWN_DIMENSION_KEY,
    REASON_UNVERIFIABLE_TOTAL,
    quarantine_row,
    validate_eval_result,
    validate_self_report,
)

DIMS = sorted(DEFAULT_DIMENSION_KEYS)


def _scores(yes=0, no=0):
    """Build a valid scores dict using real rubric keys."""
    assert yes + no <= len(DIMS)
    d = {}
    for key in DIMS[:yes]:
        d[key] = 1
    for key in DIMS[yes:yes + no]:
        d[key] = 0
    return d


class TestEvalResultValidation:
    def test_bogus_total_with_empty_scores_rejected(self):
        # The C2 case: previously merged cleanly, now rejected.
        v = validate_eval_result(97, {})
        assert v.ok is False
        assert v.reason == REASON_UNVERIFIABLE_TOTAL

    def test_bogus_total_with_missing_scores_rejected(self):
        v = validate_eval_result(97, None)
        assert v.ok is False
        assert v.reason == REASON_UNVERIFIABLE_TOTAL

    def test_zero_total_with_empty_scores_is_needs_research(self):
        # SKILL.md contract: fewer than 5 assessable -> total_score 0,
        # needs_research. Not garbage, just unscored.
        v = validate_eval_result(0, {})
        assert v.ok is True
        assert v.score is None
        assert v.needs_research is True

    def test_valid_scores_recompute_matches_report(self):
        v = validate_eval_result(87, _scores(yes=7, no=1))
        assert v.ok is True
        assert v.score == 87
        assert v.detail == ''

    def test_disagreeing_total_recomputed_not_trusted(self):
        # Agent claims 100, dimensions say 7 yes of 8 evaluated = 87.
        v = validate_eval_result(100, _scores(yes=7, no=1))
        assert v.ok is True
        assert v.score == 87
        assert 'disagrees' in v.detail

    def test_out_of_range_dimension_value_rejected(self):
        scores = _scores(yes=5)
        scores[DIMS[6]] = 7  # 0-10 scale value: invalid, rubric is yes/no
        v = validate_eval_result(57, scores)
        assert v.ok is False
        assert v.reason == REASON_INVALID_DIMENSION_VALUE

    def test_unknown_dimension_key_rejected(self):
        scores = _scores(yes=5)
        scores['vibes'] = 1
        v = validate_eval_result(100, scores)
        assert v.ok is False
        assert v.reason == REASON_UNKNOWN_DIMENSION_KEY
        assert 'vibes' in v.detail

    def test_too_few_dimensions_drops_reported_total(self):
        v = validate_eval_result(100, _scores(yes=3))
        assert v.ok is True
        assert v.score is None
        assert v.needs_research is True

    def test_nan_total_with_empty_scores_rejected_not_crash(self):
        # json.loads accepts bare NaN; must quarantine, never raise.
        v = validate_eval_result(float('nan'), {})
        assert v.ok is False
        assert v.reason == REASON_UNVERIFIABLE_TOTAL

    def test_nan_total_with_valid_scores_recomputed_not_crash(self):
        # Previously crashed at int(reported); now treated as a
        # disagreeing (non-numeric) total and the recomputed score wins.
        v = validate_eval_result(float('nan'), _scores(yes=7, no=1))
        assert v.ok is True
        assert v.score == 87
        assert 'disagrees' in v.detail

    def test_inf_total_with_valid_scores_recomputed_not_crash(self):
        v = validate_eval_result(float('inf'), _scores(yes=7, no=1))
        assert v.ok is True
        assert v.score == 87
        assert 'disagrees' in v.detail


class TestSelfReportValidation:
    def test_unscored_row_passes(self):
        v = validate_self_report(None)
        assert v.ok is True
        assert v.score is None
        v = validate_self_report('')
        assert v.ok is True

    def test_valid_score_and_dimensions(self):
        v = validate_self_report(87, 8)
        assert v.ok is True
        assert v.score == 87

    def test_score_out_of_range_rejected(self):
        assert validate_self_report(150, 8).reason == REASON_SCORE_OUT_OF_RANGE
        assert validate_self_report(-5, 8).reason == REASON_SCORE_OUT_OF_RANGE

    def test_non_numeric_score_rejected(self):
        v = validate_self_report('great fit', 8)
        assert v.ok is False
        assert v.reason == REASON_INVALID_SCORE

    def test_unachievable_score_rejected(self):
        # 97 is not floor(yes*100/evaluated) for any evaluated count <= 10.
        v = validate_self_report(97, 10)
        assert v.ok is False
        assert v.reason == REASON_SCORE_DIMENSION_MISMATCH

    def test_score_with_too_few_dimensions_rejected(self):
        v = validate_self_report(100, 3)
        assert v.ok is False
        assert v.reason == REASON_INSUFFICIENT_DIMENSIONS

    def test_dimension_scores_take_priority(self):
        scores = _scores(yes=7, no=1)
        v = validate_self_report(100, 8, dimension_scores=scores)
        assert v.ok is True
        assert v.score == 87

    def test_unknown_key_in_dimension_scores_rejected(self):
        v = validate_self_report(
            100, 5, dimension_scores={'made_up_dimension': 1},
        )
        assert v.ok is False
        assert v.reason == REASON_UNKNOWN_DIMENSION_KEY

    def test_legacy_row_without_evaluated_count_range_checked_only(self):
        v = validate_self_report(85)
        assert v.ok is True
        assert v.score == 85
        assert validate_self_report(120).ok is False

    def test_nan_score_rejected_not_crash(self):
        # NaN passes both range comparisons (nan < 0 and nan > 100 are
        # both False) and previously crashed at int(score). Must quarantine.
        v = validate_self_report(float('nan'), 8)
        assert v.ok is False
        assert v.reason == REASON_INVALID_SCORE

    def test_nan_score_legacy_path_rejected_not_crash(self):
        v = validate_self_report(float('nan'))
        assert v.ok is False
        assert v.reason == REASON_INVALID_SCORE

    def test_nan_dimensions_evaluated_rejected_not_crash(self):
        v = validate_self_report(80, float('nan'))
        assert v.ok is False
        assert v.reason == REASON_INVALID_DIMENSIONS_EVALUATED

    def test_inf_score_rejected(self):
        v = validate_self_report(float('inf'), 8)
        assert v.ok is False
        assert v.reason == REASON_INVALID_SCORE
        v = validate_self_report(float('-inf'), 8)
        assert v.ok is False
        assert v.reason == REASON_INVALID_SCORE

    def test_inf_dimensions_evaluated_rejected_not_crash(self):
        # int(float('inf')) raises OverflowError, a different crash class
        # from the NaN ValueError; both must route to quarantine.
        v = validate_self_report(80, float('inf'))
        assert v.ok is False
        assert v.reason == REASON_INVALID_DIMENSIONS_EVALUATED


class TestQuarantineFile:
    def test_quarantine_writes_shared_convention(self, tmp_path):
        row = {'company': 'Acme', 'total_score': 97, 'scores': {}}
        path = quarantine_row(
            tmp_path, 'apply_eval_results', REASON_UNVERIFIABLE_TOTAL,
            row, detail='cannot verify',
        )
        assert path == (
            tmp_path / 'quarantine'
            / 'apply_eval_results-unverifiable-total.jsonl'
        )
        record = json.loads(path.read_text().splitlines()[0])
        assert record['reason'] == REASON_UNVERIFIABLE_TOTAL
        assert record['result'] == row
        assert record['script'] == 'apply_eval_results'
        assert record['quarantined_at']

    def test_quarantine_appends(self, tmp_path):
        for i in range(2):
            quarantine_row(tmp_path, 's', 'r', {'i': i})
        lines = (tmp_path / 'quarantine' / 's-r.jsonl').read_text().splitlines()
        assert len(lines) == 2


# ---------------------------------------------------------------------------
# Integration: the merge scripts actually quarantine instead of merging.
# ---------------------------------------------------------------------------

CSV_FIELDS_MIN = {
    'company': 'ExistingCo',
    'careers_url': 'https://existing.example/careers',
    'validation_status': 'pass',
    'llm_score': '70',
    'lifecycle_state': 'active',
    'watching_run_count': '0',
}


def _write_target_csv(path, header, rows):
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction='ignore')
        w.writeheader()
        for row in rows:
            w.writerow({k: row.get(k, '') for k in header})


@pytest.fixture
def eval_env(tmp_path, monkeypatch):
    import apply_eval_results as aer

    data = tmp_path / 'data'
    data.mkdir()
    monkeypatch.setattr(aer, 'DATA', data)
    monkeypatch.setattr(aer, 'TARGET_CSV', data / 'target-companies.csv')
    monkeypatch.setattr(aer, 'RAW_CSV', data / 'raw-discovery.csv')
    monkeypatch.setattr(aer, 'SEEN_JOBS', data / 'seen-jobs.json')
    monkeypatch.setattr(aer, 'EVAL_RESULTS', data / 'eval-results.json')
    monkeypatch.setattr(aer, 'PENDING_EVAL', data / 'pending-eval.json')
    _write_target_csv(
        data / 'target-companies.csv', aer.HEADER, [CSV_FIELDS_MIN],
    )
    return aer, data


class TestApplyEvalResultsMerge:
    def test_bogus_total_quarantined_good_row_merged(self, eval_env):
        aer, data = eval_env
        results = [
            {
                'careers_url': 'https://existing.example/careers',
                'total_score': 97,
                'scores': {},  # the C2 garbage row
                'fit_summary': 'amazing',
            },
            {
                'careers_url': 'https://good.example/careers',
                'company': 'GoodCo',
                'total_score': 100,  # disagrees: dimensions say 87
                'scores': _scores(yes=7, no=1),
                'fit_summary': 'solid',
            },
        ]
        (data / 'eval-results.json').write_text(json.dumps(results))
        (data / 'pending-eval.json').write_text(json.dumps([
            {'careers_url': 'https://good.example/careers',
             'company': 'GoodCo', 'title': 'PM'},
        ]))

        rc = aer.cmd_apply(dry_run=False)
        assert rc == 0

        with (data / 'target-companies.csv').open() as f:
            rows = {r['company']: r for r in csv.DictReader(f)}

        # Garbage row quarantined: existing score untouched, not 97.
        assert rows['ExistingCo']['llm_score'] == '70'
        qfile = (
            data / 'quarantine'
            / 'apply_eval_results-unverifiable-total.jsonl'
        )
        assert qfile.exists()
        record = json.loads(qfile.read_text().splitlines()[0])
        assert record['result']['total_score'] == 97

        # Good row merged with the recomputed (not self-reported) score.
        assert rows['GoodCo']['llm_score'] == '87'

    def test_unknown_dimension_key_quarantined(self, eval_env):
        aer, data = eval_env
        scores = _scores(yes=5)
        scores['totally_new_dimension'] = 1
        results = [{
            'careers_url': 'https://existing.example/careers',
            'total_score': 100,
            'scores': scores,
        }]
        (data / 'eval-results.json').write_text(json.dumps(results))
        aer.cmd_apply(dry_run=False)
        qdir = data / 'quarantine'
        assert list(qdir.glob('apply_eval_results-unknown-dimension-key.jsonl'))
        with (data / 'target-companies.csv').open() as f:
            rows = {r['company']: r for r in csv.DictReader(f)}
        assert rows['ExistingCo']['llm_score'] == '70'

    def test_out_of_range_dimension_value_quarantined(self, eval_env):
        aer, data = eval_env
        scores = _scores(yes=5)
        scores[DIMS[6]] = 9  # numeric scale value, not yes/no
        results = [{
            'careers_url': 'https://existing.example/careers',
            'total_score': 90,
            'scores': scores,
        }]
        (data / 'eval-results.json').write_text(json.dumps(results))
        aer.cmd_apply(dry_run=False)
        qdir = data / 'quarantine'
        assert list(
            qdir.glob('apply_eval_results-invalid-dimension-value.jsonl')
        )


class TestWebProspectingMerge:
    def test_bogus_self_report_quarantined(self, tmp_path):
        import web_prospecting as wp

        data = tmp_path
        _write_target_csv(data / 'target-companies.csv', wp.HEADER, [])
        results = [
            {
                'company': 'BogusCo',
                'llm_score': 97,  # unachievable from 10 dimensions
                'llm_dimensions_evaluated': 10,
                'prospect_status': 'active_role',
                'open_positions': 'PM',
            },
            {
                'company': 'RealCo',
                'llm_score': 80,
                'llm_dimensions_evaluated': 10,
                'prospect_status': 'active_role',
                'open_positions': 'PM',
            },
        ]
        rc = wp._do_merge(results, data, dry_run=False)
        assert rc == 0

        with (data / 'target-companies.csv').open() as f:
            rows = {r['company']: r for r in csv.DictReader(f)}
        assert 'RealCo' in rows
        assert rows['RealCo']['llm_score'] == '80'
        assert 'BogusCo' not in rows

        qfile = (
            data / 'quarantine'
            / 'web_prospecting-score-dimension-mismatch.jsonl'
        )
        assert qfile.exists()
        record = json.loads(qfile.read_text().splitlines()[0])
        assert record['result']['company'] == 'BogusCo'

    def test_out_of_range_score_quarantined(self, tmp_path):
        import web_prospecting as wp

        data = tmp_path
        _write_target_csv(data / 'target-companies.csv', wp.HEADER, [])
        results = [{
            'company': 'OverCo',
            'llm_score': 150,
            'llm_dimensions_evaluated': 10,
            'prospect_status': 'active_role',
            'open_positions': 'PM',
        }]
        wp._do_merge(results, data, dry_run=False)
        with (data / 'target-companies.csv').open() as f:
            rows = {r['company']: r for r in csv.DictReader(f)}
        assert 'OverCo' not in rows
        assert (
            data / 'quarantine' / 'web_prospecting-score-out-of-range.jsonl'
        ).exists()


class TestMonitorMerge:
    def test_bogus_self_report_quarantined(self, tmp_path, monkeypatch):
        import monitor_watchlist as mw

        data = tmp_path / 'data'
        data.mkdir()
        monkeypatch.setattr(mw, 'DATA', data)
        monkeypatch.setattr(mw, 'TARGET_CSV', data / 'target-companies.csv')
        monkeypatch.setattr(mw, 'SEEN_COMPANIES', data / 'seen-companies.json')
        monkeypatch.setattr(mw, 'MONITOR_CONTEXT', data / 'monitor-context.json')
        monkeypatch.setattr(mw, 'MONITOR_RESULTS', data / 'monitor-results.json')
        _write_target_csv(
            data / 'target-companies.csv', mw.HEADER, [CSV_FIELDS_MIN],
        )
        results = [{
            'company': 'ExistingCo',
            'status': 'active_role',
            'open_positions': 'PM',
            'llm_score': 97,  # unachievable ratio score
            'llm_dimensions_evaluated': 10,
        }]
        (data / 'monitor-results.json').write_text(json.dumps(results))

        rc = mw.cmd_merge(dry_run=False)
        assert rc == 0

        with (data / 'target-companies.csv').open() as f:
            rows = {r['company']: r for r in csv.DictReader(f)}
        # Bogus self-report never reaches the CSV.
        assert rows['ExistingCo']['llm_score'] == '70'
        qfile = (
            data / 'quarantine'
            / 'monitor_watchlist-score-dimension-mismatch.jsonl'
        )
        assert qfile.exists()
