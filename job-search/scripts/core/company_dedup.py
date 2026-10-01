"""Dedup logic for company entries. Used by all merge scripts."""
from __future__ import annotations

from path_normalizer import normalize_company


def find_existing(company_name: str, rows: list[dict]) -> dict | None:
    """Find existing row matching company name (exact or alias).

    Uses normalize_company() to handle known aliases defined
    in search-config.json company_aliases.
    """
    canonical = normalize_company(company_name).strip().lower()
    if not canonical:
        return None
    for row in rows:
        existing_canonical = normalize_company(row.get('company', '')).strip().lower()
        if canonical == existing_canonical:
            return row
    return None


# Fields that describe one evaluation verdict. When a newer evaluation
# wins, these are taken as a unit (a verdict's score, rationale, and
# flags belong together). Only keys present in new_data are written, so
# callers that do not track a field never blank it.
EVALUATION_FIELDS = (
    'llm_score', 'llm_dimensions_evaluated', 'llm_rationale',
    'llm_flags', 'llm_evaluated_at',
)

# Company profile fields: copied only when the new evaluation wins and
# the new value is non-empty (never blank profile data).
PROFILE_FIELDS = (
    'role_family', 'website', 'industry', 'size', 'stage',
    'recent_funding', 'tech_signals',
)


def _parse_score(raw: object) -> float | None:
    """Parse an llm_score cell. None means "not scored" (empty or garbage).

    A score of 0 is a real evaluation result and parses to 0.0; it is
    never conflated with an empty cell (finding H2).
    """
    if raw is None:
        return None
    text = str(raw).strip()
    if not text:
        return None
    try:
        return float(text)
    except ValueError:
        return None


def _new_evaluation_wins(existing: dict, new_data: dict) -> bool:
    """Decide whether new_data's evaluation replaces existing's.

    Newer evaluation wins over older (finding H1): llm_evaluated_at
    timestamps are compared, so a re-evaluation can LOWER a stale score.
    Same-run duplicates (equal or missing timestamps on both sides) keep
    the genuine dedup semantics: higher score wins.

    A new result with no score at all (None, not 0) never clobbers an
    existing scored evaluation, regardless of timestamps.
    """
    old_score = _parse_score(existing.get('llm_score'))
    new_score = _parse_score(new_data.get('llm_score'))
    if new_score is None:
        return False

    old_at = str(existing.get('llm_evaluated_at') or '').strip()
    new_at = str(new_data.get('llm_evaluated_at') or '').strip()
    if new_at != old_at:
        # ISO-8601 timestamps compare correctly as strings; an empty
        # timestamp always loses to a dated one.
        return new_at > old_at

    # Same run (or no timestamps at all): keep the higher score.
    return old_score is None or new_score > old_score


def merge_into_existing(existing: dict, new_data: dict) -> None:
    """Merge new_data into existing row.

    Combines roles; the newer evaluation wins over the older one
    (same-run duplicates keep the higher score, see _new_evaluation_wins).
    """
    # Combine open_positions. Watch-list placeholders ("None — watch list")
    # must not survive alongside real roles.
    old_roles = existing.get('open_positions', '')
    new_roles = new_data.get('open_positions', '')
    if new_roles:
        parts = [p for p in (old_roles or '').split('; ')
                 if p and not p.lower().startswith('none')]
        if not new_roles.lower().startswith('none'):
            if new_roles.lower() not in '; '.join(parts).lower():
                parts.append(new_roles)
        elif not parts:
            parts = [new_roles]
        existing['open_positions'] = '; '.join(parts)

    if _new_evaluation_wins(existing, new_data):
        for key in EVALUATION_FIELDS:
            if key in new_data:
                existing[key] = new_data[key]
        for key in PROFILE_FIELDS:
            if new_data.get(key):
                existing[key] = new_data[key]

    # Prefer specific role_url over generic careers_url (independent of score)
    new_role_url = new_data.get('role_url', '').strip()
    if new_role_url and not existing.get('role_url', '').strip():
        existing['role_url'] = new_role_url

    # Prefer a careers_url if we don't have one yet
    new_careers_url = new_data.get('careers_url', '').strip()
    if new_careers_url and not existing.get('careers_url', '').strip():
        existing['careers_url'] = new_careers_url

    # Always update last_checked to most recent
    existing['last_checked'] = max(
        existing.get('last_checked', ''),
        new_data.get('last_checked', '')
    )
