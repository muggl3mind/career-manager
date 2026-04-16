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
SNAPSHOT_PATH = DATA / 'previous-run-snapshot.json'
SCORE_CHANGE_THRESHOLD = 15
HIGH_SCORE_THRESHOLD = 60


def compute_path_coverage(rows: list[dict]) -> dict[str, int]:
    """Count companies per normalized role_family path."""
    sys.path.insert(0, str(BASE / 'scripts' / 'core'))
    from path_normalizer import normalize_path
    counts: dict[str, int] = {}
    for r in rows:
        raw = (r.get('role_family') or '').strip()
        label = normalize_path(raw) if raw else 'Uncategorized'
        counts[label] = counts.get(label, 0) + 1
    return dict(sorted(counts.items()))


def find_thin_paths(coverage: dict[str, int], threshold: int = 8) -> list[str]:
    return [p for p, c in coverage.items() if c < threshold and p != 'Uncategorized']


def print_coverage_report(rows: list[dict]) -> None:
    coverage = compute_path_coverage(rows)
    thin = find_thin_paths(coverage)
    print("\nPath coverage:")
    for path, count in coverage.items():
        flag = "  [!] below threshold (8)" if path in thin else ""
        print(f"  {path}: {count} companies{flag}")


def load_snapshot(path: Path | None = None) -> dict | None:
    path = path or SNAPSHOT_PATH
    if not path.exists():
        return None
    try:
        return json.loads(path.read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return None


def save_snapshot(rows: list[dict], path: Path | None = None) -> None:
    path = path or SNAPSHOT_PATH
    companies = {}
    for r in rows:
        name = (r.get('company') or '').strip()
        if not name:
            continue
        try:
            score = int(float(r.get('llm_score', 0) or 0))
        except (ValueError, TypeError):
            score = 0
        companies[name] = {'score': score, 'path': r.get('role_family', '')}
    snapshot = {'timestamp': datetime.now().isoformat(), 'companies': companies}
    path.write_text(json.dumps(snapshot, indent=2, ensure_ascii=False), encoding='utf-8')


def compute_run_diff(previous: dict, current: dict[str, dict]) -> dict:
    prev_companies = previous.get('companies', {})
    added = [c for c in current if c not in prev_companies]
    removed = [c for c in prev_companies if c not in current]
    score_changes = []
    for company in current:
        if company in prev_companies:
            old_score = prev_companies[company].get('score', 0)
            new_score = current[company].get('score', 0)
            if abs(new_score - old_score) > SCORE_CHANGE_THRESHOLD:
                score_changes.append({'company': company, 'old': old_score, 'new': new_score, 'delta': new_score - old_score})
    return {
        'added': added, 'removed': removed,
        'removed_high_score': [c for c in removed if prev_companies.get(c, {}).get('score', 0) > HIGH_SCORE_THRESHOLD],
        'score_changes': score_changes,
    }


def print_run_diff(diff: dict) -> None:
    print(f"\nRun diff:")
    print(f"  +{len(diff['added'])} new companies added")
    print(f"  -{len(diff['removed'])} companies removed")
    if diff['removed_high_score']:
        print(f"  WARNING: {len(diff['removed_high_score'])} removed companies had score > {HIGH_SCORE_THRESHOLD}:")
        for c in diff['removed_high_score']:
            print(f"    {c}")
    if diff['score_changes']:
        print(f"  ~{len(diff['score_changes'])} companies with score change > {SCORE_CHANGE_THRESHOLD} points:")
        for sc in diff['score_changes']:
            print(f"    {sc['company']}: {sc['old']} -> {sc['new']} ({sc['delta']:+d})")


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
        ctx_files = list(DATA.glob('prospecting-context-*.json'))
        if ctx_files:
            for cf in ctx_files:
                results['files_for_claude'].append(str(cf))

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

    # Save snapshot before merges
    import csv as _csv
    if (DATA / 'target-companies.csv').exists():
        with (DATA / 'target-companies.csv').open(encoding='utf-8') as f:
            pre_rows = list(_csv.DictReader(f))
        save_snapshot(pre_rows)

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
    prospecting_results = list(DATA.glob('prospecting-results-*.json'))
    old_single = DATA / 'prospecting-results.json'
    if prospecting_results or old_single.exists():
        print("\n[3/3] Web prospecting merge...")
        rc = run_script('web_prospecting.py', ['merge'] + dr)
        results['prospecting_merge'] = 'ok' if rc == 0 else 'error'
        if rc != 0:
            results['errors'].append('web_prospecting.py merge failed')
    else:
        print("\n[3/3] Prospecting merge — SKIPPED (no prospecting-results files)")
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

    # Coverage check
    print("\n[0/2] Coverage check...")
    import csv as _csv
    if (DATA / 'target-companies.csv').exists():
        with (DATA / 'target-companies.csv').open(encoding='utf-8') as f:
            all_rows = list(_csv.DictReader(f))
        print_coverage_report(all_rows)

    # Cross-run consistency check
    snapshot = load_snapshot()
    if snapshot:
        if (DATA / 'target-companies.csv').exists():
            with (DATA / 'target-companies.csv').open(encoding='utf-8') as f:
                current_rows = list(_csv.DictReader(f))
            current_map = {}
            for r in current_rows:
                name = (r.get('company') or '').strip()
                if name:
                    try:
                        score = int(float(r.get('llm_score', 0) or 0))
                    except (ValueError, TypeError):
                        score = 0
                    current_map[name] = {'score': score, 'path': r.get('role_family', '')}
            diff = compute_run_diff(snapshot, current_map)
            print_run_diff(diff)
    else:
        print("\nRun diff: First run, no comparison available.")

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
    """Generate ranked action list CSV from the shared dashboard_views helper."""
    import csv as _csv
    sys.path.insert(0, str(SCRIPTS))
    from dashboard_views import build_active_views

    target_csv = DATA / 'target-companies.csv'
    apps_csv = BASE.parent / 'job-tracker' / 'data' / 'applications.csv'
    views = build_active_views(target_csv, apps_csv)

    best_fits = views['best_fits']
    stats = views['stats']

    csv_rows = []
    for i, r in enumerate(best_fits, 1):
        score_raw = (r.get('llm_score') or '').strip()
        try:
            score = float(score_raw) if score_raw else 0.0
        except (ValueError, TypeError):
            score = 0.0
        csv_rows.append({
            'rank': str(i),
            'priority': 'HIGH' if score >= 85 else 'MED',
            'company': r.get('company', ''),
            'llm_score': score_raw,
            'path': r.get('role_family', ''),
            'role': r.get('open_positions', ''),
            'apply_url': (r.get('role_url') or '').strip() or (r.get('careers_url') or '').strip(),
            'has_role_url': 'yes' if (r.get('role_url') or '').strip() else '',
            'applied_status': r.get('app_status', '') or 'not_applied',
            'applied_date': r.get('date_added', ''),
            'last_contact': r.get('last_contact', ''),
            'contact_name': r.get('contact_name', ''),
            'fit_summary': r.get('llm_rationale', ''),
            'red_flags': r.get('llm_flags', ''),
        })

    header = [
        'rank', 'priority', 'company', 'llm_score', 'path', 'role',
        'apply_url', 'has_role_url', 'applied_status', 'applied_date',
        'last_contact', 'contact_name', 'fit_summary', 'red_flags',
    ]

    with output_path.open('w', newline='', encoding='utf-8') as f:
        w = _csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(csv_rows)

    print(f"\n  Action list: {output_path.name}")
    print(f"  Best Fits (score >= 70): {stats['best_fits']}")
    print(f"  Total rows: {len(csv_rows)}")


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
