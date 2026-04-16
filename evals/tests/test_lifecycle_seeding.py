#!/usr/bin/env python3
"""
Tests for Stage 5 — lifecycle seeding on newly added rows.

Verifies that apply_eval_results.py and web_prospecting.py set lifecycle_state,
last_verified_at, and watching_run_count when inserting new rows, so that the
next run's re-verify pass picks them up cleanly.

Run: pytest career-manager/evals/tests/test_lifecycle_seeding.py -v
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
    "path_a": {"label": "Path Alpha", "queries": ["q1"], "locations": ["US"]},
}


def _write_search_config(tmp_path: Path, packs: dict) -> Path:
    cfg = {
        "query_packs": packs,
        "path_check_instructions": {"1": "Search for Path Alpha roles"},
        "role_include_patterns": [], "role_exclude_patterns": [],
        "employer_exclude_patterns": [], "location_exclude_patterns": [],
        "keywords": [], "agency_patterns": [],
        "scoring": {"domain_keywords": {}, "ai_keywords": {}, "role_keywords": {},
                    "comp_indicators": {}, "growth_indicators": {}, "culture_keywords": {}},
        "path_aliases": {}, "search_locations": ["United States"],
    }
    p = tmp_path / "search-config.json"
    p.write_text(json.dumps(cfg))
    return p


def _read_rows(path: Path) -> list:
    with path.open(encoding='utf-8') as f:
        return list(csv.DictReader(f))


class TestProspectingMergeSeedsLifecycle:
    def test_active_role_row_seeded_as_active(self, tmp_path):
        from csv_schema import HEADER
        cfg_path = _write_search_config(tmp_path, SAMPLE_PACKS)
        target = tmp_path / "target-companies.csv"
        with target.open('w', newline='', encoding='utf-8') as f:
            csv.DictWriter(f, fieldnames=HEADER).writeheader()
        (tmp_path / "seen-companies.json").write_text("{}")

        results = {
            "_meta": {"path_key": "path_a"},
            "results": [{
                "company": "ActiveCo", "website": "active.com",
                "careers_url": "https://active.com/careers",
                "role_url": "https://active.com/jobs/1",
                "open_positions": "SA role",
                "prospect_status": "active_role",
                "path": "path_a", "path_name": "Path Alpha",
                "llm_score": 80,
            }],
        }
        (tmp_path / "prospecting-results-path_a.json").write_text(json.dumps(results))

        from web_prospecting import cmd_merge_multifile
        cmd_merge_multifile(data_dir=tmp_path, dry_run=False)

        rows = _read_rows(target)
        match = next(r for r in rows if r['company'] == 'ActiveCo')
        assert match['lifecycle_state'] == 'active'
        assert match['last_verified_at'] != ''
        assert match['watching_run_count'] == '0'

    def test_watch_list_row_seeded_as_watching(self, tmp_path):
        from csv_schema import HEADER
        cfg_path = _write_search_config(tmp_path, SAMPLE_PACKS)
        target = tmp_path / "target-companies.csv"
        with target.open('w', newline='', encoding='utf-8') as f:
            csv.DictWriter(f, fieldnames=HEADER).writeheader()
        (tmp_path / "seen-companies.json").write_text("{}")

        results = {
            "_meta": {"path_key": "path_a"},
            "results": [{
                "company": "WatchCo", "website": "watch.com",
                "careers_url": "https://watch.com/careers",
                "open_positions": "",
                "prospect_status": "watch_list",
                "path": "path_a", "path_name": "Path Alpha",
                "llm_score": 88,
                "watch_reason": "no_matching_roles",
                "watch_evidence": "no open roles found",
            }],
        }
        (tmp_path / "prospecting-results-path_a.json").write_text(json.dumps(results))

        from web_prospecting import cmd_merge_multifile
        cmd_merge_multifile(data_dir=tmp_path, dry_run=False)

        rows = _read_rows(target)
        match = next(r for r in rows if r['company'] == 'WatchCo')
        assert match['lifecycle_state'] == 'watching'
        assert match['last_verified_at'] == ''
        assert match['watching_run_count'] == '0'


class TestEvalMergeSeedsLifecycle:
    def test_new_eval_row_seeded_as_active(self, tmp_path, monkeypatch):
        from csv_schema import HEADER

        target = tmp_path / "target-companies.csv"
        with target.open('w', newline='', encoding='utf-8') as f:
            csv.DictWriter(f, fieldnames=HEADER).writeheader()
        raw_csv = tmp_path / "raw-discovery.csv"
        with raw_csv.open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=HEADER + ['_raw_meta'])
            w.writeheader()

        # pending-eval.json: one job
        pending = [{
            "careers_url": "https://new.co/jobs/1",
            "title": "Solutions Architect",
            "company": "NewCo",
            "location": "New York, NY",
            "description": "AI deployment role at an AI-native finance startup...",
            "path": "path_a",
            "path_name": "Path Alpha",
            "role_family": "Path Alpha",
            "is_agency": False,
            "source": "jobspy",
        }]
        (tmp_path / "pending-eval.json").write_text(json.dumps(pending))

        # eval-results.json: matching eval with total_score 75
        eval_results = [{
            "careers_url": "https://new.co/jobs/1",
            "actual_company": None,
            "path": "path_a",
            "path_name": "Path Alpha",
            "scores": {"background_asset": 7, "ai_central": 8, "can_influence": 7,
                       "non_traditional_welcome": 7, "comp_200k_path": 8,
                       "growth_path": 8, "funding_supports_comp": 8,
                       "problems_exciting": 8, "culture_public_voice": 7,
                       "global_leverage": 7},
            "total_score": 75,
            "fit_summary": "Strong fit.",
            "hard_pass": False,
            "hard_pass_reason": "",
            "red_flags": [],
        }]
        (tmp_path / "eval-results.json").write_text(json.dumps(eval_results))
        (tmp_path / "seen-jobs.json").write_text("{}")

        import apply_eval_results as aer
        monkeypatch.setattr(aer, 'DATA', tmp_path)
        monkeypatch.setattr(aer, 'TARGET_CSV', target)
        monkeypatch.setattr(aer, 'RAW_CSV', raw_csv)
        monkeypatch.setattr(aer, 'PENDING_EVAL', tmp_path / "pending-eval.json")
        monkeypatch.setattr(aer, 'EVAL_RESULTS', tmp_path / "eval-results.json")
        monkeypatch.setattr(aer, 'SEEN_JOBS', tmp_path / "seen-jobs.json")

        aer.cmd_apply(dry_run=False)

        rows = _read_rows(target)
        match = next((r for r in rows if r['company'] == 'NewCo'), None)
        assert match is not None, "new row not added"
        assert match['lifecycle_state'] == 'active'
        assert match['last_verified_at'] != ''
        assert match['watching_run_count'] == '0'

    def test_existing_target_row_hard_pass_marked_archived(self, tmp_path, monkeypatch):
        """If an existing target row is hard-passed by re-eval, move to raw with lifecycle=archived."""
        from csv_schema import HEADER

        target = tmp_path / "target-companies.csv"
        with target.open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=HEADER)
            w.writeheader()
            w.writerow({k: '' for k in HEADER} | {
                'company': 'OldCo',
                'careers_url': 'https://old.co/jobs/1',
                'validation_status': 'pass',
                'llm_score': '72',
                'lifecycle_state': 'active',
                'last_verified_at': '2026-03-01T00:00:00+00:00',
                'watching_run_count': '0',
            })
        raw_csv = tmp_path / "raw-discovery.csv"
        with raw_csv.open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=HEADER + ['_raw_meta'])
            w.writeheader()

        (tmp_path / "pending-eval.json").write_text(json.dumps([]))

        eval_results = [{
            "careers_url": "https://old.co/jobs/1",
            "actual_company": None,
            "path": "path_a", "path_name": "Path Alpha",
            "scores": {k: 1 for k in ['background_asset', 'ai_central',
                       'can_influence', 'non_traditional_welcome', 'comp_200k_path',
                       'growth_path', 'funding_supports_comp', 'problems_exciting',
                       'culture_public_voice', 'global_leverage']},
            "total_score": 10,
            "fit_summary": "Domain mismatch on re-eval.",
            "hard_pass": True,
            "hard_pass_reason": "domain mismatch",
            "red_flags": ["domain_mismatch"],
        }]
        (tmp_path / "eval-results.json").write_text(json.dumps(eval_results))
        (tmp_path / "seen-jobs.json").write_text("{}")

        import apply_eval_results as aer
        monkeypatch.setattr(aer, 'DATA', tmp_path)
        monkeypatch.setattr(aer, 'TARGET_CSV', target)
        monkeypatch.setattr(aer, 'RAW_CSV', raw_csv)
        monkeypatch.setattr(aer, 'PENDING_EVAL', tmp_path / "pending-eval.json")
        monkeypatch.setattr(aer, 'EVAL_RESULTS', tmp_path / "eval-results.json")
        monkeypatch.setattr(aer, 'SEEN_JOBS', tmp_path / "seen-jobs.json")

        aer.cmd_apply(dry_run=False)

        # Hard-passed row should NOT be in target CSV (moved to raw)
        target_rows = _read_rows(target)
        assert not any(r['company'] == 'OldCo' for r in target_rows)

        raw_rows = _read_rows(raw_csv)
        bad = next((r for r in raw_rows if r['company'] == 'OldCo'), None)
        assert bad is not None
        assert bad['lifecycle_state'] == 'archived'
