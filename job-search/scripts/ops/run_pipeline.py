#!/usr/bin/env python3
"""
Job search pipeline orchestrator.

Runs all deterministic Python steps in sequence, pausing for Claude
to do the agent work (research + evaluation) in between.

Modes:
  phase1   — Run all exports + JobSpy discovery (Python-only steps)
  phase2   — Run all merges after Claude finishes research + evaluation
  phase3   — Action list generation

Usage:
  uv run scripts/ops/run_pipeline.py phase1                # exports + discovery
  uv run scripts/ops/run_pipeline.py phase1 --skip-jobspy  # exports only (faster)
  uv run scripts/ops/run_pipeline.py phase2                # all merges
  uv run scripts/ops/run_pipeline.py phase2 --dry-run      # preview merges
  uv run scripts/ops/run_pipeline.py phase3                # health check + action list

Full pipeline flow:
  1. User says "run job search"
  2. Claude runs: uv run scripts/ops/run_pipeline.py phase1
  3. Claude does agent work: read context files, check careers pages,
     evaluate jobs, write result files
  4. Claude runs: uv run scripts/ops/run_pipeline.py phase2
  5. Claude runs: uv run scripts/ops/run_pipeline.py phase3
"""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
DATA = BASE / 'data'
SCRIPTS = BASE / 'scripts' / 'ops'
RUN_LOG = DATA / 'run-log.jsonl'


def run_script(script: str, args: list[str] | None = None) -> int:
    """Run a Python script using the same Python that's running this script."""
    path = SCRIPTS / script
    if not path.exists():
        print(f"  ERROR: {path} not found")
        return 1

    cmd = [sys.executable, str(path)] + (args or [])

    print(f"\n{'='*60}")
    print(f"  Running: {script} {' '.join(args or [])}")
    print(f"{'='*60}")

    result = subprocess.run(cmd, cwd=str(BASE))
    return result.returncode


def phase1(skip_jobspy: bool = False, limit: int = 35) -> dict:
    """
    Phase 1: All Python-only steps before Claude does research.

    1. Monitor export (identifies stale companies)
    2. JobSpy discovery (scrapes job boards, exports pending-eval.json)
    3. Web prospecting export (prepares context for Claude)

    Returns summary dict of what Claude needs to do next.
    """
    print("\n" + "=" * 60)
    print("  PHASE 1: Python exports + discovery")
    print("=" * 60)

    results = {
        'monitor_export': None,
        'discovery': None,
        'prospecting_export': None,
        'files_for_claude': [],
        'errors': [],
    }

    # Step 1: Monitor export
    print("\n[1/3] Monitor watchlist export...")
    rc = run_script('monitor_watchlist.py', ['export'])
    results['monitor_export'] = 'ok' if rc == 0 else 'error'
    if rc != 0:
        results['errors'].append('monitor_watchlist.py export failed')
    else:
        ctx = DATA / 'monitor-context.json'
        if ctx.exists():
            results['files_for_claude'].append(str(ctx))

    # Step 2: JobSpy discovery
    if skip_jobspy:
        print("\n[2/3] JobSpy discovery — SKIPPED (--skip-jobspy)")
        results['discovery'] = 'skipped'
    else:
        print("\n[2/3] JobSpy discovery...")
        rc = run_script('discovery_pipeline.py', ['--limit', str(limit)])
        results['discovery'] = 'ok' if rc == 0 else 'error'
        if rc != 0:
            results['errors'].append('discovery_pipeline.py failed')
        else:
            pending = DATA / 'pending-eval.json'
            if pending.exists():
                results['files_for_claude'].append(str(pending))

    # Step 3: Web prospecting export
    print("\n[3/3] Web prospecting export...")
    rc = run_script('web_prospecting.py', ['export'])
    results['prospecting_export'] = 'ok' if rc == 0 else 'error'
    if rc != 0:
        results['errors'].append('web_prospecting.py export failed')
    else:
        ctx = DATA / 'prospecting-context.json'
        if ctx.exists():
            results['files_for_claude'].append(str(ctx))

    # Summary
    print("\n" + "=" * 60)
    print("  PHASE 1 COMPLETE")
    print("=" * 60)
    print(f"  Monitor export:      {results['monitor_export']}")
    print(f"  JobSpy discovery:    {results['discovery']}")
    print(f"  Prospecting export:  {results['prospecting_export']}")
    if results['errors']:
        print(f"\n  ERRORS: {', '.join(results['errors'])}")
    print(f"\n  Files for Claude to process:")
    for f in results['files_for_claude']:
        print(f"    → {f}")

    if not results['files_for_claude']:
        print("\n  No files to process — nothing for Claude to do.")
    else:
        print(f"\n  Claude: read the files above, do research + evaluation,")
        print(f"  then write result files (monitor-results.json, eval-results.json,")
        print(f"  prospecting-results.json) as needed.")
        print(f"\n  When done: uv run scripts/ops/run_pipeline.py phase2")

    # Write summary for Claude to read
    results['timestamp'] = datetime.now().isoformat()
    summary_path = DATA / 'pipeline-phase1-summary.json'
    with summary_path.open('w', encoding='utf-8') as f:
        json.dump(results, f, indent=2)

    return results


def phase2(dry_run: bool = False) -> dict:
    """
    Phase 2: All merge steps after Claude finishes research.

    1. Monitor merge (updates existing companies with new roles)
    2. Apply eval results (merges LLM scores into target-companies.csv)
    3. Web prospecting merge (adds new companies)

    Only runs merges where result files exist.
    """
    print("\n" + "=" * 60)
    print("  PHASE 2: Merge all results")
    print("=" * 60)

    dr = ['--dry-run'] if dry_run else []
    results = {
        'monitor_merge': None,
        'eval_merge': None,
        'prospecting_merge': None,
        'errors': [],
    }

    # Step 1: Monitor merge
    monitor_results = DATA / 'monitor-results.json'
    if monitor_results.exists():
        print("\n[1/3] Monitor watchlist merge...")
        rc = run_script('monitor_watchlist.py', ['merge'] + dr)
        results['monitor_merge'] = 'ok' if rc == 0 else 'error'
        if rc != 0:
            results['errors'].append('monitor_watchlist.py merge failed')
    else:
        print("\n[1/3] Monitor merge — SKIPPED (no monitor-results.json)")
        results['monitor_merge'] = 'skipped'

    # Step 2: Apply eval results
    eval_results = DATA / 'eval-results.json'
    if eval_results.exists():
        print("\n[2/3] Apply eval results...")
        rc = run_script('apply_eval_results.py', dr)
        results['eval_merge'] = 'ok' if rc == 0 else 'error'
        if rc != 0:
            results['errors'].append('apply_eval_results.py failed')
    else:
        print("\n[2/3] Eval merge — SKIPPED (no eval-results.json)")
        results['eval_merge'] = 'skipped'

    # Step 3: Web prospecting merge
    prospecting_results = DATA / 'prospecting-results.json'
    if prospecting_results.exists():
        print("\n[3/3] Web prospecting merge...")
        rc = run_script('web_prospecting.py', ['merge'] + dr)
        results['prospecting_merge'] = 'ok' if rc == 0 else 'error'
        if rc != 0:
            results['errors'].append('web_prospecting.py merge failed')
    else:
        print("\n[3/3] Prospecting merge — SKIPPED (no prospecting-results.json)")
        results['prospecting_merge'] = 'skipped'

    # Summary
    print("\n" + "=" * 60)
    print("  PHASE 2 COMPLETE")
    print("=" * 60)
    print(f"  Monitor merge:      {results['monitor_merge']}")
    print(f"  Eval merge:         {results['eval_merge']}")
    print(f"  Prospecting merge:  {results['prospecting_merge']}")
    if results['errors']:
        print(f"\n  ERRORS: {', '.join(results['errors'])}")
    if dry_run:
        print("\n  (dry-run — no files written)")
    else:
        print(f"\n  target-companies.csv updated.")
        print(f"  Next: generate action list CSV.")

    # Clean up phase1 summary
    summary_path = DATA / 'pipeline-phase1-summary.json'
    if summary_path.exists() and not dry_run:
        summary_path.unlink()

    return results


def phase3() -> dict:
    """
    Phase 3: Action list generation.

    Generates the ranked action list CSV from updated target-companies.csv.
    Health checks / evals are run separately from career-manager/evals/.
    """
    print("\n" + "=" * 60)
    print("  PHASE 3: Generate action list")
    print("=" * 60)

    results = {
        'action_list': None,
        'errors': [],
    }

    print("\n[1/2] Generating action list...")
    action_list_path = DATA / 'action-list.csv'

    try:
        _generate_action_list(action_list_path)
        results['action_list'] = str(action_list_path)
    except Exception as e:
        results['action_list'] = 'error'
        results['errors'].append(f'Action list generation failed: {e}')

    # Generate dashboard
    print("\n[2/2] Generating dashboard...")
    dashboard_rc = run_script('generate_dashboard.py', [])
    if dashboard_rc != 0:
        results['errors'].append('Dashboard generation failed')
    else:
        results['dashboard'] = str(DATA / 'dashboard.html')

    # Summary
    print("\n" + "=" * 60)
    print("  PHASE 3 COMPLETE")
    print("=" * 60)
    print(f"  Action list:   {results['action_list']}")
    if results.get('dashboard'):
        print(f"  Dashboard:     file://{results['dashboard']}")
    if results['errors']:
        print(f"\n  ISSUES: {'; '.join(results['errors'])}")
    else:
        print(f"\n  Run evals separately: python3 ../evals/scripts/health_monitor.py")

    return results


def _generate_action_list(output_path: Path) -> None:
    """Generate ranked action list CSV from target-companies + applications."""
    import csv as _csv

    target_csv = DATA / 'target-companies.csv'
    apps_csv = BASE.parent / 'job-tracker' / 'data' / 'applications.csv'

    # Read applications
    app_map = {}
    if apps_csv.exists():
        with apps_csv.open(encoding='utf-8') as f:
            for row in _csv.DictReader(f):
                key = (row.get('company', '').strip().lower())
                if key:
                    app_map[key] = {
                        'status': row.get('status', ''),
                        'date_added': row.get('date_added', ''),
                        'last_contact': row.get('last_contact', ''),
                        'contact_name': row.get('contact_name', ''),
                    }

    # Read targets (pass only)
    rows = []
    with target_csv.open(encoding='utf-8') as f:
        for row in _csv.DictReader(f):
            if row.get('validation_status') != 'pass':
                continue
            company = row.get('company', '').strip()
            key = company.lower()
            app = app_map.get(key, {})

            llm = row.get('llm_score', '').strip()
            try:
                score = float(llm) if llm else 0
            except (ValueError, TypeError):
                score = 0

            rows.append({
                'rank': '',
                'priority': 'HIGH' if score >= 75 else ('MED' if score >= 60 else 'LOW'),
                'company': company,
                'llm_score': llm,
                'path': row.get('role_family', ''),
                'role': row.get('open_positions', ''),
                'apply_url': row.get('role_url', '').strip() or row.get('careers_url', ''),
                'applied_status': app.get('status', 'not_applied'),
                'applied_date': app.get('date_added', ''),
                'last_contact': app.get('last_contact', ''),
                'contact_name': app.get('contact_name', ''),
                'fit_summary': row.get('llm_rationale', ''),
                'red_flags': row.get('llm_flags', ''),
            })

    rows.sort(key=lambda r: float(r['llm_score'] or 0), reverse=True)
    for i, r in enumerate(rows, 1):
        r['rank'] = str(i)

    header = [
        'rank', 'priority', 'company', 'llm_score', 'path', 'role', 'apply_url',
        'applied_status', 'applied_date', 'last_contact', 'contact_name',
        'fit_summary', 'red_flags',
    ]

    with output_path.open('w', newline='', encoding='utf-8') as f:
        w = _csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)

    high = sum(1 for r in rows if r['priority'] == 'HIGH')
    med = sum(1 for r in rows if r['priority'] == 'MED')
    low = sum(1 for r in rows if r['priority'] == 'LOW')
    not_applied = sum(1 for r in rows if r['applied_status'] == 'not_applied')

    print(f"\n  Action list: {output_path.name}")
    print(f"  Total: {len(rows)} companies")
    print(f"    HIGH (75+): {high}")
    print(f"    MED (60-74): {med}")
    print(f"    LOW (<60):  {low}")
    print(f"  Not yet applied: {not_applied}")


def _log_run(phase: str, exit_code: int, start_time: datetime, results: dict) -> None:
    """Append a run entry to run-log.jsonl."""
    end_time = datetime.now()
    entry = {
        'phase': phase,
        'exit_code': exit_code,
        'started_at': start_time.isoformat(),
        'finished_at': end_time.isoformat(),
        'duration_seconds': round((end_time - start_time).total_seconds(), 1),
        'errors': results.get('errors', []),
    }
    RUN_LOG.parent.mkdir(parents=True, exist_ok=True)
    with RUN_LOG.open('a', encoding='utf-8') as f:
        f.write(json.dumps(entry) + '\n')


def main() -> int:
    ap = argparse.ArgumentParser(description='Job search pipeline orchestrator')
    ap.add_argument('phase', choices=['phase1', 'phase2', 'phase3'])
    ap.add_argument('--dry-run', action='store_true', help='Preview merges without writing')
    ap.add_argument('--skip-jobspy', action='store_true', help='Skip JobSpy scrape in phase1')
    ap.add_argument('--limit', type=int, default=35, help='JobSpy results per query (default: 35)')
    args = ap.parse_args()

    start_time = datetime.now()

    if args.phase == 'phase1':
        results = phase1(skip_jobspy=args.skip_jobspy, limit=args.limit)
        exit_code = 1 if results['errors'] else 0
    elif args.phase == 'phase2':
        results = phase2(dry_run=args.dry_run)
        exit_code = 1 if results['errors'] else 0
    else:
        results = phase3()
        exit_code = 1 if results['errors'] else 0

    _log_run(args.phase, exit_code, start_time, results)

    # Run health check after pipeline completes
    if args.phase == 'phase3':
        print("\n--- Running health monitor ---")
        health_script = BASE.parent / "evals" / "scripts" / "health_monitor.py"
        if health_script.exists():
            subprocess.run([sys.executable, str(health_script)], cwd=str(health_script.parent))
        else:
            print(f"[evals] Health monitor not found at {health_script}")

    return exit_code


if __name__ == '__main__':
    raise SystemExit(main())
