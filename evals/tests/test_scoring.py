#!/usr/bin/env python3
"""Tests for the canonical ratio scoring module (job-search/scripts/core/scoring.py).

Locked decision (docs/superpowers/specs/2026-03-16-scoring-redesign.md):
score = yes_count / evaluated_count * 100, unknown dimensions are null
(never 0), minimum 5 of 10 dimensions evaluated to produce a score.
"""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'core'))

from scoring import (
    MIN_DIMENSIONS_EVALUATED,
    NEEDS_RESEARCH_FLAG,
    SCORING_INSTRUCTIONS,
    TOTAL_DIMENSIONS,
    classify_dimension,
    compute_score,
)


def _dims(yes=0, no=0, null=0):
    d = {}
    for i in range(yes):
        d[f'yes_{i}'] = True
    for i in range(no):
        d[f'no_{i}'] = False
    for i in range(null):
        d[f'null_{i}'] = None
    return d


class TestConstants:
    def test_minimum_is_five_of_ten(self):
        assert MIN_DIMENSIONS_EVALUATED == 5
        assert TOTAL_DIMENSIONS == 10

    def test_needs_research_flag_value(self):
        assert NEEDS_RESEARCH_FLAG == 'needs_research'


class TestMixed:
    def test_all_ten_evaluated_mixed(self):
        result = compute_score(_dims(yes=7, no=3))
        assert result.score == 70
        assert result.dimensions_evaluated == 10
        assert result.yes_count == 7
        assert result.needs_research is False

    def test_spec_example_seven_yes_of_eight_evaluated_is_87(self):
        # Spec worked example: 8 evaluated, 7 yes -> 87 (7/8), not 70 (7/10)
        result = compute_score(_dims(yes=7, no=1, null=2))
        assert result.score == 87
        assert result.dimensions_evaluated == 8

    def test_unknowns_excluded_not_counted_as_zero(self):
        # 5 yes + 5 unknown must be 100, not 50
        result = compute_score(_dims(yes=5, null=5))
        assert result.score == 100
        assert result.dimensions_evaluated == 5

    def test_all_no_scores_zero(self):
        result = compute_score(_dims(no=10))
        assert result.score == 0
        assert result.dimensions_evaluated == 10
        assert result.needs_research is False


class TestSparseData:
    def test_missing_keys_treated_as_not_evaluated(self):
        # Only 6 of 10 dimensions present at all
        result = compute_score(_dims(yes=5, no=1))
        assert result.score == 83  # floor(5/6 * 100)
        assert result.dimensions_evaluated == 6

    def test_sparse_below_threshold_returns_none(self):
        result = compute_score({'domain_fit': True, 'ai_centrality': False})
        assert result.score is None
        assert result.dimensions_evaluated == 2
        assert result.needs_research is True


class TestMinimumThreshold:
    def test_exactly_five_evaluated_produces_score(self):
        result = compute_score(_dims(yes=3, no=2, null=5))
        assert result.score == 60
        assert result.dimensions_evaluated == 5
        assert result.needs_research is False

    def test_four_evaluated_returns_none(self):
        result = compute_score(_dims(yes=4, null=6))
        assert result.score is None
        assert result.dimensions_evaluated == 4
        assert result.yes_count == 4
        assert result.needs_research is True


class TestZeroEvaluated:
    def test_all_null_returns_none(self):
        result = compute_score(_dims(null=10))
        assert result.score is None
        assert result.dimensions_evaluated == 0
        assert result.needs_research is True

    def test_empty_dict_returns_none(self):
        result = compute_score({})
        assert result.score is None
        assert result.dimensions_evaluated == 0
        assert result.needs_research is True

    def test_none_input_returns_none(self):
        result = compute_score(None)
        assert result.score is None
        assert result.dimensions_evaluated == 0

    def test_zero_evaluated_never_divides_even_with_zero_minimum(self):
        result = compute_score({}, minimum_evaluated=0)
        assert result.score is None
        assert result.needs_research is True


class TestValueCoercion:
    def test_string_values(self):
        result = compute_score({
            'a': 'yes', 'b': 'no', 'c': 'unknown',
            'd': 'true', 'e': 'false', 'f': 'null', 'g': '',
            'h': 'y', 'i': 'n',
        })
        assert result.dimensions_evaluated == 6
        assert result.yes_count == 3
        assert result.score == 50

    def test_one_zero_int_values(self):
        result = compute_score({'a': 1, 'b': 1, 'c': 1, 'd': 0, 'e': 0, 'f': None})
        assert result.score == 60
        assert result.dimensions_evaluated == 5

    def test_numeric_scale_values_rejected(self):
        # Legacy 0-10 numeric scales are NOT the ratio method
        with pytest.raises(ValueError):
            compute_score(_dims(yes=4, no=1) | {'comp_path': 7})

    def test_unrecognized_string_rejected(self):
        with pytest.raises(ValueError):
            classify_dimension('maybe')

    def test_classify_basics(self):
        assert classify_dimension(True) is True
        assert classify_dimension(False) is False
        assert classify_dimension(None) is None
        assert classify_dimension('n/a') is None


class TestRounding:
    def test_ratio_is_floored(self):
        # 1/3 -> 33.33 -> 33; 2/3 -> 66.66 -> 66
        assert compute_score(_dims(yes=2, no=4)).score == 33
        assert compute_score(_dims(yes=4, no=2)).score == 66

    def test_half_point_floors_per_spec_example(self):
        # 7/8 = 87.5 -> 87 per the spec's worked example
        assert compute_score(_dims(yes=7, no=1)).score == 87


class TestAgentInstructions:
    def test_instructions_describe_ratio_method(self):
        text = SCORING_INSTRUCTIONS.lower()
        assert 'yes count / evaluated count' in text
        assert 'null, never 0' in text
        assert 'fewer than 5 of 10' in text
        assert 'needs_research' in text
        assert 'fallback only' in text
