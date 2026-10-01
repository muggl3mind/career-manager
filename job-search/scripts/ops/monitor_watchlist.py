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

# Cadence gate (Phase 3 item 15a): companies verified fewer than this many
# days ago are skipped on export. Override per run with --stale-days, or
# persistently via pipeline.monitor.min_recheck_days in config.yaml.
DEFAULT_MIN_RECHECK_DAYS = 7

# Application statuses that mean the user actually applied. These companies
# bypass the cadence gate and are re-checked every run.
APPLIED_STATUSES = frozenset({'applied', 'interviewing', 'offer'})

DEFAULT_CHECK_INSTRUCTION = (
    'Check careers page for AI, Product Manager, Solutions, Innovation roles.'
)

# Load search config
import sys as _sys
_sys.path.insert(0, str(BASE / 'scripts' / 'core'))
_sys.path.insert(0, str(BASE.parent / 'scripts'))
from search_config_loader import load_search_config
from csv_io import write_csv_atomic
from path_normalizer import normalize_path, normalize_company
from company_dedup import find_existing, merge_into_existing
from scoring import SCORING_INSTRUCTIONS
from flags import (
    FLAG_SEPARATOR,
    add_flag,
    has_flag,
    normalize_flags,
    remove_flag,
)
from merge_validation import (
    add_needs_research_flag,
    quarantine_row,
    validate_self_report,
)

# Flag set on a tracked company that was exported for re-verification but
# never came back in monitor-results.json (finding H3). Such rows keep
# their old last_checked / last_verified_at and stay visibly stale.
UNREACHED_FLAG = 'monitor_unreached'
try:
    from config_loader import get as _pipeline_cfg
except Exception:
    _pipeline_cfg = lambda key, default=None: default  # noqa: E731

_SEARCH_CONFIG = load_search_config(DATA / 'search-config.json')
_CANONICAL_PATHS = [v['label'] for v in _SEARCH_CONFIG['query_packs'].values()] if _SEARCH_CONFIG else []

_ARCHIVE_GRACE_RUNS = _pipeline_cfg('pipeline.lifecycle.archive_grace_runs', 2)

# Import from web_prospecting (which now loads from search-config.json)
try:
    from web_prospecting import HEADER
except ImportError:
    _sys.path.insert(0, str(Path(__file__).parent))
    from web_prospecting import HEADER

# Path-specific check instructions
PATH_CHECK_INSTRUCTIONS = {int(k): v for k, v in _SEARCH_CONFIG.get('path_check_instructions', {}).items()} if _SEARCH_CONFIG else {}

# Target role patterns
ROLE_PATTERNS = _SEARCH_CONFIG.get('role_patterns', []) if _SEARCH_CONFIG else []

# Embedded in the export so monitor agents never read search-config.json
SEARCH_LOCATIONS = (_SEARCH_CONFIG.get('search_locations') if _SEARCH_CONFIG else None) or ['United States']


def _read_csv(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    with path.open(encoding='utf-8') as f:
        return list(csv.DictReader(f))


def _write_csv(path: Path, rows: List[Dict], header: List[str]) -> None:
    write_csv_atomic(path, rows, header)


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
        llm_val = float(llm) if llm not in (None, '') else 0.0
    except (TypeError, ValueError):
        llm_val = 0.0
    return (llm_val,)


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

    # 1. Companies from target-companies.csv
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
            registry[key]['llm_flags'] = row.get('llm_flags', '')
            if not registry[key].get('path_name'):
                registry[key]['path_name'] = row.get('role_family', '')
        else:
            registry[key] = {
                'company': name,
                'website': row.get('website', ''),
                'path': 0,
                'path_name': row.get('role_family', ''),
                'source': 'target_list',
                'current_status': row.get('validation_status', ''),
                'known_roles': row.get('open_positions', ''),
                'careers_url': row.get('careers_url', ''),
                'llm_flags': row.get('llm_flags', ''),
            }

    # 2. Companies from applications.csv (not rejected/closed)
    active_app_statuses = {'researching', 'applied', 'interviewing', 'offer', 'no_fit_now', 'declined'}
    for row in app_rows:
        name = (row.get('company') or '').strip()
        key = name.lower()
        status = (row.get('status') or '').strip().lower()
        if not key:
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

    # 3. Companies from seen-companies.json
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


def cmd_export(stale_days: int | None = None) -> int:
    """
    Build monitor-context.json with companies in 'active' or 'watching'
    lifecycle states that are due for a re-check.

    Cadence gate: companies verified fewer than min_recheck_days ago are
    skipped this run. Companies with an in-flight application (see
    APPLIED_STATUSES) are always included regardless of recency.
    """
    now = datetime.now(timezone.utc)
    min_recheck_days = (
        stale_days if stale_days is not None
        else _pipeline_cfg('pipeline.monitor.min_recheck_days', DEFAULT_MIN_RECHECK_DAYS)
    )
    try:
        min_recheck_days = int(min_recheck_days)
    except (TypeError, ValueError):
        min_recheck_days = DEFAULT_MIN_RECHECK_DAYS

    seen = _load_seen()
    target_rows = _read_csv(TARGET_CSV)
    app_rows = _read_csv(APPLICATIONS_CSV) if APPLICATIONS_CSV.exists() else []

    registry = _build_company_registry(seen, target_rows, app_rows)

    # Build lookup of lifecycle_state by company (lower-case)
    lifecycle_by_key: Dict[str, str] = {}
    for row in target_rows:
        name = (row.get('company') or '').strip().lower()
        if not name:
            continue
        state = (row.get('lifecycle_state') or '').strip()
        if not state:
            # Pre-migration fallback: pass → active, everything else → watching
            state = 'active' if row.get('validation_status') == 'pass' else 'watching'
        lifecycle_by_key[name] = state

    # Build checklist: every company in 'active' or 'watching' state
    checklist = []
    archived_skipped = 0
    recently_skipped = 0
    for key, info in sorted(registry.items()):
        state = lifecycle_by_key.get(key)
        # Companies in seen_cache or application-only with no CSV row default to 'active'
        # (we want to verify them too).
        if state is None:
            state = 'active'

        if state == 'archived':
            archived_skipped += 1
            continue

        last_checked = _get_last_checked(key, seen, target_rows)
        days_since = (now - last_checked).days if last_checked else 999

        is_applied = (info.get('app_status') or '').strip().lower() in APPLIED_STATUSES
        if not is_applied and days_since < min_recheck_days:
            recently_skipped += 1
            continue

        info['last_checked'] = last_checked.isoformat() if last_checked else None
        info['days_since_check'] = days_since
        info['lifecycle_state'] = state

        checklist.append(info)

    # Protocol text once per batch (Phase 3 item 15b): rows carry only their
    # 'path' number; the path-to-instruction map is emitted a single time.
    used_paths = set()
    for c in checklist:
        try:
            used_paths.add(int(c.get('path') or 0))
        except (TypeError, ValueError):
            used_paths.add(0)
    check_instructions = {'default': DEFAULT_CHECK_INSTRUCTION}
    for p in sorted(used_paths):
        if p in PATH_CHECK_INSTRUCTIONS:
            check_instructions[str(p)] = PATH_CHECK_INSTRUCTIONS[p]

    # Sort: applied companies first, then watching (need attention), then active oldest-first
    def _sort(x):
        is_applied = (x.get('app_status') or '').strip().lower() in APPLIED_STATUSES
        is_watching = x.get('lifecycle_state') == 'watching'
        return (0 if is_applied else 1, 0 if is_watching else 1,
                x.get('last_checked') or '', x['company'].lower())
    checklist.sort(key=_sort)

    context = {
        'mode': 'monitor_reverify',
        'generated_at': now.isoformat(),
        'archive_grace_runs': _ARCHIVE_GRACE_RUNS,
        'min_recheck_days': min_recheck_days,
        'total_companies_tracked': len(registry),
        'companies_to_check': len(checklist),
        'archived_skipped': archived_skipped,
        'recently_verified_skipped': recently_skipped,
        'search_locations': SEARCH_LOCATIONS,
        'check_instructions': check_instructions,
        'checklist': checklist,
        'role_patterns': ROLE_PATTERNS,
        'instructions': (
            'RE-VERIFY PASS — you are confirming which tracked companies still have open roles.\n'
            '\n'
            'For EACH company in the checklist below, you MUST:\n'
            '1. Visit their careers page (use careers_url if provided, otherwise search "[company] careers").\n'
            '2. Check whether relevant roles are still open. Relevant means: matching role_patterns and the '
            'check_instructions entry for the company\'s "path" value (use the "default" entry when there is '
            'no path-specific one), with the role available in one of the search_locations regions (including '
            'Remote within those countries). If the only open roles are outside search_locations, use status '
            '"watch_list" and note the location mismatch.\n'
            '3. Score the company against references/criteria.md using the ratio method (see SCORING below).\n'
            '4. Report the outcome using the status values below.\n'
            '\n'
            'Write ALL results to data/monitor-results.json as a JSON array.\n'
            '\n'
            'Status values and what they mean for lifecycle state:\n'
            '  - "active_role": role confirmed open right now → company stays/becomes ACTIVE, watching_count resets.\n'
            '  - "no_change":   careers page reachable, nothing has changed since last check → stays ACTIVE.\n'
            '  - "watch_list":  careers page reachable but relevant roles are NOT currently open → flips to WATCHING.\n'
            '                    After too many consecutive runs in WATCHING, company is archived.\n'
            '\n'
            'If the careers page is unreachable (JS portal, timeout, rate-limited), set status="no_change" '
            'AND add "fetch_empty" to llm_flags. This preserves the prior last_verified_at so the row is not '
            'falsely counted as fresh.\n'
            '\n'
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
            '  "llm_score": 77,\n'
            '  "llm_dimensions_evaluated": 9,\n'
            '  "llm_rationale": "Strong fit (7 of 9 evaluated dimensions). Comp data unavailable.",\n'
            '  "role_family": "Professional Services",\n'
            '  "llm_flags": "comp_unknown"\n'
            '}\n'
            '\n'
            + SCORING_INSTRUCTIONS
        ),
        'results_path': str(MONITOR_RESULTS),
    }

    MONITOR_CONTEXT.parent.mkdir(parents=True, exist_ok=True)
    with MONITOR_CONTEXT.open('w', encoding='utf-8') as f:
        json.dump(context, f, ensure_ascii=False)

    watching_count = sum(1 for c in checklist if c.get('lifecycle_state') == 'watching')
    active_count = sum(1 for c in checklist if c.get('lifecycle_state') == 'active')
    print(f'[monitor] re-verify export done')
    print(f'  total companies tracked: {len(registry)}')
    print(f'  to check this run:       {len(checklist)}')
    print(f'    active:                {active_count}')
    print(f'    watching:              {watching_count}')
    print(f'  archived (skipped):      {archived_skipped}')
    print(f'  verified < {min_recheck_days}d ago (skipped): {recently_skipped}')
    print(f'  context written to: {MONITOR_CONTEXT}')
    print()
    print('Next: Claude reads monitor-context.json, re-verifies careers pages,')
    print('      and writes monitor-results.json')
    print(f'Then: python3 scripts/ops/monitor_watchlist.py merge')
    return 0


def _apply_lifecycle_transition(
    row: Dict,
    result: Dict,
    archive_grace_runs: int,
    now_ts: str,
) -> str:
    """
    Set row's lifecycle_state, last_verified_at, watching_run_count based on monitor result.
    Mutates row in place. Returns the new state.

    Rules:
      status=active_role            → active, last_verified_at=now, watching_count=0
      status=no_change (reachable)  → active, last_verified_at=now, watching_count=0
      status=no_change + fetch_empty→ flip to watching, increment count (page unreachable)
      status=watch_list             → flip to watching, increment count (role closed)

    Any company that hits watching_run_count >= archive_grace_runs is archived.
    """
    status = (result.get('status') or 'no_change').strip()
    # Tolerant flag parsing (finding M6): agents emit comma-separated
    # flags per the results schema; legacy rows used '|'. has_flag
    # accepts both, so fetch_empty is never silently missed.
    fetch_empty = has_flag(result.get('llm_flags'), 'fetch_empty')

    try:
        watching_count = int(row.get('watching_run_count') or '0')
    except (ValueError, TypeError):
        watching_count = 0

    successful_verify = (
        status == 'active_role'
        or (status == 'no_change' and not fetch_empty)
    )

    if successful_verify:
        row['lifecycle_state'] = 'active'
        row['last_verified_at'] = now_ts
        row['watching_run_count'] = '0'
        return 'active'

    # Failed verify: role closed or page unreachable. Increment, keep last_verified_at.
    watching_count += 1
    row['watching_run_count'] = str(watching_count)
    if watching_count >= archive_grace_runs:
        row['lifecycle_state'] = 'archived'
        return 'archived'
    row['lifecycle_state'] = 'watching'
    return 'watching'


def _expected_from_context() -> Dict[str, str]:
    """Load the exported checklist for coverage reconciliation (finding H3).

    Returns {normalized company key: company name} for every company sent
    out in monitor-context.json. Empty dict when the context file is
    missing or unreadable (merge still proceeds, without reconciliation).
    """
    if not MONITOR_CONTEXT.exists():
        return {}
    try:
        with MONITOR_CONTEXT.open(encoding='utf-8') as f:
            context = json.load(f)
    except (json.JSONDecodeError, OSError):
        return {}
    expected: Dict[str, str] = {}
    for item in context.get('checklist', []):
        if not isinstance(item, dict):
            continue
        name = (item.get('company') or '').strip()
        key = normalize_company(name).lower()
        if key:
            expected[key] = name
    return expected


def cmd_merge(dry_run: bool = False) -> int:
    """
    Merge monitor-results.json into target-companies.csv.

    Applies lifecycle state transitions:
      - successful verify → active
      - role closed / page unreachable → watching (or archived after grace period)

    Coverage reconciliation (finding H3): every company exported in
    monitor-context.json must come back in monitor-results.json (as a
    change, a no_change, or an explicit fetch_empty). Companies the agent
    never reported on are flagged 'monitor_unreached' and keep their old
    timestamps, so a lazy agent cannot make the portfolio look freshly
    verified by simply skipping companies.
    """
    if not MONITOR_RESULTS.exists():
        print(f'ERROR: {MONITOR_RESULTS} not found. Claude must write it first.')
        return 1

    with MONITOR_RESULTS.open(encoding='utf-8') as f:
        results: List[Dict] = json.load(f)

    seen = _load_seen()
    existing_rows = _read_csv(TARGET_CSV)
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    now_ts = datetime.now(timezone.utc).isoformat()

    updated = 0
    added = 0
    no_change = 0
    quarantined = 0
    transitions = {'active': 0, 'watching': 0, 'archived': 0}

    # Coverage reconciliation (H3): everything we sent out must come back.
    expected = _expected_from_context()
    accounted: set = set()

    for r in results:
        result_key = normalize_company((r.get('company') or '').strip()).lower()
        if result_key:
            # Quarantined rows still count as accounted for: the agent
            # reported on the company, the data just failed validation.
            accounted.add(result_key)
        # Merge-time validation (finding C2): a self-reported llm_score must
        # be a real ratio value consistent with llm_dimensions_evaluated.
        # Invalid self-reports go to <data>/quarantine, never into the CSV.
        verdict = validate_self_report(
            r.get('llm_score'),
            r.get('llm_dimensions_evaluated'),
            r.get('scores'),
        )
        if not verdict.ok:
            qpath = quarantine_row(
                TARGET_CSV.parent, 'monitor_watchlist', verdict.reason, r, verdict.detail,
            )
            print(f"  [quarantine] {r.get('company', '?')}: {verdict.reason} ({verdict.detail}) -> {qpath}")
            quarantined += 1
            continue
        if verdict.detail:
            print(f"  [merge_validation] {r.get('company', '?')}: {verdict.detail}")
        if verdict.needs_research:
            r['llm_score'] = ''
            r['llm_flags'] = add_needs_research_flag(r.get('llm_flags', ''), separator=FLAG_SEPARATOR)
        elif verdict.score is not None:
            # Recomputed/validated canonical score always wins.
            r['llm_score'] = verdict.score
        # Persist confidence (finding M9): the validated evaluated-dimension
        # count travels with the score instead of being thrown away.
        if verdict.dimensions_evaluated is not None:
            r['llm_dimensions_evaluated'] = verdict.dimensions_evaluated

        # '' means "not scored"; 0 is an honest zero score (finding H2).
        scored = r.get('llm_score') not in (None, '')

        company = normalize_company((r.get('company') or '').strip())
        key = company.lower()
        website = (r.get('website') or '').strip()
        status = (r.get('status') or 'no_change').strip()
        open_positions = (r.get('open_positions') or '').strip()
        careers_url = (r.get('careers_url') or '').strip()

        # Update seen-companies.json. fetch_empty rows keep existing
        # last_checked stale so unreachable pages retry on the next export.
        fetch_empty = has_flag(r.get('llm_flags'), 'fetch_empty')
        if key in seen:
            if not fetch_empty:
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

        match = find_existing(company, existing_rows)

        if match:
            # This company came back in the results, so any stale
            # unreached flag from a previous run no longer applies (H3).
            if has_flag(match.get('llm_flags'), UNREACHED_FLAG):
                match['llm_flags'] = remove_flag(match.get('llm_flags'), UNREACHED_FLAG)

            # Always update last_checked (legacy field, UI still uses it) unless fetch_empty.
            # has_flag parses both ',' and '|' separators (finding M6).
            fetch_empty = has_flag(r.get('llm_flags'), 'fetch_empty')
            if not fetch_empty:
                match['last_checked'] = today

            # Only merge richer data if we got a real update (not no_change)
            if status != 'no_change':
                merge_data = {
                    'open_positions': open_positions,
                    'llm_score': str(r.get('llm_score', '')) if r.get('llm_score') is not None else '',
                    'llm_dimensions_evaluated': str(r.get('llm_dimensions_evaluated', '')) if r.get('llm_dimensions_evaluated') not in (None, '') else '',
                    'llm_rationale': r.get('llm_rationale', ''),
                    'llm_flags': normalize_flags(r.get('llm_flags', '')),
                    'role_url': r.get('role_url', ''),
                    'careers_url': careers_url,
                    'role_family': r.get('role_family', '') or r.get('llm_path_name', '') or r.get('path_name', ''),
                    'last_checked': today,
                }
                if scored:
                    merge_data['llm_evaluated_at'] = now_ts
                merge_into_existing(match, merge_data)
                # Promote watch_list validation_status to pass if active roles found
                if status == 'active_role' and match.get('validation_status') == 'watch_list':
                    match['validation_status'] = 'pass'
                if r.get('notes'):
                    existing_notes = match.get('notes', '')
                    match['notes'] = (
                        f"{existing_notes} | monitor {today}: {r['notes']}"
                        if existing_notes else f"monitor {today}: {r['notes']}"
                    )
                updated += 1
            else:
                no_change += 1

            new_state = _apply_lifecycle_transition(match, r, _ARCHIVE_GRACE_RUNS, now_ts)
            transitions[new_state] = transitions.get(new_state, 0) + 1
        else:
            if status == 'no_change':
                # No-change on a company we don't have a CSV row for — nothing to do
                no_change += 1
                continue
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
                'last_checked': today,
                'notes': f'source=monitor | status={status}',
                'role_family': r.get('role_family', '') or r.get('llm_path_name', '') or r.get('path_name', ''),
                'source': 'monitor',
                'location_detected': '',
                'validation_status': 'watch_list' if is_watch else 'pass',
                'exclusion_reason': '',
                'llm_score': str(r.get('llm_score', '')) if r.get('llm_score') is not None else '',
                'llm_dimensions_evaluated': str(r.get('llm_dimensions_evaluated', '')) if r.get('llm_dimensions_evaluated') not in (None, '') else '',
                'llm_rationale': r.get('llm_rationale', ''),
                'llm_flags': normalize_flags(r.get('llm_flags', '')),
                'llm_hard_pass': 'false',
                'llm_hard_pass_reason': '',
                'llm_evaluated_at': now_ts if scored else '',
                'lifecycle_state': 'active' if status == 'active_role' else 'watching',
                'last_verified_at': now_ts if status == 'active_role' else '',
                'watching_run_count': '0' if status == 'active_role' else '1',
            }
            if new_row.get('role_family'):
                new_row['role_family'] = normalize_path(new_row['role_family'], _CANONICAL_PATHS)
            existing_rows.append(new_row)
            added += 1
            transitions[new_row['lifecycle_state']] = transitions.get(new_row['lifecycle_state'], 0) + 1

    # Coverage reconciliation (H3): companies exported in the checklist
    # that never came back in the results. They keep their old
    # last_checked / last_verified_at (the loop above never touched them)
    # and get flagged so the staleness is visible, not silent.
    unreached_keys = sorted(k for k in expected if k not in accounted)
    unreached_flagged = 0
    for k in unreached_keys:
        name = expected[k]
        row = find_existing(name, existing_rows)
        if row is not None:
            row['llm_flags'] = add_flag(row.get('llm_flags', ''), UNREACHED_FLAG)
            unreached_flagged += 1
        print(f"  [unreached] {name}: exported for re-verify but missing from results; "
              f"timestamps preserved, flagged {UNREACHED_FLAG}")

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
    print(f'  quarantined:      {quarantined}')
    if expected:
        print(f'  coverage: {len(accounted & set(expected))}/{len(expected)} exported companies accounted for')
        if unreached_keys:
            print(f'  WARNING: {len(unreached_keys)} unreached '
                  f'({unreached_flagged} flagged {UNREACHED_FLAG}); '
                  'their verified timestamps were NOT bumped')
    print(f'  lifecycle transitions this run:')
    print(f'    active:   {transitions.get("active", 0)}')
    print(f'    watching: {transitions.get("watching", 0)}')
    print(f'    archived: {transitions.get("archived", 0)}')
    print(f'  total in target-companies.csv: {len(final_rows)}')

    # Normalize company names and paths before writing
    for row in final_rows:
        row['company'] = normalize_company(row.get('company', ''))
        old = row.get('role_family', '').strip()
        if old:
            row['role_family'] = normalize_path(old)

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
    ap.add_argument('--stale-days', type=int, default=None,
                    help='Skip companies verified fewer than this many days ago '
                         '(default: pipeline.monitor.min_recheck_days from config.yaml, '
                         f'else {DEFAULT_MIN_RECHECK_DAYS}). Applied companies are always included.')
    args = ap.parse_args()

    if args.mode == 'export':
        return cmd_export(stale_days=args.stale_days)
    return cmd_merge(dry_run=args.dry_run)


if __name__ == '__main__':
    raise SystemExit(main())
