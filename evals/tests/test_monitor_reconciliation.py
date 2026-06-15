"""Monitor merge: flag-separator regression (M6) + coverage reconciliation (H3).

M6: a comma-separated 'fetch_empty' (the format the results schema asks
agents for) must trip the unreachable-page safety valve exactly like the
legacy pipe-separated form.

H3: every company exported in monitor-context.json must come back in
monitor-results.json. Companies the agent silently skipped keep their old
last_checked / last_verified_at and are flagged 'monitor_unreached', so a
lazy agent cannot make the portfolio look freshly verified.
"""
import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'ops'))
sys.path.insert(0, str(Path(__file__).resolve().parents[2] / 'job-search' / 'scripts' / 'core'))


OLD_DATE = (datetime.now(timezone.utc) - timedelta(days=10)).strftime('%Y-%m-%d')
OLD_TS = (datetime.now(timezone.utc) - timedelta(days=10)).isoformat()
TODAY = datetime.now(timezone.utc).strftime('%Y-%m-%d')


def _row(company, **overrides):
    row = {
        "company": company,
        "website": f"{company.lower()}.com",
        "careers_url": f"https://{company.lower()}.com/careers",
        "last_checked": OLD_DATE,
        "validation_status": "pass",
        "llm_flags": "",
        "role_family": "Path Alpha",
        "open_positions": "Some Role",
        "lifecycle_state": "active",
        "last_verified_at": OLD_TS,
        "watching_run_count": "0",
    }
    row.update(overrides)
    return row


def _setup(tmp_path, monkeypatch, target_rows, monitor_results, checklist=None):
    from csv_schema import HEADER
    import monitor_watchlist as mw

    with (tmp_path / "target-companies.csv").open("w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=HEADER, extrasaction="ignore")
        w.writeheader()
        w.writerows(target_rows)
    (tmp_path / "monitor-results.json").write_text(json.dumps(monitor_results))
    (tmp_path / "seen-companies.json").write_text(json.dumps({}))
    if checklist is not None:
        context = {"mode": "monitor_reverify", "checklist": checklist}
        (tmp_path / "monitor-context.json").write_text(json.dumps(context))

    monkeypatch.setattr(mw, "TARGET_CSV", tmp_path / "target-companies.csv")
    monkeypatch.setattr(mw, "SEEN_COMPANIES", tmp_path / "seen-companies.json")
    monkeypatch.setattr(mw, "MONITOR_RESULTS", tmp_path / "monitor-results.json")
    monkeypatch.setattr(mw, "MONITOR_CONTEXT", tmp_path / "monitor-context.json")
    return mw


def _read_rows(tmp_path):
    with (tmp_path / "target-companies.csv").open() as f:
        return {r["company"]: r for r in csv.DictReader(f)}


class TestFlagSeparatorRegression:
    """M6: comma-separated fetch_empty must behave like pipe-separated."""

    def test_comma_separated_fetch_empty_preserves_timestamps(self, tmp_path, monkeypatch):
        mw = _setup(
            tmp_path, monkeypatch,
            [_row("DeadCo")],
            [{"company": "DeadCo", "status": "no_change",
              "llm_flags": "comp_unknown,fetch_empty"}],
        )
        mw.cmd_merge()
        row = _read_rows(tmp_path)["DeadCo"]
        assert row["last_checked"] == OLD_DATE, "comma-separated fetch_empty must not bump last_checked"
        assert row["last_verified_at"] == OLD_TS, "comma-separated fetch_empty must not bump last_verified_at"
        assert row["lifecycle_state"] == "watching", "unreachable page must flip to watching, not stay active"

    def test_lifecycle_transition_accepts_comma_flags(self):
        import monitor_watchlist as mw
        row = _row("DeadCo")
        state = mw._apply_lifecycle_transition(
            row, {"status": "no_change", "llm_flags": "comp_unknown,fetch_empty"},
            archive_grace_runs=2, now_ts=datetime.now(timezone.utc).isoformat(),
        )
        assert state == "watching"
        assert row["last_verified_at"] == OLD_TS

    def test_lifecycle_transition_still_accepts_pipe_flags(self):
        import monitor_watchlist as mw
        row = _row("DeadCo")
        state = mw._apply_lifecycle_transition(
            row, {"status": "no_change", "llm_flags": "fetch_empty|other"},
            archive_grace_runs=2, now_ts=datetime.now(timezone.utc).isoformat(),
        )
        assert state == "watching"


class TestCoverageReconciliation:
    """H3: exported companies missing from results are flagged, not freshened."""

    def _checklist(self, *names):
        return [{"company": n} for n in names]

    def test_unreached_company_flagged_and_timestamps_preserved(self, tmp_path, monkeypatch):
        mw = _setup(
            tmp_path, monkeypatch,
            [_row("AlphaCo"), _row("BetaCo"), _row("GammaCo")],
            [
                {"company": "AlphaCo", "status": "no_change", "llm_flags": ""},
                {"company": "BetaCo", "status": "no_change", "llm_flags": ""},
                # GammaCo was exported but the agent never reported on it
            ],
            checklist=self._checklist("AlphaCo", "BetaCo", "GammaCo"),
        )
        mw.cmd_merge()
        rows = _read_rows(tmp_path)

        gamma = rows["GammaCo"]
        assert "monitor_unreached" in gamma["llm_flags"].split(",")
        assert gamma["last_checked"] == OLD_DATE, "unreached company must keep old last_checked"
        assert gamma["last_verified_at"] == OLD_TS, "unreached company must keep old last_verified_at"

        # Reached companies are verified normally and not flagged
        for name in ("AlphaCo", "BetaCo"):
            assert rows[name]["last_checked"] == TODAY
            assert "monitor_unreached" not in rows[name]["llm_flags"]

    def test_blanket_no_change_does_not_freshen_skipped_rows(self, tmp_path, monkeypatch):
        """A lazy agent reporting only some companies cannot freshen the rest."""
        mw = _setup(
            tmp_path, monkeypatch,
            [_row("AlphaCo"), _row("SkippedCo")],
            [{"company": "AlphaCo", "status": "no_change", "llm_flags": ""}],
            checklist=self._checklist("AlphaCo", "SkippedCo"),
        )
        mw.cmd_merge()
        rows = _read_rows(tmp_path)
        assert rows["SkippedCo"]["last_verified_at"] == OLD_TS
        assert "monitor_unreached" in rows["SkippedCo"]["llm_flags"].split(",")

    def test_stale_unreached_flag_cleared_when_company_reached(self, tmp_path, monkeypatch):
        mw = _setup(
            tmp_path, monkeypatch,
            [_row("BackCo", llm_flags="monitor_unreached")],
            [{"company": "BackCo", "status": "no_change", "llm_flags": ""}],
            checklist=self._checklist("BackCo"),
        )
        mw.cmd_merge()
        row = _read_rows(tmp_path)["BackCo"]
        assert "monitor_unreached" not in row["llm_flags"]
        assert row["last_checked"] == TODAY

    def test_quarantined_result_counts_as_accounted(self, tmp_path, monkeypatch):
        """A company whose result failed validation was still reached: no unreached flag."""
        mw = _setup(
            tmp_path, monkeypatch,
            [_row("BadDataCo")],
            [{"company": "BadDataCo", "status": "active_role",
              "llm_score": 97, "llm_dimensions_evaluated": 10, "llm_flags": ""}],
            checklist=self._checklist("BadDataCo"),
        )
        mw.cmd_merge()
        row = _read_rows(tmp_path)["BadDataCo"]
        assert "monitor_unreached" not in row["llm_flags"]
        # And the invalid score never merged
        assert row["llm_score"] == ""
        # The quarantine record exists
        qdir = tmp_path / "quarantine"
        assert qdir.exists() and any(qdir.iterdir())

    def test_no_context_file_merges_without_reconciliation(self, tmp_path, monkeypatch):
        mw = _setup(
            tmp_path, monkeypatch,
            [_row("AlphaCo")],
            [{"company": "AlphaCo", "status": "no_change", "llm_flags": ""}],
            checklist=None,
        )
        assert mw.cmd_merge() == 0
        row = _read_rows(tmp_path)["AlphaCo"]
        assert "monitor_unreached" not in row["llm_flags"]
