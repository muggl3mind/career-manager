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
from path_normalizer import normalize_path
from search_config_loader import load_search_config

_SEARCH_CONFIG = load_search_config(DATA / 'search-config.json')
_CANONICAL_PATHS = [v['label'] for v in _SEARCH_CONFIG['query_packs'].values()] if _SEARCH_CONFIG else []


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
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


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

    if not EVAL_RESULTS.exists():
        print(f"ERROR: {EVAL_RESULTS} not found. Claude must write eval-results.json first.")
        return 1

    with EVAL_RESULTS.open(encoding='utf-8') as f:
        results: List[Dict] = json.load(f)

    # Build lookup by careers_url
    eval_by_url: Dict[str, Dict] = {r['careers_url']: r for r in results if r.get('careers_url')}

    now_ts = datetime.now(timezone.utc).isoformat()

    # Load seen-jobs for update
    seen: Dict = {}
    if SEEN_JOBS.exists():
        with SEEN_JOBS.open(encoding='utf-8') as f:
            seen = json.load(f)

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

        scores = ev.get('scores', {})
        total = ev.get('total_score') or (sum(scores.values()) if scores else 0)
        hard_pass = str(ev.get('hard_pass', False)).lower() == 'true'

        row['llm_score'] = int(total) if total else ''
        row['llm_rationale'] = ev.get('fit_summary', '')
        row['llm_flags'] = ' | '.join(ev.get('red_flags', []))
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

    # Hard-pass rows: move from target to raw
    final_target = []
    for row in target_rows:
        if row.get('careers_url') in hard_pass_urls:
            row['exclusion_reason'] = 'llm_hard_pass'
            row['validation_status'] = 'fail'
            raw_rows.append(row)
            print(f"  [hard_pass] {row.get('company')} — {row.get('open_positions')}")
        else:
            final_target.append(row)

    # Re-sort target by llm_score
    final_target.sort(key=_sort_key, reverse=True)
    for i, r in enumerate(final_target, 1):
        r['rank'] = str(i)

    print(f"\nResults: {updated} evaluated | {len(hard_pass_urls)} hard-pass removed | {len(final_target)} in target list")

    if not args.dry_run:
        _write_csv(TARGET_CSV, final_target, HEADER)
        _write_csv(RAW_CSV, raw_rows, HEADER)
        with SEEN_JOBS.open('w', encoding='utf-8') as f:
            json.dump(seen, f, indent=2, ensure_ascii=False)
        # Clean up working files
        if EVAL_RESULTS.exists():
            EVAL_RESULTS.unlink()
        if PENDING_EVAL.exists():
            PENDING_EVAL.unlink()
        _sync_xlsx()
        print(f"✓ Updated {TARGET_CSV.name} | {RAW_CSV.name} | seen-jobs.json | target-companies.xlsx")
    else:
        print("(dry-run — no files written)")

    return 0


if __name__ == '__main__':
    raise SystemExit(main())
