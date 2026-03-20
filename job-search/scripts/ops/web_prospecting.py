#!/usr/bin/env python3
"""
Web prospecting utility for Claude-driven company discovery.

Two modes:
  export  — writes data/prospecting-context.json (seen companies + existing targets)
             so Claude knows what to skip. Claude then runs WebSearch/WebFetch
             and writes data/prospecting-results.json.
  merge   — reads data/prospecting-results.json written by Claude,
             merges into target-companies.csv, updates seen-companies.json.

Usage:
  python3 scripts/ops/web_prospecting.py export
  python3 scripts/ops/web_prospecting.py merge
  python3 scripts/ops/web_prospecting.py merge --dry-run
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List

BASE = Path(__file__).resolve().parents[2]
DATA = BASE / 'data'
TARGET_CSV = DATA / 'target-companies.csv'
SEEN_COMPANIES = DATA / 'seen-companies.json'
PROSPECTING_CONTEXT = DATA / 'prospecting-context.json'
PROSPECTING_RESULTS = DATA / 'prospecting-results.json'

import sys
sys.path.insert(0, str(BASE / 'scripts' / 'core'))
from search_config_loader import load_search_config
from csv_schema import HEADER
from path_normalizer import normalize_path

_SEARCH_CONFIG = load_search_config(DATA / 'search-config.json')
PROSPECTING_PATHS = _SEARCH_CONFIG.get('prospecting_paths', []) if _SEARCH_CONFIG else []
_CANONICAL_PATHS = [v['label'] for v in _SEARCH_CONFIG['query_packs'].values()] if _SEARCH_CONFIG else []


def _sync_xlsx() -> None:
    try:
        import sys
        sys.path.insert(0, str(BASE / 'scripts' / 'core'))
        from target_companies_sync import csv_to_xlsx
        csv_to_xlsx()
    except Exception as e:
        print(f"  [xlsx] WARN: could not write xlsx: {e}")


def _read_csv(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    with path.open(encoding='utf-8') as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: List[Dict], header: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=header, extrasaction='ignore')
        w.writeheader()
        w.writerows(rows)


def _load_seen() -> Dict:
    if SEEN_COMPANIES.exists():
        with SEEN_COMPANIES.open(encoding='utf-8') as f:
            return json.load(f)
    return {}


def _save_seen(seen: Dict) -> None:
    with SEEN_COMPANIES.open('w', encoding='utf-8') as f:
        json.dump(seen, f, indent=2, ensure_ascii=False)


def _sort_key(r: Dict) -> tuple:
    llm = r.get('llm_score')
    try:
        llm_val = float(llm) if llm not in (None, '') else 0.0
    except (TypeError, ValueError):
        llm_val = 0.0
    return (llm_val,)


def cmd_export() -> int:
    """Write prospecting-context.json for Claude to read before searching."""
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(days=7)

    seen = _load_seen()
    existing_rows = _read_csv(TARGET_CSV)

    # Build set of recently-checked companies (skip) vs stale (re-check)
    skip_companies = set()
    recheck_companies = []

    # Process seen-companies.json
    for key, entry in seen.items():
        last_checked_str = entry.get('last_checked') or entry.get('first_seen', '')
        last_checked_dt = None
        if last_checked_str:
            try:
                last_checked_dt = datetime.fromisoformat(last_checked_str)
                if last_checked_dt.tzinfo is None:
                    last_checked_dt = last_checked_dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                pass

        if last_checked_dt and last_checked_dt > stale_cutoff:
            skip_companies.add(key.lower())
        else:
            recheck_companies.append({
                'company': entry.get('company', key),
                'website': entry.get('website', ''),
                'last_checked': last_checked_str,
                'path': entry.get('path'),
            })

    # Also add recently-checked CSV companies to skip
    for row in existing_rows:
        name = (row.get('company') or '').strip().lower()
        site = (row.get('website') or '').strip().lower()
        lc = row.get('last_checked', '')
        lc_dt = None
        if lc:
            try:
                lc_dt = datetime.fromisoformat(lc) if 'T' in lc else datetime.strptime(lc, '%Y-%m-%d')
                if lc_dt.tzinfo is None:
                    lc_dt = lc_dt.replace(tzinfo=timezone.utc)
            except (ValueError, TypeError):
                pass

        if lc_dt and lc_dt > stale_cutoff:
            if name:
                skip_companies.add(name)
            if site:
                skip_companies.add(site)

    # Build flat list of ALL named targets with mandatory check flag
    all_named_targets = []
    for p in PROSPECTING_PATHS:
        for t in p['named_targets']:
            all_named_targets.append({
                'company': t,
                'path': p['path'],
                'path_name': p['name'],
                'in_skip_list': t.lower() in skip_companies,
            })

    context = {
        'known_companies_skip': sorted(skip_companies),
        'known_companies_skip_count': len(skip_companies),
        'known_companies_recheck': recheck_companies,
        'known_companies_recheck_count': len(recheck_companies),
        'instructions': (
            'Cover ALL paths below. For each path:\n'
            '1. MANDATORY: Check EVERY named_target company careers page for relevant open roles. '
            'This is NOT optional — each named target MUST be visited even if in skip list '
            '(for skip list companies, just check for NEW roles not previously seen).\n'
            '2. Run the search_queries to find NEW companies not in known_companies_skip.\n'
            '3. Find new_targets_goal new companies beyond named targets.\n'
            '\n'
            'For named targets already tracked: report any new role findings in the results array.\n'
            'For truly new companies: full prospecting entry.\n'
            '\n'
            'SCORING: For each company, evaluate against references/criteria.md rubric:\n'
            '- 10 yes/no/unknown dimensions. Score = (yes / evaluated) * 100.\n'
            '- If <5 dimensions assessable, flag as "needs_research" instead of scoring.\n'
            '- Include llm_score, llm_dimensions_evaluated, llm_rationale, role_family, llm_flags in each result.\n'
            'Write ALL results to data/prospecting-results.json as a JSON array.'
        ),
        'named_targets_mandatory_check': all_named_targets,
        'named_targets_count': len(all_named_targets),
        'paths': PROSPECTING_PATHS,
        'results_schema': {
            'company': 'Company name',
            'website': 'e.g. numeric.com',
            'careers_url': 'Direct URL to careers page or specific role',
            'industry': 'e.g. AI Healthcare Software',
            'size': 'e.g. 50-200',
            'stage': 'e.g. Series B',
            'recent_funding': 'e.g. $25M Series B (Jan 2026)',
            'tech_signals': 'comma-separated AI/tech signals observed',
            'open_positions': 'Role title if found, empty string if none',
            'prospect_status': 'active_role OR watch_list',
            'fit_rationale': '2-3 sentences explaining why this company fits the profile',
            'path': '1-8 matching criteria.md paths',
            'path_name': 'e.g. AI Industry Startup',
            'notes': 'Any additional context, cold outreach angle, recent news',
            'role_url': 'Direct URL to the specific job posting (from Tavily Map). Empty string if not found.',
            'llm_score': 'Integer 0-100: (yes dimensions / evaluated dimensions) * 100',
            'llm_dimensions_evaluated': 'How many of 10 dimensions you could assess',
            'llm_rationale': '1-2 sentence fit summary from criteria.md evaluation',
            'llm_flags': 'Comma-separated: comp_unknown, growth_unknown, needs_research, etc.',
        },
    }

    PROSPECTING_CONTEXT.parent.mkdir(parents=True, exist_ok=True)
    with PROSPECTING_CONTEXT.open('w', encoding='utf-8') as f:
        json.dump(context, f, indent=2, ensure_ascii=False)

    print(f"[web_prospecting] export done")
    print(f"  companies to skip (checked <7 days): {len(skip_companies)}")
    print(f"  companies to re-check (stale >7 days): {len(recheck_companies)}")
    print(f"  named targets (mandatory check): {len(all_named_targets)}")
    print(f"  context written to: {PROSPECTING_CONTEXT}")
    print(f"\nNext: run the prospecting skill — Claude will search and write prospecting-results.json")
    print(f"Then: python3 scripts/ops/web_prospecting.py merge")
    return 0


def cmd_merge(dry_run: bool = False) -> int:
    """Merge Claude's prospecting-results.json into target-companies.csv."""
    if not PROSPECTING_RESULTS.exists():
        print(f"ERROR: {PROSPECTING_RESULTS} not found. Claude must write it first.")
        return 1

    with PROSPECTING_RESULTS.open(encoding='utf-8') as f:
        results: List[Dict] = json.load(f)

    seen = _load_seen()
    existing_rows = _read_csv(TARGET_CSV)
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    now_ts = datetime.now(timezone.utc).isoformat()

    # Build existing key set to avoid duplicates
    existing_keys = set()
    for row in existing_rows:
        name = (row.get('company') or '').strip().lower()
        site = (row.get('website') or '').strip().lower()
        if name:
            existing_keys.add(name)
        if site:
            existing_keys.add(site)

    new_rows = []
    skipped = 0
    watch_list_count = 0
    active_role_count = 0

    updated_existing = 0
    for r in results:
        company = (r.get('company') or '').strip()
        website = (r.get('website') or '').strip().lower()
        name_key = company.lower()

        if name_key in existing_keys or website in existing_keys:
            # Update existing row if new roles found (instead of silently skipping)
            new_roles = (r.get('open_positions') or '').strip()
            if new_roles and new_roles.lower() not in ('none', 'none — watch list', ''):
                for row in existing_rows:
                    if (row.get('company') or '').strip().lower() == name_key:
                        row['last_checked'] = today
                        existing_open = (row.get('open_positions') or '').strip()
                        if not existing_open or existing_open.lower() in (
                            'none — watch list', 'none', 'n/a', 'tbd', 'check careers'
                        ):
                            row['open_positions'] = new_roles
                        elif new_roles.lower() not in existing_open.lower():
                            row['open_positions'] = f"{existing_open}; {new_roles}"
                        if row.get('validation_status') == 'watch_list':
                            row['validation_status'] = 'pass'
                        # Copy LLM scoring fields (only if non-empty)
                        for field in ('llm_score', 'llm_rationale', 'llm_flags', 'role_url'):
                            val = str(r.get(field, '')).strip()
                            if val:
                                row[field] = val
                        path_val = str(r.get('role_family', '') or r.get('llm_path_name', '') or r.get('path_name', '')).strip()
                        if path_val:
                            row['role_family'] = path_val
                        if r.get('llm_score'):
                            row['llm_evaluated_at'] = now_ts
                        updated_existing += 1
                        break
            # Update seen-companies last_checked
            if name_key in seen:
                seen[name_key]['last_checked'] = now_ts
            skipped += 1
            continue

        prospect_status = r.get('prospect_status', 'watch_list')
        open_positions = r.get('open_positions', '')
        is_watch_list = prospect_status == 'watch_list' or not open_positions

        if is_watch_list:
            watch_list_count += 1
            validation_status = 'watch_list'
            open_positions = open_positions or 'None — watch list'
        else:
            active_role_count += 1
            validation_status = 'pass'

        row = {
            'rank': '',
            'company': company,
            'website': r.get('website', ''),
            'careers_url': r.get('careers_url', ''),
            'role_url': r.get('role_url', ''),
            'industry': r.get('industry', ''),
            'size': r.get('size', ''),
            'stage': r.get('stage', ''),
            'recent_funding': r.get('recent_funding', ''),
            'tech_signals': r.get('tech_signals', ''),
            'open_positions': open_positions,
            'last_checked': today,
            'notes': r.get('notes', '') + f' | source=web_prospecting | status={prospect_status}',
            'role_family': r.get('role_family', '') or r.get('llm_path_name', '') or r.get('path_name', ''),
            'source': 'web_prospecting',
            'location_detected': '',
            'validation_status': validation_status,
            'exclusion_reason': '',
            'llm_score': str(r.get('llm_score', '')) if r.get('llm_score') is not None else '',
            'llm_rationale': r.get('llm_rationale', '') or r.get('fit_rationale', ''),
            'llm_flags': r.get('llm_flags', ''),
            'llm_hard_pass': 'false',
            'llm_hard_pass_reason': '',
            'llm_evaluated_at': now_ts if r.get('llm_score') else '',
        }
        new_rows.append(row)
        if row.get('role_family'):
            row['role_family'] = normalize_path(row['role_family'], _CANONICAL_PATHS)

        # Update seen-companies cache
        seen[name_key] = {
            'first_seen': seen.get(name_key, {}).get('first_seen', now_ts),
            'last_checked': now_ts,
            'company': company,
            'website': website,
            'prospect_status': prospect_status,
            'path': r.get('path'),
        }
        existing_keys.add(name_key)
        if website:
            existing_keys.add(website)

    # Merge and re-sort: pass/active first, then watch_list
    all_rows = existing_rows + new_rows

    def full_sort_key(r):
        vs = r.get('validation_status', '')
        status_order = 0 if vs in ('pass',) else (1 if vs == 'watch_list' else 2)
        return (status_order,) + _sort_key(r)

    # Keep pass rows sorted by score, watch_list rows at end sorted by company name
    pass_rows = sorted(
        [r for r in all_rows if r.get('validation_status') not in ('watch_list', 'fail')],
        key=_sort_key, reverse=True,
    )
    watch_rows = sorted(
        [r for r in all_rows if r.get('validation_status') == 'watch_list'],
        key=lambda r: (r.get('company') or '').lower(),
    )
    fail_rows = [r for r in all_rows if r.get('validation_status') == 'fail']

    final_rows = pass_rows + watch_rows + fail_rows
    for i, r in enumerate(pass_rows, 1):
        r['rank'] = str(i)

    print(f"\n[web_prospecting] merge results:")
    print(f"  new companies: {len(new_rows)}")
    print(f"    active roles: {active_role_count}")
    print(f"    watch list:   {watch_list_count}")
    print(f"  updated existing (new roles found): {updated_existing}")
    print(f"  skipped (already known, no new roles): {skipped - updated_existing}")
    print(f"  total in target-companies.csv: {len(final_rows)}")

    if not dry_run:
        _write_csv(TARGET_CSV, final_rows, HEADER)
        _save_seen(seen)
        if PROSPECTING_RESULTS.exists():
            PROSPECTING_RESULTS.unlink()
        if PROSPECTING_CONTEXT.exists():
            PROSPECTING_CONTEXT.unlink()
        _sync_xlsx()
        print(f"\n✓ Updated {TARGET_CSV.name} | seen-companies.json | target-companies.xlsx")
    else:
        print("\n(dry-run — no files written)")

    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['export', 'merge'])
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    if args.mode == 'export':
        return cmd_export()
    return cmd_merge(dry_run=args.dry_run)


if __name__ == '__main__':
    raise SystemExit(main())
