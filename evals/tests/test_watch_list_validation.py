"""Tests for watch_list evidence validation in prospecting merge."""
import json
import csv
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'ops'))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'core'))


def _write_csv(path: Path, rows: list[dict], header: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)


def _make_result(company, status="watch_list", score=60, watch_reason=None, watch_evidence=None):
    r = {
        "company": company,
        "website": f"{company.lower()}.com",
        "careers_url": f"https://{company.lower()}.com/careers",
        "prospect_status": status,
        "open_positions": "" if status == "watch_list" else "Some Role",
        "llm_score": score,
        "llm_rationale": "Fit",
        "role_family": "Path Alpha",
        "path_name": "Path Alpha",
        "llm_flags": "",
    }
    if watch_reason is not None:
        r["watch_reason"] = watch_reason
    if watch_evidence is not None:
        r["watch_evidence"] = watch_evidence
    return r


def _write_result_file(tmp_path, slug, results):
    data = {"_meta": {"path_key": slug, "companies_found": len(results)}, "results": results}
    (tmp_path / f"prospecting-results-{slug}.json").write_text(json.dumps(data))


def _setup_merge(tmp_path):
    from csv_schema import HEADER
    _write_csv(tmp_path / "target-companies.csv", [], HEADER)
    (tmp_path / "seen-companies.json").write_text("{}")


def _merged_rows(tmp_path):
    with (tmp_path / "target-companies.csv").open() as f:
        return list(csv.DictReader(f))


class TestWatchListValidation:
    def test_valid_watch_reason_and_evidence_merged_normally(self, tmp_path):
        _setup_merge(tmp_path)
        _write_result_file(tmp_path, "a", [
            _make_result("WatchCo", watch_reason="no_matching_roles",
                         watch_evidence="Careers page shows 3 eng roles only")
        ])
        from web_prospecting import cmd_merge_multifile
        rc = cmd_merge_multifile(data_dir=tmp_path)
        assert rc == 0
        rows = _merged_rows(tmp_path)
        co = [r for r in rows if r["company"] == "WatchCo"][0]
        assert "unvalidated_watch_list" not in co.get("llm_flags", "")

    def test_missing_watch_reason_flagged(self, tmp_path):
        _setup_merge(tmp_path)
        _write_result_file(tmp_path, "a", [
            _make_result("NoReasonCo")  # no watch_reason
        ])
        from web_prospecting import cmd_merge_multifile
        cmd_merge_multifile(data_dir=tmp_path)
        rows = _merged_rows(tmp_path)
        co = [r for r in rows if r["company"] == "NoReasonCo"][0]
        assert "unvalidated_watch_list" in co.get("llm_flags", "")

    def test_invalid_watch_reason_flagged(self, tmp_path):
        _setup_merge(tmp_path)
        _write_result_file(tmp_path, "a", [
            _make_result("BadReasonCo", watch_reason="ambiguous",
                         watch_evidence="Seems unclear")
        ])
        from web_prospecting import cmd_merge_multifile
        cmd_merge_multifile(data_dir=tmp_path)
        rows = _merged_rows(tmp_path)
        co = [r for r in rows if r["company"] == "BadReasonCo"][0]
        assert "unvalidated_watch_list" in co.get("llm_flags", "")

    def test_empty_watch_evidence_flagged(self, tmp_path):
        _setup_merge(tmp_path)
        _write_result_file(tmp_path, "a", [
            _make_result("NoEvidenceCo", watch_reason="no_matching_roles",
                         watch_evidence="")
        ])
        from web_prospecting import cmd_merge_multifile
        cmd_merge_multifile(data_dir=tmp_path)
        rows = _merged_rows(tmp_path)
        co = [r for r in rows if r["company"] == "NoEvidenceCo"][0]
        assert "unvalidated_watch_list" in co.get("llm_flags", "")

    def test_unable_to_verify_gets_needs_recheck(self, tmp_path):
        _setup_merge(tmp_path)
        _write_result_file(tmp_path, "a", [
            _make_result("UnverifiedCo", watch_reason="unable_to_verify",
                         watch_evidence="Careers page returned 403")
        ])
        from web_prospecting import cmd_merge_multifile
        cmd_merge_multifile(data_dir=tmp_path)
        rows = _merged_rows(tmp_path)
        co = [r for r in rows if r["company"] == "UnverifiedCo"][0]
        assert "needs_recheck" in co.get("llm_flags", "")

    def test_active_role_no_validation_required(self, tmp_path):
        _setup_merge(tmp_path)
        _write_result_file(tmp_path, "a", [
            _make_result("ActiveCo", status="active_role", score=80)
        ])
        from web_prospecting import cmd_merge_multifile
        cmd_merge_multifile(data_dir=tmp_path)
        rows = _merged_rows(tmp_path)
        co = [r for r in rows if r["company"] == "ActiveCo"][0]
        assert "unvalidated_watch_list" not in co.get("llm_flags", "")

    def test_notes_contain_watch_reason_and_evidence(self, tmp_path):
        _setup_merge(tmp_path)
        _write_result_file(tmp_path, "a", [
            _make_result("NotesCo", watch_reason="no_matching_roles",
                         watch_evidence="Only hiring engineers")
        ])
        from web_prospecting import cmd_merge_multifile
        cmd_merge_multifile(data_dir=tmp_path)
        rows = _merged_rows(tmp_path)
        co = [r for r in rows if r["company"] == "NotesCo"][0]
        assert "no_matching_roles" in co.get("notes", "")
        assert "Only hiring engineers" in co.get("notes", "")
