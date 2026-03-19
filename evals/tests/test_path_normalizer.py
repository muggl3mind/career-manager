"""Tests for path normalization against canonical career paths."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'core'))


def test_exact_match():
    from path_normalizer import normalize_path
    canonical = ["AI Product Management", "PE Operations", "Professional Services"]
    assert normalize_path("Professional Services", canonical) == "Professional Services"


def test_close_variant():
    from path_normalizer import normalize_path
    canonical = ["AI Product Management", "PE Operations", "Professional Services"]
    result = normalize_path("AI PM", canonical)
    assert result in ("AI Product Management", "AI PM")


def test_no_match_below_threshold():
    from path_normalizer import normalize_path
    canonical = ["AI Product Management", "PE Operations"]
    assert normalize_path("Underwater Basket Weaving", canonical) == "Underwater Basket Weaving"


def test_case_insensitive():
    from path_normalizer import normalize_path
    canonical = ["Professional Services"]
    assert normalize_path("professional services", canonical) == "Professional Services"


def test_empty_canonical_list():
    from path_normalizer import normalize_path
    assert normalize_path("Anything", []) == "Anything"


def test_empty_raw_name():
    from path_normalizer import normalize_path
    assert normalize_path("", ["AI Product Management"]) == ""
