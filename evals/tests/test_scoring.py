#!/usr/bin/env python3
"""
Unit tests for score_companies.py pure functions.

Tests keyword_score() and score_company() with controlled inputs
to catch regressions in scoring math and edge cases.

Run: pytest career-manager/evals/tests/test_scoring.py -v
"""

import sys
from pathlib import Path
from unittest.mock import patch

# Add scoring module to path
CORE = Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'core'
sys.path.insert(0, str(CORE))

from score_companies import keyword_score, score_company

# Test-local keyword dicts — independent of search-config.json so tests work
# on fresh clones without onboarding.
TEST_DOMAIN_KEYWORDS = {
    'healthcare': 10, 'clinical': 10, 'patient care': 10,
    'biotech': 6, 'pharma': 4, 'insurance': 3,
}
TEST_AI_KEYWORDS = {
    'agentic ai': 10, 'ai platform': 8, 'ai': 6,
    'llm': 8, 'multi-agent': 9, 'machine learning': 7,
    'automation': 5, 'ai-native': 9,
}
TEST_ROLE_KEYWORDS = {
    'product manager': 10, 'solutions architect': 10,
    'ai lead': 9, 'innovation lead': 8,
}
TEST_COMP_INDICATORS = {
    'series c': 7, 'series d': 8, 'public': 8, 'unicorn': 9,
}
TEST_GROWTH_INDICATORS = {
    'series b': 8, 'hypergrowth': 9, 'raised': 6, 'sequoia': 7, 'a16z': 7,
}
TEST_CULTURE_KEYWORDS = {
    'remote_flexible': ['remote', 'distributed', 'flexible'],
    'innovation': ['innovation', 'builder', 'startup'],
    'technical': ['product-led', 'engineer', 'technical'],
}


# --- keyword_score tests ---

class TestKeywordScore:
    def test_empty_text_returns_zero(self):
        assert keyword_score('', TEST_DOMAIN_KEYWORDS) == 0

    def test_none_text_returns_zero(self):
        assert keyword_score(None, TEST_DOMAIN_KEYWORDS) == 0

    def test_no_matches_returns_zero(self):
        assert keyword_score('xyz completely unrelated text', TEST_DOMAIN_KEYWORDS) == 0

    def test_single_match_scales_correctly(self):
        # 'healthcare' has weight 10, max_score=25
        score = keyword_score('healthcare software', TEST_DOMAIN_KEYWORDS, max_score=25)
        # Single match: avg = 10/10 * 25 = 25.0
        assert score == 25.0

    def test_case_insensitive(self):
        score_lower = keyword_score('healthcare', TEST_DOMAIN_KEYWORDS)
        score_upper = keyword_score('HEALTHCARE', TEST_DOMAIN_KEYWORDS)
        assert score_lower == score_upper

    def test_multiple_matches_uses_top_3(self):
        # 'healthcare' (10), 'audit' (10), 'domain operations' (10), 'fintech' (6)
        text = 'healthcare clinical patient care biotech'
        score = keyword_score(text, TEST_DOMAIN_KEYWORDS, max_score=25)
        # Top 3: [10, 10, 10], avg=10, scaled = 25.0
        assert score == 25.0

    def test_lower_weight_matches_produce_lower_score(self):
        high = keyword_score('healthcare clinical', TEST_DOMAIN_KEYWORDS, max_score=25)
        low = keyword_score('pharma insurance', TEST_DOMAIN_KEYWORDS, max_score=25)
        assert high > low

    def test_max_score_parameter(self):
        score_25 = keyword_score('healthcare', TEST_DOMAIN_KEYWORDS, max_score=25)
        score_10 = keyword_score('healthcare', TEST_DOMAIN_KEYWORDS, max_score=10)
        assert score_25 == 25.0
        assert score_10 == 10.0

    def test_ai_keywords_agentic(self):
        score = keyword_score('agentic ai platform', TEST_AI_KEYWORDS, max_score=20)
        # 'agentic ai' (10), 'ai platform' (8), 'ai' (6) — top 3: [10,8,6], avg=8, scaled = 16.0
        assert score == 16.0

    def test_role_keywords(self):
        score = keyword_score('product manager', TEST_ROLE_KEYWORDS, max_score=15)
        assert score > 0

    def test_empty_keywords_dict(self):
        assert keyword_score('anything', {}) == 0

    def test_result_never_exceeds_max_score(self):
        big_text = ' '.join(TEST_DOMAIN_KEYWORDS.keys())
        score = keyword_score(big_text, TEST_DOMAIN_KEYWORDS, max_score=25)
        assert score <= 25.0


# --- score_company tests ---

class TestScoreCompany:
    def _make_row(self, **overrides):
        base = {
            'company': '', 'industry': '', 'tech_signals': '',
            'fit_rationale': '', 'open_positions': '', 'notes': '',
            'recent_funding': '', 'stage': '', 'careers_url': '',
        }
        base.update(overrides)
        return base

    def _score_with_test_keywords(self, row):
        """Run score_company with test-local keyword dicts patched in."""
        import score_companies as sc
        with patch.object(sc, 'DOMAIN_KEYWORDS', TEST_DOMAIN_KEYWORDS), \
             patch.object(sc, 'AI_KEYWORDS', TEST_AI_KEYWORDS), \
             patch.object(sc, 'ROLE_KEYWORDS', TEST_ROLE_KEYWORDS), \
             patch.object(sc, 'COMP_INDICATORS', TEST_COMP_INDICATORS), \
             patch.object(sc, 'GROWTH_INDICATORS', TEST_GROWTH_INDICATORS), \
             patch.object(sc, '_CULTURE', TEST_CULTURE_KEYWORDS):
            return score_company(row)

    def test_empty_row_returns_zero_total(self):
        result = self._score_with_test_keywords(self._make_row())
        assert result['total'] == 0
        assert result['domain'] == 0
        assert result['ai'] == 0

    def test_returns_all_component_keys(self):
        result = self._score_with_test_keywords(self._make_row())
        expected_keys = {'domain', 'ai', 'comp', 'role', 'growth', 'culture', 'total'}
        assert set(result.keys()) == expected_keys

    def test_high_domain_match(self):
        row = self._make_row(
            company='AccountingAI',
            industry='healthcare, clinical, patient care',
        )
        result = self._score_with_test_keywords(row)
        assert result['domain'] == 25.0  # top keywords all weight 10

    def test_ai_signals_scored(self):
        row = self._make_row(tech_signals='agentic ai, llm, multi-agent')
        result = self._score_with_test_keywords(row)
        assert result['ai'] > 0

    def test_role_only_uses_relevant_fields(self):
        row_in_role = self._make_row(open_positions='product manager')
        row_in_company = self._make_row(company='product manager inc')
        score_role = self._score_with_test_keywords(row_in_role)['role']
        score_company_name = self._score_with_test_keywords(row_in_company)['role']
        assert score_role > 0
        assert score_company_name == 0  # company name shouldn't affect role score

    def test_culture_remote_bonus(self):
        row_remote = self._make_row(notes='remote distributed team')
        row_no_remote = self._make_row(notes='onsite only')
        assert self._score_with_test_keywords(row_remote)['culture'] > \
               self._score_with_test_keywords(row_no_remote)['culture']

    def test_culture_capped_at_10(self):
        row = self._make_row(
            notes='remote distributed flexible innovation builder startup product-led engineer technical tier 1 dream'
        )
        assert self._score_with_test_keywords(row)['culture'] <= 10

    def test_total_is_sum_of_components(self):
        row = self._make_row(
            industry='healthcare biotech',
            tech_signals='ai platform',
            open_positions='product manager',
            notes='remote startup',
            stage='series c',
        )
        result = self._score_with_test_keywords(row)
        component_sum = round(
            result['domain'] + result['ai'] + result['comp'] +
            result['role'] + result['growth'] + result['culture'], 1
        )
        assert result['total'] == component_sum

    def test_perfect_company_scores_high(self):
        row = self._make_row(
            company='DreamCo',
            industry='healthcare, clinical',
            tech_signals='agentic ai, multi-agent, llm, ai-native',
            open_positions='senior product manager, solutions architect',
            fit_rationale='perfect role match, exactly what we need',
            notes='remote, builder culture, innovation, product-led, dream company',
            stage='series d, unicorn',
            recent_funding='raised $100m, sequoia, a16z',
        )
        result = self._score_with_test_keywords(row)
        assert result['total'] >= 70  # should score very high

    def test_irrelevant_company_scores_low(self):
        row = self._make_row(
            company='RandomCorp',
            industry='agriculture',
            notes='manual processes only',
        )
        result = self._score_with_test_keywords(row)
        assert result['total'] < 10
