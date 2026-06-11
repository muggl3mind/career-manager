"""
Shared filter logic for the career dashboard and action-list CSV.

Single source of truth: both generate_dashboard.py and run_pipeline.py consume
the output of build_active_views() so filter logic is never duplicated.
"""
from __future__ import annotations

import csv
import sys
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]

sys.path.insert(0, str(BASE / 'scripts' / 'core'))
sys.path.insert(0, str(BASE.parent / 'scripts'))
from opportunities import (
    APPLIED_APP_STATUSES,
    CLOSED_APP_STATUSES,
    application_to_view_row,
    matching_applications,
    opportunity_to_view_row,
    opportunities_from_targets,
)

try:
    from config_loader import get as _pipeline_cfg
except Exception:
    _pipeline_cfg = lambda key, default=None: default  # noqa: E731

DEFAULT_CFG = {
    'apply_min_score': _pipeline_cfg('pipeline.action_list.apply_min_score', 70),
    'watch_min_score': _pipeline_cfg('pipeline.action_list.watch_min_score', 85),
    'watch_max_rows': _pipeline_cfg('pipeline.action_list.watch_max_rows', 20),
}

_CLOSED_STATUSES = CLOSED_APP_STATUSES


def _read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding='utf-8') as f:
        return list(csv.DictReader(f))


def _get_score(row: dict) -> float:
    raw = (row.get('llm_score') or '').strip()
    try:
        return float(raw) if raw else 0.0
    except (ValueError, TypeError):
        return 0.0


def _is_active_lifecycle(row: dict) -> bool:
    state = (row.get('lifecycle_state') or '').strip()
    if state:
        return state == 'active'
    return row.get('validation_status') == 'pass'


def _split_roles(value: str) -> list[str]:
    roles = []
    for part in (value or '').split(';'):
        role = ' '.join(part.split())
        if role and role not in roles:
            roles.append(role)
    return roles


def _merge_role_list(left: str, right: str) -> str:
    roles = _split_roles(left)
    for role in _split_roles(right):
        if role not in roles:
            roles.append(role)
    return '; '.join(sorted(roles))


def _aggregate_by_company(rows: list[dict]) -> list[dict]:
    """Collapse display rows to one row per company while preserving role coverage."""
    by_company: dict[str, dict] = {}
    for row in rows:
        key = (row.get('company') or '').strip().lower()
        if not key:
            continue
        row = dict(row)
        if not (row.get('apply_url') or '').strip():
            row['apply_url'] = (
                (row.get('role_url') or '').strip()
                or (row.get('careers_url') or '').strip()
                or (row.get('source_key') or '').strip()
            )
        if key not in by_company:
            by_company[key] = row
            continue

        existing = by_company[key]
        existing['open_positions'] = _merge_role_list(
            existing.get('open_positions', ''),
            row.get('open_positions', ''),
        )
        existing['role_title'] = existing['open_positions']
        existing['opportunity_key'] = _merge_role_list(
            existing.get('opportunity_key', ''),
            row.get('opportunity_key', ''),
        )
        for field in ('role_url', 'apply_url', 'careers_url', 'source_key'):
            if not (existing.get(field) or '').strip() and (row.get(field) or '').strip():
                existing[field] = row[field]
        if not (existing.get('apply_url') or '').strip():
            existing['apply_url'] = (
                (existing.get('role_url') or '').strip()
                or (existing.get('careers_url') or '').strip()
                or (existing.get('source_key') or '').strip()
            )

        if _get_score(row) > _get_score(existing):
            keep = {
                'open_positions': existing['open_positions'],
                'role_title': existing['role_title'],
                'opportunity_key': existing['opportunity_key'],
                'role_url': existing.get('role_url', ''),
                'apply_url': existing.get('apply_url', ''),
                'careers_url': existing.get('careers_url', ''),
                'source_key': existing.get('source_key', ''),
            }
            existing.update(row)
            existing.update(keep)

    return list(by_company.values())


def aggregate_display_rows(rows: list[dict]) -> list[dict]:
    """Public wrapper for company-level dashboard/table display rows."""
    return _aggregate_by_company(rows)


def build_active_views(
    target_csv: Path,
    apps_csv: Path,
    cfg: dict | None = None,
) -> dict:
    """
    Build the four dashboard sections from target-companies.csv + applications.csv.

    Returns:
        {
            'follow_up':      [...],  # applied companies (for follow-up tracking)
            'apply_now':      [...],  # active + role_url + score >= apply_min
            'watch_outreach': [...],  # active + no role_url + score >= watch_min (capped)
            'closed_out':     [...],  # rejected / declined / no_fit_now
            'stats': {
                'follow_up': int,
                'apply_now': int,
                'watch_outreach': int,
                'closed_out': int,
                'total': int,
            },
        }
    """
    cfg = cfg or DEFAULT_CFG
    apply_min = cfg.get('apply_min_score', 70)
    watch_min = cfg.get('watch_min_score', 85)
    watch_max = cfg.get('watch_max_rows', 20)

    opportunities_csv = target_csv.parent / 'opportunities.csv'
    opportunities = _read_csv(opportunities_csv)
    if not opportunities:
        opportunities = opportunities_from_targets(_read_csv(target_csv))
    apps = _read_csv(apps_csv)

    explore_min = cfg.get('explore_min_score', 50)

    # Partition
    follow_up: list[dict] = []
    best_fits: list[dict] = []
    worth_exploring: list[dict] = []
    closed_out: list[dict] = []
    matched_app_ids: set[int] = set()

    for opportunity in opportunities:
        matches = matching_applications(opportunity, apps)
        for app in matches:
            matched_app_ids.add(id(app))
        active_matches = [a for a in matches if (a.get('status') or '').strip() in APPLIED_APP_STATUSES]
        closed_matches = [a for a in matches if (a.get('status') or '').strip() in _CLOSED_STATUSES]

        if active_matches:
            follow_up.append(opportunity_to_view_row(opportunity, active_matches[-1]))
            continue
        if closed_matches:
            closed_out.append(opportunity_to_view_row(opportunity, closed_matches[-1]))
            continue

        row = opportunity_to_view_row(opportunity, matches[-1] if matches else None)
        score = _get_score(row)

        # Must be lifecycle active
        if not _is_active_lifecycle(row):
            continue

        # All active companies scoring >= apply_min go to best_fits
        # role_url is a display bonus (clickable link), not a gate
        if score >= apply_min:
            best_fits.append(row)
        elif score >= explore_min:
            worth_exploring.append(row)

    # Add application-only entries that did not match a current opportunity.
    for app in apps:
        if id(app) in matched_app_ids:
            continue
        status = (app.get('status') or '').strip()
        row = application_to_view_row(app)
        if status in APPLIED_APP_STATUSES:
            follow_up.append(row)
        elif status in _CLOSED_STATUSES:
            closed_out.append(row)

    follow_up = _aggregate_by_company(follow_up)
    best_fits = _aggregate_by_company(best_fits)
    worth_exploring = _aggregate_by_company(worth_exploring)
    closed_out = _aggregate_by_company(closed_out)

    # Sort
    follow_up.sort(key=lambda r: r.get('date_applied') or r.get('date_added') or '', reverse=False)
    best_fits.sort(key=lambda r: _get_score(r), reverse=True)
    worth_exploring.sort(key=lambda r: _get_score(r), reverse=True)

    return {
        'follow_up': follow_up,
        'best_fits': best_fits,
        'worth_exploring': worth_exploring,
        'closed_out': closed_out,
        'stats': {
            'follow_up': len(follow_up),
            'best_fits': len(best_fits),
            'worth_exploring': len(worth_exploring),
            'closed_out': len(closed_out),
            'total': len(follow_up) + len(best_fits) + len(worth_exploring) + len(closed_out),
        },
    }
