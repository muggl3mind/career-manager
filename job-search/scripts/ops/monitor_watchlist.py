#!/usr/bin/env python3
"""
Monitor watchlist — re-check known target companies for new role openings.

Two modes:
  export  — builds data/monitor-context.json with stale companies to re-check.
             Claude reads it, visits each company's careers page, and writes
             data/monitor-results.json.
  merge   — reads monitor-results.json, updates target-companies.csv with new
             roles and last_checked timestamps.

Usage:
  python3 scripts/ops/monitor_watchlist.py export
  python3 scripts/ops/monitor_watchlist.py export --stale-days 3
  python3 scripts/ops/monitor_watchlist.py merge
  python3 scripts/ops/monitor_watchlist.py merge --dry-run
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
APPLICATIONS_CSV = BASE.parent / 'job-tracker' / 'data' / 'applications.csv'
SEEN_COMPANIES = DATA / 'seen-companies.json'
MONITOR_CONTEXT = DATA / 'monitor-context.json'
MONITOR_RESULTS = DATA / 'monitor-results.json'

DEFAULT_STALE_DAYS = 7

# Load search config
import sys as _sys
_sys.path.insert(0, str(BASE / 'scripts' / 'core'))
from search_config_loader import load_search_config

_SEARCH_CONFIG = load_search_config(DATA / 'search-config.json')

# Import from web_prospecting (which now loads from search-config.json)
try:
    from web_prospecting import PROSPECTING_PATHS, HEADER
except ImportError:
    _sys.path.insert(0, str(Path(__file__).parent))
    from web_prospecting import PROSPECTING_PATHS, HEADER

# Path-specific check instructions
PATH_CHECK_INSTRUCTIONS = {int(k): v for k, v in _SEARCH_CONFIG.get('path_check_instructions', {}).items()} if _SEARCH_CONFIG else {}

# Target role patterns
ROLE_PATTERNS = _SEARCH_CONFIG.get('role_patterns', []) if _SEARCH_CONFIG else []


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


def _sync_xlsx() -> None:
    try:
        import sys as _sys
        _sys.path.insert(0, str(BASE / 'scripts' / 'core'))
        from target_companies_sync import csv_to_xlsx
        csv_to_xlsx()
    except Exception as e:
        print(f"  [xlsx] WARN: could not write xlsx: {e}")


def _sort_key(r: Dict) -> tuple:
    llm = r.get('llm_score')
    try:
        llm_val = float(llm) if llm not in (None, '') else -1.0
    except (TypeError, ValueError):
        llm_val = -1.0
    try:
        kw_val = float(r.get('numeric_score') or 0)
    except (TypeError, ValueError):
        kw_val = 0.0
    tier_val = {'tier1_company_ats': 3, 'tier2_linkedin': 2}.get(r.get('source_tier', ''), 1)
    return (llm_val if llm_val >= 0 else kw_val, kw_val, tier_val)


def _parse_dt(s: str) -> datetime | None:
    """Parse ISO datetime or date string, return UTC datetime or None."""
    if not s:
        return None
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        pass
    # Try plain date format
    try:
        return datetime.strptime(s, '%Y-%m-%d').replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None


def _get_last_checked(company_key: str, seen: Dict, target_rows: List[Dict]) -> datetime | None:
    """Get the most recent check date for a company from all sources."""
    dates = []

    # From seen-companies.json
    entry = seen.get(company_key, {})
    for field in ('last_checked', 'first_seen'):
        dt = _parse_dt(entry.get(field, ''))
        if dt:
            dates.append(dt)

    # From target-companies.csv last_checked column
    for row in target_rows:
        if (row.get('company') or '').strip().lower() == company_key:
            dt = _parse_dt(row.get('last_checked', ''))
            if dt:
                dates.append(dt)
            break

    return max(dates) if dates else None


def _build_company_registry(
    seen: Dict,
    target_rows: List[Dict],
    app_rows: List[Dict],
) -> Dict[str, Dict]:
    """
    Build a unified registry of all companies we should monitor.
    Returns dict keyed by lowercase company name.
    """
    registry: Dict[str, Dict] = {}

    # 1. All named_targets from PROSPECTING_PATHS
    for p in PROSPECTING_PATHS:
        for name in p['named_targets']:
            key = name.lower()
            if key not in registry:
                registry[key] = {
                    'company': name,
                    'website': '',
                    'path': p['path'],
                    'path_name': p['name'],
                    'source': 'named_target',
                    'current_status': '',
                    'known_roles': '',
                    'careers_url': '',
                }

    # 2. Companies from target-companies.csv
    for row in target_rows:
        name = (row.get('company') or '').strip()
        key = name.lower()
        if not key:
            continue
        if key in registry:
            # Enrich existing entry
            registry[key]['website'] = registry[key]['website'] or row.get('website', '')
            registry[key]['careers_url'] = registry[key]['careers_url'] or row.get('careers_url', '')
            registry[key]['current_status'] = row.get('validation_status', '')
            registry[key]['known_roles'] = row.get('open_positions', '')
            if not registry[key].get('path'):
                try:
                    registry[key]['path'] = int(row.get('llm_path') or 0)
                except (ValueError, TypeError):
                    pass
                registry[key]['path_name'] = row.get('llm_path_name', '')
        else:
            registry[key] = {
                'company': name,
                'website': row.get('website', ''),
                'path': int(row.get('llm_path') or 0) if row.get('llm_path') else 0,
                'path_name': row.get('llm_path_name', ''),
                'source': 'target_list',
                'current_status': row.get('validation_status', ''),
                'known_roles': row.get('open_positions', ''),
                'careers_url': row.get('careers_url', ''),
            }

    # 3. Companies from applications.csv (not rejected/closed)
    active_app_statuses = {'researching', 'applied', 'interviewing', 'offer', 'no_fit_now', 'declined'}
    for row in app_rows:
        name = (row.get('company') or '').strip()
        key = name.lower()
        status = (row.get('status') or '').strip().lower()
        if not key or status in ('rejected', 'closed'):
            continue
        if key in registry:
            registry[key]['app_status'] = status
            registry[key]['app_role'] = row.get('role', '')
        else:
            registry[key] = {
                'company': name,
                'website': '',
                'path': 0,
                'path_name': '',
                'source': 'application',
                'current_status': '',
                'known_roles': row.get('role', ''),
                'careers_url': row.get('job_url', ''),
                'app_status': status,
                'app_role': row.get('role', ''),
            }

    # 4. Companies from seen-companies.json
    for key, entry in seen.items():
        if key not in registry:
            registry[key] = {
                'company': entry.get('company', key),
                'website': entry.get('website', ''),
                'path': entry.get('path', 0),
                'path_name': '',
                'source': 'seen_cache',
                'current_status': entry.get('prospect_status', ''),
                'known_roles': '',
                'careers_url': '',
            }
        # Always enrich website from seen cache
        if not registry[key]['website'] and entry.get('website'):
            registry[key]['website'] = entry['website']

    return registry


def cmd_export(stale_days: int = DEFAULT_STALE_DAYS) -> int:
    """Build monitor-context.json with companies that need re-checking."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=stale_days)

    seen = _load_seen()
    target_rows = _read_csv(TARGET_CSV)
    app_rows = _read_csv(APPLICATIONS_CSV) if APPLICATIONS_CSV.exists() else []

    registry = _build_company_registry(seen, target_rows, app_rows)

    # Identify stale companies
    stale = []
    fresh = []
    for key, info in sorted(registry.items()):
        last_checked = _get_last_checked(key, seen, target_rows)
        days_since = (now - last_checked).days if last_checked else 999

        info['last_checked'] = last_checked.isoformat() if last_checked else None
        info['days_since_check'] = days_since

        path_num = info.get('path', 0)
        info['check_instructions'] = PATH_CHECK_INSTRUCTIONS.get(
            path_num,
            'Check careers page for AI, Product Manager, Solutions, Innovation roles.',
        )

        if last_checked is None or last_checked < cutoff:
            stale.append(info)
        else:
            fresh.append(info)

    # Sort stale: never-checked first, then oldest first
    stale.sort(key=lambda x: (x['last_checked'] or '', x['company'].lower()))

    context = {
        'mode': 'monitor',
        'generated_at': now.isoformat(),
        'stale_threshold_days': stale_days,
        'total_companies_tracked': len(registry),
        'companies_to_check': len(stale),
        'companies_fresh': len(fresh),
        'checklist': stale,
        'role_patterns': ROLE_PATTERNS,
        'instructions': (
            'For EACH company in the checklist below, you MUST:\n'
            '1. Visit their careers page (use the careers_url if provided, otherwise search "[company] careers")\n'
            '2. Search for roles matching the role_patterns and check_instructions\n'
            '3. Score the company against references/criteria.md (10 yes/no/unknown dimensions)\n'
            '4. Report what you find — even if no new roles, report "no_change" to update last_checked\n'
            '\n'
            'Write ALL results to data/monitor-results.json as a JSON array.\n'
            'Each result must have this structure:\n'
            '{\n'
            '  "company": "Company Name",\n'
            '  "website": "company.com",\n'
            '  "careers_url": "https://company.com/careers",\n'
            '  "role_url": "https://company.com/careers/specific-role-123",\n'
            '  "open_positions": "Role Title 1; Role Title 2",\n'
            '  "status": "active_role|watch_list|no_change",\n'
            '  "path": 5,\n'
            '  "path_name": "Professional Services",\n'
            '  "notes": "Found 2 AI roles in their consulting practice.",\n'
            '  "llm_score": 82,\n'
            '  "llm_dimensions_evaluated": 9,\n'
            '  "llm_rationale": "Strong fit. Comp data unavailable.",\n'
            '  "llm_path_name": "Professional Services",\n'
            '  "llm_flags": "comp_unknown"\n'
            '}\n'
            '\n'
            'status values:\n'
            '- "active_role": Found relevant open roles\n'
            '- "watch_list": No relevant roles right now but company is a fit\n'
            '- "no_change": Already tracked, no new roles found (scoring fields optional)\n'
            '\n'
            'Scoring: For each dimension in criteria.md, assess yes/no/unknown.\n'
            'Score = (yes count / evaluated count) * 100, rounded.\n'
            'If <5 dimensions can be evaluated, use llm_flags: "needs_research" and omit llm_score.\n'
        ),
        'results_path': str(MONITOR_RESULTS),
    }

    MONITOR_CONTEXT.parent.mkdir(parents=True, exist_ok=True)
    with MONITOR_CONTEXT.open('w', encoding='utf-8') as f:
        json.dump(context, f, indent=2, ensure_ascii=False)

    print(f'[monitor] export done')
    print(f'  total companies tracked: {len(registry)}')
    print(f'  need re-check (>{stale_days} days): {len(stale)}')
    print(f'  fresh (checked within {stale_days} days): {len(fresh)}')
    print(f'  context written to: {MONITOR_CONTEXT}')
    print()
    print('Next: Claude reads monitor-context.json, checks careers pages,')
    print('      and writes monitor-results.json')
    print(f'Then: python3 scripts/ops/monitor_watchlist.py merge')
    return 0


def cmd_merge(dry_run: bool = False) -> int:
    """Merge monitor-results.json into target-companies.csv."""
    if not MONITOR_RESULTS.exists():
        print(f'ERROR: {MONITOR_RESULTS} not found. Claude must write it first.')
        return 1

    with MONITOR_RESULTS.open(encoding='utf-8') as f:
        results: List[Dict] = json.load(f)

    seen = _load_seen()
    existing_rows = _read_csv(TARGET_CSV)
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    now_ts = datetime.now(timezone.utc).isoformat()

    # Index existing rows by lowercase company name (list of indices for duplicates)
    existing_by_name: Dict[str, list] = {}
    for i, row in enumerate(existing_rows):
        name = (row.get('company') or '').strip().lower()
        if name:
            existing_by_name.setdefault(name, []).append(i)

    updated = 0
    added = 0
    no_change = 0

    for r in results:
        company = (r.get('company') or '').strip()
        key = company.lower()
        website = (r.get('website') or '').strip()
        status = (r.get('status') or 'no_change').strip()
        open_positions = (r.get('open_positions') or '').strip()
        careers_url = (r.get('careers_url') or '').strip()

        # Update seen-companies.json
        if key in seen:
            seen[key]['last_checked'] = now_ts
        else:
            seen[key] = {
                'first_seen': now_ts,
                'last_checked': now_ts,
                'company': company,
                'website': website.lower(),
                'prospect_status': status if status != 'no_change' else 'watch_list',
                'path': r.get('path'),
            }

        if status == 'no_change':
            # Just update last_checked on all matching rows
            if key in existing_by_name:
                for idx in existing_by_name[key]:
                    existing_rows[idx]['last_checked'] = today
            no_change += 1
            continue

        if key in existing_by_name:
            # Update all existing rows for this company
            for idx in existing_by_name[key]:
                row = existing_rows[idx]
                row['last_checked'] = today
            # Apply role/status updates to the first row
            row = existing_rows[existing_by_name[key][0]]
            if open_positions:
                existing_open = (row.get('open_positions') or '').strip()
                # Replace if it was a placeholder or empty
                if not existing_open or existing_open.lower() in (
                    'none — watch list', 'none', 'n/a', 'tbd', 'check careers'
                ):
                    row['open_positions'] = open_positions
                elif open_positions.lower() not in existing_open.lower():
                    row['open_positions'] = f"{existing_open}; {open_positions}"
            if careers_url and not row.get('careers_url'):
                row['careers_url'] = careers_url
            if status == 'active_role' and row.get('validation_status') == 'watch_list':
                row['validation_status'] = 'pass'
            if r.get('notes'):
                existing_notes = row.get('notes', '')
                row['notes'] = f"{existing_notes} | monitor {today}: {r['notes']}" if existing_notes else f"monitor {today}: {r['notes']}"
            # Copy LLM scoring fields (only if non-empty in result)
            for field in ('llm_score', 'llm_rationale', 'llm_path_name', 'llm_flags', 'role_url'):
                val = str(r.get(field, '')).strip()
                if val:
                    row[field] = val
            if r.get('llm_score'):
                row['llm_evaluated_at'] = now_ts
            updated += 1
        else:
            # New company — add to target list
            is_watch = status == 'watch_list' or not open_positions
            new_row = {
                'rank': '',
                'company': company,
                'website': website,
                'careers_url': careers_url,
                'role_url': r.get('role_url', ''),
                'industry': '',
                'size': '',
                'stage': '',
                'recent_funding': '',
                'tech_signals': '',
                'open_positions': open_positions or 'None — watch list',
                'fit_score': 'Watch List' if is_watch else 'Monitored',
                'fit_rationale': r.get('notes', ''),
                'last_checked': today,
                'notes': f'source=monitor | status={status}',
                'numeric_score': '',
                'score_breakdown': '',
                'role_family': r.get('path_name', ''),
                'source': 'monitor',
                'source_tier': 'tier2_prospected',
                'location_detected': '',
                'validation_status': 'watch_list' if is_watch else 'pass',
                'exclusion_reason': '',
                'llm_score': str(r.get('llm_score', '')) if r.get('llm_score') is not None else '',
                'llm_path': r.get('path', ''),
                'llm_path_name': r.get('llm_path_name', '') or r.get('path_name', ''),
                'llm_rationale': r.get('llm_rationale', ''),
                'llm_flags': r.get('llm_flags', ''),
                'llm_cv_template': '',
                'llm_hard_pass': 'false',
                'llm_hard_pass_reason': '',
                'llm_evaluated_at': now_ts if r.get('llm_score') else '',
            }
            existing_rows.append(new_row)
            existing_by_name[key] = [len(existing_rows) - 1]
            added += 1

    # Re-sort: pass rows by score desc, watch_list by name
    pass_rows = sorted(
        [r for r in existing_rows if r.get('validation_status') not in ('watch_list', 'fail')],
        key=_sort_key, reverse=True,
    )
    watch_rows = sorted(
        [r for r in existing_rows if r.get('validation_status') == 'watch_list'],
        key=lambda r: (r.get('company') or '').lower(),
    )
    fail_rows = [r for r in existing_rows if r.get('validation_status') == 'fail']

    final_rows = pass_rows + watch_rows + fail_rows
    for i, r in enumerate(pass_rows, 1):
        r['rank'] = str(i)

    print(f'\n[monitor] merge results:')
    print(f'  updated existing: {updated}')
    print(f'  added new:        {added}')
    print(f'  no change:        {no_change}')
    print(f'  total in target-companies.csv: {len(final_rows)}')

    if not dry_run:
        _write_csv(TARGET_CSV, final_rows, HEADER)
        _save_seen(seen)
        if MONITOR_RESULTS.exists():
            MONITOR_RESULTS.unlink()
        if MONITOR_CONTEXT.exists():
            MONITOR_CONTEXT.unlink()
        _sync_xlsx()
        print(f'\n  Updated {TARGET_CSV.name} | seen-companies.json | target-companies.xlsx')
    else:
        print('\n  (dry-run — no files written)')

    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description='Monitor watchlist — re-check companies for new roles')
    ap.add_argument('mode', choices=['export', 'merge'])
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--stale-days', type=int, default=DEFAULT_STALE_DAYS,
                    help=f'Days before a company is considered stale (default: {DEFAULT_STALE_DAYS})')
    args = ap.parse_args()

    if args.mode == 'export':
        return cmd_export(stale_days=args.stale_days)
    return cmd_merge(dry_run=args.dry_run)


if __name__ == '__main__':
    raise SystemExit(main())
