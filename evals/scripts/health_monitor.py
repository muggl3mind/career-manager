#!/usr/bin/env python3
"""
Level 3 Eval: Ongoing health monitoring for the job-search pipeline.

Checks freshness, coverage, cache sizes, cross-file consistency, and
score distribution. Run after every pipeline run or 2-3x per week.

Usage:
  python3 scripts/health_monitor.py
  python3 scripts/health_monitor.py --json
"""

from __future__ import annotations

import csv
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parents[1]
CAREER_MGR = EVALS_DIR.parent
JOB_SEARCH = CAREER_MGR / 'job-search'
DATA = JOB_SEARCH / 'data'
TARGET_CSV = DATA / 'target-companies.csv'
APPLICATIONS_CSV = CAREER_MGR / 'job-tracker' / 'data' / 'applications.csv'
SEEN_COMPANIES = DATA / 'seen-companies.json'
SEEN_JOBS = DATA / 'seen-jobs.json'

SCORE_HISTORY = EVALS_DIR / 'data' / 'score-history.jsonl'
DRIFT_THRESHOLD = 10  # flag if avg score shifts more than this between runs

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


def check_freshness(seen: dict) -> list[dict]:
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
        'detail': f'fresh: {fresh}, stale (>{STALE_DAYS}d): {len(stale)}, '
                  f'critical (>{CRITICAL_STALE_DAYS}d): {len(critical)}, '
                  f'never checked: {len(never_checked)}',
    })
    if critical:
        checks.append({
            'check': 'freshness_critical',
            'status': 'warn',
            'detail': ', '.join(critical[:8]) + (f' (+{len(critical)-8} more)' if len(critical) > 8 else ''),
        })
    return checks


def check_applications(target_rows: list[dict], app_rows: list[dict]) -> list[dict]:
    checks = []
    app_companies = {(r.get('company') or '').strip().lower() for r in app_rows}
    pass_rows = [r for r in target_rows if r.get('validation_status') == 'pass']
    not_applied = [r for r in pass_rows if (r.get('company') or '').strip().lower() not in app_companies]

    checks.append({
        'check': 'application_coverage',
        'status': 'info',
        'detail': f'{len(pass_rows)} actionable targets, {len(app_rows)} applications, '
                  f'{len(not_applied)} not yet applied',
    })
    return checks


def check_score_distribution(target_rows: list[dict]) -> list[dict]:
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
        'detail': f'{len(scores)} scored — min: {min_s:.0f}, max: {max_s:.0f}, '
                  f'avg: {avg:.0f}, spread: {spread:.0f}',
    })
    return checks


def check_score_drift(target_rows: list[dict]) -> list[dict]:
    """Compare current score distribution to previous run, flag drift."""
    checks = []
    scores = []
    for r in target_rows:
        try:
            scores.append(float(r.get('llm_score', '')))
        except (ValueError, TypeError):
            continue

    if not scores:
        return checks

    current = {
        'timestamp': datetime.now(timezone.utc).isoformat(),
        'count': len(scores),
        'avg': round(sum(scores) / len(scores), 1),
        'min': min(scores),
        'max': max(scores),
        'median': sorted(scores)[len(scores) // 2],
    }

    # Load previous entry for comparison
    prev = None
    if SCORE_HISTORY.exists():
        lines = SCORE_HISTORY.read_text().strip().splitlines()
        if lines:
            try:
                prev = json.loads(lines[-1])
            except json.JSONDecodeError:
                pass

    # Append current snapshot
    SCORE_HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with SCORE_HISTORY.open('a', encoding='utf-8') as f:
        f.write(json.dumps(current) + '\n')

    if prev:
        drift = abs(current['avg'] - prev['avg'])
        count_delta = current['count'] - prev['count']
        status = 'warn' if drift > DRIFT_THRESHOLD else 'pass'
        checks.append({
            'check': 'score_drift',
            'status': status,
            'detail': f"avg {prev['avg']} -> {current['avg']} (delta: {drift:.1f}), "
                      f"count {prev['count']} -> {current['count']} ({count_delta:+d})",
        })
    else:
        checks.append({
            'check': 'score_drift',
            'status': 'info',
            'detail': f"First run recorded — avg: {current['avg']}, count: {current['count']}. "
                      f"Drift comparison starts next run.",
        })

    return checks


def check_cross_file_consistency(target_rows: list[dict], seen: dict) -> list[dict]:
    checks = []
    target_companies = {(r.get('company') or '').strip().lower()
                        for r in target_rows if r.get('company')}
    seen_companies = set(seen.keys())

    in_target_not_seen = target_companies - seen_companies

    status = 'pass' if len(in_target_not_seen) < 5 else 'warn'
    checks.append({
        'check': 'cross_file_sync',
        'status': status,
        'detail': f'{len(in_target_not_seen)} companies in target CSV but not in seen-companies.json',
    })
    return checks


def check_cache_size(seen: dict, seen_jobs: dict | list) -> list[dict]:
    checks = []
    jobs_count = len(seen_jobs) if isinstance(seen_jobs, dict) else 0

    checks.append({
        'check': 'cache_size',
        'status': 'pass' if len(seen) < 500 and jobs_count < 1000 else 'warn',
        'detail': f'seen-companies: {len(seen)} entries, seen-jobs: {jobs_count} entries',
    })
    return checks


def run_health_check(as_json: bool = False) -> int:
    target_rows = _read_csv(TARGET_CSV)
    app_rows = _read_csv(APPLICATIONS_CSV)
    seen = _load_json(SEEN_COMPANIES)
    seen_jobs = _load_json(SEEN_JOBS)

    all_checks = []
    all_checks.extend(check_files_exist())
    all_checks.extend(check_target_counts(target_rows))
    all_checks.extend(check_freshness(seen))
    all_checks.extend(check_applications(target_rows, app_rows))
    all_checks.extend(check_score_distribution(target_rows))
    all_checks.extend(check_score_drift(target_rows))
    all_checks.extend(check_cross_file_consistency(target_rows, seen))
    all_checks.extend(check_cache_size(seen, seen_jobs))

    if as_json:
        print(json.dumps({
            'eval': 'health_monitor',
            'level': 3,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'checks': all_checks,
        }, indent=2))
    else:
        icons = {'pass': '\u2705', 'warn': '\u26a0\ufe0f ', 'fail': '\u274c', 'info': '\u2139\ufe0f '}
        print(f"\n{'='*60}")
        print(f"  HEALTH MONITOR — Pipeline Health")
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

    return 1 if any(c['status'] == 'fail' for c in all_checks) else 0


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description='Level 3: Health monitoring')
    ap.add_argument('--json', action='store_true', help='Output as JSON')
    args = ap.parse_args()
    return run_health_check(as_json=args.json)


if __name__ == '__main__':
    raise SystemExit(main())
