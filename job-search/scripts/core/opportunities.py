"""
Opportunity-level source of truth helpers.

Companies are monitored at company level, but actions happen at role level.
This module turns target-company rows into stable opportunity rows and
matches applications to those opportunities by role URL or role title.
"""
from __future__ import annotations

import csv
import hashlib
import json
import re
from pathlib import Path
from urllib.parse import unquote, urlsplit, urlunsplit

try:
    from csv_schema import OPPORTUNITY_HEADER
except ImportError:  # pragma: no cover - fallback for direct execution
    from .csv_schema import OPPORTUNITY_HEADER

try:
    from path_normalizer import normalize_company as _canonical_company
except ImportError:  # pragma: no cover - fallback for direct execution
    _canonical_company = lambda name: name  # noqa: E731


CLOSED_APP_STATUSES = {'rejected', 'closed', 'declined', 'no_fit_now'}
APPLIED_APP_STATUSES = {'applied', 'interviewing', 'offer'}
NON_ROLE_VALUES = {
    '',
    'none',
    'none detected',
    'none - watch list',
    'none — watch list',
    'unknown',
    'not confirmed',
}


def normalize_company(value: str) -> str:
    return re.sub(r'\s+', ' ', (value or '').strip()).lower()


def normalize_text(value: str) -> str:
    value = (value or '').lower()
    value = value.replace('&', ' and ')
    value = re.sub(r'[^a-z0-9]+', ' ', value)
    return re.sub(r'\s+', ' ', value).strip()


def normalize_url(value: str) -> str:
    """Normalize URLs for matching by stripping query, fragment, and trailing slash."""
    raw = (value or '').strip()
    if not raw:
        return ''
    parts = urlsplit(raw)
    if not parts.scheme and not parts.netloc:
        return raw.rstrip('/').lower()
    path = parts.path.rstrip('/') or '/'
    return urlunsplit((parts.scheme.lower(), parts.netloc.lower(), path, '', '')).rstrip('/')


def _token_set(value: str) -> set[str]:
    stop = {'and', 'the', 'of', 'for', 'to', 'a', 'an', 'role'}
    return {t for t in normalize_text(value).split() if t and t not in stop}


def role_titles_match(left: str, right: str) -> bool:
    """Return True when two role titles clearly describe the same opportunity."""
    l_norm = normalize_text(left)
    r_norm = normalize_text(right)
    if not l_norm or not r_norm:
        return False
    if l_norm in r_norm or r_norm in l_norm:
        return True
    left_tokens = _token_set(left)
    right_tokens = _token_set(right)
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens)
    return overlap >= 2 and overlap / min(len(left_tokens), len(right_tokens)) >= 0.6


def role_title_matches_url(role_title: str, url: str) -> bool:
    """Return True when a job URL slug appears to describe the role title."""
    parts = urlsplit(url or '')
    url_text = unquote(' '.join([parts.netloc, parts.path]))
    url_tokens = _token_set(url_text)
    role_tokens = _token_set(role_title)
    if not url_tokens or not role_tokens:
        return False
    overlap = len(url_tokens & role_tokens)
    return overlap >= 2 and overlap / min(len(role_tokens), len(url_tokens)) >= 0.6


def looks_like_job_url(value: str) -> bool:
    """Return True when a URL points to a specific job rather than a careers index."""
    parts = urlsplit(value or '')
    host = parts.netloc.lower()
    path = parts.path.lower()
    if 'linkedin.com' in host and '/jobs/view' in path:
        return True
    if 'greenhouse.io' in host and '/jobs/' in path:
        return True
    if 'lever.co' in host and path.strip('/').count('/') >= 1:
        return True
    return bool(re.search(r'/(job|jobs|positions|openings)/[^/]+', path))


def split_role_titles(open_positions: str) -> list[str]:
    """Split semicolon-delimited role inventory into display-ready role titles."""
    roles = []
    for part in (open_positions or '').split(';'):
        title = re.sub(r'\s+', ' ', part).strip()
        title_key = normalize_text(title)
        if title_key in NON_ROLE_VALUES:
            continue
        if title and title not in roles:
            roles.append(title)
    return roles


def opportunity_key(company: str, role_title: str, role_url: str, source: str = '') -> str:
    company_key = normalize_company(company)
    url_key = normalize_url(role_url)
    role_key = normalize_text(role_title)
    basis = f'{company_key}|{url_key or role_key}|{normalize_text(source)}'
    return hashlib.sha1(basis.encode('utf-8')).hexdigest()[:16]


# Agents sometimes annotate a role they rejected instead of leaving it out,
# e.g. "Product Manager | Tax (excluded, tax-core role)".
_EXCLUDED_ROLE = re.compile(r'\(\s*excluded\b', re.IGNORECASE)
_TRAILING_PAREN = re.compile(r'\s*\([^()]*\)\s*$')


def _strip_annotations(title: str) -> str:
    """Drop trailing parentheticals such as "(SF, $180K-$250K)"."""
    prev = None
    while prev != title:
        prev, title = title, _TRAILING_PAREN.sub('', title)
    return title


def _is_hard_pass(entry: dict) -> bool:
    return str(entry.get('llm_hard_pass', '')).strip().lower() == 'true'


def _entry_score(entry: dict) -> float:
    try:
        return float(entry.get('llm_score') or 0)
    except (TypeError, ValueError):
        return 0.0


def _better_entry(current: dict | None, candidate: dict) -> dict:
    """Pick the entry that represents a role posted more than once:
    any live posting beats a hard-passed one, then the higher score wins."""
    if current is None:
        return candidate
    if _is_hard_pass(current) != _is_hard_pass(candidate):
        return current if _is_hard_pass(candidate) else candidate
    return candidate if _entry_score(candidate) > _entry_score(current) else current


def load_role_scores(seen_jobs_path: Path) -> dict[tuple[str, str], dict]:
    """Index per-job evaluations from seen-jobs.json by (company, role title).

    A company row keeps one score, but each evaluated posting has its own.
    Keys use both the full title and the title without trailing
    parentheticals so annotated titles still find their evaluation.
    """
    if not seen_jobs_path or not Path(seen_jobs_path).exists():
        return {}
    try:
        seen = json.loads(Path(seen_jobs_path).read_text(encoding='utf-8'))
    except (json.JSONDecodeError, OSError):
        return {}
    index: dict[tuple[str, str], dict] = {}
    for entry in (seen.values() if isinstance(seen, dict) else []):
        if not isinstance(entry, dict) or entry.get('llm_score') in (None, ''):
            continue
        company = normalize_company(_canonical_company(entry.get('company', '')))
        title = entry.get('title', '')
        for title_key in {normalize_text(title), normalize_text(_strip_annotations(title))}:
            if company and title_key:
                index[(company, title_key)] = _better_entry(index.get((company, title_key)), entry)
    return index


def _lookup_role_score(role_scores: dict, company: str, role_title: str) -> dict | None:
    if not role_scores:
        return None
    company_key = normalize_company(company)
    return (role_scores.get((company_key, normalize_text(role_title)))
            or role_scores.get((company_key, normalize_text(_strip_annotations(role_title)))))


def default_role_scores(target_csv: Path) -> dict[tuple[str, str], dict]:
    """Per-role scores stored next to the target CSV, if any."""
    return load_role_scores(Path(target_csv).parent / 'seen-jobs.json')


def target_row_to_opportunities(row: dict, role_scores: dict | None = None) -> list[dict]:
    """Convert a target-company row into one or more opportunity rows.

    Each role takes its own evaluation from role_scores when one exists and
    falls back to the company-level score otherwise.
    """
    company = (row.get('company') or '').strip()
    if not company:
        return []

    roles = split_role_titles(row.get('open_positions', ''))
    if not roles:
        fallback = (row.get('open_positions') or row.get('role_family') or '').strip()
        roles = [fallback] if normalize_text(fallback) not in NON_ROLE_VALUES else []
    if not roles and ((row.get('role_url') or '').strip() or (row.get('careers_url') or '').strip()):
        roles = ['Open role']
    if not roles:
        return []

    lifecycle = (row.get('lifecycle_state') or '').strip()
    if not lifecycle:
        lifecycle = 'active' if row.get('validation_status') == 'pass' else 'watching'
    validation = (row.get('validation_status') or '').strip()
    is_open_company = lifecycle == 'active' and validation not in {'fail', 'watch_list'}
    status = 'open' if is_open_company else 'unknown'

    shared_role_url = (row.get('role_url') or '').strip()
    careers_url = (row.get('careers_url') or '').strip()
    multiple_roles = len(roles) > 1
    careers_url_is_job = looks_like_job_url(careers_url)

    opportunities = []
    for role_title in roles:
        if _EXCLUDED_ROLE.search(role_title):
            continue
        evaluation = _lookup_role_score(role_scores, company, role_title)
        if evaluation and _is_hard_pass(evaluation):
            continue
        scored_from = evaluation or {
            'llm_score': row.get('llm_score', ''),
            'llm_dimensions_evaluated': row.get('llm_dimensions_evaluated', ''),
            'llm_rationale': row.get('llm_rationale', ''),
            'llm_flags': row.get('llm_flags', ''),
        }
        this_role_url = ''
        if shared_role_url and (not multiple_roles or role_title_matches_url(role_title, shared_role_url)):
            this_role_url = shared_role_url
        this_careers_url = ''
        if careers_url and (not multiple_roles or not careers_url_is_job or this_role_url == careers_url):
            this_careers_url = careers_url
        apply_url = this_role_url or this_careers_url
        opportunities.append({
            'opportunity_key': opportunity_key(company, role_title, this_role_url, row.get('source', '')),
            'company': company,
            'role_title': role_title,
            'role_url': this_role_url,
            'apply_url': apply_url,
            'careers_url': this_careers_url,
            'opportunity_status': status,
            'company_lifecycle_state': lifecycle,
            'validation_status': validation,
            'llm_score': scored_from.get('llm_score', ''),
            'llm_dimensions_evaluated': scored_from.get('llm_dimensions_evaluated', ''),
            'role_family': row.get('role_family', ''),
            'source': row.get('source', ''),
            'source_key': row.get('role_url', '') or row.get('careers_url', ''),
            'last_checked': row.get('last_checked', ''),
            'last_verified_at': row.get('last_verified_at', ''),
            'fit_summary': scored_from.get('llm_rationale', ''),
            'llm_flags': scored_from.get('llm_flags', ''),
            'notes': row.get('notes', ''),
        })
    return opportunities


def read_csv(path: Path) -> list[dict]:
    if not path.exists():
        return []
    with path.open(encoding='utf-8') as f:
        return list(csv.DictReader(f))


def write_opportunities(path: Path, rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        writer = csv.DictWriter(f, fieldnames=OPPORTUNITY_HEADER, extrasaction='ignore')
        writer.writeheader()
        writer.writerows(rows)


def opportunities_from_targets(target_rows: list[dict], role_scores: dict | None = None) -> list[dict]:
    rows: list[dict] = []
    seen: set[str] = set()
    for target in target_rows:
        for opportunity in target_row_to_opportunities(target, role_scores):
            key = opportunity['opportunity_key']
            if key in seen:
                continue
            seen.add(key)
            rows.append(opportunity)
    return rows


def sync_opportunities_from_targets(target_csv: Path, opportunities_csv: Path) -> list[dict]:
    """Regenerate opportunities.csv from target-companies.csv."""
    rows = opportunities_from_targets(read_csv(target_csv), default_role_scores(target_csv))
    rows.sort(key=lambda r: (
        -_score_value(r),
        normalize_company(r.get('company', '')),
        normalize_text(r.get('role_title', '')),
    ))
    write_opportunities(opportunities_csv, rows)
    return rows


def company_best_scores(target_rows: list[dict], role_scores: dict | None = None) -> dict[str, int]:
    """Score each company by its best open role (company score if it lists none)."""
    best: dict[str, int] = {}
    for row in target_rows:
        name = (row.get('company') or '').strip()
        if not name:
            continue
        opportunities = target_row_to_opportunities(row, role_scores)
        scores = [_score_value(o) for o in opportunities] or [_score_value(row)]
        best[name] = int(max(scores))
    return best


def _score_value(row: dict) -> float:
    try:
        return float(row.get('llm_score') or 0)
    except (TypeError, ValueError):
        return 0.0


def matching_applications(opportunity: dict, apps: list[dict]) -> list[dict]:
    """Find applications that refer to the same company and same role opportunity."""
    company_key = normalize_company(opportunity.get('company', ''))
    role_url = normalize_url(opportunity.get('role_url', '')) or normalize_url(opportunity.get('apply_url', ''))
    role_title = opportunity.get('role_title', '')
    matches = []
    for app in apps:
        if normalize_company(app.get('company', '')) != company_key:
            continue
        app_url = normalize_url(app.get('job_url', ''))
        if role_url and app_url and role_url == app_url:
            matches.append(app)
            continue
        if role_titles_match(role_title, app.get('role', '')):
            matches.append(app)
            continue
        if not app_url and not normalize_text(app.get('role', '')):
            matches.append(app)
    return matches


def application_to_view_row(app: dict) -> dict:
    """Convert an application-only row to the dashboard/action row shape."""
    return {
        'opportunity_key': '',
        'company': app.get('company', ''),
        'llm_score': '',
        'role_family': '',
        'open_positions': app.get('role', ''),
        'role_title': app.get('role', ''),
        'careers_url': app.get('job_url', ''),
        'role_url': app.get('job_url', ''),
        'apply_url': app.get('job_url', ''),
        'app_status': app.get('status', ''),
        'date_added': app.get('date_added', ''),
        'date_applied': app.get('date_applied', ''),
        'last_contact': app.get('last_contact', ''),
        'contact_name': app.get('contact_name', ''),
        'contact_email': app.get('contact_email', ''),
        'app_notes': app.get('notes', ''),
        'lifecycle_state': 'active',
        'validation_status': 'pass',
    }


def opportunity_to_view_row(opportunity: dict, app: dict | None = None) -> dict:
    """Convert an opportunity plus optional matched application to legacy view row shape."""
    app = app or {}
    return {
        'opportunity_key': opportunity.get('opportunity_key', ''),
        'company': opportunity.get('company', ''),
        'llm_score': opportunity.get('llm_score', ''),
        'llm_dimensions_evaluated': opportunity.get('llm_dimensions_evaluated', ''),
        'role_family': opportunity.get('role_family', ''),
        'open_positions': opportunity.get('role_title', ''),
        'role_title': opportunity.get('role_title', ''),
        'careers_url': opportunity.get('careers_url', ''),
        'role_url': opportunity.get('role_url', ''),
        'apply_url': opportunity.get('apply_url', ''),
        'source_key': opportunity.get('source_key', ''),
        'llm_rationale': opportunity.get('fit_summary', ''),
        'llm_flags': opportunity.get('llm_flags', ''),
        'notes': opportunity.get('notes', ''),
        'app_status': app.get('status', ''),
        'date_added': app.get('date_added', ''),
        'date_applied': app.get('date_applied', ''),
        'last_contact': app.get('last_contact', ''),
        'contact_name': app.get('contact_name', ''),
        'contact_email': app.get('contact_email', ''),
        'app_notes': app.get('notes', ''),
        'lifecycle_state': opportunity.get('company_lifecycle_state', ''),
        'validation_status': opportunity.get('validation_status', ''),
    }
