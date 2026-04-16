#!/usr/bin/env python3
"""
Tests for Stage 3 — min-N quota removal + config-driven thresholds in prospecting contexts.

Verifies:
  - Prospecting context files carry discover_min_score + per_agent_query_budget
  - Instructions no longer contain "Minimum N companies" language
  - Instructions explicitly permit empty results
  - Merge step handles empty result arrays cleanly

Run: pytest career-manager/evals/tests/test_no_min_quota.py -v
"""
from __future__ import annotations

import csv
import json
import sys
from pathlib import Path

REPO = Path(__file__).resolve().parents[2]
CORE = REPO / 'job-search' / 'scripts' / 'core'
OPS = REPO / 'job-search' / 'scripts' / 'ops'

sys.path.insert(0, str(CORE))
sys.path.insert(0, str(OPS))

SAMPLE_PACKS = {
    "path_a": {
        "label": "Path A", "role_family": "Path A",
        "description": "Path A description",
        "queries": ["path A query"], "locations": ["United States"],
    },
}


def _write_search_config(tmp_path: Path, packs: dict) -> Path:
    cfg = {
        "query_packs": packs,
        "path_check_instructions": {
            str(i + 1): f"Search for roles in {v['label']}"
            for i, (k, v) in enumerate(packs.items())
        },
        "role_include_patterns": [],
        "role_exclude_patterns": [],
        "employer_exclude_patterns": [],
        "location_exclude_patterns": [],
        "keywords": [],
        "agency_patterns": [],
        "scoring": {"domain_keywords": {}, "ai_keywords": {}, "role_keywords": {},
                    "comp_indicators": {}, "growth_indicators": {}, "culture_keywords": {}},
        "path_aliases": {},
        "search_locations": ["United States"],
    }
    path = tmp_path / "search-config.json"
    path.write_text(json.dumps(cfg))
    return path


def _write_targets(tmp_path: Path) -> None:
    from csv_schema import HEADER
    path = tmp_path / "target-companies.csv"
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=HEADER)
        w.writeheader()


class TestContextCarriesThresholds:
    def test_pass1_context_contains_discover_min_score(self, tmp_path, monkeypatch):
        cfg_path = _write_search_config(tmp_path, SAMPLE_PACKS)
        _write_targets(tmp_path)
        (tmp_path / "seen-companies.json").write_text(json.dumps({}))

        from web_prospecting import cmd_export_perpath
        cmd_export_perpath(data_dir=tmp_path, config_path=cfg_path)

        ctx = json.loads((tmp_path / "prospecting-context-path_a.json").read_text())
        assert 'discover_min_score' in ctx
        assert 'per_agent_query_budget' in ctx
        assert isinstance(ctx['discover_min_score'], (int, float))
        assert isinstance(ctx['per_agent_query_budget'], int)

    def test_pass1_instructions_have_no_minimum_quota(self, tmp_path):
        cfg_path = _write_search_config(tmp_path, SAMPLE_PACKS)
        _write_targets(tmp_path)
        (tmp_path / "seen-companies.json").write_text(json.dumps({}))

        from web_prospecting import cmd_export_perpath
        cmd_export_perpath(data_dir=tmp_path, config_path=cfg_path)

        ctx = json.loads((tmp_path / "prospecting-context-path_a.json").read_text())
        instructions = ctx['instructions'].lower()
        assert 'minimum 8' not in instructions
        assert 'minimum of 8' not in instructions
        assert 'at least 8' not in instructions

    def test_pass1_instructions_permit_empty_results(self, tmp_path):
        cfg_path = _write_search_config(tmp_path, SAMPLE_PACKS)
        _write_targets(tmp_path)
        (tmp_path / "seen-companies.json").write_text(json.dumps({}))

        from web_prospecting import cmd_export_perpath
        cmd_export_perpath(data_dir=tmp_path, config_path=cfg_path)

        ctx = json.loads((tmp_path / "prospecting-context-path_a.json").read_text())
        instructions = ctx['instructions'].lower()
        assert 'empty' in instructions
        assert 'no minimum' in instructions


class TestExpansionContextCarriesThresholds:
    def _setup_pass1(self, tmp_path: Path) -> Path:
        cfg_path = _write_search_config(tmp_path, SAMPLE_PACKS)
        _write_targets(tmp_path)
        (tmp_path / "seen-companies.json").write_text(json.dumps({}))
        results = {
            "_meta": {"path": "Path A", "path_key": "path_a"},
            "results": [
                {"company": f"SeedCo{i}", "website": f"seed{i}.com",
                 "careers_url": f"https://seed{i}.com/careers",
                 "llm_score": 85 - i, "prospect_status": "active_role",
                 "path": "path_a", "path_name": "Path A"}
                for i in range(5)
            ],
        }
        (tmp_path / "prospecting-results-path_a.json").write_text(json.dumps(results))
        return cfg_path

    def test_expansion_context_contains_discover_min_score(self, tmp_path):
        cfg_path = self._setup_pass1(tmp_path)

        from web_prospecting import cmd_export_expansion
        cmd_export_expansion(data_dir=tmp_path, config_path=cfg_path)

        ctx = json.loads((tmp_path / "prospecting-context-path_a-expansion.json").read_text())
        assert 'discover_min_score' in ctx
        assert 'per_agent_query_budget' in ctx

    def test_expansion_instructions_have_no_minimum_quota(self, tmp_path):
        cfg_path = self._setup_pass1(tmp_path)

        from web_prospecting import cmd_export_expansion
        cmd_export_expansion(data_dir=tmp_path, config_path=cfg_path)

        ctx = json.loads((tmp_path / "prospecting-context-path_a-expansion.json").read_text())
        instructions = ctx['instructions'].lower()
        assert 'minimum 5' not in instructions
        assert 'minimum of 4' not in instructions
        assert 'minimum of 5' not in instructions


class TestSuggestedQueries:
    def test_pass1_context_has_suggested_queries(self, tmp_path):
        cfg_path = _write_search_config(tmp_path, SAMPLE_PACKS)
        _write_targets(tmp_path)
        (tmp_path / "seen-companies.json").write_text("{}")

        from web_prospecting import cmd_export_perpath
        cmd_export_perpath(data_dir=tmp_path, config_path=cfg_path)

        ctx = json.loads((tmp_path / "prospecting-context-path_a.json").read_text())
        assert 'suggested_queries' in ctx
        assert isinstance(ctx['suggested_queries'], list)
        assert len(ctx['suggested_queries']) > 0
        # All suggested queries must reference the path label
        assert all('Path A' in q for q in ctx['suggested_queries'])

    def test_suggested_queries_use_path_label_domain_agnostic(self, tmp_path):
        """Generator must work for any domain, not bake in finance/AI assumptions."""
        packs = {"healthcare_ai": {"label": "Healthcare AI", "queries": ["q"], "locations": ["US"]}}
        cfg_path = _write_search_config(tmp_path, packs)
        _write_targets(tmp_path)
        (tmp_path / "seen-companies.json").write_text("{}")

        from web_prospecting import cmd_export_perpath
        cmd_export_perpath(data_dir=tmp_path, config_path=cfg_path)

        ctx = json.loads((tmp_path / "prospecting-context-healthcare_ai.json").read_text())
        joined = ' '.join(ctx['suggested_queries'])
        assert 'Healthcare AI' in joined
        # Should NOT contain finance-specific leakage
        for term in ['domain operations', 'accounting', 'CPA', 'Big 4', 'PE fund']:
            assert term not in joined, f"Found hardcoded domain term: {term}"


class TestEmptyResultsMerge:
    def test_merge_accepts_empty_results_wrapper(self, tmp_path):
        """Merge should not crash when results array is empty."""
        from csv_schema import HEADER

        cfg_path = _write_search_config(tmp_path, SAMPLE_PACKS)

        target_path = tmp_path / "target-companies.csv"
        with target_path.open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=HEADER)
            w.writeheader()

        (tmp_path / "seen-companies.json").write_text(json.dumps({}))

        empty = {
            "_meta": {"path": "Path A", "path_key": "path_a",
                      "queries_executed": 10, "companies_found": 0,
                      "active_roles": 0, "watch_list": 0, "top_3": []},
            "results": [],
        }
        (tmp_path / "prospecting-results-path_a.json").write_text(json.dumps(empty))

        from web_prospecting import cmd_merge_multifile
        cmd_merge_multifile(data_dir=tmp_path, dry_run=False)

        # Should complete and leave CSV unchanged
        with target_path.open() as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 0

    def test_merge_accepts_bare_empty_array(self, tmp_path):
        """Older prospecting runs may write a bare [] instead of the wrapper."""
        from csv_schema import HEADER

        cfg_path = _write_search_config(tmp_path, SAMPLE_PACKS)

        target_path = tmp_path / "target-companies.csv"
        with target_path.open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=HEADER)
            w.writeheader()

        (tmp_path / "seen-companies.json").write_text(json.dumps({}))
        (tmp_path / "prospecting-results-path_a.json").write_text('[]')

        from web_prospecting import cmd_merge_multifile
        cmd_merge_multifile(data_dir=tmp_path, dry_run=False)

        with target_path.open() as f:
            rows = list(csv.DictReader(f))
        assert len(rows) == 0
