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
from path_normalizer import normalize_path, normalize_company
from company_dedup import find_existing, merge_into_existing

_SEARCH_CONFIG = load_search_config(DATA / 'search-config.json')
_CANONICAL_PATHS = [v['label'] for v in _SEARCH_CONFIG['query_packs'].values()] if _SEARCH_CONFIG else []


def _validate_role_family(row: Dict, canonical_paths: list[str] | None = None) -> None:
    """Flag rows whose role_family doesn't match any canonical path after normalization."""
    paths = canonical_paths if canonical_paths is not None else _CANONICAL_PATHS
    role_family = (row.get('role_family') or '').strip()
    if not role_family:
        return
    if role_family not in paths:
        flags = row.get('llm_flags', '') or ''
        if 'unknown_path' not in flags:
            row['llm_flags'] = (flags + ',unknown_path').strip(',')


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


def _parse_timestamp(ts_str: str) -> datetime | None:
    """Parse an ISO or YYYY-MM-DD timestamp string. Returns None on failure."""
    if not ts_str:
        return None
    try:
        dt = datetime.fromisoformat(ts_str) if 'T' in ts_str else datetime.strptime(ts_str, '%Y-%m-%d')
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


_RESULTS_SCHEMA = {
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
    'queries_used': 'Array of search query strings actually executed for this path',
}

VALID_WATCH_REASONS = frozenset({
    'no_careers_page',
    'no_matching_roles',
    'roles_wrong_location',
    'company_too_early',
    'domain_mismatch',
    'unable_to_verify',
})


def _validate_watch_list(result: Dict) -> Dict:
    """Validate watch_list result has proper reason and evidence.

    Mutates and returns the result dict:
    - Appends 'unvalidated_watch_list' to llm_flags if reason/evidence invalid
    - Appends 'needs_recheck' to llm_flags if reason is 'unable_to_verify'
    - Appends watch_reason and watch_evidence to notes if present
    """
    prospect_status = result.get('prospect_status', '')
    if prospect_status != 'watch_list':
        return result

    flags = result.get('llm_flags', '') or ''
    reason = (result.get('watch_reason') or '').strip()
    evidence = (result.get('watch_evidence') or '').strip()

    if not reason or reason not in VALID_WATCH_REASONS:
        print(f"  WARN: watch_list result for {result.get('company', '?')} has invalid watch_reason: '{reason}'")
        flags = (flags + ',unvalidated_watch_list').strip(',')
    elif not evidence:
        print(f"  WARN: watch_list result for {result.get('company', '?')} has empty watch_evidence")
        flags = (flags + ',unvalidated_watch_list').strip(',')
    else:
        # Valid: append reason and evidence to notes
        notes = result.get('notes', '') or ''
        notes = f"{notes} | watch_reason={reason} | watch_evidence={evidence}".strip(' |')
        result['notes'] = notes

    if reason == 'unable_to_verify':
        flags = (flags + ',needs_recheck').strip(',')

    result['llm_flags'] = flags
    return result


def cmd_export_perpath(
    data_dir: Path | None = None,
    config_path: Path | None = None,
) -> int:
    """Write one prospecting-context-{path}.json per career path for parallel agents."""
    data_dir = data_dir or DATA
    config_path = config_path or (data_dir / 'search-config.json')

    cfg = load_search_config(config_path)
    if not cfg:
        print("[web_prospecting] ERROR: could not load search config")
        return 1

    query_packs = cfg.get('query_packs', {})
    path_check_instructions = cfg.get('path_check_instructions', {})

    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(days=7)

    # Load seen companies
    seen_path = data_dir / 'seen-companies.json'
    seen: Dict = {}
    if seen_path.exists():
        with seen_path.open(encoding='utf-8') as f:
            seen = json.load(f)

    # Load existing CSV rows
    target_csv = data_dir / 'target-companies.csv'
    existing_rows = _read_csv(target_csv)

    # Build skip and recheck lists (same logic as old cmd_export)
    skip_companies: set[str] = set()
    recheck_companies: list[dict] = []

    for key, entry in seen.items():
        last_checked_str = entry.get('last_checked') or entry.get('first_seen', '')
        last_checked_dt = _parse_timestamp(last_checked_str)

        if last_checked_dt and last_checked_dt > stale_cutoff:
            skip_companies.add(key.lower())
        else:
            recheck_companies.append({
                'company': entry.get('company', key),
                'website': entry.get('website', ''),
                'last_checked': last_checked_str,
                'path': entry.get('path'),
            })

    for row in existing_rows:
        name = (row.get('company') or '').strip().lower()
        site = (row.get('website') or '').strip().lower()
        lc = row.get('last_checked', '')
        lc_dt = _parse_timestamp(lc)

        if lc_dt and lc_dt > stale_cutoff:
            if name:
                skip_companies.add(name)
            if site:
                skip_companies.add(site)

    # Build a description lookup from path_check_instructions
    # Keys in path_check_instructions are 1-indexed string numbers
    pack_keys = list(query_packs.keys())
    path_descriptions: Dict[str, str] = {}
    for i, pk in enumerate(pack_keys):
        idx_str = str(i + 1)
        path_descriptions[pk] = path_check_instructions.get(idx_str, f"Search for roles in {query_packs[pk].get('label', pk)}")

    # Build known companies per path (pass-status only, sorted by score, capped at 30)
    known_names_by_path: Dict[str, list[str]] = {}
    for pack_key, pack_val in query_packs.items():
        pack_label = pack_val.get('label', pack_key)
        path_rows = [
            row for row in existing_rows
            if row.get('validation_status') == 'pass'
            and normalize_path(row.get('role_family', ''), _CANONICAL_PATHS) == pack_label
        ]
        path_rows_sorted = sorted(path_rows, key=_sort_key, reverse=True)
        known_names_by_path[pack_key] = [
            row['company'] for row in path_rows_sorted[:30]
            if row.get('company')
        ]

    # Write one context file per path
    files_written = []
    for pack_key, pack_val in query_packs.items():
        path_label = pack_val.get('label', pack_key)
        path_desc = path_descriptions.get(pack_key, f"Search for roles in {path_label}")

        context = {
            'path_key': pack_key,
            'path_label': path_label,
            'path_description': path_desc,
            'known_companies_skip': sorted(skip_companies),
            'known_companies_recheck': [
                rc for rc in recheck_companies
                if not rc.get('path') or rc['path'] == pack_key
            ],
            'known_companies': known_names_by_path.get(pack_key, []),
            'instructions': (
                f'You are searching for companies matching the "{path_label}" career path.\n'
                f'{path_desc}\n\n'
                'Follow this 4-step research protocol:\n'
                '1. MARKET MAPPING: Find 10-15 prominent companies in this space using broad industry searches.\n'
                '2. COMPETITOR EXPANSION: For the top 5 most promising companies, search for their competitors and alternatives.\n'
                '3. FUNDING SWEEP: Search for companies in this space that received recent funding (last 12 months).\n'
                '4. CAREERS CHECK: For each candidate company, check their careers page for relevant open roles.\n\n'
                'Requirements:\n'
                '- Minimum 8 companies in your results\n'
                '- Maximum 15 web searches total\n'
                '- Skip companies in known_companies_skip\n'
                '- Re-check companies in known_companies_recheck if present\n'
                '- We already track the companies in known_companies for this path. Focus your searches on finding companies we don\'t have yet.\n\n'
                'SCORING: For each company, evaluate against references/criteria.md rubric:\n'
                '- 10 yes/no/unknown dimensions. Score = (yes / evaluated) * 100.\n'
                '- If <5 dimensions assessable, flag as "needs_research" instead of scoring.\n'
                '- Include llm_score, llm_dimensions_evaluated, llm_rationale, role_family, llm_flags, queries_used in each result.\n'
                f'Write results to data/prospecting-results-{pack_key}.json as a JSON array.'
            ),
            'results_schema': _RESULTS_SCHEMA,
        }

        out_path = data_dir / f'prospecting-context-{pack_key}.json'
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open('w', encoding='utf-8') as f:
            json.dump(context, f, indent=2, ensure_ascii=False)
        files_written.append(out_path)

    print(f"[web_prospecting] per-path export done")
    print(f"  paths: {len(files_written)}")
    print(f"  companies to skip (checked <7 days): {len(skip_companies)}")
    print(f"  companies to re-check (stale >7 days): {len(recheck_companies)}")
    for fp in files_written:
        print(f"  wrote: {fp}")
    return 0


def cmd_export() -> int:
    """Write per-path prospecting context files for Claude."""
    return cmd_export_perpath()


def _do_merge(results: List[Dict], data_dir: Path, dry_run: bool = False) -> int:
    """Core merge logic: take a list of result dicts and merge into target CSV.

    Reads target-companies.csv and seen-companies.json from data_dir,
    writes output there too.
    """
    target_csv = data_dir / 'target-companies.csv'
    seen_path = data_dir / 'seen-companies.json'

    # Load seen companies from data_dir
    seen: Dict = {}
    if seen_path.exists():
        with seen_path.open(encoding='utf-8') as f:
            seen = json.load(f)

    existing_rows = _read_csv(target_csv)
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')
    now_ts = datetime.now(timezone.utc).isoformat()

    new_rows = []
    skipped = 0
    watch_list_count = 0
    active_role_count = 0
    existing_keys = {normalize_company(row.get('company', '')).lower() for row in existing_rows}

    updated_existing = 0
    for r in results:
        company = normalize_company((r.get('company') or '').strip())
        website = (r.get('website') or '').strip().lower()
        name_key = company.lower()

        match = find_existing(company, existing_rows)
        if match:
            # Merge new data into existing row
            merge_data = {
                'open_positions': (r.get('open_positions') or '').strip(),
                'llm_score': str(r.get('llm_score', '')) if r.get('llm_score') is not None else '',
                'llm_rationale': r.get('llm_rationale', '') or r.get('fit_rationale', ''),
                'llm_flags': r.get('llm_flags', ''),
                'role_url': r.get('role_url', ''),
                'role_family': r.get('role_family', '') or r.get('llm_path_name', '') or r.get('path_name', ''),
                'website': r.get('website', ''),
                'careers_url': r.get('careers_url', ''),
                'last_checked': today,
            }
            if r.get('llm_score'):
                merge_data['llm_evaluated_at'] = now_ts
            merge_into_existing(match, merge_data)
            # Promote watch_list to pass if new active roles found
            new_roles = (r.get('open_positions') or '').strip()
            if new_roles and new_roles.lower() not in ('none', 'none — watch list', ''):
                if match.get('validation_status') == 'watch_list':
                    match['validation_status'] = 'pass'
                updated_existing += 1
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
        _validate_role_family(row)

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

    # Normalize company names and paths before writing
    for row in final_rows:
        row['company'] = normalize_company(row.get('company', ''))
        old = row.get('role_family', '').strip()
        if old:
            row['role_family'] = normalize_path(old)
        _validate_role_family(row)

    if not dry_run:
        _write_csv(target_csv, final_rows, HEADER)
        with seen_path.open('w', encoding='utf-8') as f:
            json.dump(seen, f, indent=2, ensure_ascii=False)
        # Clean up per-path and legacy single files
        for f in data_dir.glob('prospecting-results-*.json'):
            f.unlink()
        for f in data_dir.glob('prospecting-context-*.json'):
            f.unlink()
        old_results = data_dir / 'prospecting-results.json'
        old_context = data_dir / 'prospecting-context.json'
        if old_results.exists():
            old_results.unlink()
        if old_context.exists():
            old_context.unlink()
        if data_dir == DATA:
            _sync_xlsx()
        print(f"\n  Updated {target_csv.name} | seen-companies.json")
    else:
        print("\n(dry-run -- no files written)")

    return 0


def cmd_merge_multifile(data_dir: Path | None = None, dry_run: bool = False) -> int:
    """Merge multiple prospecting-results-*.json files into target CSV.

    Handles three formats:
    - New per-path: {_meta: {...}, results: [...]}
    - Old single-file array: [...]
    - Malformed files are skipped with a warning.

    Deduplicates across files: keeps higher LLM score, combines roles.
    """
    data_dir = data_dir or DATA

    result_files = sorted(data_dir.glob('prospecting-results-*.json'))
    if not result_files:
        print(f"[web_prospecting] no prospecting-results-*.json files found in {data_dir}")
        return 1

    all_results: List[Dict] = []
    for fp in result_files:
        try:
            with fp.open(encoding='utf-8') as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  WARN: skipping malformed file {fp.name}: {e}")
            continue

        if isinstance(raw, list):
            # Old format: plain array
            entries = raw
        elif isinstance(raw, dict) and 'results' in raw:
            # New per-path format with _meta wrapper
            meta = raw.get('_meta', {})
            print(f"  loading {fp.name} (path_key={meta.get('path_key', '?')})")
            entries = raw['results']
        else:
            print(f"  WARN: unexpected format in {fp.name}, skipping")
            continue

        for entry in entries:
            all_results.append(_validate_watch_list(entry))

    if not all_results:
        print("[web_prospecting] no valid results found across files")
        return 1

    # Deduplicate across files: keep higher score, combine roles
    deduped: Dict[str, Dict] = {}
    for r in all_results:
        company = normalize_company((r.get('company') or '').strip())
        key = company.lower()
        if not key:
            continue

        if key in deduped:
            existing = deduped[key]
            # Use merge_into_existing logic to combine
            try:
                old_score = float(existing.get('llm_score', '') or 0)
            except (ValueError, TypeError):
                old_score = 0
            try:
                new_score = float(r.get('llm_score', '') or 0)
            except (ValueError, TypeError):
                new_score = 0

            # Combine open_positions
            old_roles = existing.get('open_positions', '')
            new_roles = (r.get('open_positions') or '').strip()
            if new_roles and new_roles.lower() not in (old_roles or '').lower():
                existing['open_positions'] = (old_roles + '; ' + new_roles).strip('; ')

            # Keep higher score entry's fields
            if new_score > old_score:
                for field in ('llm_score', 'llm_rationale', 'llm_flags',
                              'role_family', 'path_name', 'website',
                              'careers_url', 'prospect_status',
                              'industry', 'size', 'stage', 'recent_funding',
                              'tech_signals', 'fit_rationale',
                              'watch_reason', 'watch_evidence'):
                    if r.get(field):
                        existing[field] = r[field]
        else:
            deduped[key] = dict(r)  # copy to avoid mutation
            deduped[key]['company'] = company  # normalized

    print(f"[web_prospecting] loaded {len(all_results)} results from {len(result_files)} files, {len(deduped)} unique companies")

    return _do_merge(list(deduped.values()), data_dir, dry_run)


def cmd_merge(dry_run: bool = False) -> int:
    """Merge Claude's prospecting results into target-companies.csv.

    Checks for per-path files first (prospecting-results-*.json),
    then falls back to legacy single file (prospecting-results.json).

    Uses module-level globals (TARGET_CSV, PROSPECTING_RESULTS, etc.)
    so tests can monkeypatch them.
    """
    data_dir = TARGET_CSV.parent

    # Try per-path files first
    per_path_files = list(data_dir.glob('prospecting-results-*.json'))
    if per_path_files:
        return cmd_merge_multifile(data_dir=data_dir, dry_run=dry_run)

    # Fall back to legacy single file
    if not PROSPECTING_RESULTS.exists():
        print(f"ERROR: no prospecting-results files found. Claude must write them first.")
        return 1

    with PROSPECTING_RESULTS.open(encoding='utf-8') as f:
        results: List[Dict] = json.load(f)

    # Validate path coverage
    paths_found = {r.get('path_name', '').strip().lower() for r in results if r.get('path_name')}
    expected_path_count = len(_SEARCH_CONFIG.get('query_packs', {})) if _SEARCH_CONFIG else 0
    if expected_path_count and len(paths_found) < expected_path_count:
        print(f"  WARN: only {len(paths_found)}/{expected_path_count} paths covered in prospecting results")

    return _do_merge(results, data_dir, dry_run)


def _load_expansion_history(data_dir: Path) -> Dict:
    history_path = data_dir / 'expansion-history.json'
    if history_path.exists():
        with history_path.open(encoding='utf-8') as f:
            return json.load(f)
    return {}


def _save_expansion_history(data_dir: Path, history: Dict) -> None:
    history_path = data_dir / 'expansion-history.json'
    with history_path.open('w', encoding='utf-8') as f:
        json.dump(history, f, indent=2, ensure_ascii=False)


def cmd_export_expansion(
    data_dir: Path | None = None,
    config_path: Path | None = None,
) -> int:
    """Export expansion context files for pass 2, seeded from pass 1 results.

    For each career path with >= 3 pass 1 results, writes a
    prospecting-context-{path_key}-expansion.json with a 3-step protocol
    (competitor mining, investor portfolio mining, community/list mining).
    """
    data_dir = data_dir or DATA
    config_path = config_path or (data_dir / 'search-config.json')

    cfg = load_search_config(config_path)
    if not cfg:
        print("[web_prospecting] ERROR: could not load search config")
        return 1

    query_packs = cfg.get('query_packs', {})

    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(days=7)

    # Load seen companies
    seen_path = data_dir / 'seen-companies.json'
    seen: Dict = {}
    if seen_path.exists():
        with seen_path.open(encoding='utf-8') as f:
            seen = json.load(f)

    # Load existing CSV rows
    target_csv = data_dir / 'target-companies.csv'
    existing_rows = _read_csv(target_csv)

    # Build base skip list (same logic as cmd_export_perpath)
    base_skip: set[str] = set()

    for key, entry in seen.items():
        last_checked_str = entry.get('last_checked') or entry.get('first_seen', '')
        last_checked_dt = _parse_timestamp(last_checked_str)
        if last_checked_dt and last_checked_dt > stale_cutoff:
            base_skip.add(key.lower())

    for row in existing_rows:
        name = (row.get('company') or '').strip().lower()
        site = (row.get('website') or '').strip().lower()
        lc = row.get('last_checked', '')
        lc_dt = _parse_timestamp(lc)
        if lc_dt and lc_dt > stale_cutoff:
            if name:
                base_skip.add(name)
            if site:
                base_skip.add(site)

    expansion_history = _load_expansion_history(data_dir)

    files_written = []
    for pack_key, pack_val in query_packs.items():
        path_label = pack_val.get('label', pack_key)

        # Read pass 1 results for this path
        pass1_file = data_dir / f'prospecting-results-{pack_key}.json'
        if not pass1_file.exists():
            print(f"  WARN: no pass 1 results for {pack_key}, skipping expansion")
            continue

        try:
            with pass1_file.open(encoding='utf-8') as f:
                raw = json.load(f)
        except (json.JSONDecodeError, OSError) as e:
            print(f"  WARN: could not read {pass1_file.name}: {e}")
            continue

        pass1_results = raw.get('results', []) if isinstance(raw, dict) else raw

        # Build combined candidate pool: pass1 results + CSV pass companies for this path
        def _score(r):
            try:
                return float(r.get('llm_score', 0) or 0)
            except (ValueError, TypeError):
                return 0.0

        seen_norm: set[str] = set()
        all_candidates: list[Dict] = []

        for r in pass1_results:
            cname = normalize_company((r.get('company') or '').strip())
            norm_key = cname.lower()
            if norm_key and norm_key not in seen_norm:
                seen_norm.add(norm_key)
                all_candidates.append({
                    'company': r.get('company', ''),
                    'website': r.get('website', ''),
                    'llm_score': r.get('llm_score', 0),
                    'recent_funding': r.get('recent_funding', ''),
                })

        for row in existing_rows:
            if row.get('validation_status') != 'pass':
                continue
            row_path = normalize_path(row.get('role_family', ''), _CANONICAL_PATHS)
            if row_path != path_label:
                continue
            cname = normalize_company((row.get('company') or '').strip())
            norm_key = cname.lower()
            if norm_key and norm_key not in seen_norm:
                seen_norm.add(norm_key)
                all_candidates.append({
                    'company': row.get('company', ''),
                    'website': row.get('website', ''),
                    'llm_score': 0,
                    'recent_funding': '',
                })

        if len(all_candidates) < 3:
            print(f"  WARN: only {len(all_candidates)} total candidates for {pack_key}, need >= 3 for expansion")
            continue

        # Seed rotation: never-seeded first (score desc), then previously-seeded (seed_count asc, last_seeded asc)
        never_seeded = []
        prev_seeded = []
        for candidate in all_candidates:
            hist_key = normalize_company(candidate['company']).lower()
            if hist_key in expansion_history:
                prev_seeded.append(candidate)
            else:
                never_seeded.append(candidate)

        never_seeded.sort(key=_score, reverse=True)
        prev_seeded.sort(key=lambda r: (
            expansion_history[normalize_company(r['company']).lower()].get('seed_count', 0),
            expansion_history[normalize_company(r['company']).lower()].get('last_seeded', ''),
        ))

        ordered = never_seeded + prev_seeded
        seed_companies = ordered[:5]

        # Update expansion history for each selected seed
        seeded_at = now.isoformat()
        for seed in seed_companies:
            hist_key = normalize_company(seed['company']).lower()
            if hist_key in expansion_history:
                expansion_history[hist_key]['seed_count'] = expansion_history[hist_key].get('seed_count', 0) + 1
                expansion_history[hist_key]['last_seeded'] = seeded_at
            else:
                expansion_history[hist_key] = {
                    'company': seed['company'],
                    'path': pack_key,
                    'last_seeded': seeded_at,
                    'seed_count': 1,
                }

        # Build skip list: base + all candidate company names/websites
        skip = set(base_skip)
        for r in pass1_results:
            cname = normalize_company((r.get('company') or '').strip()).lower()
            csite = (r.get('website') or '').strip().lower()
            if cname:
                skip.add(cname)
            if csite:
                skip.add(csite)

        seed_names = ', '.join(s['company'] for s in seed_companies)

        instructions = (
            f'EXPANSION PASS for "{path_label}" career path.\n'
            f'Seed companies from pass 1: {seed_names}\n\n'
            'Follow this 3-step expansion protocol:\n\n'
            '1. COMPETITOR MINING: For each seed company, search "[company] competitors" '
            'and "[company] alternatives". Find 3-5 new companies per seed.\n\n'
            '2. INVESTOR PORTFOLIO MINING: For seeds with known funding, search '
            '"[investor name] portfolio companies" to find similar-stage companies '
            'in the same space.\n\n'
            '3. COMMUNITY/LIST MINING: Search for curated lists, directories, and '
            'communities in this space (e.g., "top [industry] startups 2026", '
            '"[industry] company directory").\n\n'
            'Requirements:\n'
            '- Skip companies in known_companies_skip\n'
            '- Minimum 5 new companies in results\n'
            '- Maximum 15 web searches total\n'
            '- Check careers page for each candidate company\n\n'
            'SCORING: Same rubric as pass 1. Evaluate against references/criteria.md.\n'
            f'Write results to data/prospecting-results-{pack_key}-expansion.json'
        )

        context = {
            'path_key': pack_key,
            'path_label': path_label,
            'pass': 'expansion',
            'seed_companies': seed_companies,
            'known_companies_skip': sorted(skip),
            'instructions': instructions,
            'results_schema': _RESULTS_SCHEMA,
        }

        out_path = data_dir / f'prospecting-context-{pack_key}-expansion.json'
        out_path.parent.mkdir(parents=True, exist_ok=True)
        with out_path.open('w', encoding='utf-8') as f:
            json.dump(context, f, indent=2, ensure_ascii=False)
        files_written.append(out_path)

    _save_expansion_history(data_dir, expansion_history)

    print(f"[web_prospecting] expansion export done")
    print(f"  expansion files written: {len(files_written)}")
    for fp in files_written:
        print(f"  wrote: {fp}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument('mode', choices=['export', 'export-expansion', 'merge'])
    ap.add_argument('--dry-run', action='store_true')
    args = ap.parse_args()

    if args.mode == 'export':
        return cmd_export()
    if args.mode == 'export-expansion':
        return cmd_export_expansion()
    return cmd_merge(dry_run=args.dry_run)


if __name__ == '__main__':
    raise SystemExit(main())
