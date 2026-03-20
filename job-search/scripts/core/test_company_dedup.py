"""Tests for company_dedup module."""
from __future__ import annotations

import sys
from pathlib import Path

# Ensure core dir is on path
sys.path.insert(0, str(Path(__file__).resolve().parent))

from company_dedup import find_existing, merge_into_existing


def _make_row(company: str, **kwargs) -> dict:
    row = {'company': company, 'open_positions': '', 'llm_score': '', 'last_checked': ''}
    row.update(kwargs)
    return row


class TestFindExisting:
    def test_find_existing_exact_match(self):
        rows = [_make_row('Anthropic'), _make_row('OpenAI')]
        result = find_existing('anthropic', rows)
        assert result is not None
        assert result['company'] == 'Anthropic'

    def test_find_existing_alias_match(self):
        """Alias should match via normalize_company. Requires alias to be configured."""
        # This test verifies the alias mechanism works. Add aliases via
        # _company_alias() in path_normalizer.py for your target companies.
        # Example: _company_alias("Acme Corp", "acme", "acme inc")
        from path_normalizer import _company_alias, _COMPANY_ALIAS
        _company_alias("Acme Corp", "acme inc")
        try:
            rows = [_make_row('Acme Corp'), _make_row('OpenAI')]
            result = find_existing('Acme Inc', rows)
            assert result is not None
            assert result['company'] == 'Acme Corp'
        finally:
            # Clean up test alias
            _COMPANY_ALIAS.pop('acme inc', None)
            _COMPANY_ALIAS.pop('acme corp', None)

    def test_find_existing_alias_match_reverse(self):
        """Reverse alias lookup should also work."""
        from path_normalizer import _company_alias, _COMPANY_ALIAS
        _company_alias("Acme Corp", "acme inc")
        try:
            rows = [_make_row('Acme Inc'), _make_row('OpenAI')]
            result = find_existing('Acme Corp', rows)
            assert result is not None
            assert result['company'] == 'Acme Inc'
        finally:
            _COMPANY_ALIAS.pop('acme inc', None)
            _COMPANY_ALIAS.pop('acme corp', None)

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
        # Should not append since it's already there
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
