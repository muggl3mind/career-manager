"""Tests for company_dedup module."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

# Ensure core dir is on path
sys.path.insert(0, str(Path(__file__).resolve().parent))


@pytest.fixture(autouse=True)
def reset_normalizer(tmp_path):
    """Reset path_normalizer cache and point to temp config."""
    import path_normalizer
    path_normalizer._cache = None
    yield
    path_normalizer._cache = None


from company_dedup import find_existing, merge_into_existing


def _make_row(company: str, **kwargs) -> dict:
    row = {'company': company, 'open_positions': '', 'llm_score': '', 'last_checked': ''}
    row.update(kwargs)
    return row


def _write_config(tmp_path, aliases=None):
    """Write a minimal search-config.json with optional aliases."""
    config = {
        "query_packs": {},
        "company_aliases": aliases or {},
        "role_include_patterns": [],
        "role_exclude_patterns": [],
        "employer_exclude_patterns": [],
        "location_exclude_patterns": [],
        "keywords": {"domain": []},
        "gold_companies": [],
    }
    path = tmp_path / "search-config.json"
    path.write_text(json.dumps(config))
    return path


class TestFindExisting:
    def test_find_existing_exact_match(self):
        rows = [_make_row('Anthropic'), _make_row('OpenAI')]
        result = find_existing('anthropic', rows)
        assert result is not None
        assert result['company'] == 'Anthropic'

    def test_find_existing_alias_match(self, tmp_path):
        """Alias should match via normalize_company from search-config.json."""
        import path_normalizer
        config_path = _write_config(tmp_path, aliases={"acme inc": "Acme Corp"})
        path_normalizer.CONFIG_PATH = config_path
        path_normalizer._cache = None

        rows = [_make_row('Acme Corp'), _make_row('OpenAI')]
        result = find_existing('Acme Inc', rows)
        assert result is not None
        assert result['company'] == 'Acme Corp'

    def test_find_existing_alias_match_reverse(self, tmp_path):
        """Reverse alias lookup — canonical name finds aliased row."""
        import path_normalizer
        config_path = _write_config(tmp_path, aliases={
            "acme inc": "Acme Corp",
            "acme corp": "Acme Corp",
        })
        path_normalizer.CONFIG_PATH = config_path
        path_normalizer._cache = None

        rows = [_make_row('Acme Inc'), _make_row('OpenAI')]
        result = find_existing('Acme Corp', rows)
        assert result is not None
        assert result['company'] == 'Acme Inc'

    def test_find_existing_no_match(self):
        rows = [_make_row('Anthropic'), _make_row('OpenAI')]
        result = find_existing('Snowflake', rows)
        assert result is None

    def test_find_existing_empty_name(self):
        rows = [_make_row('Anthropic')]
        result = find_existing('', rows)
        assert result is None


class TestMergeIntoExisting:
    def test_merge_keeps_higher_score(self):
        existing = _make_row('Anthropic', llm_score='70', llm_rationale='Old rationale')
        new_data = {'llm_score': '85', 'llm_rationale': 'New rationale', 'last_checked': '2026-03-20'}
        merge_into_existing(existing, new_data)
        assert existing['llm_score'] == '85'
        assert existing['llm_rationale'] == 'New rationale'

    def test_merge_keeps_existing_higher_score(self):
        existing = _make_row('Anthropic', llm_score='90', llm_rationale='Great fit')
        new_data = {'llm_score': '60', 'llm_rationale': 'Weak fit', 'last_checked': '2026-03-20'}
        merge_into_existing(existing, new_data)
        assert existing['llm_score'] == '90'
        assert existing['llm_rationale'] == 'Great fit'

    def test_merge_combines_roles(self):
        existing = _make_row('Anthropic', open_positions='ML Engineer')
        new_data = {'open_positions': 'Data Scientist', 'last_checked': '2026-03-20'}
        merge_into_existing(existing, new_data)
        assert 'ML Engineer' in existing['open_positions']
        assert 'Data Scientist' in existing['open_positions']

    def test_merge_no_duplicate_roles(self):
        existing = _make_row('Anthropic', open_positions='ML Engineer')
        new_data = {'open_positions': 'ML Engineer', 'last_checked': '2026-03-20'}
        merge_into_existing(existing, new_data)
        assert existing['open_positions'] == 'ML Engineer'

    def test_merge_updates_last_checked(self):
        existing = _make_row('Anthropic', last_checked='2026-03-10')
        new_data = {'last_checked': '2026-03-20'}
        merge_into_existing(existing, new_data)
        assert existing['last_checked'] == '2026-03-20'

    def test_merge_keeps_later_last_checked(self):
        existing = _make_row('Anthropic', last_checked='2026-03-25')
        new_data = {'last_checked': '2026-03-20'}
        merge_into_existing(existing, new_data)
        assert existing['last_checked'] == '2026-03-25'


class TestNewerEvaluationWins:
    """Finding H1: the score ratchet. Re-evaluations must be able to
    LOWER a stale score; same-run duplicates keep higher-score dedup."""

    def test_newer_eval_with_lower_score_wins(self):
        existing = _make_row(
            'Anthropic', llm_score='88', llm_rationale='Old great fit',
            llm_evaluated_at='2026-05-01T00:00:00+00:00',
        )
        new_data = {
            'llm_score': '60',
            'llm_rationale': 'Cooled off',
            'llm_evaluated_at': '2026-06-01T00:00:00+00:00',
            'last_checked': '2026-06-01',
        }
        merge_into_existing(existing, new_data)
        assert existing['llm_score'] == '60'
        assert existing['llm_rationale'] == 'Cooled off'
        assert existing['llm_evaluated_at'] == '2026-06-01T00:00:00+00:00'

    def test_older_eval_never_clobbers_newer(self):
        existing = _make_row(
            'Anthropic', llm_score='60', llm_rationale='Current verdict',
            llm_evaluated_at='2026-06-01T00:00:00+00:00',
        )
        new_data = {
            'llm_score': '95',
            'llm_rationale': 'Stale enthusiasm',
            'llm_evaluated_at': '2026-04-01T00:00:00+00:00',
            'last_checked': '2026-04-01',
        }
        merge_into_existing(existing, new_data)
        assert existing['llm_score'] == '60'
        assert existing['llm_rationale'] == 'Current verdict'

    def test_newer_honest_zero_overwrites_stale_score(self):
        # H2 interaction: 0 is a real score and must be able to replace 88.
        existing = _make_row(
            'Anthropic', llm_score='88',
            llm_evaluated_at='2026-05-01T00:00:00+00:00',
        )
        new_data = {
            'llm_score': '0',
            'llm_rationale': 'No longer a fit',
            'llm_evaluated_at': '2026-06-01T00:00:00+00:00',
        }
        merge_into_existing(existing, new_data)
        assert existing['llm_score'] == '0'

    def test_unscored_result_never_clobbers_score(self):
        # A needs_research re-check (empty llm_score) must not erase a score.
        existing = _make_row(
            'Anthropic', llm_score='75', llm_rationale='Scored',
            llm_evaluated_at='2026-05-01T00:00:00+00:00',
        )
        new_data = {
            'llm_score': '',
            'llm_rationale': 'Could not assess',
            'llm_evaluated_at': '2026-06-01T00:00:00+00:00',
        }
        merge_into_existing(existing, new_data)
        assert existing['llm_score'] == '75'
        assert existing['llm_rationale'] == 'Scored'

    def test_same_timestamp_keeps_higher_score(self):
        # Same-run duplicates: genuine dedup semantics preserved.
        ts = '2026-06-01T00:00:00+00:00'
        existing = _make_row('Anthropic', llm_score='80', llm_evaluated_at=ts)
        new_data = {'llm_score': '70', 'llm_evaluated_at': ts}
        merge_into_existing(existing, new_data)
        assert existing['llm_score'] == '80'

        new_data = {'llm_score': '90', 'llm_evaluated_at': ts}
        merge_into_existing(existing, new_data)
        assert existing['llm_score'] == '90'

    def test_any_score_beats_unscored_existing(self):
        existing = _make_row('Anthropic', llm_score='')
        new_data = {'llm_score': '40', 'llm_evaluated_at': '2026-06-01T00:00:00+00:00'}
        merge_into_existing(existing, new_data)
        assert existing['llm_score'] == '40'

    def test_dimensions_evaluated_travels_with_winning_eval(self):
        # Finding M9: confidence stays attached to the verdict it belongs to.
        existing = _make_row(
            'Anthropic', llm_score='88', llm_dimensions_evaluated='5',
            llm_evaluated_at='2026-05-01T00:00:00+00:00',
        )
        new_data = {
            'llm_score': '70',
            'llm_dimensions_evaluated': '10',
            'llm_evaluated_at': '2026-06-01T00:00:00+00:00',
        }
        merge_into_existing(existing, new_data)
        assert existing['llm_score'] == '70'
        assert existing['llm_dimensions_evaluated'] == '10'
