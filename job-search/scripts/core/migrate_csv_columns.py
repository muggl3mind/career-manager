#!/usr/bin/env python3
"""
Migrate target-companies.csv from 32-column to 24-column schema.

Removes dead columns and merges llm_path_name into role_family.
Idempotent: safe to run multiple times.

Usage:
    python3 job-search/scripts/core/migrate_csv_columns.py
    python3 job-search/scripts/core/migrate_csv_columns.py --dry-run
"""
from __future__ import annotations

import argparse
import csv
from pathlib import Path

REMOVED_COLUMNS = {
    'fit_score', 'fit_rationale', 'numeric_score', 'score_breakdown',
    'source_tier', 'llm_path', 'llm_path_name', 'llm_cv_template',
}

BASE = Path(__file__).resolve().parents[2]
DATA = BASE / 'data'
TARGET_CSV = DATA / 'target-companies.csv'


def migrate(path: Path, dry_run: bool = False) -> dict:
    """Migrate a CSV file to the new schema. Returns stats dict."""
    if not path.exists():
        return {'status': 'skipped', 'reason': 'file not found'}

    with path.open(encoding='utf-8') as f:
        reader = csv.DictReader(f)
        old_header = reader.fieldnames or []
        rows = list(reader)

    # Check if already migrated
    if 'llm_path_name' not in old_header and 'fit_score' not in old_header:
        return {'status': 'skipped', 'reason': 'already migrated'}

    # Merge llm_path_name into role_family
    merged = 0
    for row in rows:
        llm_pn = row.get('llm_path_name', '').strip()
        rf = row.get('role_family', '').strip()
        if llm_pn and (not rf or rf == 'manual'):
            row['role_family'] = llm_pn
            merged += 1

    # Build new header (preserve order, remove dead columns)
    new_header = [col for col in old_header if col not in REMOVED_COLUMNS]

    if not dry_run:
        with path.open('w', newline='', encoding='utf-8') as f:
            w = csv.DictWriter(f, fieldnames=new_header, extrasaction='ignore')
            w.writeheader()
            w.writerows(rows)

    return {
        'status': 'migrated',
        'rows': len(rows),
        'columns_removed': len([c for c in old_header if c in REMOVED_COLUMNS]),
        'path_names_merged': merged,
        'old_columns': len(old_header),
        'new_columns': len(new_header),
    }


def main():
    ap = argparse.ArgumentParser(description='Migrate target-companies.csv to new schema')
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    result = migrate(TARGET_CSV, dry_run=args.dry_run)
    print(f"Migration result: {result}")
    if args.dry_run:
        print("(dry-run, no files written)")


if __name__ == '__main__':
    main()
