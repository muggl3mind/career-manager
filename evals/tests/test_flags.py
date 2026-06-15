"""Tests for the canonical llm_flags helpers (finding M6).

The flag-separator mismatch: web_prospecting wrote comma-separated flags
(and the results schema told agents "Comma-separated") while the monitor
lifecycle parsed flags with split('|'). 'fetch_empty' inside a
comma-separated string was never detected, so unreachable (possibly dead)
companies were counted as freshly verified. scripts/core/flags.py is now
the single source of truth: write with ',', read both ',' and '|'.
"""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'core'))

from flags import (
    FLAG_SEPARATOR,
    add_flag,
    has_flag,
    join_flags,
    normalize_flags,
    remove_flag,
    split_flags,
)


class TestSplitFlags:
    def test_empty_inputs(self):
        assert split_flags('') == []
        assert split_flags(None) == []

    def test_comma_separated(self):
        assert split_flags('comp_unknown,fetch_empty') == ['comp_unknown', 'fetch_empty']

    def test_pipe_separated_legacy(self):
        assert split_flags('comp_unknown|fetch_empty') == ['comp_unknown', 'fetch_empty']

    def test_mixed_separators(self):
        assert split_flags('a,b|c') == ['a', 'b', 'c']

    def test_strips_whitespace_and_empties(self):
        # apply_eval_results joins red flags with ' | '
        assert split_flags('needs_research | fetch_empty') == ['needs_research', 'fetch_empty']
        assert split_flags(',,a,|,b,') == ['a', 'b']


class TestHasFlag:
    def test_regression_m6_comma_separated_fetch_empty(self):
        """The exact bug: comma-separated fetch_empty was missed by split('|')."""
        flags = 'comp_unknown,fetch_empty'
        assert 'fetch_empty' not in flags.split('|')  # the old broken parse
        assert has_flag(flags, 'fetch_empty')          # the fix

    def test_pipe_separated_still_detected(self):
        assert has_flag('needs_research|fetch_empty|some_other', 'fetch_empty')

    def test_no_substring_false_positive(self):
        assert not has_flag('fetch_empty_retry', 'fetch_empty')

    def test_absent(self):
        assert not has_flag('comp_unknown', 'fetch_empty')
        assert not has_flag('', 'fetch_empty')
        assert not has_flag(None, 'fetch_empty')


class TestJoinAddRemove:
    def test_join_uses_canonical_separator(self):
        assert FLAG_SEPARATOR == ','
        assert join_flags(['a', 'b']) == 'a,b'

    def test_normalize_rewrites_pipes_to_commas(self):
        assert normalize_flags('a|b|c') == 'a,b,c'
        assert normalize_flags(' a | b ') == 'a,b'
        assert normalize_flags('') == ''

    def test_add_flag_idempotent(self):
        assert add_flag('', 'x') == 'x'
        assert add_flag('a', 'x') == 'a,x'
        assert add_flag('a,x', 'x') == 'a,x'
        assert add_flag('a|x', 'x') == 'a,x'

    def test_remove_flag(self):
        assert remove_flag('a,x,b', 'x') == 'a,b'
        assert remove_flag('a|x', 'x') == 'a'
        assert remove_flag('a', 'x') == 'a'
        assert remove_flag('', 'x') == ''
