"""Tests for the company-research merge script (finding M8).

The company-research agent used to freehand-edit target-companies.csv,
writing columns that do not exist in the schema (fit_score,
fit_rationale). merge_research.py is now the only sanctioned path:
known legacy aliases are mapped onto schema columns, unknown columns are
rejected to quarantine, and pipeline-managed columns can never be set by
research.
"""
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'ops'))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'core'))

import merge_research as mr


def _existing_row(company='AlphaCo', **overrides):
    from csv_schema import HEADER
    row = {field: '' for field in HEADER}
    row.update({
        'company': company,
        'website': 'alphaco.com',
        'last_checked': '2026-01-01',
        'last_verified_at': '2026-01-01T00:00:00+00:00',
        'lifecycle_state': 'active',
        'validation_status': 'pass',
        'llm_score': '60',
        'watching_run_count': '0',
    })
    row.update(overrides)
    return row


def _quarantine_records(tmp_path):
    records = []
    qdir = tmp_path / 'quarantine'
    if not qdir.exists():
        return records
    for f in qdir.glob('*.jsonl'):
        for line in f.read_text().splitlines():
            records.append(json.loads(line))
    return records


class TestColumnClassification:
    def test_aliases_are_mapped(self):
        clean, protected, unknown = mr.classify_columns({
            'company': 'X', 'fit_score': 80, 'fit_rationale': 'good', 'path_name': 'Alpha',
        })
        assert clean['llm_score'] == 80
        assert clean['llm_rationale'] == 'good'
        assert clean['role_family'] == 'Alpha'
        assert not protected and not unknown

    def test_unknown_columns_detected(self):
        _, _, unknown = mr.classify_columns({'company': 'X', 'vibes': 'great'})
        assert unknown == ['vibes']

    def test_protected_columns_detected(self):
        _, protected, _ = mr.classify_columns({
            'company': 'X', 'lifecycle_state': 'active', 'last_verified_at': 'now',
        })
        assert sorted(protected) == ['last_verified_at', 'lifecycle_state']


class TestMergeResults:
    def test_unknown_column_rejected_to_quarantine(self, tmp_path):
        rows = [_existing_row()]
        stats = mr.merge_results(
            [{'company': 'AlphaCo', 'industry': 'Fintech', 'made_up_column': 1}],
            rows, tmp_path,
        )
        assert stats['quarantined'] == 1
        assert stats['updated'] == 0
        assert rows[0]['industry'] == '', 'rejected row must not partially merge'
        records = _quarantine_records(tmp_path)
        assert len(records) == 1
        assert records[0]['reason'] == mr.REASON_UNKNOWN_COLUMN
        assert 'made_up_column' in records[0]['detail']

    def test_protected_column_rejected(self, tmp_path):
        rows = [_existing_row()]
        stats = mr.merge_results(
            [{'company': 'AlphaCo', 'last_verified_at': '2026-06-11T00:00:00+00:00'}],
            rows, tmp_path,
        )
        assert stats['quarantined'] == 1
        assert rows[0]['last_verified_at'] == '2026-01-01T00:00:00+00:00'
        assert _quarantine_records(tmp_path)[0]['reason'] == mr.REASON_PROTECTED_COLUMN

    def test_fit_score_alias_validated_and_merged(self, tmp_path):
        rows = [_existing_row()]
        stats = mr.merge_results(
            [{'company': 'AlphaCo', 'fit_score': 80, 'llm_dimensions_evaluated': 5,
              'fit_rationale': '4 of 5 evaluated dimensions fit'}],
            rows, tmp_path,
        )
        assert stats == {'updated': 1, 'added': 0, 'quarantined': 0}
        assert rows[0]['llm_score'] == '80'
        assert rows[0]['llm_rationale'] == '4 of 5 evaluated dimensions fit'
        assert rows[0]['llm_evaluated_at'] != ''

    def test_unachievable_score_quarantined(self, tmp_path):
        """97 is not floor(yes*100/evaluated) for any yes with 10 evaluated."""
        rows = [_existing_row()]
        stats = mr.merge_results(
            [{'company': 'AlphaCo', 'fit_score': 97, 'llm_dimensions_evaluated': 10}],
            rows, tmp_path,
        )
        assert stats['quarantined'] == 1
        assert rows[0]['llm_score'] == '60', 'invalid score must not overwrite'

    def test_enrichment_does_not_touch_verification_state(self, tmp_path):
        rows = [_existing_row()]
        mr.merge_results(
            [{'company': 'AlphaCo', 'industry': 'Fintech', 'size': '50-200',
              'notes': 'PE-backed, hiring in product'}],
            rows, tmp_path,
        )
        assert rows[0]['industry'] == 'Fintech'
        assert rows[0]['size'] == '50-200'
        assert 'research' in rows[0]['notes']
        # Research is not a careers-page verification:
        assert rows[0]['last_checked'] == '2026-01-01'
        assert rows[0]['last_verified_at'] == '2026-01-01T00:00:00+00:00'
        assert rows[0]['lifecycle_state'] == 'active'

    def test_new_company_added_via_schema(self, tmp_path):
        from csv_schema import HEADER
        rows = []
        stats = mr.merge_results(
            [{'company': 'NewCo', 'website': 'newco.com', 'industry': 'AI'}],
            rows, tmp_path,
        )
        assert stats['added'] == 1
        new = rows[0]
        assert new['company'] == 'NewCo'
        assert new['source'] == 'company_research'
        assert new['validation_status'] == 'watch_list'
        assert set(new) - set(HEADER) == set(), 'new rows must only use schema columns'

    def test_missing_company_quarantined(self, tmp_path):
        rows = []
        stats = mr.merge_results([{'industry': 'AI'}], rows, tmp_path)
        assert stats['quarantined'] == 1
        assert rows == []
        assert _quarantine_records(tmp_path)[0]['reason'] == mr.REASON_MISSING_COMPANY
