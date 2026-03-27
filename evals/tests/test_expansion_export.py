"""Tests for expansion pass export and merge integration."""
import json
import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'ops'))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'core'))


def _write_csv(path: Path, rows: list[dict], header: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _make_pass1_results(path_key, companies):
    """Build a pass 1 result file dict with given companies."""
    results = []
    for name, score in companies:
        results.append({
            "company": name,
            "website": f"{name.lower().replace(' ', '')}.com",
            "careers_url": f"https://{name.lower().replace(' ', '')}.com/careers",
            "prospect_status": "active_role",
            "open_positions": "Some Role",
            "llm_score": score,
            "llm_rationale": "Good fit",
            "role_family": "Path Alpha",
            "path_name": "Path Alpha",
            "recent_funding": "$10M Series A" if score > 70 else "",
        })
    return {
        "_meta": {
            "path": "Path Alpha",
            "path_key": path_key,
            "queries_executed": 12,
            "companies_found": len(companies),
        },
        "results": results,
    }


def _write_search_config(tmp: Path, packs: dict) -> Path:
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
    }
    p = tmp / "search-config.json"
    p.write_text(json.dumps(cfg))
    return p


SAMPLE_PACKS = {
    "path_a": {"label": "Path Alpha", "queries": ["q1"], "locations": ["US"], "job_type": "fulltime"},
    "path_b": {"label": "Path Beta", "queries": ["q1"], "locations": ["US"], "job_type": "fulltime"},
}


class TestExpansionExport:
    def test_expansion_context_written_per_path(self, tmp_path):
        from csv_schema import HEADER
        cfg_path = _write_search_config(tmp_path, SAMPLE_PACKS)
        _write_csv(tmp_path / "target-companies.csv", [], HEADER)
        (tmp_path / "seen-companies.json").write_text("{}")

        companies = [(f"Co{i}", 80 - i * 2) for i in range(5)]
        for pk in ["path_a", "path_b"]:
            data = _make_pass1_results(pk, companies)
            (tmp_path / f"prospecting-results-{pk}.json").write_text(json.dumps(data))

        from web_prospecting import cmd_export_expansion
        rc = cmd_export_expansion(data_dir=tmp_path, config_path=cfg_path)
        assert rc == 0

        exp_files = sorted(tmp_path.glob("prospecting-context-*-expansion.json"))
        assert len(exp_files) == 2
        slugs = {f.stem.replace("prospecting-context-", "").replace("-expansion", "") for f in exp_files}
        assert slugs == {"path_a", "path_b"}

    def test_expansion_context_has_protocol_instructions(self, tmp_path):
        from csv_schema import HEADER
        cfg_path = _write_search_config(tmp_path, SAMPLE_PACKS)
        _write_csv(tmp_path / "target-companies.csv", [], HEADER)
        (tmp_path / "seen-companies.json").write_text("{}")

        companies = [(f"Co{i}", 80 - i * 2) for i in range(5)]
        data = _make_pass1_results("path_a", companies)
        (tmp_path / "prospecting-results-path_a.json").write_text(json.dumps(data))

        from web_prospecting import cmd_export_expansion
        cmd_export_expansion(data_dir=tmp_path, config_path=cfg_path)

        ctx = json.loads((tmp_path / "prospecting-context-path_a-expansion.json").read_text())
        instructions = ctx["instructions"]
        assert "COMPETITOR MINING" in instructions
        assert "INVESTOR PORTFOLIO" in instructions
        assert "COMMUNITY/LIST MINING" in instructions

    def test_expansion_skip_list_includes_pass1_and_known(self, tmp_path):
        from csv_schema import HEADER
        cfg_path = _write_search_config(tmp_path, SAMPLE_PACKS)
        _write_csv(tmp_path / "target-companies.csv", [{
            "company": "ExistingCo",
            "website": "existing.com",
            "last_checked": "2026-03-23",
            "validation_status": "pass",
        }], HEADER)
        (tmp_path / "seen-companies.json").write_text(json.dumps({
            "existingco": {"company": "ExistingCo", "website": "existing.com",
                           "last_checked": "2026-03-23T00:00:00+00:00", "first_seen": "2026-03-20T00:00:00+00:00"}
        }))

        companies = [("Co1", 80), ("Co2", 75), ("Co3", 70)]
        data = _make_pass1_results("path_a", companies)
        (tmp_path / "prospecting-results-path_a.json").write_text(json.dumps(data))

        from web_prospecting import cmd_export_expansion
        cmd_export_expansion(data_dir=tmp_path, config_path=cfg_path)

        ctx = json.loads((tmp_path / "prospecting-context-path_a-expansion.json").read_text())
        skip = [s.lower() for s in ctx["known_companies_skip"]]
        assert "co1" in skip
        assert "co2" in skip
        assert "co3" in skip
        assert "existingco" in skip

    def test_expansion_skipped_if_fewer_than_3_pass1_companies(self, tmp_path):
        from csv_schema import HEADER
        cfg_path = _write_search_config(tmp_path, SAMPLE_PACKS)
        _write_csv(tmp_path / "target-companies.csv", [], HEADER)
        (tmp_path / "seen-companies.json").write_text("{}")

        companies = [("Co1", 80), ("Co2", 75)]
        data = _make_pass1_results("path_a", companies)
        (tmp_path / "prospecting-results-path_a.json").write_text(json.dumps(data))

        from web_prospecting import cmd_export_expansion
        cmd_export_expansion(data_dir=tmp_path, config_path=cfg_path)

        exp_files = list(tmp_path.glob("prospecting-context-path_a-expansion.json"))
        assert len(exp_files) == 0

    def test_expansion_skipped_if_no_pass1_results(self, tmp_path):
        from csv_schema import HEADER
        cfg_path = _write_search_config(tmp_path, SAMPLE_PACKS)
        _write_csv(tmp_path / "target-companies.csv", [], HEADER)
        (tmp_path / "seen-companies.json").write_text("{}")

        companies = [(f"Co{i}", 80 - i * 2) for i in range(5)]
        data = _make_pass1_results("path_b", companies)
        (tmp_path / "prospecting-results-path_b.json").write_text(json.dumps(data))

        from web_prospecting import cmd_export_expansion
        cmd_export_expansion(data_dir=tmp_path, config_path=cfg_path)

        exp_files = list(tmp_path.glob("prospecting-context-*-expansion.json"))
        assert len(exp_files) == 1
        assert "path_b" in exp_files[0].name

    def test_expansion_and_pass1_both_merged(self, tmp_path):
        """Both prospecting-results-path_a.json and prospecting-results-path_a-expansion.json get merged."""
        from csv_schema import HEADER
        _write_csv(tmp_path / "target-companies.csv", [], HEADER)
        (tmp_path / "seen-companies.json").write_text("{}")

        pass1 = {
            "_meta": {"path_key": "path_a"},
            "results": [{
                "company": "Pass1Co", "website": "pass1.com",
                "careers_url": "https://pass1.com/careers",
                "prospect_status": "active_role", "open_positions": "PM",
                "llm_score": 80, "llm_rationale": "Fit",
                "role_family": "Path Alpha", "path_name": "Path Alpha",
            }],
        }
        expansion = {
            "_meta": {"path_key": "path_a", "pass": "expansion"},
            "results": [{
                "company": "ExpansionCo", "website": "expansion.com",
                "careers_url": "https://expansion.com/careers",
                "prospect_status": "active_role", "open_positions": "Engineer",
                "llm_score": 75, "llm_rationale": "Fit",
                "role_family": "Path Alpha", "path_name": "Path Alpha",
            }],
        }
        (tmp_path / "prospecting-results-path_a.json").write_text(json.dumps(pass1))
        (tmp_path / "prospecting-results-path_a-expansion.json").write_text(json.dumps(expansion))

        from web_prospecting import cmd_merge_multifile
        rc = cmd_merge_multifile(data_dir=tmp_path)
        assert rc == 0

        with (tmp_path / "target-companies.csv").open() as f:
            rows = list(csv.DictReader(f))
        names = {r["company"] for r in rows}
        assert "Pass1Co" in names
        assert "ExpansionCo" in names


class TestCumulativeExpansionSeeds:
    @pytest.fixture(autouse=True)
    def _patch_canonical_paths(self, monkeypatch):
        import web_prospecting
        monkeypatch.setattr(web_prospecting, '_CANONICAL_PATHS', ['Path Alpha', 'Path Beta'])

    def test_seeds_from_csv_when_pass1_has_few_results(self, tmp_path):
        """CSV has 4 pass companies for Path Alpha; pass1 has only 2. Expansion should run (6 >= 3)."""
        from csv_schema import HEADER
        cfg_path = _write_search_config(tmp_path, SAMPLE_PACKS)

        # CSV has 4 companies matching Path Alpha
        csv_companies = [
            {"company": f"CsvCo{i}", "website": f"csvco{i}.com", "role_family": "Path Alpha",
             "validation_status": "pass", "last_checked": ""}
            for i in range(4)
        ]
        _write_csv(tmp_path / "target-companies.csv", csv_companies, HEADER)
        (tmp_path / "seen-companies.json").write_text("{}")

        # Pass1 has only 2 results (below threshold of 3)
        pass1_companies = [("P1Co0", 85), ("P1Co1", 80)]
        data = _make_pass1_results("path_a", pass1_companies)
        (tmp_path / "prospecting-results-path_a.json").write_text(json.dumps(data))

        from web_prospecting import cmd_export_expansion
        rc = cmd_export_expansion(data_dir=tmp_path, config_path=cfg_path)
        assert rc == 0

        # Expansion file should be written because 2 + 4 = 6 >= 3
        exp_file = tmp_path / "prospecting-context-path_a-expansion.json"
        assert exp_file.exists(), "Expansion file should exist when CSV makes up the shortfall"

        ctx = json.loads(exp_file.read_text())
        seed_names = {s["company"] for s in ctx["seed_companies"]}
        # CSV companies should appear as seeds
        assert any(name.startswith("CsvCo") for name in seed_names), (
            f"Expected CSV companies in seeds, got: {seed_names}"
        )

    def test_expansion_history_written(self, tmp_path):
        """After export-expansion, expansion-history.json should exist with seed tracking entries."""
        from csv_schema import HEADER
        cfg_path = _write_search_config(tmp_path, SAMPLE_PACKS)
        _write_csv(tmp_path / "target-companies.csv", [], HEADER)
        (tmp_path / "seen-companies.json").write_text("{}")

        companies = [(f"Co{i}", 80 - i * 2) for i in range(5)]
        data = _make_pass1_results("path_a", companies)
        (tmp_path / "prospecting-results-path_a.json").write_text(json.dumps(data))

        from web_prospecting import cmd_export_expansion
        rc = cmd_export_expansion(data_dir=tmp_path, config_path=cfg_path)
        assert rc == 0

        history_path = tmp_path / "expansion-history.json"
        assert history_path.exists(), "expansion-history.json should be written after export"

        history = json.loads(history_path.read_text())
        assert len(history) > 0, "History should have at least one entry"

        # Each entry must have required fields
        for key, entry in history.items():
            assert "last_seeded" in entry, f"Entry {key} missing last_seeded"
            assert "seed_count" in entry, f"Entry {key} missing seed_count"
            assert "company" in entry, f"Entry {key} missing company"

    def test_seed_rotation_prefers_never_seeded(self, tmp_path):
        """Never-seeded companies are preferred over previously-seeded ones."""
        from csv_schema import HEADER
        cfg_path = _write_search_config(tmp_path, SAMPLE_PACKS)
        _write_csv(tmp_path / "target-companies.csv", [], HEADER)
        (tmp_path / "seen-companies.json").write_text("{}")

        # Pass1 has Co0-Co6, all same score so seed selection is by history only
        companies = [(f"Co{i}", 80) for i in range(7)]
        data = _make_pass1_results("path_a", companies)
        (tmp_path / "prospecting-results-path_a.json").write_text(json.dumps(data))

        # Pre-populate history: Co0, Co1, Co2 already seeded
        history = {
            f"co{i}": {"company": f"Co{i}", "last_seeded": "2026-03-20T00:00:00+00:00", "seed_count": 1}
            for i in range(3)
        }
        (tmp_path / "expansion-history.json").write_text(json.dumps(history))

        from web_prospecting import cmd_export_expansion
        rc = cmd_export_expansion(data_dir=tmp_path, config_path=cfg_path)
        assert rc == 0

        ctx = json.loads((tmp_path / "prospecting-context-path_a-expansion.json").read_text())
        seed_names = {s["company"] for s in ctx["seed_companies"]}

        # Never-seeded Co3 and Co4 should be among the seeds
        assert "Co3" in seed_names, f"Expected Co3 (never-seeded) in seeds, got: {seed_names}"
        assert "Co4" in seed_names, f"Expected Co4 (never-seeded) in seeds, got: {seed_names}"
