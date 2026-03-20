#!/usr/bin/env python3
"""
Generate a static HTML dashboard from pipeline CSV data.

Usage:
  uv run job-search/scripts/ops/generate_dashboard.py           # summary dashboard
  uv run job-search/scripts/ops/generate_dashboard.py --full    # full target list

Reads directly from source-of-truth CSVs (target-companies.csv + applications.csv).
Reads brand tokens from /brand/theme.css at build time if available, otherwise uses built-in defaults.
"""
from __future__ import annotations

import argparse
import csv
import html
import sys
from datetime import datetime, date, timedelta
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
DATA = BASE / 'data'
TRACKER_DATA = Path(__file__).resolve().parents[3] / 'job-tracker' / 'data'
BRAND = Path(__file__).resolve().parents[5] / 'brand'


FALLBACK_THEME = """\
:root {
  --bg-deep: #0e1420;
  --bg-base: #181e28;
  --bg-surface: #1e2838;
  --bg-elevated: #263040;
  --text-headline: #f5f8fc;
  --text-body: #c0cad5;
  --text-muted: #5a6a78;
  --text-dim: #4a5a6a;
  --accent: #96c3e6;
  --accent-bg: rgba(150,195,230,0.1);
  --accent-border: rgba(150,195,230,0.08);
  --status-matched: #5cb87a;
  --status-matched-bg: rgba(92,184,122,0.12);
  --status-partial: #d4a043;
  --status-partial-bg: rgba(212,160,67,0.12);
  --status-missing: #cf5555;
  --status-missing-bg: rgba(207,85,85,0.12);
  --accent-light: #2563eb;
  --accent-light-bg: rgba(37,99,235,0.08);
  --card-bg: #ffffff;
  --card-text-primary: #1a2030;
  --card-text-secondary: #3a4a5a;
  --card-text-muted: #8090a0;
  --card-border: #e8ecf0;
}
"""


def read_brand_css() -> str:
    """Read theme.css from brand folder for inlining. Falls back to embedded defaults."""
    path = BRAND / 'theme.css'
    if not path.exists():
        print(f"  INFO: Brand theme not found at {path}, using built-in defaults")
        return FALLBACK_THEME
    return path.read_text(encoding='utf-8')


STALE_DAYS = 14

STATUS_LABELS = {
    'applied': ('Applied', 'status-applied'),
    'researching': ('Researching', 'status-researching'),
    'rejected': ('Rejected', 'status-rejected'),
    'closed': ('Closed', 'status-closed'),
    'declined': ('Declined', 'status-declined'),
    'no_fit_now': ('No Fit', 'status-nofit'),
}


def get_score(row: dict) -> float:
    """Extract score from row. Returns -1.0 for unscored (application-only or watch_list)."""
    val = row.get('llm_score', '')
    if val:
        try:
            return float(val)
        except (ValueError, TypeError):
            pass
    return -1.0


def parse_roles(roles_str: str) -> tuple[list[str], int]:
    """Parse semicolon-delimited roles. Returns (display_roles[:2], total_count)."""
    if not roles_str or not roles_str.strip():
        return [], 0
    parts = [r.strip() for r in roles_str.split(';') if r.strip()]
    return parts[:2], len(parts)


def format_score(score: float) -> str:
    """Format score for display. Returns '—' for unscored."""
    if score < 0:
        return '—'
    return f'{score:.0f}'


def score_color(score: float) -> str:
    """Return CSS class based on score value."""
    if score < 0:
        return 'score-low'
    if score >= 75:
        return 'score-high'
    elif score >= 60:
        return 'score-med'
    return 'score-low'


def escape(val: str) -> str:
    """HTML-escape a string."""
    return html.escape(val or '', quote=True)


def read_target_companies(path: Path | None = None) -> list[dict]:
    """Read target-companies.csv, filter to pass, sort by score descending."""
    if path is None:
        path = DATA / 'target-companies.csv'
    if not path.exists():
        return []
    with path.open(encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    rows = [r for r in rows if r.get('validation_status') == 'pass']
    rows.sort(key=lambda r: get_score(r), reverse=True)
    return rows


def read_applications(path: Path | None = None) -> list[dict]:
    """Read applications.csv. Returns empty list if file not found."""
    if path is None:
        path = TRACKER_DATA / 'applications.csv'
    if not path.exists():
        return []
    with path.open(encoding='utf-8') as f:
        return list(csv.DictReader(f))


def merge_data(targets: list[dict], apps: list[dict]) -> list[dict]:
    """Merge target companies with application data on company name.

    Returns target rows enriched with app_status, date_added,
    last_contact, contact_name fields.
    """
    app_map: dict[str, dict] = {}
    for a in apps:
        key = a.get('company', '').strip().lower()
        if key:
            app_map[key] = a

    # Enrich each target row with application data
    enriched = []
    matched_app_keys: set[str] = set()
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
                'open_positions': app.get('role', ''),
                'careers_url': app.get('job_url', ''),
                'app_status': app.get('status', ''),
                'date_added': app.get('date_added', ''),
                'date_applied': app.get('date_applied', ''),
                'last_contact': app.get('last_contact', ''),
                'contact_name': app.get('contact_name', ''),
                'contact_email': app.get('contact_email', ''),
                'app_notes': app.get('notes', ''),
                'llm_score': '',
                'role_family': '',
            })

    # Deduplicate: one row per company, keep highest score, consolidate roles
    seen: dict[str, dict] = {}
    for row in enriched:
        key = row.get('company', '').strip().lower()
        if key in seen:
            existing = seen[key]
            # Merge open_positions
            existing_roles = existing.get('open_positions', '')
            new_roles = row.get('open_positions', '')
            if new_roles:
                if existing_roles:
                    existing['open_positions'] = existing_roles + '; ' + new_roles
                else:
                    existing['open_positions'] = new_roles
            # Keep higher score
            if get_score(row) > get_score(existing):
                # Preserve merged roles before overwriting
                merged_roles = existing['open_positions']
                existing.update(row)
                existing['open_positions'] = merged_roles
        else:
            seen[key] = row

    return list(seen.values())


def classify_staleness(row: dict) -> str:
    """Classify a company's staleness: 'stale', 'warm', or 'recent'."""
    today = date.today()

    last_contact = row.get('last_contact', '').strip()
    date_added = row.get('date_added', '').strip()

    if last_contact:
        try:
            contact_date = date.fromisoformat(last_contact)
            days_since = (today - contact_date).days
            if days_since >= STALE_DAYS:
                return 'warm'
            return 'recent'
        except ValueError:
            pass

    date_applied = row.get('date_applied', '').strip()
    if date_applied:
        try:
            applied_date = date.fromisoformat(date_applied)
            days_since = (today - applied_date).days
            if days_since >= STALE_DAYS:
                return 'stale'
            return 'recent'
        except ValueError:
            pass

    if date_added:
        try:
            added_date = date.fromisoformat(date_added)
            days_since = (today - added_date).days
            if days_since >= STALE_DAYS:
                return 'stale'
            return 'recent'
        except ValueError:
            pass

    return 'stale'


def suggested_action(row: dict, staleness: str) -> str:
    """Generate suggested next action text based on staleness and contacts."""
    contact = row.get('contact_name', '').strip()
    date_applied = row.get('date_applied', '').strip()
    date_added = row.get('date_added', '').strip()
    ref_date = date_applied or date_added

    if staleness == 'stale':
        if contact:
            return f"Follow up with {contact}"
        return "Consider re-applying or finding a contact"

    if staleness == 'warm':
        if contact:
            return f"Re-engage with {contact}"
        return "Consider re-applying or finding a contact"

    # recent
    if contact and ref_date:
        try:
            ref = date.fromisoformat(ref_date)
            followup_by = ref + timedelta(days=STALE_DAYS)
            return f"Follow up with {contact} if no response by {followup_by.isoformat()}"
        except ValueError:
            pass
    return "Wait for response"


def get_section(row: dict) -> str:
    """Determine which dashboard section a company belongs in."""
    status = row.get('app_status', '').strip()
    if status == 'applied':
        return 'followup'
    if status in ('rejected', 'closed', 'declined', 'no_fit_now'):
        return 'closed_out'
    return 'bestfits'


def _days_since(date_str: str) -> int:
    """Return days since a date string, or -1 if unparseable."""
    if not date_str or not date_str.strip():
        return -1
    try:
        return (date.today() - date.fromisoformat(date_str.strip())).days
    except ValueError:
        return -1


def build_followup_cards(rows: list[dict]) -> str:
    """Build HTML for Applied section: all applied companies as cards.

    Each card gets a data-staleness attribute so JS can filter to
    show only stale ones when "Need Follow-up" pill is clicked.
    Stale cards are visually highlighted with red border.
    """
    if not rows:
        return '<p class="empty-message">No applications to follow up on. Explore best fits below.</p>'

    # Sort by staleness (oldest date_applied first)
    def sort_key(r):
        days = _days_since(r.get('date_applied', '') or r.get('date_added', ''))
        return -days if days >= 0 else -9999

    rows = sorted(rows, key=sort_key)

    cards = []
    for r in rows:
        company = escape(r.get('company', ''))
        score = get_score(r)
        color = score_color(score)
        staleness = classify_staleness(r)
        action = suggested_action(r, staleness)

        display_roles, role_count = parse_roles(
            r.get('open_positions', '') or r.get('role', ''))
        role_text = escape(display_roles[0]) if display_roles else '-'
        if role_count > 1:
            role_text += f' <span class="fc-role-count">(+{role_count - 1} more)</span>'

        date_applied = r.get('date_applied', '').strip() or r.get('date_added', '').strip()
        days = _days_since(date_applied)
        days_text = f'{days} days ago' if days >= 0 else 'unknown'

        try:
            applied_display = datetime.fromisoformat(date_applied).strftime('%b %d')
        except (ValueError, TypeError):
            applied_display = '\u2014'

        contact = escape(r.get('contact_name', '').strip())
        contact_html = f'<div class="fc-contact">{contact}</div>' if contact else ''

        cards.append(f'''<div class="followup-card {staleness}" data-staleness="{staleness}">
  <div class="fc-top">
    <div class="fc-company">{company}</div>
    <span class="fc-score {color}">{format_score(score)}</span>
  </div>
  <div class="fc-role">{role_text}</div>
  <div class="fc-meta">
    <span>Applied {applied_display}</span>
    <span class="{"fc-alert" if staleness == "stale" else ""}">{days_text}</span>
  </div>
  {contact_html}
  <div class="fc-action">{escape(action)}</div>
</div>''')

    return f'<div class="followup-grid" id="followupGrid">{"".join(cards)}</div>'


def build_closed_out_cards(rows: list[dict]) -> str:
    """Build grayed-out cards for rejected/closed/declined/no_fit_now companies."""
    if not rows:
        return ''

    cards = []
    for r in rows:
        company = escape(r.get('company', ''))
        status = r.get('app_status', '').strip()
        label, css_class = STATUS_LABELS.get(status, ('Closed', 'status-closed'))

        display_roles, _ = parse_roles(
            r.get('open_positions', '') or r.get('role', ''))
        role_text = escape(display_roles[0]) if display_roles else '-'

        date_display_str = r.get('date_applied', '').strip() or r.get('date_added', '').strip()
        try:
            date_display = datetime.fromisoformat(date_display_str).strftime('%b %d')
        except (ValueError, TypeError):
            date_display = '\u2014'

        cards.append(f'''<div class="followup-card closed-out">
  <div class="fc-top">
    <div class="fc-company">{company}</div>
    <span class="status-badge {css_class}">{label}</span>
  </div>
  <div class="fc-role">{role_text}</div>
  <div class="fc-meta"><span>{date_display}</span></div>
</div>''')

    return f'''<div class="closed-out-section">
  <h3 class="closed-out-heading">Closed ({len(rows)})</h3>
  <div class="followup-grid">{"".join(cards)}</div>
</div>'''


def build_bestfits_section(rows: list[dict], limit_per_path: int = 3) -> str:
    """Build HTML for Section 2: Best Fits grouped by career path."""
    if not rows:
        return '<p class="empty-message">No companies to explore yet.</p>'

    # Group by path
    path_groups: dict[str, list[dict]] = {}
    for r in rows:
        path = r.get('role_family', '').strip() or 'Other'
        path_groups.setdefault(path, []).append(r)

    # Sort each group by score descending
    for group in path_groups.values():
        group.sort(key=lambda r: get_score(r), reverse=True)

    # Sort paths by highest score in each group
    sorted_paths = sorted(
        path_groups.keys(),
        key=lambda p: get_score(path_groups[p][0]) if path_groups[p] else 0,
        reverse=True,
    )

    sections = []
    for path in sorted_paths:
        group = path_groups[path]
        visible = group if limit_per_path == 0 else group[:limit_per_path]
        hidden = [] if limit_per_path == 0 else group[limit_per_path:]

        def _render_row(r: dict, rank: int) -> str:
            score = get_score(r)
            color = score_color(score)
            company = escape(r.get('company', ''))
            rationale = r.get('llm_rationale', '') or ''
            if len(rationale) > 200:
                rationale = rationale[:197] + '...'
            rationale = escape(rationale)

            display_roles, role_count = parse_roles(r.get('open_positions', ''))
            role_text = escape(', '.join(display_roles[:2])) if display_roles else '-'
            if role_count > 2:
                role_text += f' <span class="cr-role-count">(+{role_count - 2} more)</span>'

            url = (r.get('role_url', '') or r.get('careers_url', '')).strip()
            company_el = f'<a href="{escape(url)}" target="_blank">{company}</a>' if url else company

            return f'''<div class="company-row">
  <span class="cr-rank">#{rank}</span>
  <span class="cr-score {color}">{format_score(score)}</span>
  <span class="cr-name">{company_el}</span>
  <span class="cr-roles">{role_text}</span>
  <span class="cr-rationale">{rationale}</span>
</div>'''

        all_rows_html = [_render_row(r, i) for i, r in enumerate(group, 1)]
        path_id = escape(path.replace(' ', '-').lower())
        count = len(group)

        sections.append(f'''<div class="path-group" data-path-id="{path_id}">
  <div class="path-label" data-toggle-path="{path_id}">
    <span class="path-toggle" id="toggle-{path_id}">&#9654;</span>
    {escape(path)} <span class="path-count">({count})</span>
  </div>
  <div class="path-content" id="content-{path_id}" style="display:none">
    {"".join(all_rows_html)}
  </div>
</div>''')

    toggle_all = '<div class="toggle-all" id="toggleAllBtn">Expand All</div>'
    return toggle_all + '\n'.join(sections)


def build_pipeline_table(rows: list[dict]) -> str:
    """Build HTML for Section 3: Full Pipeline table with filters."""
    paths = sorted(set(
        r.get('role_family', '').strip()
        for r in rows
        if r.get('role_family', '').strip()
    ))
    path_options = '\n'.join(
        f'<option value="{escape(p)}">{escape(p)}</option>' for p in paths)

    table_rows = []
    for r in rows:
        company = escape(r.get('company', ''))
        score = get_score(r)
        color = score_color(score)
        path = escape(r.get('role_family', '').strip() or 'Other')

        display_roles, role_count = parse_roles(r.get('open_positions', ''))
        role_text = escape(', '.join(display_roles[:2])) if display_roles else '-'
        if role_count > 2:
            role_text += f' <span class="role-extra">(+{role_count - 2})</span>'

        status = r.get('app_status', '').strip()
        label, css_class = STATUS_LABELS.get(status, ('Not Applied', 'status-not'))

        last_action_date = (r.get('last_contact', '').strip()
                           or r.get('date_applied', '').strip()
                           or r.get('date_added', '').strip())
        try:
            last_action = datetime.fromisoformat(last_action_date).strftime('%b %d')
        except (ValueError, TypeError):
            last_action = '\u2014'

        url = (r.get('role_url', '') or r.get('careers_url', '')).strip()
        company_el = f'<a href="{escape(url)}" target="_blank">{company}</a>' if url else company

        table_rows.append(f'''<tr data-path="{escape(r.get('role_family', ''))}" data-score="{format_score(score)}" data-status="{escape(status)}">
  <td>{company_el}</td>
  <td class="{color}">{format_score(score)}</td>
  <td>{path}</td>
  <td class="pipeline-roles">{role_text}</td>
  <td><span class="status-badge {css_class}">{label}</span></td>
  <td>{last_action}</td>
</tr>''')

    return f'''<div class="filters">
  <input type="text" id="pipelineSearch" placeholder="Search company or role...">
  <select id="pathFilter">
    <option value="">All Paths</option>
    {path_options}
  </select>
  <select id="statusFilter">
    <option value="">All Status</option>
    <option value="applied">Applied</option>
    <option value="researching">Researching</option>
    <option value="rejected">Rejected</option>
    <option value="not_applied">Not Applied</option>
  </select>
  <select id="scoreFilter">
    <option value="">All Scores</option>
    <option value="75">75+ (High)</option>
    <option value="60">60+ (Med+)</option>
  </select>
</div>

<table class="pipeline-table" id="pipelineTable">
<thead>
<tr>
  <th data-sort-col="0">Company</th>
  <th data-sort-col="1">Score</th>
  <th data-sort-col="2">Path</th>
  <th data-sort-col="3">Roles</th>
  <th data-sort-col="4">Status</th>
  <th data-sort-col="5">Last Action</th>
</tr>
</thead>
<tbody>
{"".join(table_rows)}
</tbody>
</table>'''


def compute_stats(merged: list[dict]) -> dict:
    """Compute dashboard statistics from merged data."""
    followup = [r for r in merged if get_section(r) == 'followup']
    closed_out = [r for r in merged if get_section(r) == 'closed_out']
    bestfits = [r for r in merged if get_section(r) == 'bestfits']
    stale = [r for r in followup if classify_staleness(r) in ('stale', 'warm')]

    return {
        'need_followup': len(stale),
        'applied': len(followup),
        'closed_out': len(closed_out),
        'to_explore': len(bestfits),
        'total': len(followup) + len(closed_out) + len(bestfits),
    }


def build_html(merged: list[dict], full_mode: bool) -> str:
    """Build the complete HTML dashboard string."""
    stats = compute_stats(merged)
    run_date = datetime.now().strftime('%Y-%m-%d %H:%M')
    title = 'Career Dashboard (Full)' if full_mode else 'Career Dashboard'

    followup_rows = [r for r in merged if get_section(r) == 'followup']
    closed_out_rows = [r for r in merged if get_section(r) == 'closed_out']
    bestfit_rows = [r for r in merged if get_section(r) == 'bestfits']
    limit = 0 if full_mode else 3

    followup_html = build_followup_cards(followup_rows)
    closed_out_html = build_closed_out_cards(closed_out_rows)
    bestfits_html = build_bestfits_section(bestfit_rows, limit_per_path=limit)
    pipeline_html = build_pipeline_table(merged)

    stale_count = sum(1 for r in followup_rows if classify_staleness(r) in ('stale', 'warm'))

    brand_css = read_brand_css()
    css = _get_css()
    js = _get_js()

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<link href="https://fonts.googleapis.com/css2?family=Sora:wght@400;600;700&family=DM+Mono:wght@400&display=swap" rel="stylesheet">
<style>
{brand_css}
{css}
</style>
</head>
<body>

<div class="header">
  <h1>{title}</h1>
  <div class="date">Updated {run_date}</div>
</div>

<div class="stats">
  <div class="stat alert stat-clickable" id="pillFollowup">
    <div class="value">{stats['need_followup']}</div>
    <div class="label">Need Follow-up</div>
  </div>
  <div class="stat active stat-clickable" id="pillApplied">
    <div class="value">{stats['applied']}</div>
    <div class="label">Applied</div>
  </div>
  <div class="stat stat-clickable" id="pillExplore">
    <div class="value">{stats['to_explore']}</div>
    <div class="label">To Explore</div>
  </div>
  <div class="stat good stat-clickable" id="pillPipeline">
    <div class="value">{stats['total']}</div>
    <div class="label">Total Pipeline</div>
  </div>
</div>

<div class="section" id="appliedSection" style="display:none">
  <div class="section-header">
    <h2>Applied</h2>
    <span class="badge">{stale_count} need follow-up</span>
  </div>
  {followup_html}
  {closed_out_html}
</div>

<div class="divider"></div>

<div class="section" id="bestFitsSection">
  <div class="section-header">
    <h2>Best Fits to Explore</h2>
    <span class="badge-muted">{stats['to_explore']} not yet applied</span>
  </div>
  {bestfits_html}
</div>

<div class="divider"></div>

<div class="section" id="pipelineSection">
  <div class="section-header">
    <h2>Full Pipeline</h2>
    <span class="badge-muted">{stats['total']} companies</span>
  </div>
  {pipeline_html}
</div>

<p class="generated">Generated {run_date}</p>

<script>
{js}
</script>

</body>
</html>'''


def _get_css() -> str:
    """Return all inline CSS for the dashboard."""
    return '''* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: 'Sora', -apple-system, system-ui, sans-serif; background: #f5f6fa; color: var(--card-text-primary); padding: 24px; }

.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; background: linear-gradient(135deg, var(--bg-deep), var(--bg-base)); padding: 20px 28px; border-radius: 12px; }
.header h1 { font-size: 1.4rem; font-weight: 700; color: var(--text-headline); }
.header .date { color: var(--text-muted); font-size: 0.8rem; }

.stats { display: flex; gap: 12px; margin-bottom: 28px; }
.stat { background: var(--bg-surface); padding: 14px 20px; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.15); flex: 1; text-align: center; border: 1px solid var(--accent-border); }
.stat-clickable { cursor: pointer; transition: box-shadow 0.15s, transform 0.15s; }
.stat-clickable:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.25); transform: translateY(-1px); }
.stat-clickable.stat-active-pill { box-shadow: 0 0 0 2px var(--accent); }
.stat .value { font-size: 1.6rem; font-weight: 700; font-family: 'DM Mono', 'SF Mono', 'Fira Code', monospace; color: #f5f8fc; }
.stat .label { font-size: 0.75rem; color: #8899aa; margin-top: 2px; text-transform: uppercase; letter-spacing: 0.5px; }
.stat.alert .value { color: #ff7b7b; }
.stat.active .value { color: #7bb8ff; }
.stat.good .value { color: #7be6a0; }

.section { margin-bottom: 32px; }
.section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; padding-left: 12px; border-left: 3px solid var(--accent-light); }
.section-header h2 { font-size: 1.1rem; font-weight: 700; }
.badge { background: var(--status-missing); color: #fff; font-size: 0.7rem; padding: 3px 8px; border-radius: 10px; font-weight: 600; }
.badge-muted { background: var(--card-border); color: var(--card-text-secondary); font-size: 0.7rem; padding: 3px 8px; border-radius: 10px; }
.divider { height: 1px; background: var(--card-border); margin: 8px 0 24px; }
.generated { color: var(--card-text-muted); font-size: 0.8rem; margin-top: 20px; }
.empty-message { color: var(--card-text-muted); font-style: italic; padding: 20px 0; }

.followup-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; }
.followup-card { background: var(--card-bg); border-radius: 10px; padding: 16px; box-shadow: 0 1px 4px rgba(0,0,0,0.06); border-left: 4px solid var(--card-border); }
.followup-card.stale { border-left-color: var(--status-missing); }
.followup-card.recent { border-left-color: var(--status-matched); }
.followup-card.warm { border-left-color: var(--status-partial); }
.fc-top { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; }
.fc-company { font-weight: 700; font-size: 0.95rem; }
.fc-score { font-size: 0.8rem; font-weight: 700; padding: 2px 8px; border-radius: 6px; font-family: 'DM Mono', 'SF Mono', 'Fira Code', monospace; }
.fc-score.score-high { background: var(--status-matched-bg); color: var(--status-matched); }
.fc-score.score-med { background: var(--status-partial-bg); color: var(--status-partial); }
.fc-score.score-low { background: var(--status-missing-bg); color: var(--status-missing); }
.fc-role { font-size: 0.82rem; color: var(--card-text-secondary); margin-bottom: 6px; }
.fc-role-count { color: var(--card-text-muted); font-size: 0.75rem; }
.fc-meta { display: flex; gap: 12px; font-size: 0.75rem; color: var(--card-text-muted); }
.fc-alert { color: var(--status-missing); font-weight: 600; }
.fc-contact { font-size: 0.78rem; color: var(--accent-light); margin-top: 6px; }
.fc-action { margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--card-border); font-size: 0.8rem; color: var(--card-text-secondary); font-style: italic; }

.path-group { margin-bottom: 16px; }
.path-label { font-size: 0.8rem; font-weight: 600; color: var(--accent-light); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; padding: 8px 14px; background: linear-gradient(135deg, #eef4fb, #e8edf5); border-radius: 6px; cursor: pointer; border-left: 3px solid var(--accent-light); }
.company-row { background: var(--card-bg); border-radius: 8px; padding: 12px 16px; margin-bottom: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); display: flex; align-items: center; gap: 16px; }
.company-row:hover { background: #f8f9ff; }
.cr-rank { font-size: 0.75rem; color: var(--card-text-muted); font-weight: 600; width: 24px; }
.cr-score { font-weight: 700; font-size: 0.85rem; width: 32px; font-family: 'DM Mono', 'SF Mono', 'Fira Code', monospace; }
.cr-score.score-high { color: var(--status-matched); }
.cr-score.score-med { color: var(--status-partial); }
.cr-score.score-low { color: var(--status-missing); }
.cr-name { font-weight: 600; font-size: 0.9rem; min-width: 140px; }
.cr-name a { color: var(--accent-light); text-decoration: none; }
.cr-name a:hover { text-decoration: underline; }
.cr-roles { font-size: 0.82rem; color: var(--card-text-secondary); max-width: 200px; }
.cr-role-count { color: var(--card-text-muted); font-size: 0.75rem; }
.cr-rationale { font-size: 0.78rem; color: var(--card-text-muted); flex: 1; }
.show-more { text-align: center; padding: 8px; color: var(--accent-light); font-size: 0.85rem; cursor: pointer; }
.show-more:hover { text-decoration: underline; }
.path-toggle { display: inline-block; font-size: 0.7rem; margin-right: 6px; transition: transform 0.2s; }
.path-toggle.open { transform: rotate(90deg); }
.path-count { color: var(--card-text-muted); font-weight: 400; font-size: 0.75rem; }
.toggle-all { text-align: right; color: var(--accent-light); font-size: 0.82rem; cursor: pointer; margin-bottom: 12px; }
.toggle-all:hover { text-decoration: underline; }
.followup-card.filter-hidden { display: none; }

.filters { display: flex; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
.filters select, .filters input { padding: 6px 10px; border: 1px solid var(--card-border); border-radius: 6px; font-size: 0.8rem; background: var(--card-bg); }
.filters input { width: 200px; }
.pipeline-table { width: 100%; border-collapse: collapse; background: var(--card-bg); border-radius: 10px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.06); font-size: 0.82rem; }
.pipeline-table th { background: var(--bg-elevated); padding: 10px 14px; text-align: left; font-size: 0.75rem; color: #a0b0c0; text-transform: uppercase; letter-spacing: 0.3px; border-bottom: none; cursor: pointer; user-select: none; font-weight: 600; }
.pipeline-table th:hover { background: var(--bg-surface); color: #f5f8fc; }
.pipeline-table td { padding: 10px 14px; border-bottom: 1px solid var(--card-border); }
.pipeline-table tr:hover { background: #fafbff; }
.pipeline-table a { color: var(--accent-light); text-decoration: none; }
.pipeline-table a:hover { text-decoration: underline; }
.pipeline-roles { max-width: 250px; }
.role-extra { color: var(--card-text-muted); font-size: 0.75rem; }
.status-badge { font-size: 0.7rem; padding: 3px 10px; border-radius: 5px; font-weight: 600; white-space: nowrap; border: 1px solid transparent; }
.status-applied { background: var(--accent-light); color: #fff; }
.status-researching { background: var(--accent-light-bg); color: var(--accent-light); border-color: var(--accent-light); }
.status-rejected { background: var(--status-missing); color: #fff; }
.status-closed { background: var(--card-text-muted); color: #fff; }
.status-declined { background: var(--status-partial); color: #fff; }
.status-nofit { background: var(--card-border); color: var(--card-text-muted); }
.status-not { background: var(--card-border); color: var(--card-text-muted); }
.closed-out-section { margin-top: 2rem; }
.closed-out-heading { color: var(--card-text-muted); font-size: 0.9rem; font-weight: 600; margin-bottom: 0.75rem; border-top: 1px solid var(--card-border); padding-top: 1rem; }
.followup-card.closed-out { opacity: 0.45; border-color: var(--card-border); }
.followup-card.closed-out:hover { opacity: 0.7; }'''


def _get_js() -> str:
    """Return all inline JavaScript for the dashboard."""
    return '''(function() {
  // --- Pipeline table filter ---
  function filterPipeline() {
    var search = (document.getElementById('pipelineSearch').value || '').toLowerCase();
    var pathVal = document.getElementById('pathFilter').value;
    var statusVal = document.getElementById('statusFilter').value;
    var scoreVal = document.getElementById('scoreFilter').value;
    var minScore = scoreVal ? parseFloat(scoreVal) : 0;

    var rows = document.querySelectorAll('#pipelineTable tbody tr');
    for (var i = 0; i < rows.length; i++) {
      var tr = rows[i];
      var text = tr.textContent.toLowerCase();
      var path = tr.dataset.path || '';
      var score = parseFloat(tr.dataset.score) || 0;
      var status = tr.dataset.status || '';

      var matchSearch = !search || text.indexOf(search) !== -1;
      var matchPath = !pathVal || path === pathVal;
      var matchScore = score >= minScore;
      var matchStatus = true;
      if (statusVal === 'not_applied') {
        matchStatus = !status;
      } else if (statusVal) {
        matchStatus = status === statusVal;
      }
      tr.style.display = (matchSearch && matchPath && matchScore && matchStatus) ? '' : 'none';
    }
  }

  document.getElementById('pipelineSearch').addEventListener('input', filterPipeline);
  document.getElementById('pathFilter').addEventListener('change', filterPipeline);
  document.getElementById('statusFilter').addEventListener('change', filterPipeline);
  document.getElementById('scoreFilter').addEventListener('change', filterPipeline);

  // --- Pipeline table sort ---
  var ths = document.querySelectorAll('#pipelineTable th[data-sort-col]');
  for (var i = 0; i < ths.length; i++) {
    ths[i].addEventListener('click', function() {
      var colIdx = parseInt(this.dataset.sortCol);
      var table = document.getElementById('pipelineTable');
      var tbody = table.querySelector('tbody');
      var rows = Array.prototype.slice.call(tbody.querySelectorAll('tr'));

      var dir = table.dataset.sortCol == colIdx && table.dataset.sortDir === 'asc' ? 'desc' : 'asc';
      table.dataset.sortCol = colIdx;
      table.dataset.sortDir = dir;

      rows.sort(function(a, b) {
        var aVal = a.cells[colIdx] ? a.cells[colIdx].textContent.trim() : '';
        var bVal = b.cells[colIdx] ? b.cells[colIdx].textContent.trim() : '';
        var aNum = parseFloat(aVal);
        var bNum = parseFloat(bVal);
        if (!isNaN(aNum) && !isNaN(bNum)) {
          return dir === 'asc' ? aNum - bNum : bNum - aNum;
        }
        return dir === 'asc' ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
      });

      for (var j = 0; j < rows.length; j++) {
        tbody.appendChild(rows[j]);
      }
    });
  }

  // --- Path group expand/collapse ---
  var pathLabels = document.querySelectorAll('.path-label[data-toggle-path]');
  for (var i = 0; i < pathLabels.length; i++) {
    pathLabels[i].addEventListener('click', function() {
      var pathId = this.dataset.togglePath;
      var content = document.getElementById('content-' + pathId);
      var toggle = document.getElementById('toggle-' + pathId);
      if (content.style.display === 'none') {
        content.style.display = 'block';
        toggle.classList.add('open');
      } else {
        content.style.display = 'none';
        toggle.classList.remove('open');
      }
    });
  }

  // --- Expand/Collapse All ---
  document.getElementById('toggleAllBtn').addEventListener('click', function() {
    var contents = document.querySelectorAll('.path-content');
    var toggles = document.querySelectorAll('.path-toggle');
    var btn = this;
    var anyHidden = false;
    for (var i = 0; i < contents.length; i++) {
      if (contents[i].style.display === 'none') { anyHidden = true; break; }
    }
    for (var i = 0; i < contents.length; i++) {
      contents[i].style.display = anyHidden ? 'block' : 'none';
    }
    for (var i = 0; i < toggles.length; i++) {
      if (anyHidden) { toggles[i].classList.add('open'); }
      else { toggles[i].classList.remove('open'); }
    }
    btn.textContent = anyHidden ? 'Collapse All' : 'Expand All';
  });

  // --- Stats pills ---
  function clearPillHighlight() {
    var pills = document.querySelectorAll('.stat-clickable');
    for (var i = 0; i < pills.length; i++) {
      pills[i].classList.remove('stat-active-pill');
    }
  }

  document.getElementById('pillFollowup').addEventListener('click', function() {
    clearPillHighlight();
    this.classList.add('stat-active-pill');
    document.getElementById('appliedSection').style.display = '';
    var cards = document.querySelectorAll('.followup-card');
    for (var i = 0; i < cards.length; i++) {
      var s = cards[i].dataset.staleness;
      if (s === 'stale' || s === 'warm') {
        cards[i].classList.remove('filter-hidden');
      } else {
        cards[i].classList.add('filter-hidden');
      }
    }
    document.getElementById('appliedSection').scrollIntoView({behavior: 'smooth'});
  });

  document.getElementById('pillApplied').addEventListener('click', function() {
    clearPillHighlight();
    this.classList.add('stat-active-pill');
    document.getElementById('appliedSection').style.display = '';
    var cards = document.querySelectorAll('.followup-card');
    for (var i = 0; i < cards.length; i++) {
      cards[i].classList.remove('filter-hidden');
    }
    document.getElementById('appliedSection').scrollIntoView({behavior: 'smooth'});
  });

  document.getElementById('pillExplore').addEventListener('click', function() {
    clearPillHighlight();
    this.classList.add('stat-active-pill');
    document.getElementById('bestFitsSection').scrollIntoView({behavior: 'smooth'});
  });

  document.getElementById('pillPipeline').addEventListener('click', function() {
    clearPillHighlight();
    this.classList.add('stat-active-pill');
    document.getElementById('pipelineSection').scrollIntoView({behavior: 'smooth'});
  });

})();'''


def main():
    parser = argparse.ArgumentParser(description='Generate career manager dashboard')
    parser.add_argument('--full', action='store_true', help='Show all companies per path')
    args = parser.parse_args()

    print("\n[Dashboard] Reading CSV data...")

    targets = read_target_companies()
    apps = read_applications()
    merged = merge_data(targets, apps)

    print(f"  {len(targets)} target companies, {len(apps)} applications")

    html_content = build_html(merged, full_mode=args.full)

    if args.full:
        output_path = DATA / 'dashboard-full.html'
    else:
        output_path = DATA / 'dashboard.html'

    output_path.write_text(html_content, encoding='utf-8')
    print(f"  Dashboard written: {output_path}")
    print(f"\n  Dashboard ready: file://{output_path}")


if __name__ == '__main__':
    main()
