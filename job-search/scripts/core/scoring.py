#!/usr/bin/env python3
"""Canonical fit-score calculation for the job-search pipeline.

Single source of truth for the March 2026 ratio scoring method
(docs/superpowers/specs/2026-03-16-scoring-redesign.md):

- Each of the 10 rubric dimensions in references/criteria.md is assessed
  yes (fits), no (does not fit), or unknown (cannot determine).
- Unknown dimensions are null, never 0. They are excluded from the score,
  so a company is never penalized for missing information.
- score = (yes_count / evaluated_count) * 100
- A score is only produced when at least MIN_DIMENSIONS_EVALUATED of the
  TOTAL_DIMENSIONS dimensions were evaluated. Below that threshold the
  company is flagged "needs_research" and no score is emitted.
- The keyword scorer is a fallback only. It runs on rows with no llm_score
  and never overrides one.

Rounding follows the spec's worked example (7 yes of 8 evaluated = 87):
the ratio is floored, not rounded half up.

Any other description of scoring (SKILL.md prose, exported agent context
files, the onboarding criteria.md template) must defer to this module.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional

MIN_DIMENSIONS_EVALUATED = 5
TOTAL_DIMENSIONS = 10
NEEDS_RESEARCH_FLAG = 'needs_research'

# Agent-facing prompt text. Embed this wherever agents are instructed to
# score companies, so every agent sees the identical method.
SCORING_INSTRUCTIONS = (
    'SCORING (canonical ratio method, scripts/core/scoring.py):\n'
    '- Assess each of the 10 dimensions in references/criteria.md as yes (fits), '
    'no (does not fit), or unknown (cannot determine).\n'
    '- Unknown dimensions are null, never 0. They are excluded from the score.\n'
    '- llm_score = (yes count / evaluated count) * 100, rounded down. '
    'Example: 7 yes of 8 evaluated = 87.\n'
    '- llm_dimensions_evaluated = number of dimensions assessed yes or no '
    '(unknowns do not count).\n'
    '- If fewer than 5 of 10 dimensions are evaluable, set llm_flags to '
    '"needs_research" and omit llm_score.\n'
    '- The keyword scorer is a fallback only. It never overrides an llm_score.\n'
)

# Field documentation for exported results-schema dictionaries.
LLM_SCORE_FIELD_DOC = (
    'Integer 0-100: (yes dimensions / evaluated dimensions) * 100, rounded down. '
    'Unknown dimensions are null, never 0. Omit if fewer than 5 of 10 dimensions '
    'were evaluable (set llm_flags to "needs_research" instead).'
)
LLM_DIMENSIONS_EVALUATED_FIELD_DOC = (
    'How many of the 10 dimensions you assessed as yes or no (unknowns excluded). '
    'Minimum 5 to produce a score.'
)


@dataclass(frozen=True)
class ScoreResult:
    """Outcome of a ratio-score computation.

    score is None when fewer than the minimum number of dimensions were
    evaluated (needs_research is True in that case).
    """

    score: Optional[int]
    dimensions_evaluated: int
    yes_count: int
    needs_research: bool
    dimensions_total: int = TOTAL_DIMENSIONS


def classify_dimension(value: object) -> Optional[bool]:
    """Normalize one dimension assessment to True (yes), False (no), or None (unknown).

    Accepted inputs: booleans, None, 0/1, and the strings
    yes/no/true/false/y/n/0/1/unknown/null/none/n/a/na/'' (case-insensitive).
    Anything else raises ValueError so contract violations surface early.
    """
    if value is None:
        return None
    if isinstance(value, bool):
        return value
    if isinstance(value, (int, float)):
        if value == 1:
            return True
        if value == 0:
            return False
        raise ValueError(
            f'Dimension value {value!r} is not a yes/no/unknown assessment. '
            'The ratio method uses true/false/null, not numeric scales.'
        )
    if isinstance(value, str):
        v = value.strip().lower()
        if v in ('yes', 'true', 'y', '1'):
            return True
        if v in ('no', 'false', 'n', '0'):
            return False
        if v in ('', 'unknown', 'null', 'none', 'n/a', 'na'):
            return None
        raise ValueError(
            f'Dimension value {value!r} is not a yes/no/unknown assessment.'
        )
    raise ValueError(
        f'Dimension value {value!r} ({type(value).__name__}) is not a '
        'yes/no/unknown assessment.'
    )


def compute_score(
    dimensions: Optional[Mapping[str, object]],
    minimum_evaluated: int = MIN_DIMENSIONS_EVALUATED,
) -> ScoreResult:
    """Compute the canonical ratio score from a dimensions mapping.

    dimensions maps dimension name to a yes/no/unknown assessment (see
    classify_dimension). Missing keys and None/unknown values are treated
    identically: not evaluated, excluded from the ratio, never counted as 0.

    Returns a ScoreResult. score is the floored ratio percentage, or None
    (with needs_research True) when fewer than minimum_evaluated dimensions
    were assessed yes or no.
    """
    yes_count = 0
    no_count = 0
    for raw in (dimensions or {}).values():
        verdict = classify_dimension(raw)
        if verdict is True:
            yes_count += 1
        elif verdict is False:
            no_count += 1

    evaluated = yes_count + no_count
    if evaluated < minimum_evaluated or evaluated == 0:
        return ScoreResult(
            score=None,
            dimensions_evaluated=evaluated,
            yes_count=yes_count,
            needs_research=True,
        )

    return ScoreResult(
        score=(yes_count * 100) // evaluated,
        dimensions_evaluated=evaluated,
        yes_count=yes_count,
        needs_research=False,
    )
