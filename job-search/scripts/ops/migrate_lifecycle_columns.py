#!/usr/bin/env python3
"""
Stage 1 migration — add lifecycle columns to target-companies.csv.

Adds three columns:
  - lifecycle_state         (active | watching | archived)
  - last_verified_at        (ISO timestamp of last successful re-verify)
  - watching_run_count      (# of consecutive runs in 'watching' state)

Existing rows are seeded as:
  - lifecycle_state='active' if validation_status='pass'
  - lifecycle_state='watching' otherwise
  - last_verified_at=llm_evaluated_at (or empty if missing)
  - watching_run_count=0

Idempotent: if the columns already exist, exits cleanly.
Run with --dry-run to preview without writing.
"""
from __future__ import annotations

import argparse
import csv
import sys
from pathlib import Path

DATA = Path(__file__).resolve().parents[2] / 'data'
TARGET_CSV = DATA / 'target-companies.csv'

NEW_COLUMNS = ['lifecycle_state', 'last_verified_at', 'watching_run_count']


def migrate(csv_path: Path, dry_run: bool = False) -> dict:
    """Add lifecycle columns to the CSV. Returns a summary dict."""
    if not csv_path.exists():
        raise FileNotFoundError(f'{csv_path} does not exist')

    with csv_path.open(encoding='utf-8') as f:
        reader = csv.DictReader(f)
        existing_fields = list(reader.fieldnames or [])
        rows = list(reader)

    already_migrated = all(col in existing_fields for col in NEW_COLUMNS)
    if already_migrated:
        return {'status': 'already_migrated', 'rows': len(rows), 'dry_run': dry_run}

    # Build new fieldnames — preserve order, append new columns at the end
    new_fields = list(existing_fields)
    for col in NEW_COLUMNS:
        if col not in new_fields:
            new_fields.append(col)

    # Seed existing rows
    state_counts = {'active': 0, 'watching': 0, 'archived': 0}
    for row in rows:
        if row.get('validation_status', '').strip() == 'pass':
            row['lifecycle_state'] = 'active'
            state_counts['active'] += 1
        else:
            row['lifecycle_state'] = 'watching'
            state_counts['watching'] += 1
        row['last_verified_at'] = row.get('llm_evaluated_at', '').strip()
        row['watching_run_count'] = '0'

    summary = {
        'status': 'migrated',
        'rows': len(rows),
        'added_columns': NEW_COLUMNS,
        'state_counts': state_counts,
        'dry_run': dry_run,
    }

    if dry_run:
        return summary

    # Write back atomically
    tmp_path = csv_path.with_suffix('.csv.tmp')
    with tmp_path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=new_fields)
        writer.writeheader()
        writer.writerows(rows)
    tmp_path.replace(csv_path)

    return summary


def main() -> int:
    ap = argparse.ArgumentParser(description='Add lifecycle columns to target-companies.csv')
    ap.add_argument('--dry-run', action='store_true', help='Preview without writing')
    ap.add_argument('--csv', type=Path, default=TARGET_CSV, help='Path to target-companies.csv')
    args = ap.parse_args()

    try:
        summary = migrate(args.csv, dry_run=args.dry_run)
    except FileNotFoundError as e:
        print(f'ERROR: {e}', file=sys.stderr)
        return 1

    print(f"[migrate_lifecycle_columns] status: {summary['status']}")
    print(f"  rows: {summary['rows']}")
    if summary['status'] == 'migrated':
        print(f"  added columns: {', '.join(summary['added_columns'])}")
        print(f"  state seed:    active={summary['state_counts']['active']}, watching={summary['state_counts']['watching']}")
    if summary['dry_run']:
        print('  (dry-run — no files written)')
    return 0


if __name__ == '__main__':
    sys.exit(main())
