"""Tests for path normalization — config-driven version."""
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'core'))


@pytest.fixture(autouse=True)
def reset_normalizer_cache():
    """Reset the module cache and CONFIG_PATH before each test."""
    import path_normalizer
    original_config_path = path_normalizer.CONFIG_PATH
    path_normalizer._cache = None
    yield
    path_normalizer._cache = None
    path_normalizer.CONFIG_PATH = original_config_path


@pytest.fixture
def config_dir(tmp_path):
    """Create a temp search-config.json with test data."""
    config = {
        "query_packs": {
            "dental_ai": {"label": "Dental AI Startup", "queries": []},
            "dental_saas": {"label": "Dental Practice Software", "queries": []},
        },
        "path_aliases": {
            "dental ai": "Dental AI Startup",
            "dental tech startup": "Dental AI Startup",
            "dental saas": "Dental Practice Software",
        },
        "company_aliases": {
            "SmileTech Inc": "SmileTech",
            "SmileTech Corp": "SmileTech",
        },
        "role_include_patterns": [],
        "role_exclude_patterns": [],
        "employer_exclude_patterns": [],
        "location_exclude_patterns": [],
        "keywords": {"domain": []},
    }
    config_path = tmp_path / "search-config.json"
    config_path.write_text(json.dumps(config))
    return tmp_path


def test_normalize_path_exact_match(config_dir, monkeypatch):
    monkeypatch.setattr("path_normalizer.CONFIG_PATH", config_dir / "search-config.json")
    from path_normalizer import normalize_path
    assert normalize_path("Dental AI Startup") == "Dental AI Startup"


def test_normalize_path_case_insensitive(config_dir, monkeypatch):
    monkeypatch.setattr("path_normalizer.CONFIG_PATH", config_dir / "search-config.json")
    from path_normalizer import normalize_path
    assert normalize_path("dental ai startup") == "Dental AI Startup"


def test_normalize_path_unknown_passes_through(config_dir, monkeypatch):
    monkeypatch.setattr("path_normalizer.CONFIG_PATH", config_dir / "search-config.json")
    from path_normalizer import normalize_path
    assert normalize_path("Underwater Basket Weaving") == "Underwater Basket Weaving"


def test_normalize_path_empty():
    from path_normalizer import normalize_path
    assert normalize_path("") == ""


def test_normalize_path_with_whitespace(config_dir, monkeypatch):
    monkeypatch.setattr("path_normalizer.CONFIG_PATH", config_dir / "search-config.json")
    from path_normalizer import normalize_path
    assert normalize_path("  Dental AI Startup  ") == "Dental AI Startup"


def test_path_alias_resolves(config_dir, monkeypatch):
    """Fuzzy LLM variant resolves via path_aliases."""
    monkeypatch.setattr("path_normalizer.CONFIG_PATH", config_dir / "search-config.json")
    from path_normalizer import normalize_path
    assert normalize_path("dental ai") == "Dental AI Startup"
    assert normalize_path("dental tech startup") == "Dental AI Startup"


def test_exact_label_preferred_over_alias(config_dir, monkeypatch):
    """Exact query_pack label match takes precedence over alias."""
    monkeypatch.setattr("path_normalizer.CONFIG_PATH", config_dir / "search-config.json")
    from path_normalizer import normalize_path
    assert normalize_path("Dental AI Startup") == "Dental AI Startup"


def test_normalize_company_alias(config_dir, monkeypatch):
    monkeypatch.setattr("path_normalizer.CONFIG_PATH", config_dir / "search-config.json")
    from path_normalizer import normalize_company
    assert normalize_company("SmileTech Inc") == "SmileTech"
    assert normalize_company("smiletech corp") == "SmileTech"


def test_normalize_company_no_alias(config_dir, monkeypatch):
    monkeypatch.setattr("path_normalizer.CONFIG_PATH", config_dir / "search-config.json")
    from path_normalizer import normalize_company
    assert normalize_company("NoAlias Co") == "NoAlias Co"


def test_normalize_company_empty():
    from path_normalizer import normalize_company
    assert normalize_company("") == ""


def test_get_canonical_paths(config_dir, monkeypatch):
    monkeypatch.setattr("path_normalizer.CONFIG_PATH", config_dir / "search-config.json")
    from path_normalizer import get_canonical_paths
    paths = get_canonical_paths()
    assert "Dental AI Startup" in paths
    assert "Dental Practice Software" in paths


def test_no_config_file_graceful():
    """Without search-config.json, functions still work (pass-through)."""
    import path_normalizer
    path_normalizer.CONFIG_PATH = Path("/nonexistent/search-config.json")
    path_normalizer._cache = None
    assert path_normalizer.normalize_path("Anything") == "Anything"
    assert path_normalizer.normalize_company("Anything") == "Anything"
    assert path_normalizer.get_canonical_paths() == []


def test_backwards_compat_canonical_paths_param(config_dir, monkeypatch):
    """The canonical_paths parameter is ignored (backwards compat)."""
    monkeypatch.setattr("path_normalizer.CONFIG_PATH", config_dir / "search-config.json")
    from path_normalizer import normalize_path
    assert normalize_path("Dental AI Startup", []) == "Dental AI Startup"


def test_config_path_resolves_correctly():
    """CONFIG_PATH should point to job-search/data/search-config.json."""
    from path_normalizer import CONFIG_PATH
    assert CONFIG_PATH.parts[-3:] == ("job-search", "data", "search-config.json")
