#!/usr/bin/env python3
"""
Level 2 Eval: Runtime verification of pipeline outputs.

Run after a pipeline run completes. Validates that outputs are complete,
consistent, and correct — without re-running the pipeline.

Usage:
  python3 scripts/runtime_verify.py
  python3 scripts/runtime_verify.py --json
"""

from __future__ import annotations

import csv
import json
from datetime import datetime, timezone
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parents[1]
CAREER_MGR = EVALS_DIR.parent
JOB_SEARCH = CAREER_MGR / 'job-search'
DATA = JOB_SEARCH / 'data'
TARGET_CSV = DATA / 'target-companies.csv'
OPPORTUNITIES_CSV = DATA / 'opportunities.csv'
ACTION_CSV = DATA / 'action-list.csv'
SEEN_COMPANIES = DATA / 'seen-companies.json'
SEEN_JOBS = DATA / 'seen-jobs.json'
APPLICATIONS_CSV = CAREER_MGR / 'job-tracker' / 'data' / 'applications.csv'


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


def check_output_files_exist() -> list[dict]:
    """Verify expected output files exist after a pipeline run."""
    checks = []
    for path, label, required in [
        (TARGET_CSV, 'target-companies.csv', True),
        (OPPORTUNITIES_CSV, 'opportunities.csv', True),
        (ACTION_CSV, 'action-list.csv', True),
        (SEEN_COMPANIES, 'seen-companies.json', True),
        (SEEN_JOBS, 'seen-jobs.json', False),
    ]:
        exists = path.exists()
        if required:
            status = 'pass' if exists else 'fail'
        else:
            status = 'pass' if exists else 'warn'
        checks.append({
            'check': f'output_exists:{label}',
            'status': status,
            'detail': f'{"exists" if exists else "MISSING"} — {path}',
        })
    return checks


def check_completeness(target_rows: list[dict]) -> list[dict]:
    """Verify no rows were silently dropped."""
    checks = []
    total = len(target_rows)
    empty_company = sum(1 for r in target_rows if not (r.get('company') or '').strip())
    empty_status = sum(1 for r in target_rows if not (r.get('validation_status') or '').strip())

    checks.append({
        'check': 'row_count',
        'status': 'pass' if total > 0 else 'fail',
        'detail': f'{total} rows in target-companies.csv',
    })
    if empty_company:
        checks.append({
            'check': 'empty_company_names',
            'status': 'fail',
            'detail': f'{empty_company} rows have empty company name',
        })
    if empty_status:
        checks.append({
            'check': 'empty_validation_status',
            'status': 'warn',
            'detail': f'{empty_status} rows have empty validation_status',
        })
    return checks


def check_action_list_matches_opportunities(opportunity_rows: list[dict], action_rows: list[dict]) -> list[dict]:
    """Action list rows should come from open opportunity rows, not raw company rows."""
    checks = []
    open_pairs = {
        ((r.get('company') or '').strip().lower(), (r.get('role_title') or '').strip().lower())
        for r in opportunity_rows
        if (r.get('opportunity_status') or '').strip() == 'open'
    }
    action_pairs = set()
    for row in action_rows:
        company = (row.get('company') or '').strip().lower()
        roles = [
            part.strip().lower()
            for part in (row.get('role') or '').split(';')
            if part.strip()
        ]
        if not roles:
            action_pairs.add((company, ''))
            continue
        for role in roles:
            action_pairs.add((company, role))
    in_action_not_opportunity = action_pairs - open_pairs

    if in_action_not_opportunity:
        checks.append({
            'check': 'action_list_extra',
            'status': 'warn',
            'detail': f'{len(in_action_not_opportunity)} action rows do not match open opportunities',
        })
    else:
        checks.append({
            'check': 'action_list_sync',
            'status': 'pass',
            'detail': f'Action list rows all match open opportunities ({len(action_rows)} rows)',
        })
    return checks


def check_score_integrity(target_rows: list[dict]) -> list[dict]:
    """Verify LLM scores are valid numbers in range."""
    checks = []
    pass_rows = [r for r in target_rows if r.get('validation_status') == 'pass']
    scored = 0
    out_of_range = 0
    for r in pass_rows:
        raw = (r.get('llm_score') or '').strip()
        if not raw:
            continue
        try:
            score = float(raw)
            scored += 1
            if score < 0 or score > 100:
                out_of_range += 1
        except ValueError:
            out_of_range += 1

    checks.append({
        'check': 'score_integrity',
        'status': 'pass' if out_of_range == 0 else 'fail',
        'detail': f'{scored}/{len(pass_rows)} pass-status targets scored, {out_of_range} out of range or invalid',
    })
    return checks


def check_no_working_files() -> list[dict]:
    """After phase 2, intermediate working files should be cleaned up."""
    checks = []
    working_files = [
        ('monitor-context.json', 'phase 1 monitor export'),
        ('pending-eval.json', 'phase 1 eval export'),
        ('prospecting-context.json', 'phase 1 prospecting export'),
        ('monitor-results.json', 'agent monitor results'),
        ('eval-results.json', 'agent eval results'),
        ('prospecting-results.json', 'agent prospecting results'),
        ('pipeline-phase1-summary.json', 'phase 1 summary'),
    ]
    leftover = []
    for fname, desc in working_files:
        if (DATA / fname).exists():
            leftover.append(f'{fname} ({desc})')

    if leftover:
        checks.append({
            'check': 'working_files_cleanup',
            'status': 'info',
            'detail': f'{len(leftover)} working files still present: ' + ', '.join(leftover[:4]),
        })
    else:
        checks.append({
            'check': 'working_files_cleanup',
            'status': 'pass',
            'detail': 'All intermediate working files cleaned up',
        })
    return checks


def check_duplicate_companies(target_rows: list[dict]) -> list[dict]:
    """Check for unintentional duplicate company entries."""
    checks = []
    seen = {}
    dupes = []
    for r in target_rows:
        name = (r.get('company') or '').strip().lower()
        if not name:
            continue
        if name in seen:
            dupes.append(name)
        else:
            seen[name] = 0
        seen[name] += 1

    dupe_set = set(dupes)
    if dupe_set:
        examples = sorted(dupe_set)[:5]
        checks.append({
            'check': 'duplicate_companies',
            'status': 'warn',
            'detail': f'{len(dupe_set)} companies appear multiple times: ' + ', '.join(examples),
        })
    else:
        checks.append({
            'check': 'duplicate_companies',
            'status': 'pass',
            'detail': f'{len(seen)} unique companies, no duplicates',
        })
    return checks


def run_runtime_verify(as_json: bool = False) -> int:
    target_rows = _read_csv(TARGET_CSV)
    opportunity_rows = _read_csv(OPPORTUNITIES_CSV)
    action_rows = _read_csv(ACTION_CSV)

    all_checks = []
    all_checks.extend(check_output_files_exist())
    all_checks.extend(check_completeness(target_rows))
    all_checks.extend(check_action_list_matches_opportunities(opportunity_rows, action_rows))
    all_checks.extend(check_score_integrity(target_rows))
    all_checks.extend(check_no_working_files())
    all_checks.extend(check_duplicate_companies(target_rows))

    if as_json:
        print(json.dumps({
            'eval': 'runtime_verify',
            'level': 2,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'checks': all_checks,
        }, indent=2))
    else:
        icons = {'pass': '\u2705', 'warn': '\u26a0\ufe0f ', 'fail': '\u274c', 'info': '\u2139\ufe0f '}
        print(f"\n{'='*60}")
        print(f"  RUNTIME VERIFICATION — Pipeline Outputs")
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
            print(f"  STATUS: ISSUES FOUND")
        elif warns:
            print(f"  STATUS: REVIEW WARNINGS")
        else:
            print(f"  STATUS: CLEAN")
        print(f"{'='*60}\n")

    return 1 if any(c['status'] == 'fail' for c in all_checks) else 0


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description='Level 2: Runtime verification')
    ap.add_argument('--json', action='store_true', help='Output as JSON')
    args = ap.parse_args()
    return run_runtime_verify(as_json=args.json)


if __name__ == '__main__':
    raise SystemExit(main())
