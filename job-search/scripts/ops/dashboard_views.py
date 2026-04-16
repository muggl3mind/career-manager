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

sys.path.insert(0, str(BASE.parent / 'scripts'))
try:
    from config_loader import get as _pipeline_cfg
except Exception:
    _pipeline_cfg = lambda key, default=None: default  # noqa: E731

DEFAULT_CFG = {
    'apply_min_score': _pipeline_cfg('pipeline.action_list.apply_min_score', 70),
    'watch_min_score': _pipeline_cfg('pipeline.action_list.watch_min_score', 85),
    'watch_max_rows': _pipeline_cfg('pipeline.action_list.watch_max_rows', 20),
}

_CLOSED_STATUSES = {'rejected', 'closed', 'declined', 'no_fit_now'}


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

    targets = _read_csv(target_csv)
    apps = _read_csv(apps_csv)

    # Build app lookup
    app_map: dict[str, dict] = {}
    for a in apps:
        key = a.get('company', '').strip().lower()
        if key:
            app_map[key] = a

    # Enrich targets with app data, track which app keys matched
    matched_app_keys: set[str] = set()
    enriched: list[dict] = []
    for t in targets:
        row = dict(t)
        key = t.get('company', '').strip().lower()
        app = app_map.get(key, {})
        if app:
            matched_app_keys.add(key)
        row['app_status'] = app.get('status', '')
        row['date_added'] = app.get('date_added', '')
        row['date_applied'] = app.get('date_applied', '')
        row['last_contact'] = app.get('last_contact', '')
        row['contact_name'] = app.get('contact_name', '')
        row['contact_email'] = app.get('contact_email', '')
        row['app_notes'] = app.get('notes', '')
        enriched.append(row)

    # Add application-only entries (not in target-companies.csv)
    for key, app in app_map.items():
        if key not in matched_app_keys:
            enriched.append({
                'company': app.get('company', ''),
                'llm_score': '',
                'role_family': '',
                'open_positions': app.get('role', ''),
                'careers_url': app.get('job_url', ''),
                'role_url': app.get('job_url', ''),
                'app_status': app.get('status', ''),
                'date_added': app.get('date_added', ''),
                'date_applied': app.get('date_applied', ''),
                'last_contact': app.get('last_contact', ''),
                'contact_name': app.get('contact_name', ''),
                'contact_email': app.get('contact_email', ''),
                'app_notes': app.get('notes', ''),
                'lifecycle_state': 'active',
                'validation_status': 'pass',
            })

    explore_min = cfg.get('explore_min_score', 50)

    # Partition
    follow_up: list[dict] = []
    best_fits: list[dict] = []
    worth_exploring: list[dict] = []
    closed_out: list[dict] = []

    for row in enriched:
        status = row.get('app_status', '').strip()
        score = _get_score(row)

        # Applied → follow_up
        if status == 'applied':
            follow_up.append(row)
            continue

        # Rejected/closed → closed_out
        if status in _CLOSED_STATUSES:
            closed_out.append(row)
            continue

        # Must be lifecycle active
        if not _is_active_lifecycle(row):
            continue

        # All active companies scoring >= apply_min go to best_fits
        # role_url is a display bonus (clickable link), not a gate
        if score >= apply_min:
            best_fits.append(row)
        elif score >= explore_min:
            worth_exploring.append(row)

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
