#!/usr/bin/env python3
"""
Generate a single self-contained interactive HTML dashboard from pipeline CSV data.

Usage:
  uv run job-search/scripts/ops/generate_dashboard.py           # summary dashboard
  uv run job-search/scripts/ops/generate_dashboard.py --full    # full target list

Reads directly from source-of-truth CSVs (target-companies.csv + applications.csv).
Reads brand tokens from /brand/theme.css at build time if available, otherwise uses
built-in defaults.

Rendering model: the Python side only computes data (scores, sections, staleness,
suggested actions, etc.) and serializes it to JSON. That JSON is embedded in the
emitted HTML inside a <script type="application/json"> block, and a single inline
<script> (vanilla JS, no dependencies) renders every section, chart, filter and
expandable detail card client-side. The page is fully self-contained: no CDN links,
no web fonts, no external images, no fetch calls. It works offline from file://.
"""
from __future__ import annotations

import argparse
import csv
import html
import json
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


def read_watch_list_companies(path: Path | None = None) -> list[dict]:
    """Read watch_list companies with score >= 50, sorted by score descending."""
    if path is None:
        path = DATA / 'target-companies.csv'
    if not path.exists():
        return []
    with path.open(encoding='utf-8') as f:
        rows = list(csv.DictReader(f))
    watch = [r for r in rows if r.get('validation_status') == 'watch_list' and get_score(r) >= 50]
    watch.sort(key=lambda r: get_score(r), reverse=True)
    return watch


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


# ---------------------------------------------------------------------------
# Data-assembly layer: turns merged/view rows into plain JSON-serializable
# records. Nothing below builds HTML strings — the client-side script owns
# all markup, so field values are kept as raw text (never HTML-escaped here);
# the renderer uses textContent/DOM APIs, which is XSS-safe by construction.
# ---------------------------------------------------------------------------

def _score_tier(score: float) -> str:
    """Bucket a score for the client-side score-tier filter and histogram."""
    if score < 0:
        return 'unscored'
    if score >= 85:
        return 'tier_85'
    if score >= 70:
        return 'tier_70'
    if score >= 60:
        return 'tier_60'
    return 'tier_below_60'


def _split_role_list(value: str) -> list[str]:
    """Split a semicolon-delimited role inventory into a clean list (no truncation)."""
    if not value:
        return []
    return [r.strip() for r in value.split(';') if r.strip()]


def _row_url(row: dict) -> str:
    """Best available link for a company row: role/apply link, else careers, else source."""
    return (row.get('apply_url', '') or row.get('role_url', '')
            or row.get('careers_url', '') or row.get('source_key', '')).strip()


def _resolve_group(path: str, display_groups: dict | None) -> str:
    """Map a raw career-path label to its display group, mirroring the old
    server-rendered grouping: unmapped paths land in 'Other'; with no
    display_groups configured, the raw path is used as its own group."""
    if not display_groups:
        return path
    for group_name, path_labels in display_groups.items():
        if path in path_labels:
            return group_name
    return 'Other'


def _row_record(row: dict, section: str) -> dict:
    """Build one JSON-serializable record describing a company for the client renderer."""
    score = get_score(row)
    roles = _split_role_list(row.get('open_positions', '') or row.get('role', ''))
    status = (row.get('app_status', '') or '').strip()
    label, css_class = STATUS_LABELS.get(status, ('Not Applied', 'status-not'))
    path = (row.get('role_family', '') or '').strip() or 'Other'
    flags = [f.strip() for f in (row.get('llm_flags', '') or '').split(',') if f.strip()]
    last_action_date = (row.get('last_contact', '').strip()
                         or row.get('date_applied', '').strip()
                         or row.get('date_added', '').strip())

    record = {
        'company': (row.get('company', '') or '').strip(),
        'path': path,
        'roles': roles,
        'role_count': len(roles),
        'score': score if score >= 0 else None,
        'score_display': format_score(score),
        'score_tier': _score_tier(score),
        'status': status,
        'status_label': label,
        'status_class': css_class,
        'section': section,
        'rationale': (row.get('llm_rationale', '') or '').strip(),
        'flags': flags,
        'notes': (row.get('app_notes', '') or row.get('notes', '') or '').strip(),
        'contact_name': (row.get('contact_name', '') or '').strip(),
        'date_added': row.get('date_added', '') or '',
        'date_applied': row.get('date_applied', '') or '',
        'last_contact': row.get('last_contact', '') or '',
        'last_action_date': last_action_date,
        'url': _row_url(row),
        'careers_url': (row.get('careers_url', '') or '').strip(),
    }

    if section == 'follow_up':
        staleness = classify_staleness(row)
        record['staleness'] = staleness
        record['suggested_action'] = suggested_action(row, staleness)
        record['days_since'] = _days_since(row.get('date_applied', '') or row.get('date_added', ''))

    return record


def build_dashboard_data(
    views: dict,
    full_mode: bool,
    display_groups: dict | None = None,
    watch_list_rows: list[dict] | None = None,
) -> dict:
    """Assemble the single JSON blob the client-side renderer consumes.

    `views` is the dict produced by dashboard_views.build_active_views()
    (or the equivalent shape built by build_html() for legacy callers).
    """
    from dashboard_views import aggregate_display_rows

    stats = views['stats']
    followup_rows = views['follow_up']
    closed_out_rows = views['closed_out']
    bestfit_rows = views['best_fits']
    worth_exploring_rows = views.get('worth_exploring', [])
    watch_list_rows = watch_list_rows or []

    stale_count = sum(1 for r in followup_rows if classify_staleness(r) in ('stale', 'warm'))

    follow_up_records = [_row_record(r, 'follow_up') for r in followup_rows]
    closed_out_records = [_row_record(r, 'closed_out') for r in closed_out_rows]

    best_fit_records = []
    for r in bestfit_rows:
        rec = _row_record(r, 'best_fits')
        rec['group'] = _resolve_group(rec['path'], display_groups)
        best_fit_records.append(rec)

    worth_exploring_records = [_row_record(r, 'worth_exploring') for r in worth_exploring_rows]
    watch_list_records = [_row_record(r, 'watch_list') for r in watch_list_rows]

    # Full pipeline table: all currently-visible (non-closed) rows, one per company.
    all_visible = aggregate_display_rows(followup_rows + bestfit_rows + worth_exploring_rows)
    pipeline_records = [_row_record(r, 'pipeline') for r in all_visible]

    resolve_path = _canonical_path_resolver()
    for rec in (follow_up_records + closed_out_records + best_fit_records
                + worth_exploring_records + watch_list_records + pipeline_records):
        rec['path_canon'] = resolve_path(rec.get('path', ''))

    paths = sorted({
        (r.get('role_family', '') or '').strip()
        for r in all_visible
        if (r.get('role_family', '') or '').strip()
    })

    stats_out = {
        'follow_up': stats['follow_up'],
        'best_fits': stats['best_fits'],
        'worth_exploring': stats.get('worth_exploring', 0),
        'closed_out': stats['closed_out'],
        'total': stats['total'],
        'need_followup': stale_count,
        'watch_list': len(watch_list_records),
    }

    return {
        'meta': {
            'title': 'Career Dashboard (Full)' if full_mode else 'Career Dashboard',
            'run_date': datetime.now().strftime('%Y-%m-%d %H:%M'),
            'full_mode': full_mode,
            'per_path_limit': 0 if full_mode else 3,
        },
        'stats': stats_out,
        'paths': paths,
        'sections': {
            'follow_up': follow_up_records,
            'closed_out': closed_out_records,
            'best_fits': best_fit_records,
            'worth_exploring': worth_exploring_records,
            'watch_list': watch_list_records,
            'pipeline': pipeline_records,
        },
    }


def _load_display_groups(search_config_path: Path | None = None) -> dict | None:
    """Load display_groups from search-config.json if present and valid."""
    path = search_config_path or (DATA / 'search-config.json')
    if not path.exists():
        return None
    try:
        with path.open(encoding='utf-8') as f:
            search_config = json.load(f)
        return search_config.get('display_groups') or None
    except (json.JSONDecodeError, OSError):
        return None


def _canonical_path_resolver(search_config_path: Path | None = None):
    """Build a raw role_family -> canonical path label resolver.

    Legacy rows carry free-text role families ("Enterprise Finance Software
    (Solutions Architect)", bare path keys like "tier1_ai"); collapse them to
    canonical query-pack labels where recognizable so the per-path chart and
    filter stay readable. Unrecognized values resolve to '' (the client
    buckets those into 'Other').
    """
    path = search_config_path or (DATA / 'search-config.json')
    try:
        sys.path.insert(0, str(BASE / 'scripts' / 'core'))
        from path_normalizer import normalize_path
        with path.open(encoding='utf-8') as f:
            search_config = json.load(f)
    except (ImportError, json.JSONDecodeError, OSError):
        return lambda raw: ''
    key_to_label = {k: (v.get('label') or '')
                    for k, v in (search_config.get('query_packs') or {}).items()}
    canon = [label for label in key_to_label.values() if label]

    def resolve(raw: str) -> str:
        raw = (raw or '').strip()
        if not raw:
            return ''
        n = normalize_path(raw)
        if n in canon:
            return n
        if key_to_label.get(raw):
            return key_to_label[raw]
        base = normalize_path(raw.split('(')[0].strip())
        if base in canon:
            return base
        low = raw.lower()
        for c in canon:
            if low.startswith(c.lower()):
                return c
        return ''

    return resolve


def _strip_external_css(css: str) -> str:
    """Drop @import rules and any line referencing an http(s) URL from inlined CSS.

    Brand theme.css may carry web-font imports or commented-out <link> tags;
    the dashboard must stay fully offline, so none of that may reach the page.
    """
    kept = []
    for line in css.splitlines():
        lowered = line.lower()
        if '@import' in lowered or 'http://' in lowered or 'https://' in lowered:
            continue
        kept.append(line)
    return '\n'.join(kept)


def render_dashboard_html(data: dict) -> str:
    """Render the full self-contained HTML page around a build_dashboard_data() blob."""
    title = data['meta']['title']
    run_date = data['meta']['run_date']

    brand_css = _strip_external_css(read_brand_css())
    css = _get_css()
    js = _get_js()
    data_json = json.dumps(data, ensure_ascii=False)
    # Guard against a literal "</script>" inside any free-text field (rationale,
    # notes, etc.) breaking out of the embedded JSON block.
    data_json = data_json.replace('</', '<\\/')

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{escape(title)}</title>
<style>
{brand_css}
{css}
</style>
</head>
<body>

<div class="header">
  <h1>{escape(title)}</h1>
  <div class="date">Updated {escape(run_date)}</div>
</div>

<div class="stats" id="statsRow"></div>

<div class="charts-row" id="chartsRow"></div>

<div class="section" id="appliedSection">
  <div class="section-header">
    <h2>Applied</h2>
    <span class="badge" id="appliedBadge"></span>
  </div>
  <div id="followupGrid"></div>
  <div id="closedOutContainer"></div>
</div>

<div class="divider"></div>

<div class="section" id="bestFitsSection">
  <div class="section-header">
    <h2>Best Fits</h2>
    <span class="badge-muted" id="bestFitsBadge"></span>
  </div>
  <div id="bestFitsContainer"></div>
</div>

<div class="divider"></div>

<div class="section" id="worthExploringSection">
  <div class="section-header">
    <h2>Worth Exploring</h2>
    <span class="badge-muted" id="worthExploringBadge"></span>
  </div>
  <div id="worthExploringContainer"></div>
</div>

<div class="divider"></div>

<div class="section" id="watchListSection">
  <div class="section-header collapsible-header" data-collapse-target="watchListContent">
    <h2><span class="section-toggle">&#9654;</span> Worth Monitoring</h2>
    <span class="badge-muted" id="watchListBadge"></span>
  </div>
  <div class="collapsible-content" id="watchListContent" style="display:none">
    <div id="watchListContainer"></div>
  </div>
</div>

<div class="divider"></div>

<div class="section" id="pipelineSection">
  <div class="section-header collapsible-header" data-collapse-target="pipelineContent">
    <h2><span class="section-toggle">&#9654;</span> Full Pipeline</h2>
    <span class="badge-muted" id="pipelineBadge"></span>
  </div>
  <div class="collapsible-content" id="pipelineContent" style="display:none">
    <div class="filters">
      <input type="text" id="pipelineSearch" placeholder="Search company, role or notes...">
      <select id="pathFilter"><option value="">All Paths</option></select>
      <select id="statusFilter">
        <option value="">All Status</option>
        <option value="applied">Applied</option>
        <option value="researching">Researching</option>
        <option value="not_applied">Not Applied</option>
      </select>
      <select id="scoreFilter">
        <option value="">All Scores</option>
        <option value="tier_85">85+ (High)</option>
        <option value="tier_70">70-84</option>
        <option value="tier_60">60-69</option>
        <option value="tier_below_60">Below 60</option>
        <option value="unscored">Unscored</option>
      </select>
    </div>
    <div id="pipelineContainer"></div>
  </div>
</div>

<p class="generated">Generated {escape(run_date)}</p>

<script type="application/json" id="dashboard-data">{data_json}</script>
<script>
{js}
</script>

</body>
</html>'''


def _get_css() -> str:
    """Return all inline CSS for the dashboard."""
    return '''* { margin: 0; padding: 0; box-sizing: border-box; }
body { font-family: -apple-system, "Segoe UI", system-ui, sans-serif; background: #f5f6fa; color: var(--card-text-primary); padding: 24px; font-size: 15px; }

.header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 24px; background: linear-gradient(135deg, var(--bg-deep), var(--bg-base)); padding: 20px 28px; border-radius: 12px; }
.header h1 { font-size: 1.5rem; font-weight: 700; color: var(--text-headline); }
.header .date { color: var(--text-muted); font-size: 0.85rem; }

.stats { display: flex; gap: 12px; margin-bottom: 20px; flex-wrap: wrap; }
.stat { background: var(--bg-surface); padding: 14px 20px; border-radius: 10px; box-shadow: 0 2px 8px rgba(0,0,0,0.15); flex: 1; min-width: 130px; text-align: center; border: 1px solid var(--accent-border); }
.stat-clickable { cursor: pointer; transition: box-shadow 0.15s, transform 0.15s; }
.stat-clickable:hover { box-shadow: 0 4px 16px rgba(0,0,0,0.25); transform: translateY(-1px); }
.stat-clickable.stat-active-pill { box-shadow: 0 0 0 2px var(--accent); }
.stat .value { font-size: 1.7rem; font-weight: 700; font-family: "SF Mono", "Fira Code", ui-monospace, monospace; color: #f5f8fc; }
.stat .label { font-size: 0.78rem; color: #8899aa; margin-top: 2px; text-transform: uppercase; letter-spacing: 0.5px; }
.stat.alert .value { color: #ff7b7b; }
.stat.active .value { color: #7bb8ff; }
.stat.good .value { color: #7be6a0; }

.charts-row { display: flex; gap: 14px; margin-bottom: 28px; flex-wrap: wrap; }
.chart-panel { background: var(--card-bg); border-radius: 10px; padding: 14px 16px; box-shadow: 0 1px 4px rgba(0,0,0,0.06); flex: 1; min-width: 260px; }
.chart-panel h3 { font-size: 0.82rem; text-transform: uppercase; letter-spacing: 0.4px; color: var(--card-text-secondary); margin-bottom: 8px; font-weight: 700; }
.chart-svg { width: 100%; height: auto; display: block; }
.chart-label { font-size: 9px; fill: var(--card-text-secondary); font-family: inherit; }
.chart-value { font-size: 9px; fill: var(--card-text-primary); font-weight: 700; font-family: inherit; }
.funnel-bar { fill: var(--accent-light); }
.hist-bar { fill: var(--status-partial); }
.path-bar { fill: var(--status-matched); }

.section { margin-bottom: 32px; }
.section-header { display: flex; justify-content: space-between; align-items: center; margin-bottom: 14px; padding-left: 12px; border-left: 3px solid var(--accent-light); }
.section-header h2 { font-size: 1.15rem; font-weight: 700; }
.badge { background: var(--status-missing); color: #fff; font-size: 0.72rem; padding: 3px 8px; border-radius: 10px; font-weight: 600; }
.badge-muted { background: var(--card-border); color: var(--card-text-secondary); font-size: 0.72rem; padding: 3px 8px; border-radius: 10px; }
.divider { height: 1px; background: var(--card-border); margin: 8px 0 24px; }
.collapsible-header { cursor: pointer; user-select: none; }
.collapsible-header:hover { opacity: 0.85; }
.section-toggle { display: inline-block; font-size: 0.7rem; transition: transform 0.15s; margin-right: 4px; }
.section-toggle.open { transform: rotate(90deg); }
.generated { color: var(--card-text-muted); font-size: 0.8rem; margin-top: 20px; }
.empty-message { color: var(--card-text-muted); font-style: italic; padding: 20px 0; }

.followup-grid { display: grid; grid-template-columns: repeat(auto-fill, minmax(320px, 1fr)); gap: 12px; }
.followup-card { background: var(--card-bg); border-radius: 10px; padding: 16px; box-shadow: 0 1px 4px rgba(0,0,0,0.06); border-left: 4px solid var(--card-border); cursor: pointer; }
.followup-card.stale { border-left-color: var(--status-missing); }
.followup-card.recent { border-left-color: var(--status-matched); }
.followup-card.warm { border-left-color: var(--status-partial); }
.fc-top { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 8px; }
.fc-company { font-weight: 700; font-size: 1rem; }
.fc-score { font-size: 0.8rem; font-weight: 700; padding: 2px 8px; border-radius: 6px; font-family: "SF Mono", "Fira Code", ui-monospace, monospace; }
.fc-score.score-high { background: var(--status-matched-bg); color: var(--status-matched); }
.fc-score.score-med { background: var(--status-partial-bg); color: var(--status-partial); }
.fc-score.score-low { background: var(--status-missing-bg); color: var(--status-missing); }
.fc-role { font-size: 0.85rem; color: var(--card-text-secondary); margin-bottom: 6px; }
.fc-role-count { color: var(--card-text-muted); font-size: 0.78rem; }
.fc-meta { display: flex; gap: 12px; font-size: 0.78rem; color: var(--card-text-muted); }
.fc-alert { color: var(--status-missing); font-weight: 600; }
.fc-contact { font-size: 0.8rem; color: var(--accent-light); margin-top: 6px; }
.fc-action { margin-top: 10px; padding-top: 10px; border-top: 1px solid var(--card-border); font-size: 0.82rem; color: var(--card-text-secondary); font-style: italic; }
.followup-card.filter-hidden { display: none; }
.followup-card.closed-out { opacity: 0.45; border-color: var(--card-border); cursor: default; }
.followup-card.closed-out:hover { opacity: 0.7; }
.closed-out-section { margin-top: 2rem; }
.closed-out-heading { color: var(--card-text-muted); font-size: 0.92rem; font-weight: 600; margin-bottom: 0.75rem; border-top: 1px solid var(--card-border); padding-top: 1rem; }

.card-detail { margin-top: 10px; padding-top: 10px; border-top: 1px dashed var(--card-border); font-size: 0.82rem; color: var(--card-text-secondary); }
.card-detail[hidden] { display: none; }
.detail-flags { display: flex; flex-wrap: wrap; gap: 6px; margin: 6px 0; }
.flag-chip { background: var(--accent-light-bg); color: var(--accent-light); border-radius: 10px; padding: 2px 9px; font-size: 0.72rem; }
.detail-links a { color: var(--accent-light); text-decoration: none; margin-right: 12px; font-size: 0.82rem; }
.detail-links a:hover { text-decoration: underline; }
.detail-rationale { margin-bottom: 6px; line-height: 1.4; }

.path-group { margin-bottom: 16px; }
.path-label { font-size: 0.82rem; font-weight: 600; color: var(--accent-light); text-transform: uppercase; letter-spacing: 0.5px; margin-bottom: 8px; padding: 8px 14px; background: linear-gradient(135deg, #eef4fb, #e8edf5); border-radius: 6px; cursor: pointer; border-left: 3px solid var(--accent-light); }
.company-row { background: var(--card-bg); border-radius: 8px; padding: 12px 16px; margin-bottom: 6px; box-shadow: 0 1px 3px rgba(0,0,0,0.04); display: flex; align-items: center; gap: 16px; cursor: pointer; flex-wrap: wrap; }
.company-row:hover { background: #f8f9ff; }
.cr-rank { font-size: 0.78rem; color: var(--card-text-muted); font-weight: 600; width: 24px; }
.cr-score { font-weight: 700; font-size: 0.88rem; width: 32px; font-family: "SF Mono", "Fira Code", ui-monospace, monospace; }
.cr-score.score-high { color: var(--status-matched); }
.cr-score.score-med { color: var(--status-partial); }
.cr-score.score-low { color: var(--status-missing); }
.cr-name { font-weight: 600; font-size: 0.92rem; min-width: 140px; }
.cr-name a { color: var(--accent-light); text-decoration: none; }
.cr-name a:hover { text-decoration: underline; }
.cr-roles { font-size: 0.84rem; color: var(--card-text-secondary); max-width: 220px; }
.cr-role-count { color: var(--card-text-muted); font-size: 0.76rem; }
.cr-rationale { font-size: 0.8rem; color: var(--card-text-muted); flex: 1; min-width: 160px; }
.cr-detail { flex-basis: 100%; }
.path-toggle { display: inline-block; font-size: 0.7rem; margin-right: 6px; transition: transform 0.2s; }
.path-toggle.open { transform: rotate(90deg); }
.path-count { color: var(--card-text-muted); font-weight: 400; font-size: 0.76rem; }
.toggle-all { text-align: right; color: var(--accent-light); font-size: 0.85rem; cursor: pointer; margin-bottom: 12px; }
.toggle-all:hover { text-decoration: underline; }
.show-more { text-align: center; padding: 8px; color: var(--accent-light); font-size: 0.85rem; cursor: pointer; }
.show-more:hover { text-decoration: underline; }

.filters { display: flex; gap: 10px; margin-bottom: 12px; flex-wrap: wrap; }
.filters select, .filters input { padding: 7px 10px; border: 1px solid var(--card-border); border-radius: 6px; font-size: 0.85rem; background: var(--card-bg); }
.filters input { width: 220px; }
.pipeline-table { width: 100%; border-collapse: collapse; background: var(--card-bg); border-radius: 10px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.06); font-size: 0.85rem; }
.pipeline-table th { background: var(--bg-elevated); padding: 10px 14px; text-align: left; font-size: 0.76rem; color: #a0b0c0; text-transform: uppercase; letter-spacing: 0.3px; border-bottom: none; cursor: pointer; user-select: none; font-weight: 600; }
.pipeline-table th:hover { background: var(--bg-surface); color: #f5f8fc; }
.pipeline-table td { padding: 10px 14px; border-bottom: 1px solid var(--card-border); }
.pipeline-table tbody tr:not(.detail-row) { cursor: pointer; }
.pipeline-table tbody tr:not(.detail-row):hover { background: #fafbff; }
.pipeline-table a { color: var(--accent-light); text-decoration: none; }
.pipeline-table a:hover { text-decoration: underline; }
.pipeline-roles { max-width: 250px; }
.role-extra { color: var(--card-text-muted); font-size: 0.76rem; }
.status-badge { font-size: 0.72rem; padding: 3px 10px; border-radius: 5px; font-weight: 600; white-space: nowrap; border: 1px solid transparent; }
.status-applied { background: var(--accent-light); color: #fff; }
.status-researching { background: var(--accent-light-bg); color: var(--accent-light); border-color: var(--accent-light); }
.status-rejected { background: var(--status-missing); color: #fff; }
.status-closed { background: var(--card-text-muted); color: #fff; }
.status-declined { background: var(--status-partial); color: #fff; }
.status-nofit { background: var(--card-border); color: var(--card-text-muted); }
.status-not { background: var(--card-border); color: var(--card-text-muted); }

.detail-row td { background: #f8f9fc; padding: 14px 18px; border-bottom: 1px solid var(--card-border); }
.detail-row[hidden] { display: none; }

.watch-list-section .section-header { border-left-color: var(--status-partial); }
.worth-exploring-table .we-rationale { max-width: 280px; font-size: 0.8rem; color: var(--card-text-secondary); }
#worthExploringSection .section-header { border-left-color: var(--status-partial); }

@media (max-width: 720px) {
  .stats { flex-direction: column; }
  .charts-row { flex-direction: column; }
  .filters input { width: 100%; }
}'''


def _get_js() -> str:
    """Return all inline JavaScript for the dashboard. Vanilla JS, no dependencies."""
    return r'''(function() {
  'use strict';

  var DATA = JSON.parse(document.getElementById('dashboard-data').textContent);
  var svgNS = 'http://www.w3.org/2000/svg';

  function el(tag, cls, text) {
    var e = document.createElement(tag);
    if (cls) e.className = cls;
    if (text !== undefined && text !== null) e.textContent = text;
    return e;
  }

  function fmtDate(iso) {
    if (!iso) return '—';
    var d = new Date(iso + 'T00:00:00');
    if (isNaN(d.getTime())) return '—';
    var months = ['Jan','Feb','Mar','Apr','May','Jun','Jul','Aug','Sep','Oct','Nov','Dec'];
    return months[d.getMonth()] + ' ' + d.getDate();
  }

  function scoreColor(tier, score) {
    if (score === null || score === undefined) return 'score-low';
    if (tier === 'tier_85' || tier === 'tier_70') return 'score-high';
    if (tier === 'tier_60') return 'score-med';
    return 'score-low';
  }

  // ---------------------------------------------------------------------
  // Stats pills
  // ---------------------------------------------------------------------
  function renderStats() {
    var s = DATA.stats;
    var pills = [
      {id: 'pillFollowup', cls: 'stat alert stat-clickable', value: s.need_followup, label: 'Need Follow-up'},
      {id: 'pillApplied', cls: 'stat active stat-clickable', value: s.follow_up, label: 'Applied'},
      {id: 'pillExplore', cls: 'stat stat-clickable', value: s.best_fits, label: 'Best Fits'},
      {id: 'pillWorthExploring', cls: 'stat stat-clickable', value: s.worth_exploring, label: 'Worth Exploring'},
      {id: 'pillWatch', cls: 'stat stat-clickable', value: s.watch_list, label: 'Worth Monitoring'},
      {id: 'pillPipeline', cls: 'stat good stat-clickable', value: s.total, label: 'Total Pipeline'}
    ];
    var row = document.getElementById('statsRow');
    pills.forEach(function(p) {
      var stat = el('div', p.cls);
      stat.id = p.id;
      stat.appendChild(el('div', 'value', String(p.value)));
      stat.appendChild(el('div', 'label', p.label));
      row.appendChild(stat);
    });

    document.getElementById('appliedBadge').textContent = s.need_followup + ' need follow-up';
    document.getElementById('bestFitsBadge').textContent = s.best_fits + ' companies scoring 70+';
    document.getElementById('worthExploringBadge').textContent = s.worth_exploring + ' companies scoring 50-69';
    document.getElementById('watchListBadge').textContent = s.watch_list + ' companies';
    document.getElementById('pipelineBadge').textContent = s.total + ' companies';

    function clearPillHighlight() {
      document.querySelectorAll('.stat-clickable').forEach(function(p) { p.classList.remove('stat-active-pill'); });
    }

    document.getElementById('pillFollowup').addEventListener('click', function() {
      clearPillHighlight();
      this.classList.add('stat-active-pill');
      document.querySelectorAll('.followup-card').forEach(function(c) {
        var stale = c.dataset.staleness === 'stale' || c.dataset.staleness === 'warm';
        c.classList.toggle('filter-hidden', c.dataset.section === 'follow_up' && !stale);
      });
      document.getElementById('appliedSection').scrollIntoView({behavior: 'smooth'});
    });
    document.getElementById('pillApplied').addEventListener('click', function() {
      clearPillHighlight();
      this.classList.add('stat-active-pill');
      document.querySelectorAll('.followup-card').forEach(function(c) { c.classList.remove('filter-hidden'); });
      document.getElementById('appliedSection').scrollIntoView({behavior: 'smooth'});
    });
    document.getElementById('pillExplore').addEventListener('click', function() {
      clearPillHighlight();
      this.classList.add('stat-active-pill');
      expandAllPathGroups();
      document.getElementById('bestFitsSection').scrollIntoView({behavior: 'smooth'});
    });
    document.getElementById('pillWorthExploring').addEventListener('click', function() {
      clearPillHighlight();
      this.classList.add('stat-active-pill');
      document.getElementById('worthExploringSection').scrollIntoView({behavior: 'smooth'});
    });
    document.getElementById('pillWatch').addEventListener('click', function() {
      clearPillHighlight();
      this.classList.add('stat-active-pill');
      openCollapsible('watchListContent');
      document.getElementById('watchListSection').scrollIntoView({behavior: 'smooth'});
    });
    document.getElementById('pillPipeline').addEventListener('click', function() {
      clearPillHighlight();
      this.classList.add('stat-active-pill');
      openCollapsible('pipelineContent');
      document.getElementById('pipelineSection').scrollIntoView({behavior: 'smooth'});
    });
  }

  function openCollapsible(id) {
    var content = document.getElementById(id);
    if (content.style.display === 'none') {
      content.style.display = 'block';
      var header = content.previousElementSibling;
      var toggle = header && header.querySelector('.section-toggle');
      if (toggle) toggle.classList.add('open');
    }
  }

  function expandAllPathGroups() {
    document.querySelectorAll('#bestFitsSection .path-content').forEach(function(c) { c.style.display = 'block'; });
    document.querySelectorAll('#bestFitsSection .path-toggle').forEach(function(t) { t.classList.add('open'); });
    var btn = document.getElementById('toggleAllBtn');
    if (btn) btn.textContent = 'Collapse All';
  }

  // ---------------------------------------------------------------------
  // Collapsible section headers
  // ---------------------------------------------------------------------
  function wireCollapsibleHeaders() {
    document.querySelectorAll('.collapsible-header[data-collapse-target]').forEach(function(header) {
      header.addEventListener('click', function() {
        var content = document.getElementById(this.dataset.collapseTarget);
        var toggle = this.querySelector('.section-toggle');
        if (content.style.display === 'none') {
          content.style.display = 'block';
          if (toggle) toggle.classList.add('open');
        } else {
          content.style.display = 'none';
          if (toggle) toggle.classList.remove('open');
        }
      });
    });
  }

  // ---------------------------------------------------------------------
  // Detail expansion (rationale, flags, suggested action, links)
  // ---------------------------------------------------------------------
  function detailContent(rec) {
    var wrap = el('div', 'card-detail-inner');
    if (rec.rationale) wrap.appendChild(el('div', 'detail-rationale', rec.rationale));
    if (rec.flags && rec.flags.length) {
      var flagsWrap = el('div', 'detail-flags');
      rec.flags.forEach(function(f) { flagsWrap.appendChild(el('span', 'flag-chip', f)); });
      wrap.appendChild(flagsWrap);
    }
    if (rec.suggested_action) {
      wrap.appendChild(el('div', 'detail-rationale', 'Suggested action: ' + rec.suggested_action));
    }
    if (rec.notes) {
      wrap.appendChild(el('div', 'detail-rationale', rec.notes));
    }
    var links = el('div', 'detail-links');
    var any = false;
    if (rec.url) {
      var a1 = el('a', null, 'Open role/application');
      a1.href = rec.url; a1.target = '_blank'; a1.rel = 'noopener';
      links.appendChild(a1); any = true;
    }
    if (rec.careers_url && rec.careers_url !== rec.url) {
      var a2 = el('a', null, 'Careers page');
      a2.href = rec.careers_url; a2.target = '_blank'; a2.rel = 'noopener';
      links.appendChild(a2); any = true;
    }
    if (any) wrap.appendChild(links);
    if (!rec.rationale && !(rec.flags && rec.flags.length) && !rec.suggested_action && !rec.notes && !any) {
      wrap.appendChild(el('div', 'detail-rationale', 'No additional details available.'));
    }
    return wrap;
  }

  // ---------------------------------------------------------------------
  // Applied / Closed-out cards
  // ---------------------------------------------------------------------
  function buildFollowupCard(rec, staleClass) {
    var card = el('div', 'followup-card ' + (staleClass || ''));
    card.dataset.section = 'follow_up';
    if (rec.staleness) card.dataset.staleness = rec.staleness;

    var top = el('div', 'fc-top');
    top.appendChild(el('div', 'fc-company', rec.company));
    var score = el('span', 'fc-score ' + scoreColor(rec.score_tier, rec.score), rec.score_display);
    top.appendChild(score);
    card.appendChild(top);

    var roleText = rec.roles.length ? rec.roles[0] : '-';
    var roleLine = el('div', 'fc-role', roleText);
    if (rec.roles.length > 1) {
      roleLine.appendChild(el('span', 'fc-role-count', ' (+' + (rec.roles.length - 1) + ' more)'));
    }
    card.appendChild(roleLine);

    var meta = el('div', 'fc-meta');
    var refDate = rec.date_applied || rec.date_added;
    meta.appendChild(el('span', null, 'Applied ' + fmtDate(refDate)));
    var days = rec.days_since;
    var daysText = days >= 0 ? (days + ' days ago') : 'unknown';
    meta.appendChild(el('span', rec.staleness === 'stale' ? 'fc-alert' : '', daysText));
    card.appendChild(meta);

    if (rec.contact_name) card.appendChild(el('div', 'fc-contact', rec.contact_name));
    card.appendChild(el('div', 'fc-action', rec.suggested_action || ''));

    var detail = el('div', 'card-detail');
    detail.hidden = true;
    detail.appendChild(detailContent(rec));
    card.appendChild(detail);

    card.addEventListener('click', function() { detail.hidden = !detail.hidden; });
    return card;
  }

  function buildClosedCard(rec) {
    var card = el('div', 'followup-card closed-out');
    var top = el('div', 'fc-top');
    top.appendChild(el('div', 'fc-company', rec.company));
    top.appendChild(el('span', 'status-badge ' + rec.status_class, rec.status_label));
    card.appendChild(top);
    var roleText = rec.roles.length ? rec.roles[0] : '-';
    card.appendChild(el('div', 'fc-role', roleText));
    card.appendChild(el('div', 'fc-meta', null)).appendChild(el('span', null, fmtDate(rec.date_applied || rec.date_added)));
    return card;
  }

  function renderFollowup() {
    var followUp = DATA.sections.follow_up;
    var grid = document.getElementById('followupGrid');
    if (!followUp.length) {
      grid.appendChild(el('p', 'empty-message', 'No applications to follow up on. Explore best fits below.'));
    } else {
      var sorted = followUp.slice().sort(function(a, b) {
        var da = a.days_since >= 0 ? a.days_since : -9999;
        var db = b.days_since >= 0 ? b.days_since : -9999;
        return db - da;
      });
      var container = el('div', 'followup-grid');
      container.id = 'followupGridInner';
      sorted.forEach(function(rec) { container.appendChild(buildFollowupCard(rec, rec.staleness)); });
      grid.appendChild(container);
    }

    var closedOut = DATA.sections.closed_out;
    var closedContainer = document.getElementById('closedOutContainer');
    if (closedOut.length) {
      var section = el('div', 'closed-out-section');
      section.appendChild(el('h3', 'closed-out-heading', 'Closed (' + closedOut.length + ')'));
      var grid2 = el('div', 'followup-grid');
      closedOut.forEach(function(rec) { grid2.appendChild(buildClosedCard(rec)); });
      section.appendChild(grid2);
      closedContainer.appendChild(section);
    }
  }

  // ---------------------------------------------------------------------
  // Best Fits: grouped, collapsible path groups
  // ---------------------------------------------------------------------
  function buildCompanyRow(rec, rank) {
    var row = el('div', 'company-row');
    if (rank !== undefined) row.appendChild(el('span', 'cr-rank', '#' + rank));
    row.appendChild(el('span', 'cr-score ' + scoreColor(rec.score_tier, rec.score), rec.score_display));

    var nameWrap = el('span', 'cr-name');
    if (rec.url) {
      var a = el('a', null, rec.company);
      a.href = rec.url; a.target = '_blank'; a.rel = 'noopener';
      nameWrap.appendChild(a);
    } else {
      nameWrap.textContent = rec.company;
    }
    row.appendChild(nameWrap);

    var roles = rec.roles.slice(0, 2).join(', ') || '-';
    var rolesEl = el('span', 'cr-roles', roles);
    if (rec.roles.length > 2) rolesEl.appendChild(el('span', 'cr-role-count', ' (+' + (rec.roles.length - 2) + ' more)'));
    row.appendChild(rolesEl);

    var rationale = rec.rationale.length > 200 ? rec.rationale.slice(0, 197) + '...' : rec.rationale;
    row.appendChild(el('span', 'cr-rationale', rationale));

    var detail = el('div', 'card-detail cr-detail');
    detail.hidden = true;
    detail.appendChild(detailContent(rec));
    row.appendChild(detail);

    row.addEventListener('click', function(e) {
      if (e.target.tagName === 'A') return;
      detail.hidden = !detail.hidden;
    });
    return row;
  }

  function renderBestFits() {
    var rows = DATA.sections.best_fits;
    var container = document.getElementById('bestFitsContainer');
    if (!rows.length) {
      container.appendChild(el('p', 'empty-message', 'No companies to explore yet.'));
      return;
    }

    var groups = {};
    rows.forEach(function(r) {
      var g = r.group || r.path || 'Other';
      (groups[g] = groups[g] || []).push(r);
    });
    Object.keys(groups).forEach(function(g) {
      groups[g].sort(function(a, b) { return (b.score || -1) - (a.score || -1); });
    });
    var groupNames = Object.keys(groups).sort(function(a, b) {
      var as = groups[a][0].score;
      var bs = groups[b][0].score;
      return (bs === null || bs === undefined ? -1 : bs) - (as === null || as === undefined ? -1 : as);
    });

    var autoExpand = rows.length < 50;

    var toggleAll = el('div', 'toggle-all', autoExpand ? 'Collapse All' : 'Expand All');
    toggleAll.id = 'toggleAllBtn';
    container.appendChild(toggleAll);

    groupNames.forEach(function(g) {
      var members = groups[g];
      var groupEl = el('div', 'path-group');

      var labelEl = el('div', 'path-label');
      var toggleIcon = el('span', 'path-toggle' + (autoExpand ? ' open' : ''), '▶');
      labelEl.appendChild(toggleIcon);
      labelEl.appendChild(document.createTextNode(g + ' '));
      labelEl.appendChild(el('span', 'path-count', '(' + members.length + ')'));
      groupEl.appendChild(labelEl);

      var content = el('div', 'path-content');
      content.style.display = autoExpand ? 'block' : 'none';
      members.forEach(function(rec, i) { content.appendChild(buildCompanyRow(rec, i + 1)); });
      groupEl.appendChild(content);

      labelEl.addEventListener('click', function() {
        var isHidden = content.style.display === 'none';
        content.style.display = isHidden ? 'block' : 'none';
        toggleIcon.classList.toggle('open', isHidden);
      });

      container.appendChild(groupEl);
    });

    toggleAll.addEventListener('click', function() {
      var contents = container.querySelectorAll('.path-content');
      var toggles = container.querySelectorAll('.path-toggle');
      var anyHidden = Array.prototype.some.call(contents, function(c) { return c.style.display === 'none'; });
      contents.forEach(function(c) { c.style.display = anyHidden ? 'block' : 'none'; });
      toggles.forEach(function(t) { t.classList.toggle('open', anyHidden); });
      toggleAll.textContent = anyHidden ? 'Collapse All' : 'Expand All';
    });
  }

  // ---------------------------------------------------------------------
  // Flat tables: Worth Exploring, Watch List, Pipeline
  // ---------------------------------------------------------------------
  function buildFlatRow(rec, showStatus) {
    var tr = el('tr');
    tr.dataset.path = rec.path;
    tr.dataset.score = rec.score === null ? '' : String(rec.score);
    tr.dataset.status = rec.status;
    tr.dataset.section = rec.section;

    var tdCompany = el('td');
    if (rec.url) {
      var a = el('a', null, rec.company);
      a.href = rec.url; a.target = '_blank'; a.rel = 'noopener';
      tdCompany.appendChild(a);
    } else {
      tdCompany.textContent = rec.company;
    }
    tr.appendChild(tdCompany);

    tr.appendChild(el('td', scoreColor(rec.score_tier, rec.score), rec.score_display));
    tr.appendChild(el('td', null, rec.path));

    var rolesTd = el('td', 'pipeline-roles');
    rolesTd.textContent = rec.roles.slice(0, 2).join(', ') || '-';
    if (rec.roles.length > 2) rolesTd.appendChild(el('span', 'role-extra', ' (+' + (rec.roles.length - 2) + ')'));
    tr.appendChild(rolesTd);

    if (showStatus) {
      var statusTd = el('td');
      statusTd.appendChild(el('span', 'status-badge ' + rec.status_class, rec.status_label));
      tr.appendChild(statusTd);
    } else {
      var rationale = rec.rationale.length > 150 ? rec.rationale.slice(0, 147) + '...' : rec.rationale;
      tr.appendChild(el('td', 'we-rationale', rationale));
    }

    if (rec.section === 'pipeline') {
      tr.appendChild(el('td', null, fmtDate(rec.last_action_date)));
    }

    return tr;
  }

  function buildDetailRow(rec, colspan) {
    var tr = el('tr', 'detail-row');
    tr.hidden = true;
    var td = el('td');
    td.colSpan = colspan;
    td.appendChild(detailContent(rec));
    tr.appendChild(td);
    return tr;
  }

  function renderFlatTable(containerId, rows, headers, showStatus) {
    var container = document.getElementById(containerId);
    if (!rows.length) {
      container.appendChild(el('p', 'empty-message', 'Nothing here right now.'));
      return;
    }
    var table = el('table', 'pipeline-table' + (showStatus ? '' : ' worth-exploring-table'));
    var thead = el('thead');
    var headRow = el('tr');
    headers.forEach(function(h) { headRow.appendChild(el('th', null, h)); });
    thead.appendChild(headRow);
    table.appendChild(thead);

    var tbody = el('tbody');
    var colspan = headers.length;
    rows.forEach(function(rec) {
      var tr = buildFlatRow(rec, showStatus);
      var detailTr = buildDetailRow(rec, colspan);
      tr.addEventListener('click', function(e) {
        if (e.target.tagName === 'A') return;
        detailTr.hidden = !detailTr.hidden;
      });
      tbody.appendChild(tr);
      tbody.appendChild(detailTr);
    });
    table.appendChild(tbody);
    container.appendChild(table);
  }

  function renderWorthExploring() {
    renderFlatTable('worthExploringContainer', DATA.sections.worth_exploring,
      ['Company', 'Score', 'Path', 'Roles', 'Why'], false);
  }

  function renderWatchList() {
    renderFlatTable('watchListContainer', DATA.sections.watch_list,
      ['Company', 'Score', 'Path', 'Roles', 'Status'], true);
  }

  // ---------------------------------------------------------------------
  // Pipeline table: filters, search, sort
  // ---------------------------------------------------------------------
  var pipelineHeaders = [
    {label: 'Company', key: 'company'},
    {label: 'Score', key: 'score'},
    {label: 'Path', key: 'path'},
    {label: 'Roles', key: 'roles'},
    {label: 'Status', key: 'status_label'},
    {label: 'Last Action', key: 'last_action_date'}
  ];
  var pipelineSort = {key: null, dir: 'asc'};

  function pipelineSearchText(rec) {
    return [rec.company, rec.roles.join(' '), rec.notes, rec.rationale].join(' ').toLowerCase();
  }

  // Raw role_family values accumulate free-text variants over time; bucket
  // everything outside the top paths (by pipeline count) into 'Other' so the
  // chart and path filter stay readable.
  var PATH_BUCKET_LIMIT = 8;
  var pathBucketTop = null;
  function pathBuckets() {
    if (pathBucketTop) return pathBucketTop;
    var counts = {};
    DATA.sections.pipeline.forEach(function(rec) {
      var p = rec.path_canon || rec.path || 'Other';
      counts[p] = (counts[p] || 0) + 1;
    });
    pathBucketTop = Object.keys(counts).sort(function(a, b) {
      return counts[b] - counts[a];
    }).slice(0, PATH_BUCKET_LIMIT);
    return pathBucketTop;
  }
  function bucketOf(rec) {
    var p = rec.path_canon || rec.path || 'Other';
    return pathBuckets().indexOf(p) !== -1 ? p : 'Other';
  }

  function applyPipelineFilters() {
    var search = (document.getElementById('pipelineSearch').value || '').toLowerCase();
    var pathVal = document.getElementById('pathFilter').value;
    var statusVal = document.getElementById('statusFilter').value;
    var scoreVal = document.getElementById('scoreFilter').value;

    var rows = DATA.sections.pipeline.filter(function(rec) {
      var matchSearch = !search || pipelineSearchText(rec).indexOf(search) !== -1;
      var matchPath = !pathVal || bucketOf(rec) === pathVal;
      var matchScore = !scoreVal || rec.score_tier === scoreVal;
      var matchStatus = true;
      if (statusVal === 'not_applied') {
        matchStatus = !rec.status;
      } else if (statusVal) {
        matchStatus = rec.status === statusVal;
      }
      return matchSearch && matchPath && matchScore && matchStatus;
    });

    if (pipelineSort.key) {
      rows = rows.slice().sort(function(a, b) {
        var av = a[pipelineSort.key];
        var bv = b[pipelineSort.key];
        if (pipelineSort.key === 'roles') { av = a.roles.join(', '); bv = b.roles.join(', '); }
        if (pipelineSort.key === 'score') {
          av = av === null ? -1 : av; bv = bv === null ? -1 : bv;
          return pipelineSort.dir === 'asc' ? av - bv : bv - av;
        }
        av = (av || '').toString().toLowerCase();
        bv = (bv || '').toString().toLowerCase();
        if (av < bv) return pipelineSort.dir === 'asc' ? -1 : 1;
        if (av > bv) return pipelineSort.dir === 'asc' ? 1 : -1;
        return 0;
      });
    }

    renderPipelineTable(rows);
  }

  function renderPipelineTable(rows) {
    var container = document.getElementById('pipelineContainer');
    container.innerHTML = '';
    if (!rows.length) {
      container.appendChild(el('p', 'empty-message', 'No companies match these filters.'));
      return;
    }
    var table = el('table', 'pipeline-table');
    table.id = 'pipelineTable';
    var thead = el('thead');
    var headRow = el('tr');
    pipelineHeaders.forEach(function(h) {
      var th = el('th', null, h.label);
      if (pipelineSort.key === h.key) th.textContent = h.label + (pipelineSort.dir === 'asc' ? ' ▲' : ' ▼');
      th.addEventListener('click', function() {
        pipelineSort.dir = (pipelineSort.key === h.key && pipelineSort.dir === 'asc') ? 'desc' : 'asc';
        pipelineSort.key = h.key;
        applyPipelineFilters();
      });
      headRow.appendChild(th);
    });
    thead.appendChild(headRow);
    table.appendChild(thead);

    var tbody = el('tbody');
    var colspan = pipelineHeaders.length;
    rows.forEach(function(rec) {
      var tr = buildFlatRow(rec, true);
      var detailTr = buildDetailRow(rec, colspan);
      tr.addEventListener('click', function(e) {
        if (e.target.tagName === 'A') return;
        detailTr.hidden = !detailTr.hidden;
      });
      tbody.appendChild(tr);
      tbody.appendChild(detailTr);
    });
    table.appendChild(tbody);
    container.appendChild(table);
  }

  function renderPipeline() {
    var pathFilter = document.getElementById('pathFilter');
    var bucketNames = pathBuckets().slice();
    var hasOther = DATA.sections.pipeline.some(function(rec) {
      return bucketOf(rec) === 'Other';
    });
    if (hasOther && bucketNames.indexOf('Other') === -1) bucketNames.push('Other');
    bucketNames.forEach(function(p) {
      var opt = el('option', null, p);
      opt.value = p;
      pathFilter.appendChild(opt);
    });
    document.getElementById('pipelineSearch').addEventListener('input', applyPipelineFilters);
    pathFilter.addEventListener('change', applyPipelineFilters);
    document.getElementById('statusFilter').addEventListener('change', applyPipelineFilters);
    document.getElementById('scoreFilter').addEventListener('change', applyPipelineFilters);
    applyPipelineFilters();
  }

  // ---------------------------------------------------------------------
  // Hand-rolled SVG charts
  // ---------------------------------------------------------------------
  function svgEl(tag, attrs) {
    var e = document.createElementNS(svgNS, tag);
    for (var k in attrs) e.setAttribute(k, attrs[k]);
    return e;
  }

  function buildFunnelChart() {
    var all = DATA.sections.pipeline;
    var counts = {researching: 0, applied: 0, interviewing: 0, offer: 0};
    all.concat(DATA.sections.follow_up).forEach(function(rec) {
      if (counts.hasOwnProperty(rec.status)) counts[rec.status] += 1;
    });
    var stages = [['Researching', counts.researching], ['Applied', counts.applied],
                  ['Interviewing', counts.interviewing], ['Offer', counts.offer]];
    var total = stages.reduce(function(s, x) { return s + x[1]; }, 0);
    if (!total) return null;

    var w = 300, barH = 26, gap = 12, padTop = 8, labelW = 82;
    var h = padTop + stages.length * (barH + gap);
    var max = Math.max.apply(null, stages.map(function(s) { return s[1]; })) || 1;
    var svg = svgEl('svg', {viewBox: '0 0 ' + w + ' ' + h, class: 'chart-svg'});
    stages.forEach(function(s, i) {
      var y = padTop + i * (barH + gap);
      var barW = Math.max(3, (s[1] / max) * (w - labelW - 40));
      svg.appendChild(svgEl('rect', {x: labelW, y: y, width: barW, height: barH, rx: 4, class: 'funnel-bar'}));
      var label = svgEl('text', {x: labelW - 6, y: y + barH / 2 + 4, 'text-anchor': 'end', class: 'chart-label'});
      label.textContent = s[0];
      svg.appendChild(label);
      var value = svgEl('text', {x: labelW + barW + 6, y: y + barH / 2 + 4, class: 'chart-value'});
      value.textContent = String(s[1]);
      svg.appendChild(value);
    });
    return svg;
  }

  function buildHistogramChart() {
    var all = DATA.sections.pipeline.concat(DATA.sections.follow_up, DATA.sections.closed_out);
    var buckets = [
      {label: '0-49', min: 0, max: 50, count: 0},
      {label: '50-59', min: 50, max: 60, count: 0},
      {label: '60-69', min: 60, max: 70, count: 0},
      {label: '70-79', min: 70, max: 80, count: 0},
      {label: '80-89', min: 80, max: 90, count: 0},
      {label: '90-100', min: 90, max: 101, count: 0}
    ];
    var unscored = 0;
    all.forEach(function(rec) {
      if (rec.score === null || rec.score === undefined) { unscored += 1; return; }
      for (var i = 0; i < buckets.length; i++) {
        if (rec.score >= buckets[i].min && rec.score < buckets[i].max) { buckets[i].count += 1; break; }
      }
    });
    var total = buckets.reduce(function(s, b) { return s + b.count; }, 0) + unscored;
    if (!total) return null;

    var allBars = buckets.concat([{label: 'Unscored', count: unscored}]);
    var w = 320, barW = 40, gap = 10, padLeft = 24, padBottom = 24, chartH = 120;
    var maxCount = Math.max.apply(null, allBars.map(function(b) { return b.count; })) || 1;
    var h = chartH + padBottom;
    var svg = svgEl('svg', {viewBox: '0 0 ' + w + ' ' + h, class: 'chart-svg'});
    allBars.forEach(function(b, i) {
      var x = padLeft + i * (barW + gap);
      var barH = (b.count / maxCount) * (chartH - 16);
      var y = chartH - barH;
      svg.appendChild(svgEl('rect', {x: x, y: y, width: barW, height: Math.max(barH, 1), class: 'hist-bar', rx: 2}));
      var value = svgEl('text', {x: x + barW / 2, y: y - 4, 'text-anchor': 'middle', class: 'chart-value'});
      value.textContent = String(b.count);
      svg.appendChild(value);
      var label = svgEl('text', {x: x + barW / 2, y: chartH + 14, 'text-anchor': 'middle', class: 'chart-label'});
      label.textContent = b.label;
      svg.appendChild(label);
    });
    return svg;
  }

  function buildPathChart() {
    var counts = {};
    DATA.sections.pipeline.forEach(function(rec) {
      var p = bucketOf(rec);
      counts[p] = (counts[p] || 0) + 1;
    });
    var entries = Object.keys(counts).map(function(k) { return [k, counts[k]]; })
      .sort(function(a, b) { return b[1] - a[1]; });
    if (!entries.length) return null;

    var w = 300, barH = 22, gap = 10, padTop = 8, labelW = 120;
    var h = padTop + entries.length * (barH + gap);
    var max = Math.max.apply(null, entries.map(function(e) { return e[1]; })) || 1;
    var svg = svgEl('svg', {viewBox: '0 0 ' + w + ' ' + h, class: 'chart-svg'});
    entries.forEach(function(e, i) {
      var y = padTop + i * (barH + gap);
      var barW = Math.max(3, (e[1] / max) * (w - labelW - 40));
      svg.appendChild(svgEl('rect', {x: labelW, y: y, width: barW, height: barH, rx: 3, class: 'path-bar'}));
      var label = svgEl('text', {x: labelW - 6, y: y + barH / 2 + 4, 'text-anchor': 'end', class: 'chart-label'});
      label.textContent = e[0].length > 18 ? e[0].slice(0, 16) + '…' : e[0];
      svg.appendChild(label);
      var value = svgEl('text', {x: labelW + barW + 6, y: y + barH / 2 + 4, class: 'chart-value'});
      value.textContent = String(e[1]);
      svg.appendChild(value);
    });
    return svg;
  }

  function renderCharts() {
    var row = document.getElementById('chartsRow');
    var specs = [
      {title: 'Pipeline Funnel', build: buildFunnelChart},
      {title: 'Score Distribution', build: buildHistogramChart},
      {title: 'Companies per Path', build: buildPathChart}
    ];
    specs.forEach(function(spec) {
      var panel = el('div', 'chart-panel');
      panel.appendChild(el('h3', null, spec.title));
      var svg = spec.build();
      if (svg) {
        panel.appendChild(svg);
      } else {
        panel.appendChild(el('p', 'empty-message', 'Not enough data yet.'));
      }
      row.appendChild(panel);
    });
  }

  // ---------------------------------------------------------------------
  // Boot
  // ---------------------------------------------------------------------
  renderStats();
  renderCharts();
  renderFollowup();
  renderBestFits();
  renderWorthExploring();
  renderWatchList();
  renderPipeline();
  wireCollapsibleHeaders();
})();'''


# Backward-compat aliases for existing dashboard tests
def compute_stats(merged: list[dict]) -> dict:
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


def _merged_to_views(merged: list[dict]) -> dict:
    """Partition an old-style flat merged list into the views shape build_dashboard_data()
    expects. Used by build_html() and by rendering-layer tests that don't go through
    dashboard_views.build_active_views()."""
    follow_up = [r for r in merged if get_section(r) == 'followup']
    closed_out = [r for r in merged if get_section(r) == 'closed_out']
    bestfits = [r for r in merged if get_section(r) == 'bestfits']
    return {
        'follow_up': follow_up,
        'best_fits': bestfits,
        'worth_exploring': [],
        'closed_out': closed_out,
        'stats': {
            'follow_up': len(follow_up),
            'best_fits': len(bestfits),
            'worth_exploring': 0,
            'closed_out': len(closed_out),
            'total': len(follow_up) + len(bestfits) + len(closed_out),
        },
    }


def build_html(merged: list[dict], full_mode: bool) -> str:
    """Backward-compat: convert old-style merged list to views dict, then render."""
    views = _merged_to_views(merged)
    display_groups = _load_display_groups()
    data = build_dashboard_data(views, full_mode, display_groups=display_groups)
    return render_dashboard_html(data)


def main():
    parser = argparse.ArgumentParser(description='Generate career manager dashboard')
    parser.add_argument('--full', action='store_true', help='Show all companies per path')
    args = parser.parse_args()

    print("\n[Dashboard] Building views from opportunities.csv + applications.csv...")

    from dashboard_views import build_active_views
    sys.path.insert(0, str(BASE / 'scripts' / 'core'))
    from opportunities import sync_opportunities_from_targets

    target_csv = DATA / 'target-companies.csv'
    opportunities_csv = DATA / 'opportunities.csv'
    apps_csv = TRACKER_DATA / 'applications.csv'
    sync_opportunities_from_targets(target_csv, opportunities_csv)
    views = build_active_views(target_csv, apps_csv)
    watch_list_rows = read_watch_list_companies(target_csv)
    stats = views['stats']

    print(f"  Follow-up: {stats['follow_up']} | Best Fits: {stats['best_fits']} | Worth Exploring: {stats.get('worth_exploring', 0)} | Closed: {stats['closed_out']}")

    display_groups = _load_display_groups()
    data = build_dashboard_data(views, full_mode=args.full, display_groups=display_groups,
                                 watch_list_rows=watch_list_rows)
    html_content = render_dashboard_html(data)

    if args.full:
        output_path = DATA / 'dashboard-full.html'
    else:
        output_path = DATA / 'dashboard.html'

    output_path.write_text(html_content, encoding='utf-8')
    print(f"  Dashboard written: {output_path}")
    print(f"\n  Dashboard ready: file://{output_path}")


if __name__ == '__main__':
    main()
