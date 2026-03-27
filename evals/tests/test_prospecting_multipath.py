"""Tests for per-path prospecting export and merge."""
import json
import csv
import sys
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'ops'))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'core'))


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
        "scoring": {"domain_keywords": {}, "ai_keywords": {}, "role_keywords": {}, "comp_indicators": {}, "growth_indicators": {}, "culture_keywords": {}},
        "path_aliases": {},
    }
    p = tmp / "search-config.json"
    p.write_text(json.dumps(cfg))
    return p


def _write_csv(path: Path, rows: list[dict], header: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)


SAMPLE_PACKS = {
    "path_a": {"label": "Path Alpha", "queries": ["alpha q1"], "locations": ["US"], "job_type": "fulltime"},
    "path_b": {"label": "Path Beta", "queries": ["beta q1"], "locations": ["US"], "job_type": "fulltime"},
}


class TestPerPathExport:
    def test_export_writes_one_file_per_path(self, tmp_path):
        cfg_path = _write_search_config(tmp_path, SAMPLE_PACKS)
        target_csv = tmp_path / "target-companies.csv"
        _write_csv(target_csv, [], ["company", "website", "last_checked", "validation_status"])
        seen_path = tmp_path / "seen-companies.json"
        seen_path.write_text("{}")

        from web_prospecting import cmd_export_perpath
        cmd_export_perpath(data_dir=tmp_path, config_path=cfg_path)

        files = sorted(tmp_path.glob("prospecting-context-*.json"))
        assert len(files) == 2
        slugs = {f.stem.replace("prospecting-context-", "") for f in files}
        assert slugs == {"path_a", "path_b"}

    def test_each_context_file_has_required_fields(self, tmp_path):
        cfg_path = _write_search_config(tmp_path, SAMPLE_PACKS)
        target_csv = tmp_path / "target-companies.csv"
        _write_csv(target_csv, [], ["company", "website", "last_checked", "validation_status"])
        seen_path = tmp_path / "seen-companies.json"
        seen_path.write_text("{}")

        from web_prospecting import cmd_export_perpath
        cmd_export_perpath(data_dir=tmp_path, config_path=cfg_path)

        for f in tmp_path.glob("prospecting-context-*.json"):
            ctx = json.loads(f.read_text())
            assert "path_key" in ctx
            assert "path_label" in ctx
            assert "path_description" in ctx
            assert "known_companies_skip" in ctx
            assert "instructions" in ctx
            assert "results_schema" in ctx


class TestMultiFileMerge:
    def _write_target_csv(self, path, rows=None):
        from csv_schema import HEADER
        _write_csv(path, rows or [], HEADER)

    def test_merge_reads_multiple_result_files(self, tmp_path):
        """cmd_merge should glob for prospecting-results-*.json files."""
        self._write_target_csv(tmp_path / "target-companies.csv")
        (tmp_path / "seen-companies.json").write_text("{}")

        for slug, company in [("path_a", "AlphaCo"), ("path_b", "BetaCo")]:
            data = {
                "_meta": {"path_key": slug, "companies_found": 1},
                "results": [{
                    "company": company, "website": f"{company.lower()}.com",
                    "careers_url": f"https://{company.lower()}.com/careers",
                    "prospect_status": "active_role",
                    "open_positions": "Product Manager",
                    "llm_score": 80, "llm_rationale": "Good fit",
                    "role_family": "Path Alpha", "path_name": "Path Alpha",
                }],
            }
            (tmp_path / f"prospecting-results-{slug}.json").write_text(json.dumps(data))

        from web_prospecting import cmd_merge_multifile
        rc = cmd_merge_multifile(data_dir=tmp_path)
        assert rc == 0

        with (tmp_path / "target-companies.csv").open() as f:
            rows = list(csv.DictReader(f))
        names = {r["company"] for r in rows}
        assert "AlphaCo" in names
        assert "BetaCo" in names

    def test_merge_deduplicates_across_files(self, tmp_path):
        """Same company in two files: keep higher score, combine roles."""
        self._write_target_csv(tmp_path / "target-companies.csv")
        (tmp_path / "seen-companies.json").write_text("{}")

        for slug, score, role in [("path_a", 70, "PM"), ("path_b", 85, "Solutions Architect")]:
            data = {
                "_meta": {"path_key": slug},
                "results": [{
                    "company": "SharedCo", "website": "shared.com",
                    "careers_url": "https://shared.com/careers",
                    "prospect_status": "active_role",
                    "open_positions": role,
                    "llm_score": score, "llm_rationale": "Fit",
                    "role_family": "Path Alpha", "path_name": "Path Alpha",
                }],
            }
            (tmp_path / f"prospecting-results-{slug}.json").write_text(json.dumps(data))

        from web_prospecting import cmd_merge_multifile
        cmd_merge_multifile(data_dir=tmp_path)

        with (tmp_path / "target-companies.csv").open() as f:
            rows = list(csv.DictReader(f))
        shared = [r for r in rows if r["company"] == "SharedCo"]
        assert len(shared) == 1
        assert int(shared[0]["llm_score"]) == 85

    def test_merge_handles_old_format(self, tmp_path):
        """Plain JSON array (no _meta wrapper) still works."""
        self._write_target_csv(tmp_path / "target-companies.csv")
        (tmp_path / "seen-companies.json").write_text("{}")

        data = [{
            "company": "LegacyCo", "website": "legacy.com",
            "careers_url": "https://legacy.com/careers",
            "prospect_status": "active_role",
            "open_positions": "Engineer",
            "llm_score": 75, "llm_rationale": "OK",
            "role_family": "Path Alpha", "path_name": "Path Alpha",
        }]
        (tmp_path / "prospecting-results-legacy.json").write_text(json.dumps(data))

        from web_prospecting import cmd_merge_multifile
        rc = cmd_merge_multifile(data_dir=tmp_path)
        assert rc == 0

    def test_merge_skips_malformed_file(self, tmp_path):
        """Invalid JSON in one file should not block other files."""
        self._write_target_csv(tmp_path / "target-companies.csv")
        (tmp_path / "seen-companies.json").write_text("{}")

        good = {"_meta": {"path_key": "a"}, "results": [{
            "company": "GoodCo", "website": "good.com",
            "careers_url": "https://good.com/careers",
            "prospect_status": "active_role", "open_positions": "PM",
            "llm_score": 80, "llm_rationale": "Fit",
            "role_family": "Path A", "path_name": "Path A",
        }]}
        (tmp_path / "prospecting-results-good.json").write_text(json.dumps(good))
        (tmp_path / "prospecting-results-bad.json").write_text("{invalid json")

        from web_prospecting import cmd_merge_multifile
        rc = cmd_merge_multifile(data_dir=tmp_path)
        assert rc == 0

        with (tmp_path / "target-companies.csv").open() as f:
            rows = list(csv.DictReader(f))
        assert any(r["company"] == "GoodCo" for r in rows)


class TestSkipAwareExport:
    @pytest.fixture(autouse=True)
    def _patch_canonical_paths(self, monkeypatch):
        import web_prospecting
        monkeypatch.setattr(web_prospecting, '_CANONICAL_PATHS', ['Path Alpha', 'Path Beta'])

    def _write_target_csv(self, path, rows=None):
        from csv_schema import HEADER
        _write_csv(path, rows or [], HEADER)

    def test_known_companies_in_context(self, tmp_path):
        """Export includes known_companies with pass-status companies sorted by score."""
        cfg_path = _write_search_config(tmp_path, SAMPLE_PACKS)
        target_csv = tmp_path / "target-companies.csv"
        from csv_schema import HEADER
        rows = [
            {h: "" for h in HEADER} | {
                "company": f"KnownCo{i}",
                "role_family": "Path Alpha",
                "validation_status": "pass",
                "llm_score": str(score),
            }
            for i, score in enumerate([90, 85, 80, 75, 70])
        ]
        _write_csv(target_csv, rows, HEADER)
        (tmp_path / "seen-companies.json").write_text("{}")

        from web_prospecting import cmd_export_perpath
        cmd_export_perpath(data_dir=tmp_path, config_path=cfg_path)

        ctx = json.loads((tmp_path / "prospecting-context-path_a.json").read_text())
        assert "known_companies" in ctx
        known = ctx["known_companies"]
        assert len(known) == 5
        assert known[0] == "KnownCo0"  # highest score first

    def test_known_companies_capped_at_30(self, tmp_path):
        """known_companies is capped at 30 entries even when more exist."""
        cfg_path = _write_search_config(tmp_path, SAMPLE_PACKS)
        target_csv = tmp_path / "target-companies.csv"
        from csv_schema import HEADER
        rows = [
            {h: "" for h in HEADER} | {
                "company": f"Co{i}",
                "role_family": "Path Alpha",
                "validation_status": "pass",
                "llm_score": str(50 + i),
            }
            for i in range(40)
        ]
        _write_csv(target_csv, rows, HEADER)
        (tmp_path / "seen-companies.json").write_text("{}")

        from web_prospecting import cmd_export_perpath
        cmd_export_perpath(data_dir=tmp_path, config_path=cfg_path)

        ctx = json.loads((tmp_path / "prospecting-context-path_a.json").read_text())
        assert len(ctx["known_companies"]) == 30

    def test_known_companies_only_pass_status(self, tmp_path):
        """known_companies only includes rows with validation_status == 'pass'."""
        cfg_path = _write_search_config(tmp_path, SAMPLE_PACKS)
        target_csv = tmp_path / "target-companies.csv"
        from csv_schema import HEADER
        rows = [
            {h: "" for h in HEADER} | {
                "company": "PassCo",
                "role_family": "Path Alpha",
                "validation_status": "pass",
                "llm_score": "80",
            },
            {h: "" for h in HEADER} | {
                "company": "WatchCo",
                "role_family": "Path Alpha",
                "validation_status": "watch_list",
                "llm_score": "70",
            },
            {h: "" for h in HEADER} | {
                "company": "FailCo",
                "role_family": "Path Alpha",
                "validation_status": "fail",
                "llm_score": "60",
            },
        ]
        _write_csv(target_csv, rows, HEADER)
        (tmp_path / "seen-companies.json").write_text("{}")

        from web_prospecting import cmd_export_perpath
        cmd_export_perpath(data_dir=tmp_path, config_path=cfg_path)

        ctx = json.loads((tmp_path / "prospecting-context-path_a.json").read_text())
        assert ctx["known_companies"] == ["PassCo"]

    def test_instructions_mention_known_companies(self, tmp_path):
        """Instructions reference known_companies when pass companies exist."""
        cfg_path = _write_search_config(tmp_path, SAMPLE_PACKS)
        target_csv = tmp_path / "target-companies.csv"
        from csv_schema import HEADER
        rows = [
            {h: "" for h in HEADER} | {
                "company": "SomeCo",
                "role_family": "Path Alpha",
                "validation_status": "pass",
                "llm_score": "75",
            },
        ]
        _write_csv(target_csv, rows, HEADER)
        (tmp_path / "seen-companies.json").write_text("{}")

        from web_prospecting import cmd_export_perpath
        cmd_export_perpath(data_dir=tmp_path, config_path=cfg_path)

        ctx = json.loads((tmp_path / "prospecting-context-path_a.json").read_text())
        instructions = ctx["instructions"]
        assert "already track" in instructions or "known_companies" in instructions
