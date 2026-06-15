#!/usr/bin/env python3
"""Merge company-research findings into target-companies.csv (finding M8).

The company-research agent used to freehand-edit the CSV, writing columns
that do not exist in the schema (fit_score, fit_rationale). Those edits
silently vanished or corrupted rows. This script is now the only sanctioned
path from a research dossier into the CSV.

Usage:
  uv run job-search/scripts/ops/merge_research.py                # data/research-results.json
  uv run job-search/scripts/ops/merge_research.py path/to.json
  uv run job-search/scripts/ops/merge_research.py --dry-run

Input: a JSON object (or array of objects), one per researched company.

Column policy (consistent with merge_validation.py + csv_schema.py):
- "company" is required.
- Enrichment columns are merged directly: website, careers_url, role_url,
  industry, size, stage, recent_funding, tech_signals, open_positions,
  notes, role_family.
- Known legacy aliases are MAPPED to schema columns:
  fit_score -> llm_score, fit_rationale -> llm_rationale,
  path_name -> role_family.
- Scoring fields (llm_score, llm_dimensions_evaluated, scores, llm_flags,
  llm_rationale) go through merge_validation.validate_self_report. The
  March 2026 ratio spec applies; invalid self-reports are quarantined.
- Pipeline-managed columns (rank, validation_status, lifecycle_state,
  last_verified_at, watching_run_count, last_checked, source,
  location_detected, exclusion_reason, llm_hard_pass, llm_hard_pass_reason,
  llm_evaluated_at) are REJECTED: research must not fake verification
  state or lifecycle.
- Any other key is REJECTED as an unknown column.

Rejected rows are appended to <data>/quarantine/merge_research-<reason>.jsonl.
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

BASE = Path(__file__).resolve().parents[2]
DATA = BASE / 'data'
TARGET_CSV = DATA / 'target-companies.csv'
RESEARCH_RESULTS = DATA / 'research-results.json'

import sys as _sys
_sys.path.insert(0, str(BASE / 'scripts' / 'core'))
from csv_schema import HEADER
from csv_io import write_csv_atomic
from company_dedup import find_existing
from path_normalizer import normalize_path, normalize_company
from search_config_loader import load_search_config
from flags import FLAG_SEPARATOR, normalize_flags
from merge_validation import (
    add_needs_research_flag,
    quarantine_row,
    validate_self_report,
)

_SEARCH_CONFIG = load_search_config(DATA / 'search-config.json')
_CANONICAL_PATHS = [v['label'] for v in _SEARCH_CONFIG['query_packs'].values()] if _SEARCH_CONFIG else []

# Quarantine reason slugs (same convention as merge_validation).
REASON_UNKNOWN_COLUMN = 'unknown-column'
REASON_PROTECTED_COLUMN = 'protected-column'
REASON_MISSING_COMPANY = 'missing-company'

# Enrichment columns research is allowed to write directly.
RESEARCH_UPDATABLE = frozenset({
    'website', 'careers_url', 'role_url', 'industry', 'size', 'stage',
    'recent_funding', 'tech_signals', 'open_positions', 'notes',
    'role_family',
})

# Scoring fields handled via validate_self_report, never merged raw.
SCORING_FIELDS = frozenset({
    'llm_score', 'llm_dimensions_evaluated', 'llm_rationale',
    'llm_flags', 'scores',
})

# Legacy/freehand keys mapped onto real schema columns.
COLUMN_ALIASES = {
    'fit_score': 'llm_score',
    'fit_rationale': 'llm_rationale',
    'path_name': 'role_family',
}

# Schema columns the pipeline owns; research may never set these.
PROTECTED_COLUMNS = frozenset(HEADER) - RESEARCH_UPDATABLE - SCORING_FIELDS - {'company'}


def _read_csv(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    with path.open(encoding='utf-8') as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: List[Dict], header: List[str]) -> None:
    write_csv_atomic(path, rows, header)


def _sync_xlsx() -> None:
    try:
        from target_companies_sync import csv_to_xlsx
        csv_to_xlsx()
    except Exception as e:
        print(f"  [xlsx] WARN: could not write xlsx: {e}")


def classify_columns(result: Dict) -> tuple[Dict, List[str], List[str]]:
    """Map aliases and sort a result's keys into (clean, protected, unknown).

    Returns the cleaned result dict (aliases renamed to schema columns)
    plus the lists of protected and unknown keys found.
    """
    clean: Dict = {}
    protected: List[str] = []
    unknown: List[str] = []
    for key, value in result.items():
        mapped = COLUMN_ALIASES.get(key, key)
        if mapped == 'company' or mapped in RESEARCH_UPDATABLE or mapped in SCORING_FIELDS:
            clean[mapped] = value
        elif mapped in PROTECTED_COLUMNS:
            protected.append(key)
        else:
            unknown.append(key)
    return clean, protected, unknown


def merge_results(
    results: List[Dict],
    existing_rows: List[Dict],
    data_dir: Path,
) -> Dict[str, int]:
    """Merge cleaned research results into existing_rows in place."""
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    now_ts = datetime.now(timezone.utc).isoformat()
    stats = {'updated': 0, 'added': 0, 'quarantined': 0}

    for raw in results:
        if not isinstance(raw, dict):
            quarantine_row(data_dir, 'merge_research', REASON_UNKNOWN_COLUMN,
                           {'result': raw}, 'result is not a JSON object')
            stats['quarantined'] += 1
            continue

        clean, protected, unknown = classify_columns(raw)

        if not (clean.get('company') or '').strip():
            quarantine_row(data_dir, 'merge_research', REASON_MISSING_COMPANY,
                           raw, 'result has no company name')
            stats['quarantined'] += 1
            continue
        if protected:
            quarantine_row(
                data_dir, 'merge_research', REASON_PROTECTED_COLUMN, raw,
                f"pipeline-managed columns not writable by research: {', '.join(sorted(protected))}",
            )
            print(f"  [quarantine] {clean['company']}: protected columns {sorted(protected)}")
            stats['quarantined'] += 1
            continue
        if unknown:
            quarantine_row(
                data_dir, 'merge_research', REASON_UNKNOWN_COLUMN, raw,
                f"unknown columns: {', '.join(sorted(unknown))}; "
                f"allowed: company, {', '.join(sorted(RESEARCH_UPDATABLE | SCORING_FIELDS))}",
            )
            print(f"  [quarantine] {clean['company']}: unknown columns {sorted(unknown)}")
            stats['quarantined'] += 1
            continue

        # Scoring fields go through the same merge validation as every
        # other entry point (March 2026 ratio spec).
        verdict = validate_self_report(
            clean.get('llm_score'),
            clean.get('llm_dimensions_evaluated'),
            clean.get('scores'),
        )
        if not verdict.ok:
            qpath = quarantine_row(
                data_dir, 'merge_research', verdict.reason, raw, verdict.detail,
            )
            print(f"  [quarantine] {clean['company']}: {verdict.reason} ({verdict.detail}) -> {qpath}")
            stats['quarantined'] += 1
            continue
        if verdict.detail:
            print(f"  [merge_validation] {clean['company']}: {verdict.detail}")
        if verdict.needs_research:
            clean['llm_score'] = ''
            clean['llm_flags'] = add_needs_research_flag(
                clean.get('llm_flags', ''), separator=FLAG_SEPARATOR,
            )
        elif verdict.score is not None:
            clean['llm_score'] = str(verdict.score)
        else:
            clean.pop('llm_score', None)

        company = normalize_company(clean['company'].strip())
        role_family = (clean.get('role_family') or '').strip()
        if role_family:
            clean['role_family'] = normalize_path(role_family, _CANONICAL_PATHS)

        row = find_existing(company, existing_rows)
        if row is not None:
            for field in sorted(RESEARCH_UPDATABLE - {'notes'}):
                value = str(clean.get(field) or '').strip()
                if value:
                    row[field] = value
            if (clean.get('notes') or '').strip():
                existing_notes = (row.get('notes') or '').strip()
                addition = f"research {today}: {clean['notes'].strip()}"
                row['notes'] = f"{existing_notes} | {addition}" if existing_notes else addition
            if clean.get('llm_rationale'):
                row['llm_rationale'] = clean['llm_rationale']
            if clean.get('llm_flags'):
                row['llm_flags'] = normalize_flags(clean['llm_flags'])
            if clean.get('llm_score') not in (None, ''):
                row['llm_score'] = str(clean['llm_score'])
                row['llm_evaluated_at'] = now_ts
                if 'llm_dimensions_evaluated' in HEADER and clean.get('llm_dimensions_evaluated') not in (None, ''):
                    row['llm_dimensions_evaluated'] = str(clean['llm_dimensions_evaluated'])
            # Deliberately untouched: last_checked, last_verified_at,
            # lifecycle_state, validation_status, rank. Research is not a
            # careers-page verification (finding H3 spirit).
            stats['updated'] += 1
        else:
            open_positions = str(clean.get('open_positions') or '').strip()
            new_row = {field: '' for field in HEADER}
            new_row.update({
                'company': company,
                'website': clean.get('website', ''),
                'careers_url': clean.get('careers_url', ''),
                'role_url': clean.get('role_url', ''),
                'industry': clean.get('industry', ''),
                'size': clean.get('size', ''),
                'stage': clean.get('stage', ''),
                'recent_funding': clean.get('recent_funding', ''),
                'tech_signals': clean.get('tech_signals', ''),
                'open_positions': open_positions or 'None — watch list',
                'last_checked': today,
                'notes': (f"research {today}: {clean['notes'].strip()} | source=company_research"
                          if (clean.get('notes') or '').strip() else 'source=company_research'),
                'role_family': clean.get('role_family', ''),
                'source': 'company_research',
                'validation_status': 'pass' if open_positions else 'watch_list',
                'llm_score': str(clean.get('llm_score', '')) if clean.get('llm_score') not in (None, '') else '',
                'llm_rationale': clean.get('llm_rationale', ''),
                'llm_flags': normalize_flags(clean.get('llm_flags', '')),
                'llm_hard_pass': 'false',
                'llm_evaluated_at': now_ts if clean.get('llm_score') not in (None, '') else '',
                'lifecycle_state': 'active' if open_positions else 'watching',
                'last_verified_at': '',
                'watching_run_count': '0',
            })
            if 'llm_dimensions_evaluated' in HEADER and clean.get('llm_dimensions_evaluated') not in (None, ''):
                new_row['llm_dimensions_evaluated'] = str(clean['llm_dimensions_evaluated'])
            existing_rows.append(new_row)
            stats['added'] += 1

    return stats


def main() -> int:
    ap = argparse.ArgumentParser(description='Merge company-research findings into target-companies.csv')
    ap.add_argument('results', nargs='?', default=str(RESEARCH_RESULTS),
                    help=f'Path to research results JSON (default: {RESEARCH_RESULTS})')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    results_path = Path(args.results)
    if not results_path.exists():
        print(f'ERROR: {results_path} not found. Write the research findings JSON first.')
        return 1

    with results_path.open(encoding='utf-8') as f:
        payload = json.load(f)
    results = payload if isinstance(payload, list) else [payload]

    existing_rows = _read_csv(TARGET_CSV)
    stats = merge_results(results, existing_rows, TARGET_CSV.parent)

    print(f'\n[research] merge results:')
    print(f"  updated existing: {stats['updated']}")
    print(f"  added new:        {stats['added']}")
    print(f"  quarantined:      {stats['quarantined']}")
    print(f'  total in target-companies.csv: {len(existing_rows)}')

    if not args.dry_run:
        _write_csv(TARGET_CSV, existing_rows, HEADER)
        results_path.unlink()
        _sync_xlsx()
        print(f'\n  Updated {TARGET_CSV.name} | consumed {results_path.name}')
    else:
        print('\n  (dry-run: no files written)')
    return 0


if __name__ == '__main__':
    raise SystemExit(main())
