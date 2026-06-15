#!/usr/bin/env python3
"""Merge-time validation for agent self-reported scores.

Every place an agent-written results JSON enters target-companies.csv
(apply_eval_results.py, web_prospecting.py, monitor_watchlist.py) must
validate the self-report before merging. Previously there was zero
validation on merge, so a row like {"total_score": 97, "scores": {}}
merged cleanly and became the day's top action.

Rules (March 2026 ratio spec; scripts/core/scoring.py is canonical):

- Dimensions are yes/no/unknown assessments (true/false/null, 1/0,
  "yes"/"no"). Numeric scale values like 7 are invalid: the rubric is
  not a 0-10 scale.
- Dimension keys must belong to the rubric set.
- When per-dimension data is present, the total is recomputed with
  scoring.compute_score and the recomputed value always wins. A
  disagreeing self-reported total is logged, never merged.
- A non-zero self-reported total with no dimension data is unverifiable
  and is rejected.
- When only (llm_score, llm_dimensions_evaluated) are reported, the
  score must be an achievable ratio value: floor(yes * 100 / evaluated)
  for some 0 <= yes <= evaluated. A score of 97 is not achievable from
  any evaluated count up to 10, so it is rejected.
- Rejected rows are appended to <data>/quarantine/<script>-<reason>.jsonl
  with full context so they can be re-processed after correction.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Optional

from scoring import (
    MIN_DIMENSIONS_EVALUATED,
    NEEDS_RESEARCH_FLAG,
    TOTAL_DIMENSIONS,
    classify_dimension,
    compute_score,
)

# The rubric dimension keys used in agent self-reports (job-search/SKILL.md
# eval-results schema; generated from references/criteria.md by onboarding).
# Callers can pass their own set when the rubric differs.
DEFAULT_DIMENSION_KEYS = frozenset({
    'background_asset',
    'ai_central',
    'can_influence',
    'non_traditional_welcome',
    'comp_200k_path',
    'growth_path',
    'funding_supports_comp',
    'problems_exciting',
    'culture_public_voice',
    'global_leverage',
})

QUARANTINE_DIRNAME = 'quarantine'

# Quarantine reason slugs (also used as file name suffixes).
REASON_UNVERIFIABLE_TOTAL = 'unverifiable-total'
REASON_UNKNOWN_DIMENSION_KEY = 'unknown-dimension-key'
REASON_INVALID_DIMENSION_VALUE = 'invalid-dimension-value'
REASON_INVALID_SCORE = 'invalid-score'
REASON_SCORE_OUT_OF_RANGE = 'score-out-of-range'
REASON_INVALID_DIMENSIONS_EVALUATED = 'invalid-dimensions-evaluated'
REASON_INSUFFICIENT_DIMENSIONS = 'insufficient-dimensions'
REASON_SCORE_DIMENSION_MISMATCH = 'score-dimension-mismatch'


@dataclass
class MergeValidation:
    """Outcome of validating one agent-reported result row.

    ok      False means the row must be quarantined, not merged.
    score   Canonical integer score to merge. None means "no score"
            (unscored row, or needs_research). 0 is a real score
            (0 yes of >= 5 evaluated), distinct from None.
    needs_research
            True when the row should be stored unscored with the
            needs_research flag.
    reason  Quarantine reason slug when ok is False.
    detail  Human-readable explanation (mismatch notes, error text).
    dimensions_evaluated
            How many dimensions were assessed yes or no (confidence,
            finding M9). None when the row carries no evaluated count
            (legacy self-reports without dimension data).
    """

    ok: bool
    score: Optional[int] = None
    needs_research: bool = False
    reason: str = ''
    detail: str = ''
    dimensions_evaluated: Optional[int] = None


def _coerce_number(value: object) -> Optional[float]:
    """Return value as a finite float, or None when it is not numeric.

    Non-finite floats (NaN, inf) are treated as non-numeric. json.loads
    accepts bare NaN/Infinity tokens, and NaN passes both sides of a
    range check (nan < 0 and nan > 100 are both False) before crashing
    int(). Garbage self-reports must quarantine, never crash the merge.
    """
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if not math.isfinite(number):
        return None
    return number


def _check_dimension_data(
    scores: Mapping[str, object],
    dimension_keys: frozenset[str],
) -> Optional[MergeValidation]:
    """Validate dimension keys and values. Returns a failure outcome or None."""
    unknown = sorted(set(scores) - set(dimension_keys))
    if unknown:
        return MergeValidation(
            ok=False,
            reason=REASON_UNKNOWN_DIMENSION_KEY,
            detail=f"unknown dimension keys: {', '.join(unknown)}",
        )
    for key, value in scores.items():
        try:
            classify_dimension(value)
        except ValueError as e:
            return MergeValidation(
                ok=False,
                reason=REASON_INVALID_DIMENSION_VALUE,
                detail=f'{key}: {e}',
            )
    return None


def validate_eval_result(
    reported_total: object,
    scores: Optional[Mapping[str, object]],
    dimension_keys: frozenset[str] = DEFAULT_DIMENSION_KEYS,
) -> MergeValidation:
    """Validate one eval-results.json row (apply_eval_results.py).

    scores is the per-dimension dict (1 = yes, 0 = no, unknowns omitted).
    reported_total is the agent's self-reported total_score.

    The recomputed ratio score always wins when dimension data is valid.
    A non-zero reported total without dimension data is rejected as
    unverifiable.
    """
    scores = scores or {}
    reported = _coerce_number(reported_total)
    reported_truthy = (
        bool(reported) if reported is not None
        else reported_total not in (None, '', False)
    )

    if not scores:
        if reported_truthy:
            return MergeValidation(
                ok=False,
                reason=REASON_UNVERIFIABLE_TOTAL,
                detail=(
                    f'total_score={reported_total!r} reported with no '
                    'dimension data; cannot verify'
                ),
            )
        # Legitimately unscored (needs_research per the spec).
        return MergeValidation(
            ok=True, score=None, needs_research=True, dimensions_evaluated=0,
        )

    failure = _check_dimension_data(scores, dimension_keys)
    if failure:
        return failure

    result = compute_score(scores)
    detail = ''
    if result.needs_research:
        if reported_truthy:
            detail = (
                f'total_score={reported_total!r} rejected: only '
                f'{result.dimensions_evaluated} of {TOTAL_DIMENSIONS} '
                f'dimensions evaluated (minimum {MIN_DIMENSIONS_EVALUATED}); '
                'stored as needs_research'
            )
        return MergeValidation(
            ok=True, score=None, needs_research=True, detail=detail,
            dimensions_evaluated=result.dimensions_evaluated,
        )

    if reported is None or int(reported) != result.score:
        detail = (
            f'total_score={reported_total!r} disagrees with recomputed '
            f'{result.score} ({result.yes_count} yes of '
            f'{result.dimensions_evaluated} evaluated); using recomputed'
        )
    return MergeValidation(
        ok=True, score=result.score, detail=detail,
        dimensions_evaluated=result.dimensions_evaluated,
    )


def _achievable_scores(evaluated: int) -> set[int]:
    """All ratio scores reachable with `evaluated` dimensions assessed."""
    return {(yes * 100) // evaluated for yes in range(evaluated + 1)}


def validate_self_report(
    llm_score: object,
    dimensions_evaluated: object = None,
    dimension_scores: Optional[Mapping[str, object]] = None,
    dimension_keys: frozenset[str] = DEFAULT_DIMENSION_KEYS,
) -> MergeValidation:
    """Validate one prospecting/monitor result row.

    These rows self-report llm_score (0-100) and llm_dimensions_evaluated
    (0-10), and may include per-dimension data. When dimension data is
    present it is authoritative and the score is recomputed from it.
    Otherwise the score is checked for range and for consistency with the
    reported evaluated count (it must be an achievable ratio value).
    """
    if dimension_scores:
        return validate_eval_result(llm_score, dimension_scores, dimension_keys)

    if llm_score in (None, ''):
        # Unscored row (e.g. watch_list entry): nothing to verify.
        return MergeValidation(ok=True, score=None)

    score = _coerce_number(llm_score)
    if score is None:
        return MergeValidation(
            ok=False,
            reason=REASON_INVALID_SCORE,
            detail=f'llm_score={llm_score!r} is not numeric',
        )
    if score < 0 or score > 100:
        return MergeValidation(
            ok=False,
            reason=REASON_SCORE_OUT_OF_RANGE,
            detail=f'llm_score={llm_score!r} outside 0-100',
        )

    if dimensions_evaluated in (None, ''):
        # Legacy rows without an evaluated count: range check is all we can do.
        if score != int(score):
            return MergeValidation(
                ok=False,
                reason=REASON_SCORE_DIMENSION_MISMATCH,
                detail=(
                    f'llm_score={llm_score!r} is not an integer ratio score'
                ),
            )
        return MergeValidation(ok=True, score=int(score))

    evaluated = _coerce_number(dimensions_evaluated)
    if evaluated is None or evaluated != int(evaluated):
        return MergeValidation(
            ok=False,
            reason=REASON_INVALID_DIMENSIONS_EVALUATED,
            detail=(
                f'llm_dimensions_evaluated={dimensions_evaluated!r} '
                'is not an integer'
            ),
        )
    evaluated = int(evaluated)
    if evaluated < 0 or evaluated > TOTAL_DIMENSIONS:
        return MergeValidation(
            ok=False,
            reason=REASON_INVALID_DIMENSIONS_EVALUATED,
            detail=(
                f'llm_dimensions_evaluated={evaluated} outside '
                f'0-{TOTAL_DIMENSIONS}'
            ),
        )

    if evaluated < MIN_DIMENSIONS_EVALUATED:
        if score:
            return MergeValidation(
                ok=False,
                reason=REASON_INSUFFICIENT_DIMENSIONS,
                detail=(
                    f'llm_score={llm_score!r} reported with only {evaluated} '
                    f'dimensions evaluated (minimum '
                    f'{MIN_DIMENSIONS_EVALUATED}); spec says omit the score'
                ),
            )
        return MergeValidation(
            ok=True, score=None, needs_research=True,
            dimensions_evaluated=evaluated,
        )

    if score != int(score) or int(score) not in _achievable_scores(evaluated):
        return MergeValidation(
            ok=False,
            reason=REASON_SCORE_DIMENSION_MISMATCH,
            detail=(
                f'llm_score={llm_score!r} is not achievable from '
                f'{evaluated} evaluated dimensions '
                '(must equal floor(yes*100/evaluated))'
            ),
        )

    return MergeValidation(
        ok=True, score=int(score), dimensions_evaluated=evaluated,
    )


def quarantine_row(
    data_dir: Path,
    script: str,
    reason: str,
    row: Mapping[str, object],
    detail: str = '',
) -> Path:
    """Append a rejected result row to the shared quarantine convention.

    File: <data_dir>/quarantine/<script>-<reason>.jsonl, one JSON object
    per line with timestamp, reason, detail, and the full original row so
    it can be corrected and re-processed.
    """
    qdir = Path(data_dir) / QUARANTINE_DIRNAME
    qdir.mkdir(parents=True, exist_ok=True)
    path = qdir / f'{script}-{reason}.jsonl'
    record = {
        'quarantined_at': datetime.now(timezone.utc).isoformat(),
        'script': script,
        'reason': reason,
        'detail': detail,
        'result': dict(row),
    }
    with path.open('a', encoding='utf-8') as f:
        f.write(json.dumps(record, ensure_ascii=False, default=str) + '\n')
    return path


def add_needs_research_flag(flags: str, separator: str = ',') -> str:
    """Append the needs_research flag to a flag string if absent."""
    flags = flags or ''
    if NEEDS_RESEARCH_FLAG in flags:
        return flags
    if not flags:
        return NEEDS_RESEARCH_FLAG
    return f'{flags}{separator}{NEEDS_RESEARCH_FLAG}'
