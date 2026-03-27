#!/usr/bin/env python3
"""
Level 1 Eval: Static code review of the job-search pipeline.

Reads source files and checks for known bug patterns without executing them.
Returns non-zero exit code if critical issues found.

Usage:
  python3 scripts/code_review.py
  python3 scripts/code_review.py --json
"""

from __future__ import annotations

import ast
import json
import re
import sys
from pathlib import Path

EVALS_DIR = Path(__file__).resolve().parents[1]
CAREER_MGR = EVALS_DIR.parent
JOB_SEARCH = CAREER_MGR / 'job-search'
SCRIPTS_OPS = JOB_SEARCH / 'scripts' / 'ops'
SCRIPTS_CORE = JOB_SEARCH / 'scripts' / 'core'


def _read(path: Path) -> str:
    if not path.exists():
        return ''
    return path.read_text(encoding='utf-8')


def check_preserve_existing_sources(src: str) -> dict:
    """Bug: discovery_pipeline.py preserve_existing_manual missing source=monitor."""
    check = {
        'check': 'preserve_existing_sources',
        'file': 'scripts/ops/discovery_pipeline.py',
        'status': 'pass',
        'detail': '',
    }
    # Find the set of preserved sources
    match = re.search(r"if\s+src\s+in\s+\{([^}]+)\}", src)
    if not match:
        check['status'] = 'warn'
        check['detail'] = 'Could not locate preserve_existing_manual source check'
        return check

    sources_str = match.group(1)
    sources = {s.strip().strip("'\"") for s in sources_str.split(',')}

    if 'monitor' not in sources:
        check['status'] = 'fail'
        check['detail'] = (
            f"source='monitor' missing from preserve set. "
            f"Current sources: {sorted(sources)}. "
            f"Companies added via monitor_watchlist.py will be dropped on next discovery run."
        )
    else:
        check['detail'] = f"All expected sources present: {sorted(sources)}"
    return check


def check_exit_codes(src: str) -> dict:
    """Bug: discovery_pipeline.py main() always returns 0."""
    check = {
        'check': 'discovery_exit_code',
        'file': 'scripts/ops/discovery_pipeline.py',
        'status': 'pass',
        'detail': '',
    }
    # Parse the AST to find main() return statements
    try:
        tree = ast.parse(src)
    except SyntaxError:
        check['status'] = 'warn'
        check['detail'] = 'Could not parse file'
        return check

    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == 'main':
            returns = [n for n in ast.walk(node) if isinstance(n, ast.Return)]
            # Check if any return is non-zero
            has_nonzero = False
            for ret in returns:
                if ret.value is None:
                    continue
                if isinstance(ret.value, ast.Constant) and ret.value.value != 0:
                    has_nonzero = True
                if isinstance(ret.value, ast.UnaryOp):
                    has_nonzero = True  # e.g., return -1
            if not has_nonzero:
                check['status'] = 'fail'
                check['detail'] = (
                    'main() only returns 0. Errors during discovery/validation '
                    'will not propagate to the orchestrator.'
                )
            else:
                check['detail'] = 'main() has error exit paths'
            break
    else:
        check['status'] = 'warn'
        check['detail'] = 'main() function not found'
    return check


def check_dict_overwrite(src: str) -> dict:
    """Bug: monitor_watchlist.py existing_by_name overwrites for duplicate companies."""
    check = {
        'check': 'monitor_dict_overwrite',
        'file': 'scripts/ops/monitor_watchlist.py',
        'status': 'pass',
        'detail': '',
    }
    # Look for the pattern: existing_by_name[name] = i (simple dict, not list)
    if re.search(r'existing_by_name\[name\]\s*=\s*i\b', src):
        # Check if it's Dict[str, int] (single value) vs Dict[str, list]
        if 'Dict[str, int]' in src or 'dict[str, int]' in src:
            check['status'] = 'fail'
            check['detail'] = (
                'existing_by_name is Dict[str, int] — last row wins for duplicate company names. '
                'Should be Dict[str, list[int]] to track all rows per company.'
            )
        elif 'Dict[str, List[int]]' in src or 'dict[str, list[int]]' in src:
            check['detail'] = 'existing_by_name uses list of indices (correct)'
        else:
            # Fall back to pattern check
            check['status'] = 'fail'
            check['detail'] = (
                'existing_by_name[name] = i overwrites previous entries. '
                'Companies with multiple rows will lose data during merge.'
            )
    else:
        check['detail'] = 'No simple dict overwrite pattern found'
    return check


def check_skill_dir_path(src: str) -> dict:
    """Bug: score_companies.py SKILL_DIR resolves to scripts/ not job-search/."""
    check = {
        'check': 'score_companies_path',
        'file': 'scripts/core/score_companies.py',
        'status': 'pass',
        'detail': '',
    }
    # The file is at scripts/core/score_companies.py (3 levels below job-search/)
    # .parent.parent = scripts/ (wrong), .parent.parent.parent or .parents[2] = job-search/ (correct)
    match = re.search(r'SKILL_DIR\s*=\s*Path\(__file__\)\.resolve\(\)((?:\.parent)+)', src)
    if not match:
        # Check for .parents[] syntax
        match2 = re.search(r'SKILL_DIR\s*=\s*Path\(__file__\)\.resolve\(\)\.parents\[(\d+)\]', src)
        if match2:
            depth = int(match2.group(1))
            if depth == 2:
                check['detail'] = 'SKILL_DIR uses .parents[2] (correct for scripts/core/)'
            else:
                check['status'] = 'fail'
                check['detail'] = f'SKILL_DIR uses .parents[{depth}], expected .parents[2]'
        else:
            check['status'] = 'warn'
            check['detail'] = 'Could not locate SKILL_DIR assignment'
        return check

    parent_chain = match.group(1)
    depth = parent_chain.count('.parent')
    if depth == 2:
        check['status'] = 'fail'
        check['detail'] = (
            f'SKILL_DIR = Path(__file__).resolve(){parent_chain} resolves to scripts/ '
            f'(2 levels up from scripts/core/). Needs 3 levels (.parent.parent.parent) '
            f'to reach job-search/. CSV_PATH will point to scripts/data/ which does not exist.'
        )
    elif depth == 3:
        check['detail'] = 'SKILL_DIR uses .parent.parent.parent (correct for scripts/core/)'
    else:
        check['status'] = 'warn'
        check['detail'] = f'SKILL_DIR goes {depth} levels up — verify manually'
    return check


def check_run_pipeline_self_eval(src: str) -> dict:
    """Check: run_pipeline.py phase3 should not embed health checks from within the pipeline."""
    check = {
        'check': 'pipeline_self_eval',
        'file': 'scripts/ops/run_pipeline.py',
        'status': 'pass',
        'detail': '',
    }
    if 'pipeline_health' in src:
        check['status'] = 'warn'
        check['detail'] = (
            'run_pipeline.py references pipeline_health.py — evaluation should be '
            'run from outside the pipeline (career-manager/evals/), not embedded in it.'
        )
    else:
        check['detail'] = 'No self-evaluation embedded in pipeline'
    return check


def run_code_review(as_json: bool = False) -> int:
    """Run all static checks and print report."""
    from datetime import datetime, timezone

    discovery_src = _read(SCRIPTS_OPS / 'discovery_pipeline.py')
    monitor_src = _read(SCRIPTS_OPS / 'monitor_watchlist.py')
    score_src = _read(SCRIPTS_CORE / 'score_companies.py')
    pipeline_src = _read(SCRIPTS_OPS / 'run_pipeline.py')

    all_checks = []
    all_checks.append(check_preserve_existing_sources(discovery_src))
    all_checks.append(check_exit_codes(discovery_src))
    all_checks.append(check_dict_overwrite(monitor_src))
    all_checks.append(check_skill_dir_path(score_src))
    all_checks.append(check_run_pipeline_self_eval(pipeline_src))

    if as_json:
        print(json.dumps({
            'eval': 'code_review',
            'level': 1,
            'timestamp': datetime.now(timezone.utc).isoformat(),
            'checks': all_checks,
        }, indent=2))
    else:
        icons = {'pass': '\u2705', 'warn': '\u26a0\ufe0f ', 'fail': '\u274c', 'info': '\u2139\ufe0f '}
        print(f"\n{'='*60}")
        print(f"  CODE REVIEW — Job Search Pipeline")
        print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
        print(f"{'='*60}\n")

        for c in all_checks:
            icon = icons.get(c['status'], '  ')
            print(f"  {icon} [{c['file']}]")
            print(f"     {c['check']}: {c['detail']}\n")

        fails = sum(1 for c in all_checks if c['status'] == 'fail')
        warns = sum(1 for c in all_checks if c['status'] == 'warn')
        passes = sum(1 for c in all_checks if c['status'] == 'pass')

        print(f"{'='*60}")
        print(f"  {passes} pass, {warns} warn, {fails} fail")
        if fails:
            print(f"  STATUS: ISSUES FOUND")
        elif warns:
            print(f"  STATUS: REVIEW WARNINGS")
        else:
            print(f"  STATUS: CLEAN")
        print(f"{'='*60}\n")

    has_failures = any(c['status'] == 'fail' for c in all_checks)
    return 1 if has_failures else 0


def main() -> int:
    import argparse
    ap = argparse.ArgumentParser(description='Level 1: Static code review')
    ap.add_argument('--json', action='store_true', help='Output as JSON')
    args = ap.parse_args()
    return run_code_review(as_json=args.json)


if __name__ == '__main__':
    raise SystemExit(main())
