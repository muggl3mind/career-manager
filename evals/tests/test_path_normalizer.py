"""Tests for path normalization against canonical career paths."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'core'))


def test_known_alias_resolves():
    from path_normalizer import normalize_path
    # "Professional Services" is a known alias for "Accounting Professional Services"
    assert normalize_path("Professional Services") == "Accounting Professional Services"


def test_canonical_name_unchanged():
    from path_normalizer import normalize_path
    assert normalize_path("Tier 1 AI Companies") == "Tier 1 AI Companies"


def test_unknown_name_passes_through():
    from path_normalizer import normalize_path
    assert normalize_path("Underwater Basket Weaving") == "Underwater Basket Weaving"


def test_case_insensitive():
    from path_normalizer import normalize_path
    assert normalize_path("tier 1 ai companies") == "Tier 1 AI Companies"


def test_empty_canonical_list_ignored():
    from path_normalizer import normalize_path
    # canonical_paths param is kept for backwards compat but ignored
    assert normalize_path("Tier 1 AI Companies", []) == "Tier 1 AI Companies"


def test_empty_raw_name():
    from path_normalizer import normalize_path
    assert normalize_path("") == ""
