#!/usr/bin/env python3
"""
Evaluation export utility for job discovery.

Writes jobs that need LLM evaluation to data/pending-eval.json.
Claude Code (the skill) reads this file, evaluates each job, and writes
results to data/eval-results.json. apply_eval_results.py then merges
those back into target-companies.csv.

Export shape:
- data/pending-eval.json always holds the full JSON array of pending
  jobs. apply_eval_results.py reads it for job metadata, so it exists
  even when the batch is sharded.
- Batches of EVAL_SHARD_SIZE jobs or fewer write only that legacy file,
  so small runs behave exactly as before.
- Larger batches additionally write data/pending-eval-shard-1.json
  through pending-eval-shard-N.json (1-based, batch order preserved),
  each a JSON array of at most EVAL_SHARD_SIZE jobs. Launch one eval
  agent per shard file instead of handing the full batch to one agent.
- Stale shard files from earlier runs are deleted on every non-dry-run
  export.
- Agent-facing exports are compact JSON (no indentation) to cut tokens.

No API key required. Claude Code is the LLM.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Dict, List, Optional, Tuple

BASE = Path(__file__).resolve().parents[2]
DATA = BASE / 'data'
SEEN_JOBS = DATA / 'seen-jobs.json'
PENDING_EVAL = DATA / 'pending-eval.json'

# Max jobs handed to a single eval agent. Batches above this size are
# split into pending-eval-shard-N.json work units (see module docstring).
EVAL_SHARD_SIZE = 40

_SHARD_GLOB = 'pending-eval-shard-*.json'

# Cached verdicts expire after this many days (finding H5). A job
# re-posted at the same URL after the TTL gets a fresh evaluation
# instead of keeping its old score forever. Documented in SKILL.md
# ("Cache behavior").
EVAL_CACHE_TTL_DAYS = 30

# LLM fields restored from the cache / kept blank for pending jobs.
LLM_FIELDS = (
    'llm_score', 'llm_dimensions_evaluated', 'role_family',
    'llm_rationale', 'llm_flags', 'llm_hard_pass',
    'llm_hard_pass_reason', 'llm_evaluated_at',
)


def _parse_timestamp(value: str) -> Optional[datetime]:
    try:
        dt = datetime.fromisoformat(value)
    except (TypeError, ValueError):
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def _cache_fresh(cached: Dict, now: datetime,
                 ttl_days: int = EVAL_CACHE_TTL_DAYS) -> bool:
    """True when a cached verdict is still within its TTL.

    Entries without a parseable evaluation timestamp are treated as
    stale, so they get re-evaluated rather than trusted forever.
    """
    evaluated_at = cached.get('llm_evaluated_at') or cached.get('first_seen') or ''
    dt = _parse_timestamp(evaluated_at)
    if dt is None:
        return False
    return (now - dt) <= timedelta(days=ttl_days)


def load_seen_jobs() -> Dict:
    if SEEN_JOBS.exists():
        with SEEN_JOBS.open(encoding='utf-8') as f:
            return json.load(f)
    return {}


def save_seen_jobs(seen: Dict) -> None:
    SEEN_JOBS.parent.mkdir(parents=True, exist_ok=True)
    with SEEN_JOBS.open('w', encoding='utf-8') as f:
        json.dump(seen, f, indent=2, ensure_ascii=False)


def shard_path(index: int) -> Path:
    """Path of the 1-based Nth shard file, next to PENDING_EVAL."""
    return PENDING_EVAL.with_name(f'pending-eval-shard-{index}.json')


def _clear_stale_shards() -> None:
    for path in PENDING_EVAL.parent.glob(_SHARD_GLOB):
        path.unlink()


def _dump_compact(payload: List[Dict], path: Path) -> None:
    with path.open('w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False)


def write_pending_export(pending: List[Dict],
                         shard_size: int = EVAL_SHARD_SIZE) -> List[Path]:
    """Write the pending-eval export; return the agent-facing paths.

    PENDING_EVAL always gets the full array (apply_eval_results.py
    reads it for job metadata). Batches larger than shard_size also get
    shard files of at most shard_size jobs, one per eval agent, and the
    returned paths are those shards. Stale shards from earlier runs are
    removed first either way.
    """
    PENDING_EVAL.parent.mkdir(parents=True, exist_ok=True)
    _clear_stale_shards()
    _dump_compact(pending, PENDING_EVAL)
    if len(pending) <= shard_size:
        return [PENDING_EVAL]
    paths = []
    for start in range(0, len(pending), shard_size):
        path = shard_path(start // shard_size + 1)
        _dump_compact(pending[start:start + shard_size], path)
        paths.append(path)
    return paths


def export_pending(jobs: List[Dict], dry_run: bool = False, verbose: bool = True,
                   shard_size: int = EVAL_SHARD_SIZE) -> Tuple[List[Dict], List[Dict]]:
    """
    Separate jobs into already-evaluated (cached) and new (pending).

    - Restores cached LLM fields for already-seen jobs whose verdict is
      still within EVAL_CACHE_TTL_DAYS (finding H5: no eternal verdicts).
    - Cached hard-passes are skipped entirely (finding H4: they never
      resurrect into the active list) until their TTL expires.
    - Writes new and expired jobs to data/pending-eval.json for Claude
      to evaluate; batches above shard_size also get per-agent shard
      files (see module docstring).
    - Returns (scored_jobs, all_jobs) where scored_jobs only contains
      jobs with cached LLM verdicts (ready for target CSV).
    """
    seen = load_seen_jobs()
    now = datetime.now(timezone.utc)
    pending = []
    scored_jobs = []
    cached_count = 0
    expired_count = 0
    hard_pass_skipped = 0

    for job in jobs:
        url = job.get('careers_url') or job.get('url', '')
        cached = seen.get(url)
        has_verdict = cached is not None and cached.get('llm_score') is not None
        if has_verdict and not _cache_fresh(cached, now):
            expired_count += 1
            has_verdict = False
            if verbose:
                print(f"  [eval] expired {job.get('company')} - {job.get('open_positions')} (cached verdict older than {EVAL_CACHE_TTL_DAYS}d, re-evaluating)")
        if has_verdict:
            if str(cached.get('llm_hard_pass', '')).strip().lower() == 'true':
                # Hard-passed within TTL: do not resurrect, do not re-evaluate.
                hard_pass_skipped += 1
                if verbose:
                    print(f"  [eval] hard-pass cached, skipping {job.get('company')} - {job.get('open_positions')}")
                continue
            job['llm_score'] = cached.get('llm_score')
            job['llm_dimensions_evaluated'] = cached.get('llm_dimensions_evaluated', '')
            job['role_family'] = cached.get('role_family', '')
            job['llm_rationale'] = cached.get('llm_rationale', '')
            job['llm_flags'] = cached.get('llm_flags', '')
            job['llm_hard_pass'] = cached.get('llm_hard_pass', 'false')
            job['llm_hard_pass_reason'] = cached.get('llm_hard_pass_reason', '')
            job['llm_evaluated_at'] = cached.get('llm_evaluated_at', '')
            cached_count += 1
            scored_jobs.append(job)
            if verbose:
                print(f"  [eval] cached  {job.get('company')} - {job.get('open_positions')} (llm_score={job['llm_score']})")
        else:
            # Ensure blank LLM fields so CSV columns are consistent
            for col in LLM_FIELDS:
                job.setdefault(col, '')
            pending.append({
                'careers_url': url,
                'title': job.get('open_positions', ''),
                'company': job.get('company', ''),
                'location': job.get('location_detected', ''),
                'description': (job.get('description') or '')[:3000],
                'role_family': job.get('role_family', ''),
                'is_agency': 'is_agency=true' in (job.get('notes', '')),
                'source': job.get('source', ''),
            })

    if verbose:
        print(
            f"[evaluate_jobs] {len(jobs)} total | {cached_count} cached | "
            f"{expired_count} cache-expired | {hard_pass_skipped} hard-pass skipped | "
            f"{len(pending)} pending eval"
        )

    if not dry_run:
        if pending:
            written = write_pending_export(pending, shard_size=shard_size)
            print(f"[evaluate_jobs] wrote {len(pending)} jobs to {PENDING_EVAL}")
            if len(written) > 1:
                print(f"[evaluate_jobs] split into {len(written)} shards of <= {shard_size} jobs (one eval agent per shard):")
                for path in written:
                    print(f"  [evaluate_jobs] {path}")
            print(f"[evaluate_jobs] Claude will evaluate these - run the skill to continue")
        else:
            _clear_stale_shards()

    return scored_jobs, jobs
