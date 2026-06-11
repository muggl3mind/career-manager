"""Tests for fetch_empty preservation in monitor merge.

When Tavily rate-limits a careers page fetch, the agent emits
status=no_change with llm_flags containing 'fetch_empty'. The merge
must NOT bump last_checked to today in that case, so the row ages
naturally and gets retried on the next run.
"""
import json
import csv
import sys
from pathlib import Path
from datetime import datetime, timedelta, timezone

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'ops'))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'core'))


def _write_csv(path: Path, rows: list[dict], header: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def _setup(tmp_path, monkeypatch, target_rows, monitor_results):
    from csv_schema import HEADER
    import monitor_watchlist as mw

    _write_csv(tmp_path / "target-companies.csv", target_rows, HEADER)
    (tmp_path / "monitor-results.json").write_text(json.dumps(monitor_results))
    (tmp_path / "seen-companies.json").write_text(json.dumps({}))

    monkeypatch.setattr(mw, "TARGET_CSV", tmp_path / "target-companies.csv")
    monkeypatch.setattr(mw, "SEEN_COMPANIES", tmp_path / "seen-companies.json")
    monkeypatch.setattr(mw, "MONITOR_RESULTS", tmp_path / "monitor-results.json")
    return mw


class TestFetchEmptyPreservation:
    def test_no_change_bumps_last_checked(self, tmp_path, monkeypatch):
        """When status=no_change with no fetch_empty, last_checked advances to today."""
        from csv_schema import HEADER
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime('%Y-%m-%d')
        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

        target_rows = [{
            "company": "NormalCo",
            "website": "normalco.com",
            "careers_url": "https://normalco.com/careers",
            "last_checked": old_date,
            "validation_status": "pass",
            "llm_flags": "",
            "role_family": "Path Alpha",
            "open_positions": "",
        }]
        monitor_results = [{
            "company": "NormalCo",
            "status": "no_change",
            "llm_flags": "",
        }]

        mw = _setup(tmp_path, monkeypatch, target_rows, monitor_results)
        mw.cmd_merge()

        with (tmp_path / "target-companies.csv").open() as f:
            reader = csv.DictReader(f)
            rows = list(reader)

        match = next(r for r in rows if r["company"] == "NormalCo")
        assert match["last_checked"] == today, f"expected today, got {match['last_checked']}"

    def test_fetch_empty_preserves_last_checked(self, tmp_path, monkeypatch):
        """When status=no_change with fetch_empty in llm_flags, last_checked stays unchanged."""
        from csv_schema import HEADER
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime('%Y-%m-%d')

        target_rows = [{
            "company": "RateLimitedCo",
            "website": "rl.com",
            "careers_url": "https://rl.com/careers",
            "last_checked": old_date,
            "validation_status": "pass",
            "llm_flags": "",
            "role_family": "Path Alpha",
            "open_positions": "",
        }]
        monitor_results = [{
            "company": "RateLimitedCo",
            "status": "no_change",
            "llm_flags": "fetch_empty",
        }]

        mw = _setup(tmp_path, monkeypatch, target_rows, monitor_results)
        mw.cmd_merge()

        with (tmp_path / "target-companies.csv").open() as f:
            rows = list(csv.DictReader(f))

        match = next(r for r in rows if r["company"] == "RateLimitedCo")
        assert match["last_checked"] == old_date, (
            f"fetch_empty should preserve old last_checked, got {match['last_checked']}"
        )

    def test_fetch_empty_in_compound_flags_preserves(self, tmp_path, monkeypatch):
        """fetch_empty alongside other pipe-separated flags still preserves."""
        from csv_schema import HEADER
        old_date = (datetime.now(timezone.utc) - timedelta(days=10)).strftime('%Y-%m-%d')

        target_rows = [{
            "company": "MultiFlagCo",
            "website": "mf.com",
            "careers_url": "https://mf.com/careers",
            "last_checked": old_date,
            "validation_status": "pass",
            "llm_flags": "",
            "role_family": "Path Alpha",
            "open_positions": "",
        }]
        monitor_results = [{
            "company": "MultiFlagCo",
            "status": "no_change",
            "llm_flags": "needs_research|fetch_empty|some_other",
        }]

        mw = _setup(tmp_path, monkeypatch, target_rows, monitor_results)
        mw.cmd_merge()

        with (tmp_path / "target-companies.csv").open() as f:
            rows = list(csv.DictReader(f))

        match = next(r for r in rows if r["company"] == "MultiFlagCo")
        assert match["last_checked"] == old_date
