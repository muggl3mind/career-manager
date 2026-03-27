"""Tests for role_family path validation in web_prospecting merge."""
import csv
import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'ops'))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'core'))


@pytest.fixture(autouse=True)
def patch_canonical_paths(monkeypatch):
    import web_prospecting
    monkeypatch.setattr(web_prospecting, '_CANONICAL_PATHS', ['Path Alpha'])


def _make_result_file(tmp_path: Path, company: str, role_family: str) -> None:
    from csv_schema import HEADER
    # Write empty target CSV
    target_csv = tmp_path / "target-companies.csv"
    with target_csv.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=HEADER)
        writer.writeheader()

    # Write empty seen-companies
    (tmp_path / "seen-companies.json").write_text("{}")

    # Write a prospecting-results file
    data = {
        "_meta": {"path_key": "path_a", "companies_found": 1},
        "results": [{
            "company": company,
            "website": f"{company.lower().replace(' ', '')}.com",
            "careers_url": f"https://{company.lower().replace(' ', '')}.com/careers",
            "prospect_status": "active_role",
            "open_positions": "Engineer",
            "llm_score": 75,
            "llm_rationale": "Good fit",
            "role_family": role_family,
            "llm_flags": "",
        }],
    }
    (tmp_path / "prospecting-results-path_a.json").write_text(json.dumps(data))


def _read_output_rows(tmp_path: Path) -> list[dict]:
    target_csv = tmp_path / "target-companies.csv"
    with target_csv.open(encoding="utf-8") as f:
        return list(csv.DictReader(f))


class TestPathValidation:
    def test_recognized_path_no_flag(self, tmp_path):
        """role_family matching a canonical path should NOT get unknown_path flag."""
        _make_result_file(tmp_path, "AlphaCo", "Path Alpha")

        from web_prospecting import cmd_merge_multifile
        rc = cmd_merge_multifile(data_dir=tmp_path)
        assert rc == 0

        rows = _read_output_rows(tmp_path)
        assert len(rows) == 1
        flags = rows[0].get("llm_flags", "")
        assert "unknown_path" not in flags, f"Expected no unknown_path flag, got: {flags!r}"

    def test_unrecognized_path_gets_flag(self, tmp_path):
        """role_family not matching any canonical path should get unknown_path flag."""
        _make_result_file(tmp_path, "TestCo", "Test Path")

        from web_prospecting import cmd_merge_multifile
        rc = cmd_merge_multifile(data_dir=tmp_path)
        assert rc == 0

        rows = _read_output_rows(tmp_path)
        assert len(rows) == 1
        flags = rows[0].get("llm_flags", "")
        assert "unknown_path" in flags, f"Expected unknown_path flag, got: {flags!r}"

    def test_empty_path_no_flag(self, tmp_path):
        """Empty role_family should NOT get unknown_path flag."""
        _make_result_file(tmp_path, "EmptyCo", "")

        from web_prospecting import cmd_merge_multifile
        rc = cmd_merge_multifile(data_dir=tmp_path)
        assert rc == 0

        rows = _read_output_rows(tmp_path)
        assert len(rows) == 1
        flags = rows[0].get("llm_flags", "")
        assert "unknown_path" not in flags, f"Expected no unknown_path flag for empty path, got: {flags!r}"
