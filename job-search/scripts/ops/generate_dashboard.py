#!/usr/bin/env python3
"""
Generate a static HTML dashboard from pipeline CSV data.

Usage:
  uv run job-search/scripts/ops/generate_dashboard.py           # summary dashboard
  uv run job-search/scripts/ops/generate_dashboard.py --full    # full target list
"""

from __future__ import annotations

import argparse
import csv
import html
import json
import sys
from datetime import datetime
from pathlib import Path

BASE = Path(__file__).resolve().parents[2]
DATA = BASE / 'data'


def read_action_list() -> list[dict]:
    """Read action-list.csv and return rows as dicts."""
    path = DATA / 'action-list.csv'
    if not path.exists():
        print(f"  ERROR: {path} not found. Run phase 3 first.")
        sys.exit(1)
    with path.open(encoding='utf-8') as f:
        return list(csv.DictReader(f))


def read_target_companies(limit: int = 0, pass_only: bool = True) -> list[dict]:
    """Read target-companies.csv. If limit > 0, return top N by llm_score."""
    path = DATA / 'target-companies.csv'
    if not path.exists():
        return []
    with path.open(encoding='utf-8') as f:
        rows = list(csv.DictReader(f))

    if pass_only:
        rows = [r for r in rows if r.get('validation_status') == 'pass']

    def score_key(r):
        try:
            return float(r.get('llm_score', '') or '0')
        except (ValueError, TypeError):
            return 0.0
    rows.sort(key=score_key, reverse=True)

    if limit > 0:
        rows = rows[:limit]
    return rows


def build_source_map(targets: list[dict]) -> dict[str, str]:
    """Map lowercase company name -> source from target-companies.csv."""
    return {
        r.get('company', '').strip().lower(): r.get('source', '')
        for r in targets
    }


def score_color(score_str: str) -> str:
    """Return CSS color class based on score value."""
    try:
        s = float(score_str)
    except (ValueError, TypeError):
        return 'score-low'
    if s >= 75:
        return 'score-high'
    elif s >= 60:
        return 'score-med'
    return 'score-low'


def escape(val: str) -> str:
    """HTML-escape a string."""
    return html.escape(val or '', quote=True)


def build_html(action_rows: list[dict], all_targets: list[dict],
               full_mode: bool, full_targets: list[dict] | None = None) -> str:
    """Build the complete HTML dashboard string."""

    source_map = build_source_map(all_targets)

    # Stats
    total_companies = len(all_targets)
    action_count = len(action_rows)
    scores = []
    for r in action_rows:
        try:
            scores.append(float(r.get('llm_score', '0') or '0'))
        except (ValueError, TypeError):
            pass
    avg_score = sum(scores) / len(scores) if scores else 0
    run_date = datetime.now().strftime('%Y-%m-%d %H:%M')

    # Collect unique paths for filter dropdown
    paths = sorted(set(
        r.get('path', '').strip()
        for r in action_rows
        if r.get('path', '').strip()
    ))

    # Build action list table rows
    def make_table_row(r: dict, include_source: bool = False) -> str:
        company = escape(r.get('company', ''))
        apply_url = r.get('apply_url', '').strip()
        role = escape(r.get('role', '') or r.get('open_positions', ''))
        score = r.get('llm_score', '')
        path = escape(r.get('path', '') or r.get('role_family', ''))
        rationale = escape(r.get('fit_summary', '') or r.get('llm_rationale', ''))
        color = score_color(score)

        # Role URL: try role_url, fall back to careers_url, then apply_url
        role_url = (r.get('role_url', '') or r.get('careers_url', '') or apply_url).strip()

        company_link = f'<a href="{escape(apply_url)}" target="_blank">{company}</a>' if apply_url else company
        role_link = f'<a href="{escape(role_url)}" target="_blank">{role}</a>' if role_url and role else (role or '-')

        source = ''
        if include_source:
            key = r.get('company', '').strip().lower()
            source = escape(source_map.get(key, ''))

        source_cell = f'<td>{source}</td>' if include_source else ''

        return f'''<tr data-path="{escape(r.get('path', ''))}" data-score="{escape(score)}">
  <td>{company_link}</td>
  <td>{role_link}</td>
  <td class="{color}">{escape(score)}</td>
  <td>{path}</td>
  <td class="rationale">{rationale}</td>
  {source_cell}
</tr>'''

    action_table_rows = '\n'.join(make_table_row(r, include_source=True) for r in action_rows)

    # Path filter options
    path_options = '\n'.join(f'<option value="{escape(p)}">{escape(p)}</option>' for p in paths)

    title = 'Career Manager Dashboard (Full)' if full_mode else 'Career Manager Dashboard'

    # All Targets table (full mode only)
    full_section = ''
    if full_mode and full_targets:
        all_target_rows_html = '\n'.join(make_table_row(r, include_source=True) for r in full_targets)
        full_section = f'''<h2>All Targets ({len(full_targets)} companies)</h2>

<table id="allTable">
<thead>
<tr>
  <th onclick="sortTable('allTable', 0)">Company</th>
  <th onclick="sortTable('allTable', 1)">Role</th>
  <th onclick="sortTable('allTable', 2)">Score</th>
  <th onclick="sortTable('allTable', 3)">Path</th>
  <th onclick="sortTable('allTable', 4)">Rationale</th>
  <th onclick="sortTable('allTable', 5)">Source</th>
</tr>
</thead>
<tbody>
{all_target_rows_html}
</tbody>
</table>'''

    return f'''<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  * {{ margin: 0; padding: 0; box-sizing: border-box; }}
  body {{ font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif; background: #f5f5f5; color: #333; padding: 20px; }}
  h1 {{ margin-bottom: 8px; font-size: 1.5rem; }}
  .stats {{ display: flex; gap: 16px; margin-bottom: 20px; flex-wrap: wrap; }}
  .stat {{ background: #fff; padding: 16px 24px; border-radius: 8px; box-shadow: 0 1px 3px rgba(0,0,0,0.1); }}
  .stat .value {{ font-size: 1.8rem; font-weight: 700; color: #2563eb; }}
  .stat .label {{ font-size: 0.85rem; color: #666; margin-top: 4px; }}
  .filters {{ display: flex; gap: 12px; margin-bottom: 16px; align-items: center; flex-wrap: wrap; }}
  .filters input, .filters select {{ padding: 8px 12px; border: 1px solid #ddd; border-radius: 6px; font-size: 0.9rem; }}
  .filters input {{ width: 250px; }}
  table {{ width: 100%; border-collapse: collapse; background: #fff; border-radius: 8px; overflow: hidden; box-shadow: 0 1px 3px rgba(0,0,0,0.1); margin-bottom: 32px; }}
  th {{ background: #f8f9fa; padding: 12px 16px; text-align: left; font-size: 0.85rem; color: #555; cursor: pointer; user-select: none; border-bottom: 2px solid #e5e7eb; }}
  th:hover {{ background: #e5e7eb; }}
  td {{ padding: 10px 16px; border-bottom: 1px solid #f0f0f0; font-size: 0.9rem; }}
  tr:hover {{ background: #f8f9fa; }}
  a {{ color: #2563eb; text-decoration: none; }}
  a:hover {{ text-decoration: underline; }}
  .score-high {{ color: #16a34a; font-weight: 700; }}
  .score-med {{ color: #d97706; font-weight: 600; }}
  .score-low {{ color: #dc2626; }}
  .rationale {{ max-width: 300px; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }}
  .rationale:hover {{ white-space: normal; overflow: visible; }}
  h2 {{ margin: 24px 0 12px; font-size: 1.2rem; }}
  .generated {{ color: #999; font-size: 0.8rem; margin-top: 20px; }}
</style>
</head>
<body>

<h1>{title}</h1>

<div class="stats">
  <div class="stat"><div class="value">{total_companies}</div><div class="label">Total Companies</div></div>
  <div class="stat"><div class="value">{action_count}</div><div class="label">Action Items</div></div>
  <div class="stat"><div class="value">{avg_score:.0f}</div><div class="label">Avg Fit Score</div></div>
  <div class="stat"><div class="value">{run_date}</div><div class="label">Generated</div></div>
</div>

<h2>Action List</h2>

<div class="filters">
  <input type="text" id="search" placeholder="Search company or role..." oninput="filterTable()">
  <select id="pathFilter" onchange="filterTable()">
    <option value="">All Paths</option>
    {path_options}
  </select>
  <select id="scoreFilter" onchange="filterTable()">
    <option value="">All Scores</option>
    <option value="75">75+ (High)</option>
    <option value="60">60+ (Med+)</option>
    <option value="40">40+ (Low+)</option>
  </select>
</div>

<table id="actionTable">
<thead>
<tr>
  <th onclick="sortTable('actionTable', 0)">Company</th>
  <th onclick="sortTable('actionTable', 1)">Role</th>
  <th onclick="sortTable('actionTable', 2)">Score</th>
  <th onclick="sortTable('actionTable', 3)">Path</th>
  <th onclick="sortTable('actionTable', 4)">Rationale</th>
  <th onclick="sortTable('actionTable', 5)">Source</th>
</tr>
</thead>
<tbody>
{action_table_rows}
</tbody>
</table>

{full_section}

<p class="generated">Generated {run_date}</p>

<script>
function filterTable() {{
  const search = document.getElementById('search').value.toLowerCase();
  const pathVal = document.getElementById('pathFilter').value;
  const scoreVal = document.getElementById('scoreFilter').value;
  const minScore = scoreVal ? parseFloat(scoreVal) : 0;

  document.querySelectorAll('#actionTable tbody tr').forEach(tr => {{
    const text = tr.textContent.toLowerCase();
    const path = tr.dataset.path || '';
    const score = parseFloat(tr.dataset.score) || 0;

    const matchSearch = !search || text.includes(search);
    const matchPath = !pathVal || path === pathVal;
    const matchScore = score >= minScore;

    tr.style.display = (matchSearch && matchPath && matchScore) ? '' : 'none';
  }});
}}

function sortTable(tableId, colIdx) {{
  const table = document.getElementById(tableId);
  const tbody = table.querySelector('tbody');
  const rows = Array.from(tbody.querySelectorAll('tr'));

  const dir = table.dataset.sortCol == colIdx && table.dataset.sortDir === 'asc' ? 'desc' : 'asc';
  table.dataset.sortCol = colIdx;
  table.dataset.sortDir = dir;

  rows.sort((a, b) => {{
    let aVal = a.cells[colIdx]?.textContent.trim() || '';
    let bVal = b.cells[colIdx]?.textContent.trim() || '';

    // Try numeric sort for score column
    const aNum = parseFloat(aVal);
    const bNum = parseFloat(bVal);
    if (!isNaN(aNum) && !isNaN(bNum)) {{
      return dir === 'asc' ? aNum - bNum : bNum - aNum;
    }}

    return dir === 'asc' ? aVal.localeCompare(bVal) : bVal.localeCompare(aVal);
  }});

  rows.forEach(r => tbody.appendChild(r));
}}
</script>

</body>
</html>'''


def main():
    parser = argparse.ArgumentParser(description='Generate career manager dashboard')
    parser.add_argument('--full', action='store_true', help='Include all target companies')
    args = parser.parse_args()

    print("\n[Dashboard] Reading CSV data...")

    action_rows = read_action_list()
    all_targets = read_target_companies()

    if args.full:
        all_targets_unfiltered = read_target_companies(pass_only=False)
        html_content = build_html(action_rows, all_targets, full_mode=True,
                                  full_targets=all_targets_unfiltered)
        output_path = DATA / 'dashboard-full.html'
    else:
        html_content = build_html(action_rows, all_targets, full_mode=False)
        output_path = DATA / 'dashboard.html'

    output_path.write_text(html_content, encoding='utf-8')
    print(f"  Dashboard written: {output_path}")
    print(f"\n  Dashboard ready: file://{output_path}")


if __name__ == '__main__':
    main()
