#!/usr/bin/env python3
"""
Evaluation export utility for job discovery.

Writes jobs that need LLM evaluation to data/pending-eval.json.
Claude Code (the skill) reads this file, evaluates each job, and writes
results to data/eval-results.json. apply_eval_results.py then merges
those back into target-companies.csv.

No API key required — Claude Code is the LLM.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, List

BASE = Path(__file__).resolve().parents[2]
DATA = BASE / 'data'
SEEN_JOBS = DATA / 'seen-jobs.json'
PENDING_EVAL = DATA / 'pending-eval.json'


def load_seen_jobs() -> Dict:
    if SEEN_JOBS.exists():
        with SEEN_JOBS.open(encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_seen_jobs(seen: Dict) -> None:
    SEEN_JOBS.parent.mkdir(parents=True, exist_ok=True)
    with SEEN_JOBS.open('w', encoding='utf-8') as f:
        json.dump(seen, f, indent=2, ensure_ascii=False)


def export_pending(jobs: List[Dict], dry_run: bool = False, verbose: bool = True) -> List[Dict]:
    """
    Separate jobs into already-evaluated (cached) and new (pending).

    - Restores cached LLM fields for already-seen jobs.
    - Writes new jobs to data/pending-eval.json for Claude to evaluate.
    - Returns all jobs with cached fields populated where available.
    """
    seen = load_seen_jobs()
    pending = []
    cached_count = 0

    for job in jobs:
        url = job.get('careers_url') or job.get('url', '')
        cached = seen.get(url)
        if cached and cached.get('llm_score') is not None:
            job['llm_score'] = cached.get('llm_score')
            job['llm_path'] = cached.get('llm_path')
            job['llm_path_name'] = cached.get('llm_path_name', '')
            job['llm_rationale'] = cached.get('llm_rationale', '')
            job['llm_flags'] = cached.get('llm_flags', '')
            job['llm_hard_pass'] = cached.get('llm_hard_pass', 'false')
            job['llm_hard_pass_reason'] = cached.get('llm_hard_pass_reason', '')
            job['llm_evaluated_at'] = cached.get('llm_evaluated_at', '')
            cached_count += 1
            if verbose:
                print(f"  [eval] cached  {job.get('company')} — {job.get('open_positions')} (llm_score={job['llm_score']})")
        else:
            # Ensure blank LLM fields so CSV columns are consistent
            for col in ('llm_score', 'llm_path', 'llm_path_name', 'llm_rationale',
                        'llm_flags', 'llm_hard_pass',
                        'llm_hard_pass_reason', 'llm_evaluated_at'):
                job.setdefault(col, '')
            pending.append({
                'careers_url': url,
                'title': job.get('open_positions', ''),
                'company': job.get('company', ''),
                'location': job.get('location_detected', ''),
                'description': (job.get('description') or '')[:3000],
                'role_family': job.get('role_family', ''),
            })

    if verbose:
        print(f"[evaluate_jobs] {len(jobs)} total | {cached_count} cached | {len(pending)} pending eval")

    if not dry_run and pending:
        PENDING_EVAL.parent.mkdir(parents=True, exist_ok=True)
        with PENDING_EVAL.open('w', encoding='utf-8') as f:
            json.dump(pending, f, indent=2, ensure_ascii=False)
        print(f"[evaluate_jobs] wrote {len(pending)} jobs to {PENDING_EVAL}")
        print(f"[evaluate_jobs] Claude will evaluate these — run the skill to continue")

    return jobs
