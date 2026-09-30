#!/usr/bin/env python3
"""
Merge Claude's LLM evaluations into target-companies.csv.

Reads data/eval-results.json (written by Claude after evaluating pending-eval.json),
merges results into target-companies.csv and raw-discovery.csv, and updates seen-jobs.json.

Usage:
  python3 scripts/ops/apply_eval_results.py
  python3 scripts/ops/apply_eval_results.py --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

import sys

BASE = Path(__file__).resolve().parents[2]
DATA = BASE / 'data'
TARGET_CSV = DATA / 'target-companies.csv'
RAW_CSV = DATA / 'raw-discovery.csv'
SEEN_JOBS = DATA / 'seen-jobs.json'
EVAL_RESULTS = DATA / 'eval-results.json'
PENDING_EVAL = DATA / 'pending-eval.json'

sys.path.insert(0, str(BASE / 'scripts' / 'core'))
from csv_schema import HEADER
from csv_io import write_csv_atomic
from path_normalizer import normalize_path, normalize_company
from company_dedup import find_existing, merge_into_existing
from search_config_loader import load_search_config
from scoring import NEEDS_RESEARCH_FLAG
from flags import join_flags
from merge_validation import quarantine_row, validate_eval_result

_SEARCH_CONFIG = load_search_config(DATA / 'search-config.json')
_CANONICAL_PATHS = [v['label'] for v in _SEARCH_CONFIG['query_packs'].values()] if _SEARCH_CONFIG else []


def _normalize_all_paths(rows: list[dict]) -> int:
    """Normalize role_family for all rows.

    Returns count of rows that were updated.
    """
    fixed = 0
    for row in rows:
        # Normalize company name
        old_company = row.get('company', '').strip()
        new_company = normalize_company(old_company)
        if new_company != old_company:
            row['company'] = new_company

        # Normalize path
        old = row.get('role_family', '').strip()
        new = normalize_path(old) if old else ''
        if new != old:
            row['role_family'] = new
            fixed += 1
    return fixed


def _read_csv(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    with path.open(encoding='utf-8') as f:
        return list(csv.DictReader(f))


def _sync_xlsx() -> None:
    try:
        import sys
        sys.path.insert(0, str(BASE / 'scripts' / 'core'))
        from target_companies_sync import csv_to_xlsx
        csv_to_xlsx()
    except Exception as e:
        print(f"  [xlsx] WARN: could not write xlsx: {e}")


def _write_csv(path: Path, rows: List[Dict], header: List[str]) -> None:
    write_csv_atomic(path, rows, header)


def _sort_key(r: Dict) -> tuple:
    llm = r.get('llm_score')
    try:
        llm_val = float(llm) if llm not in (None, '') else 0.0
    except (TypeError, ValueError):
        llm_val = 0.0
    return (llm_val,)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()
    return cmd_apply(dry_run=args.dry_run)


def _score_cell(total) -> str:
    """CSV cell for a validated total: '' means "not scored", '0' is a
    real zero score (finding H2: never conflate the two)."""
    return '' if total is None else str(int(total))


def _dims_cell(dims) -> str:
    """CSV cell for llm_dimensions_evaluated (finding M9)."""
    return '' if dims in (None, '') else str(int(dims))


def _validate_results(results: List[Dict]) -> List[Dict]:
    """Validate agent self-reports before any merge (finding C2).

    The recomputed ratio score always wins when dimension data is present.
    Rows that cannot be verified (non-zero total with no dimension data,
    unknown rubric keys, non yes/no/unknown dimension values) are appended
    to data/quarantine/apply_eval_results-<reason>.jsonl and never merged.
    Rows with too few evaluated dimensions are kept unscored with the
    needs_research flag, per the SKILL.md eval-results contract.

    After validation each row's total_score is canonical: an int (0 is a
    real score) or None (not scored / needs_research). The evaluated
    dimension count is stored on the row as llm_dimensions_evaluated
    (finding M9: confidence is persisted, not thrown away).
    """
    valid: List[Dict] = []
    quarantined = 0
    for ev in results:
        label = ev.get('actual_company') or ev.get('careers_url') or '?'
        verdict = validate_eval_result(ev.get('total_score'), ev.get('scores'))
        if not verdict.ok:
            qpath = quarantine_row(
                DATA, 'apply_eval_results', verdict.reason, ev, verdict.detail,
            )
            print(f"  [quarantine] {label}: {verdict.reason} ({verdict.detail}) -> {qpath}")
            quarantined += 1
            continue
        if verdict.detail:
            print(f"  [merge_validation] {label}: {verdict.detail}")
        if verdict.needs_research:
            ev['total_score'] = None
            red_flags = list(ev.get('red_flags') or [])
            if NEEDS_RESEARCH_FLAG not in red_flags:
                red_flags.append(NEEDS_RESEARCH_FLAG)
            ev['red_flags'] = red_flags
        else:
            ev['total_score'] = verdict.score
        ev['llm_dimensions_evaluated'] = verdict.dimensions_evaluated
        valid.append(ev)
    if quarantined:
        print(f"  [quarantine] {quarantined} result(s) rejected; see {DATA / 'quarantine'}")
    return valid


def _load_eval_results() -> List[Dict]:
    """Load eval results, preferring per-shard files when present.

    Multi-shard runs write eval-results-shard-N.json (one per parallel eval
    agent) instead of racing on a single eval-results.json. This helper
    merges shard files in order, falling back to the single-file format
    when no shards exist. Duplicate careers_urls across shards keep the
    later-shard verdict (matching within-shard resume semantics).

    Shard files are searched in EVAL_RESULTS.parent so tests that
    monkeypatch EVAL_RESULTS also relocate shard discovery.
    """
    shard_paths = sorted(EVAL_RESULTS.parent.glob('eval-results-shard-*.json'))
    merged: List[Dict] = []
    seen_urls: set = set()
    if shard_paths:
        for path in shard_paths:
            with path.open(encoding='utf-8') as f:
                for row in json.load(f):
                    url = row.get('careers_url', '')
                    if url and url in seen_urls:
                        # Later shards overwrite earlier ones on collision.
                        merged = [r for r in merged if r.get('careers_url') != url]
                    merged.append(row)
                    if url:
                        seen_urls.add(url)
        print(f"  [eval_merge] loaded {len(merged)} results from {len(shard_paths)} shard file(s)")
        return merged
    if EVAL_RESULTS.exists():
        with EVAL_RESULTS.open(encoding='utf-8') as f:
            return json.load(f)
    return []


def cmd_apply(dry_run: bool = False) -> int:
    results = _load_eval_results()
    if not results:
        print(
            f"ERROR: no eval results found. Expected eval-results-shard-*.json "
            f"(one per parallel eval agent) or {EVAL_RESULTS.name}."
        )
        return 1

    # Merge-time validation: quarantine unverifiable or invalid self-reports.
    results = _validate_results(results)

    # Build lookup by careers_url
    eval_by_url: Dict[str, Dict] = {r['careers_url']: r for r in results if r.get('careers_url')}

    now_ts = datetime.now(timezone.utc).isoformat()

    # Load seen-jobs for update
    seen: Dict = {}
    if SEEN_JOBS.exists():
        with SEEN_JOBS.open(encoding='utf-8') as f:
            seen = json.load(f)

    # Load pending-eval.json for job metadata (needed to add new rows)
    pending_meta: Dict[str, Dict] = {}
    if PENDING_EVAL.exists():
        with PENDING_EVAL.open(encoding='utf-8') as f:
            for job in json.load(f):
                url = job.get('careers_url', '')
                if url:
                    pending_meta[url] = job

    # Merge into target-companies.csv
    target_rows = _read_csv(TARGET_CSV)
    raw_rows = _read_csv(RAW_CSV)
    hard_pass_urls = set()

    updated = 0
    for row in target_rows:
        url = row.get('careers_url', '')
        ev = eval_by_url.get(url)
        if not ev:
            continue

        total = ev.get('total_score')
        hard_pass = str(ev.get('hard_pass', False)).lower() == 'true'

        # Resolve agency company name
        actual = ev.get('actual_company')
        if actual:
            row['company'] = actual

        # '' = not scored (needs_research); '0' = honest zero (finding H2).
        row['llm_score'] = _score_cell(total)
        row['llm_dimensions_evaluated'] = _dims_cell(ev.get('llm_dimensions_evaluated'))
        row['llm_rationale'] = ev.get('fit_summary', '')
        row['llm_flags'] = join_flags(ev.get('red_flags', []))
        row['llm_hard_pass'] = 'true' if hard_pass else 'false'
        row['llm_hard_pass_reason'] = ev.get('hard_pass_reason') or ''
        row['llm_evaluated_at'] = now_ts
        if ev.get('path_name'):
            row['role_family'] = ev['path_name']
        row['role_family'] = normalize_path(row.get('role_family', ''), _CANONICAL_PATHS)

        if hard_pass:
            hard_pass_urls.add(url)

        # Update seen-jobs cache
        seen[url] = {
            'first_seen': now_ts,
            'llm_score': row['llm_score'],
            'llm_dimensions_evaluated': row.get('llm_dimensions_evaluated', ''),
            'role_family': row.get('role_family', ''),
            'llm_rationale': row.get('llm_rationale', ''),
            'llm_flags': row.get('llm_flags', ''),
            'llm_hard_pass': row.get('llm_hard_pass', ''),
            'llm_hard_pass_reason': row.get('llm_hard_pass_reason', ''),
            'llm_evaluated_at': now_ts,
            'title': row.get('open_positions', ''),
            'company': row.get('company', ''),
        }
        updated += 1

    # Add new rows that were not in target CSV (discovered after scoring gate)
    added = 0
    for url, ev in eval_by_url.items():
        hard_pass = str(ev.get('hard_pass', False)).lower() == 'true'
        meta = pending_meta.get(url, {})
        actual = ev.get('actual_company')
        company_name = normalize_company(actual or meta.get('company', ''))
        if hard_pass:
            hard_pass_urls.add(url)
            # Cache the hard-pass verdict (finding H4): without this,
            # new hard-passes were re-evaluated on every run.
            seen[url] = {
                'first_seen': seen.get(url, {}).get('first_seen', now_ts),
                'llm_score': _score_cell(ev.get('total_score')),
                'llm_dimensions_evaluated': _dims_cell(ev.get('llm_dimensions_evaluated')),
                'role_family': ev.get('path_name', '') or meta.get('role_family', ''),
                'llm_rationale': ev.get('fit_summary', ''),
                'llm_flags': join_flags(ev.get('red_flags', [])),
                'llm_hard_pass': 'true',
                'llm_hard_pass_reason': ev.get('hard_pass_reason') or '',
                'llm_evaluated_at': now_ts,
                'title': meta.get('title', ''),
                'company': company_name,
            }
            continue
        total = ev.get('total_score')
        if total is None and not company_name:
            # Unscored result with no usable identity: nothing to add.
            continue

        # Check if this company already exists (by name, not just URL)
        match = find_existing(company_name, target_rows)
        if match:
            # Merge into existing row (the newer evaluation wins; an
            # unscored needs_research result never clobbers a score).
            merge_into_existing(match, {
                'open_positions': meta.get('title', ''),
                'llm_score': _score_cell(total),
                'llm_dimensions_evaluated': _dims_cell(ev.get('llm_dimensions_evaluated')),
                'llm_rationale': ev.get('fit_summary', ''),
                'llm_flags': join_flags(ev.get('red_flags', [])),
                'llm_evaluated_at': now_ts,
                'role_family': ev.get('path_name', '') or meta.get('role_family', ''),
                'last_checked': now_ts[:10],
            })
            continue

        new_row = {
            'rank': '',
            'company': company_name,
            'website': '',
            'careers_url': url,
            'role_url': '',
            'industry': '',
            'size': '',
            'stage': '',
            'recent_funding': '',
            'tech_signals': '',
            'open_positions': meta.get('title', ''),
            'last_checked': now_ts[:10],
            'notes': f"source={meta.get('source', 'jobspy')}",
            'role_family': ev.get('path_name', '') or meta.get('role_family', ''),
            'source': meta.get('source', 'jobspy'),
            'location_detected': meta.get('location', ''),
            'validation_status': 'pass',
            'exclusion_reason': '',
            'llm_score': _score_cell(total),
            'llm_dimensions_evaluated': _dims_cell(ev.get('llm_dimensions_evaluated')),
            'llm_rationale': ev.get('fit_summary', ''),
            'llm_flags': join_flags(ev.get('red_flags', [])),
            'llm_hard_pass': 'false',
            'llm_hard_pass_reason': '',
            'llm_evaluated_at': now_ts,
            'lifecycle_state': 'active',
            'last_verified_at': now_ts,
            'watching_run_count': '0',
        }
        target_rows.append(new_row)
        # Also update seen-jobs cache for new rows
        seen[url] = {
            'first_seen': now_ts,
            'llm_score': new_row['llm_score'],
            'llm_dimensions_evaluated': new_row.get('llm_dimensions_evaluated', ''),
            'role_family': new_row.get('role_family', ''),
            'llm_rationale': new_row.get('llm_rationale', ''),
            'llm_flags': new_row.get('llm_flags', ''),
            'llm_hard_pass': new_row.get('llm_hard_pass', ''),
            'llm_hard_pass_reason': new_row.get('llm_hard_pass_reason', ''),
            'llm_evaluated_at': now_ts,
            'title': new_row.get('open_positions', ''),
            'company': new_row.get('company', ''),
        }
        added += 1

    if added:
        print(f"  [new_rows] added {added} newly evaluated jobs to target CSV")

    # Hard-pass rows: move from target to raw
    final_target = []
    for row in target_rows:
        if row.get('careers_url') in hard_pass_urls:
            row['exclusion_reason'] = 'llm_hard_pass'
            row['validation_status'] = 'fail'
            row['lifecycle_state'] = 'archived'
            raw_rows.append(row)
            print(f"  [hard_pass] {row.get('company')} — {row.get('open_positions')}")
        else:
            final_target.append(row)

    # Normalize all paths (fixes empty + variant labels)
    path_fixes = _normalize_all_paths(final_target)
    if path_fixes:
        print(f"  [path_normalize] fixed {path_fixes} role_family values")

    # Re-sort target by llm_score
    final_target.sort(key=_sort_key, reverse=True)
    for i, r in enumerate(final_target, 1):
        r['rank'] = str(i)

    print(f"\nResults: {updated} evaluated | {added} added | {len(hard_pass_urls)} hard-pass removed | {len(final_target)} in target list")

    if not dry_run:
        _write_csv(TARGET_CSV, final_target, HEADER)
        _write_csv(RAW_CSV, raw_rows, HEADER)
        with SEEN_JOBS.open('w', encoding='utf-8') as f:
            json.dump(seen, f, indent=2, ensure_ascii=False)
        # Clean up working files (relative to EVAL_RESULTS.parent so
        # monkeypatched tests locate their own tmp shards).
        if EVAL_RESULTS.exists():
            EVAL_RESULTS.unlink()
        for shard_path in EVAL_RESULTS.parent.glob('eval-results-shard-*.json'):
            shard_path.unlink()
        if PENDING_EVAL.exists():
            PENDING_EVAL.unlink()
        for shard_path in PENDING_EVAL.parent.glob('pending-eval-shard-*.json'):
            shard_path.unlink()
        _sync_xlsx()
        print(f"✓ Updated {TARGET_CSV.name} | {RAW_CSV.name} | seen-jobs.json | target-companies.xlsx")
    else:
        print("(dry-run — no files written)")

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
