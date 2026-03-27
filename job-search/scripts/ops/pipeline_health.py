#!/usr/bin/env python3
"""
Pipeline health check — independent evaluation of pipeline output.

Reads output files fresh and validates completeness, coverage, freshness,
and consistency. Returns non-zero exit code if critical checks fail.

Usage:
  python3 scripts/ops/pipeline_health.py           # full health report
  python3 scripts/ops/pipeline_health.py --json     # machine-readable output
"""

from __future__ import annotations

import argparse
import csv
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
DATA = BASE / 'data'
TARGET_CSV = DATA / 'target-companies.csv'
APPLICATIONS_CSV = BASE.parent / 'job-tracker' / 'data' / 'applications.csv'
SEEN_COMPANIES = DATA / 'seen-companies.json'
SEEN_JOBS = DATA / 'seen-jobs.json'

STALE_DAYS = 7
CRITICAL_STALE_DAYS = 14


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding='utf-8') as f:
        return list(csv.DictReader(f))


def _load_json(path: Path) -> dict | list:
    if not path.exists():
        return {}
    with path.open(encoding='utf-8') as f:
        return json.load(f)


def _parse_date(s: str) -> datetime | None:
    if not s:
        return None
    for fmt in ('%Y-%m-%dT%H:%M:%S.%f%z', '%Y-%m-%dT%H:%M:%S%z', '%Y-%m-%d'):
        try:
            dt = datetime.strptime(s, fmt)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            return dt
        except ValueError:
            continue
    try:
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt
    except (ValueError, TypeError):
        return None


def check_files_exist() -> list[dict]:
    """Check that required data files exist."""
    checks = []
    for path, label in [
        (TARGET_CSV, 'target-companies.csv'),
        (APPLICATIONS_CSV, 'applications.csv'),
        (SEEN_COMPANIES, 'seen-companies.json'),
    ]:
        exists = path.exists()
        checks.append({
            'check': f'file_exists:{label}',
            'status': 'pass' if exists else 'fail',
            'detail': str(path),
        })
    return checks


def check_target_counts(rows: list[dict]) -> list[dict]:
    """Check target-companies.csv has reasonable content."""
    checks = []
    total = len(rows)
    pass_count = sum(1 for r in rows if r.get('validation_status') == 'pass')
    watch_count = sum(1 for r in rows if r.get('validation_status') == 'watch_list')
    scored = sum(1 for r in rows if r.get('llm_score') not in (None, ''))

    checks.append({
        'check': 'target_total',
        'status': 'pass' if total > 0 else 'fail',
        'detail': f'{total} total ({pass_count} pass, {watch_count} watch_list)',
    })
    checks.append({
        'check': 'targets_scored',
        'status': 'pass' if scored >= pass_count * 0.5 else 'warn',
        'detail': f'{scored}/{pass_count} pass-status targets have LLM scores',
    })
    return checks


def check_freshness(seen: dict, target_rows: list[dict]) -> list[dict]:
    """Check for stale data — companies not checked recently."""
    checks = []
    now = datetime.now(timezone.utc)
    stale_cutoff = now - timedelta(days=STALE_DAYS)
    critical_cutoff = now - timedelta(days=CRITICAL_STALE_DAYS)

    stale = []
    critical = []
    never_checked = []

    for key, entry in seen.items():
        last_str = entry.get('last_checked') or entry.get('first_seen', '')
        last_dt = _parse_date(last_str)
        name = entry.get('company', key)

        if last_dt is None:
            never_checked.append(name)
        elif last_dt < critical_cutoff:
            critical.append(name)
        elif last_dt < stale_cutoff:
            stale.append(name)

    total_seen = len(seen)
    fresh = total_seen - len(stale) - len(critical) - len(never_checked)

    checks.append({
        'check': 'freshness_summary',
        'status': 'pass' if not critical else ('warn' if len(critical) < 10 else 'fail'),
        'detail': f'fresh: {fresh}, stale (>{STALE_DAYS}d): {len(stale)}, critical (>{CRITICAL_STALE_DAYS}d): {len(critical)}, never checked: {len(never_checked)}',
    })
    if critical:
        checks.append({
            'check': 'freshness_critical',
            'status': 'warn',
            'detail': ', '.join(critical[:8]) + (f' (+{len(critical)-8} more)' if len(critical) > 8 else ''),
        })
    return checks


def check_applications(target_rows: list[dict], app_rows: list[dict]) -> list[dict]:
    """Check applied vs actionable ratio."""
    checks = []
    app_companies = {(r.get('company') or '').strip().lower() for r in app_rows}
    pass_rows = [r for r in target_rows if r.get('validation_status') == 'pass']
    not_applied = [r for r in pass_rows if (r.get('company') or '').strip().lower() not in app_companies]

    checks.append({
        'check': 'application_coverage',
        'status': 'info',
        'detail': f'{len(pass_rows)} actionable targets, {len(app_rows)} applications, {len(not_applied)} not yet applied',
    })
    return checks


def check_score_distribution(target_rows: list[dict]) -> list[dict]:
    """Check for suspicious score clustering."""
    checks = []
    scores = []
    for r in target_rows:
        try:
            s = float(r.get('llm_score', ''))
            scores.append(s)
        except (ValueError, TypeError):
            continue

    if not scores:
        checks.append({
            'check': 'score_distribution',
            'status': 'warn',
            'detail': 'No LLM scores found',
        })
        return checks

    avg = sum(scores) / len(scores)
    min_s = min(scores)
    max_s = max(scores)
    spread = max_s - min_s

    status = 'pass' if spread > 20 else 'warn'
    checks.append({
        'check': 'score_distribution',
        'status': status,
        'detail': f'{len(scores)} scored — min: {min_s:.0f}, max: {max_s:.0f}, avg: {avg:.0f}, spread: {spread:.0f}',
    })
    return checks


def check_cross_file_consistency(target_rows: list[dict], seen: dict) -> list[dict]:
    """Check that target-companies.csv and seen-companies.json are in sync."""
    checks = []
    target_companies = {(r.get('company') or '').strip().lower() for r in target_rows if r.get('company')}
    seen_companies = set(seen.keys())

    in_target_not_seen = target_companies - seen_companies
    # Seen but not in target is expected (watch_list entries may not be in CSV)

    status = 'pass' if len(in_target_not_seen) < 5 else 'warn'
    checks.append({
        'check': 'cross_file_sync',
        'status': status,
        'detail': f'{len(in_target_not_seen)} companies in target CSV but not in seen-companies.json',
    })
    return checks


def check_cache_size(seen: dict, seen_jobs: dict | list) -> list[dict]:
    """Check for cache bloat."""
    checks = []
    jobs_count = len(seen_jobs) if isinstance(seen_jobs, dict) else 0

    checks.append({
        'check': 'cache_size',
        'status': 'pass' if len(seen) < 500 and jobs_count < 1000 else 'warn',
        'detail': f'seen-companies: {len(seen)} entries, seen-jobs: {jobs_count} entries',
    })
    return checks


def run_health_check(as_json: bool = False) -> int:
    """Run all health checks, print report, return exit code."""
    target_rows = _read_csv(TARGET_CSV)
    app_rows = _read_csv(APPLICATIONS_CSV)
    seen = _load_json(SEEN_COMPANIES)
    seen_jobs = _load_json(SEEN_JOBS)

    all_checks = []
    all_checks.extend(check_files_exist())
    all_checks.extend(check_target_counts(target_rows))
    all_checks.extend(check_freshness(seen, target_rows))
    all_checks.extend(check_applications(target_rows, app_rows))
    all_checks.extend(check_score_distribution(target_rows))
    all_checks.extend(check_cross_file_consistency(target_rows, seen))
    all_checks.extend(check_cache_size(seen, seen_jobs))

    if as_json:
        print(json.dumps({
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'checks': all_checks,
        }, indent=2))
    else:
        icons = {'pass': '\u2705', 'warn': '\u26a0\ufe0f ', 'fail': '\u274c', 'info': '\u2139\ufe0f '}
        print(f"\n{'='*60}")
        print(f"  PIPELINE HEALTH CHECK")
        print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"{'='*60}\n")

        for c in all_checks:
            icon = icons.get(c['status'], '  ')
            print(f"  {icon} {c['check']}: {c['detail']}")

        fails = sum(1 for c in all_checks if c['status'] == 'fail')
        warns = sum(1 for c in all_checks if c['status'] == 'warn')
        passes = sum(1 for c in all_checks if c['status'] == 'pass')

        print(f"\n{'='*60}")
        print(f"  {passes} pass, {warns} warn, {fails} fail")
        if fails:
            print(f"  STATUS: UNHEALTHY")
        elif warns:
            print(f"  STATUS: DEGRADED")
        else:
            print(f"  STATUS: HEALTHY")
        print(f"{'='*60}\n")

    has_failures = any(c['status'] == 'fail' for c in all_checks)
    return 1 if has_failures else 0


def main() -> int:
    ap = argparse.ArgumentParser(description='Pipeline health check')
    ap.add_argument('--json', action='store_true', help='Output as JSON')
    args = ap.parse_args()
    return run_health_check(as_json=args.json)


if __name__ == '__main__':
    raise SystemExit(main())
