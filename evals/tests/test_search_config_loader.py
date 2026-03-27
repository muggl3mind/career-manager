#!/usr/bin/env python3
"""Tests for search_config_loader."""

import json
import os
import sys
import tempfile
from pathlib import Path

import pytest

# Add the module to path
sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent / "job-search" / "scripts" / "core"))

from search_config_loader import load_search_config, REQUIRED_KEYS


@pytest.fixture
def valid_config(tmp_path):
    """Create a minimal valid search-config.json."""
    config = {
        "query_packs": {
            "test_pack": {
                "label": "Test Pack",
                "queries": ["test query 1", "test query 2"]
            }
        },
        "role_include_patterns": ["product manager", "engineer"],
        "role_exclude_patterns": ["intern"],
        "employer_exclude_patterns": ["university"],
        "location_exclude_patterns": ["london"],
        "role_rescue_keywords": ["ai", "product"],
        "keywords": {
            "domain": ["accounting"],
            "ai": ["ai"],
            "tech": ["python"]
        },
    }
    config_path = tmp_path / "search-config.json"
    config_path.write_text(json.dumps(config))
    return config_path


@pytest.fixture
def missing_key_config(tmp_path):
    """Config missing required keys."""
    config = {"query_packs": {}}
    config_path = tmp_path / "search-config.json"
    config_path.write_text(json.dumps(config))
    return config_path


def test_load_valid_config(valid_config):
    result = load_search_config(valid_config)
    assert result is not None
    assert "query_packs" in result
    assert result["query_packs"]["test_pack"]["label"] == "Test Pack"
    assert len(result["role_include_patterns"]) == 2


def test_load_missing_file():
    result = load_search_config(Path("/nonexistent/search-config.json"))
    assert result is None


def test_load_missing_keys(missing_key_config):
    result = load_search_config(missing_key_config)
    assert result is None


def test_query_pack_to_path_derivation(valid_config):
    result = load_search_config(valid_config)
    pack_to_path = {k: v["label"] for k, v in result["query_packs"].items()}
    assert pack_to_path == {"test_pack": "Test Pack"}


def test_regex_patterns_compilable(valid_config):
    """Verify all pattern lists contain valid regex."""
    import re
    result = load_search_config(valid_config)
    for pattern in result["role_include_patterns"]:
        re.compile(pattern)  # Should not raise
    for pattern in result["role_exclude_patterns"]:
        re.compile(pattern)


def test_load_invalid_regex(tmp_path):
    """Config with invalid regex should return None."""
    config = {
        "query_packs": {"p": {"label": "P", "queries": ["q"]}},
        "role_include_patterns": ["[unclosed"],
        "role_exclude_patterns": [],
        "employer_exclude_patterns": [],
        "location_exclude_patterns": [],
        "keywords": {"domain": [], "ai": [], "tech": []},
    }
    config_path = tmp_path / "search-config.json"
    config_path.write_text(json.dumps(config))
    result = load_search_config(config_path)
    assert result is None


def test_load_malformed_json(tmp_path):
    """Malformed JSON should return None."""
    config_path = tmp_path / "search-config.json"
    config_path.write_text("{bad json")
    result = load_search_config(config_path)
    assert result is None


def test_search_locations_optional(valid_config):
    """search_locations is optional — pipeline defaults to US if missing."""
    result = load_search_config(valid_config)
    # Field is optional, so config loads fine without it
    assert result is not None
    # Pipeline code uses .get() with default, so no crash
    assert result.get("search_locations", ["United States"]) == ["United States"]


def test_search_locations_present(tmp_path):
    """search_locations is read when present."""
    config = {
        "search_locations": ["United States", "Ireland"],
        "query_packs": {
            "test_pack": {
                "label": "Test Pack",
                "queries": ["test query"]
            }
        },
        "role_include_patterns": ["engineer"],
        "role_exclude_patterns": ["intern"],
        "employer_exclude_patterns": ["university"],
        "location_exclude_patterns": [],
        "keywords": {"domain": ["ai"], "ai": ["ai"], "tech": ["python"]},
    }
    config_path = tmp_path / "search-config.json"
    config_path.write_text(json.dumps(config))
    result = load_search_config(config_path)
    assert result["search_locations"] == ["United States", "Ireland"]
