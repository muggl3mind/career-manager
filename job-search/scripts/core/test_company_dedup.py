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
