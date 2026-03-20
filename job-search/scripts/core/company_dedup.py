"""Dedup logic for company entries. Used by all merge scripts."""
from __future__ import annotations

from path_normalizer import normalize_company


def find_existing(company_name: str, rows: list[dict]) -> dict | None:
    """Find existing row matching company name (exact or alias).

    Uses normalize_company() to handle known aliases like
    "Allvue" -> "Allvue Systems".
    """
    canonical = normalize_company(company_name).strip().lower()
    if not canonical:
        return None
    for row in rows:
        existing_canonical = normalize_company(row.get('company', '')).strip().lower()
        if canonical == existing_canonical:
            return row
    return None


def merge_into_existing(existing: dict, new_data: dict) -> None:
    """Merge new_data into existing row. Keeps higher score, combines roles."""
    # Combine open_positions
    old_roles = existing.get('open_positions', '')
    new_roles = new_data.get('open_positions', '')
    if new_roles and new_roles.lower() not in (old_roles or '').lower():
        existing['open_positions'] = (old_roles + '; ' + new_roles).strip('; ')

    # Keep higher score
    try:
        old_score = float(existing.get('llm_score', '') or 0)
    except ValueError:
        old_score = 0
    try:
        new_score = float(new_data.get('llm_score', '') or 0)
    except ValueError:
        new_score = 0

    if new_score > old_score:
        for key in ('llm_score', 'llm_rationale', 'llm_flags', 'llm_evaluated_at',
                     'role_family', 'website',
                     'industry', 'size', 'stage', 'recent_funding', 'tech_signals'):
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
