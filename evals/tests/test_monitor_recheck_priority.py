"""Tests for monitor recheck prioritization of needs_recheck companies."""
import json
import csv
import sys
from pathlib import Path
from datetime import datetime, timezone

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'ops'))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'core'))


def _write_csv(path: Path, rows: list[dict], header: list[str]) -> None:
    with path.open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


class TestMonitorRecheckPriority:
    def test_needs_recheck_included_despite_recent_check(self, tmp_path, monkeypatch):
        """Company with needs_recheck in llm_flags should be in stale list even if recently checked."""
        from csv_schema import HEADER
        import monitor_watchlist as mw

        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

        # Write target CSV with a recently checked company that has needs_recheck
        _write_csv(tmp_path / "target-companies.csv", [{
            "company": "UnverifiedCo",
            "website": "unverified.com",
            "careers_url": "https://unverified.com/careers",
            "last_checked": today,
            "validation_status": "watch_list",
            "llm_flags": "needs_recheck",
            "role_family": "Path Alpha",
            "open_positions": "",
        }], HEADER)

        # Write seen-companies with recent timestamp
        (tmp_path / "seen-companies.json").write_text(json.dumps({
            "unverifiedco": {
                "company": "UnverifiedCo",
                "website": "unverified.com",
                "last_checked": datetime.now(timezone.utc).isoformat(),
                "first_seen": datetime.now(timezone.utc).isoformat(),
            }
        }))

        # Monkeypatch paths
        monkeypatch.setattr(mw, "TARGET_CSV", tmp_path / "target-companies.csv")
        monkeypatch.setattr(mw, "SEEN_COMPANIES", tmp_path / "seen-companies.json")
        monkeypatch.setattr(mw, "APPLICATIONS_CSV", tmp_path / "applications.csv")
        monkeypatch.setattr(mw, "MONITOR_CONTEXT", tmp_path / "monitor-context.json")

        mw.cmd_export()

        with (tmp_path / "monitor-context.json").open() as f:
            ctx = json.load(f)

        company_names = [c["company"] for c in ctx["checklist"]]
        assert "UnverifiedCo" in company_names

    def test_normal_recent_company_excluded(self, tmp_path, monkeypatch):
        """Company without needs_recheck and recently checked should NOT be in stale list."""
        from csv_schema import HEADER
        import monitor_watchlist as mw

        today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

        _write_csv(tmp_path / "target-companies.csv", [{
            "company": "FreshCo",
            "website": "fresh.com",
            "careers_url": "https://fresh.com/careers",
            "last_checked": today,
            "validation_status": "pass",
            "llm_flags": "",
            "role_family": "Path Alpha",
            "open_positions": "PM",
        }], HEADER)

        (tmp_path / "seen-companies.json").write_text(json.dumps({
            "freshco": {
                "company": "FreshCo",
                "website": "fresh.com",
                "last_checked": datetime.now(timezone.utc).isoformat(),
                "first_seen": datetime.now(timezone.utc).isoformat(),
            }
        }))

        monkeypatch.setattr(mw, "TARGET_CSV", tmp_path / "target-companies.csv")
        monkeypatch.setattr(mw, "SEEN_COMPANIES", tmp_path / "seen-companies.json")
        monkeypatch.setattr(mw, "APPLICATIONS_CSV", tmp_path / "applications.csv")
        monkeypatch.setattr(mw, "MONITOR_CONTEXT", tmp_path / "monitor-context.json")

        mw.cmd_export()

        with (tmp_path / "monitor-context.json").open() as f:
            ctx = json.load(f)

        company_names = [c["company"] for c in ctx["checklist"]]
        assert "FreshCo" not in company_names
