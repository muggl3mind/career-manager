#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import re
from collections import Counter
from datetime import datetime
from pathlib import Path
from typing import Dict, List, Tuple

import requests
try:
    from jobspy import scrape_jobs
    JOBSPY_AVAILABLE = True
except ImportError:
    JOBSPY_AVAILABLE = False
    print("[jobspy] python-jobspy not installed — job board scraping disabled")

BASE = Path(__file__).resolve().parents[2]

import sys
sys.path.insert(0, str(BASE.parent / "scripts"))
from config_loader import get as config_get
sys.path.insert(0, str(BASE / "scripts" / "core"))
from search_config_loader import load_search_config
from csv_schema import HEADER
from company_dedup import find_existing, merge_into_existing
from path_normalizer import normalize_company

DATA = BASE / 'data'

RAW_CSV = DATA / 'raw-discovery.csv'
TARGET_CSV = DATA / 'target-companies.csv'

# --- Search configuration (loaded from search-config.json) ---
# Load at module level but do NOT sys.exit() here — that would kill test runners
# and any module that imports discovery_pipeline. The exit guard is in main().
_SEARCH_CONFIG = load_search_config(DATA / 'search-config.json')

def _build_regex(patterns: list) -> re.Pattern:
    """Compile a list of patterns into a single word-boundary regex. Returns a never-match pattern if list is empty."""
    if not patterns:
        return re.compile(r'(?!)')  # never matches
    # Strip inline flags (e.g., (?i)) that conflict with re.I
    cleaned = [re.sub(r'\(\?[aiLmsux]+\)', '', p) for p in patterns]
    return re.compile(r'\b(' + '|'.join(cleaned) + r')\b', re.I)

# JobSpy country codes for Indeed — LinkedIn uses free-text location strings
COUNTRY_INDEED_MAP = {
    "United States": "USA",
    "United Kingdom": "GBR",
    "Ireland": "IRL",
    "Canada": "CAN",
    "Australia": "AUS",
    "Germany": "DEU",
    "France": "FRA",
    "Netherlands": "NLD",
    "Singapore": "SGP",
    "India": "IND",
    "Japan": "JPN",
    "Spain": "ESP",
    "Italy": "ITA",
    "Hong Kong": "HKG",
}

if _SEARCH_CONFIG:
    QUERY_PACKS = {k: v["queries"] for k, v in _SEARCH_CONFIG["query_packs"].items()}
    QUERY_PACK_TO_PATH = {k: v["label"] for k, v in _SEARCH_CONFIG["query_packs"].items()}
    ROLE_INCLUDE = _SEARCH_CONFIG["role_include_patterns"]
    ROLE_EXCLUDE = _SEARCH_CONFIG["role_exclude_patterns"]
    BA_ALLOWED_CONTEXT = _SEARCH_CONFIG.get("role_rescue_keywords", [])
    EMPLOYER_EXCLUDE = _build_regex(_SEARCH_CONFIG.get("employer_exclude_patterns", []))
    AGENCY_DETECT = _build_regex(_SEARCH_CONFIG.get("agency_patterns", []))
    NON_US_PAT = _build_regex(_SEARCH_CONFIG.get("location_exclude_patterns", []))
    _kw = _SEARCH_CONFIG.get("keywords", {})
    DOMAIN_KEYWORDS = _kw.get("domain", [])
    AI_KEYWORDS = _kw.get("ai", [])
    TECH_KEYWORDS = _kw.get("tech", [])
    SEARCH_LOCATIONS = _SEARCH_CONFIG.get("search_locations") or ["United States"]
else:
    # Defaults so imports don't crash — main() will exit if config is missing
    QUERY_PACKS = {}
    QUERY_PACK_TO_PATH = {}
    ROLE_INCLUDE = []
    ROLE_EXCLUDE = []
    BA_ALLOWED_CONTEXT = []
    EMPLOYER_EXCLUDE = re.compile(r'(?!)')
    AGENCY_DETECT = re.compile(r'(?!)')
    NON_US_PAT = re.compile(r'(?!)')
    DOMAIN_KEYWORDS = []
    AI_KEYWORDS = []
    TECH_KEYWORDS = []
    SEARCH_LOCATIONS = ["United States"]

PLACEHOLDER_PAT = re.compile(r"\b(check careers|see careers|careers page|tbd|n/?a)\b", re.I)


def _sync_xlsx() -> None:
    try:
        import sys as _sys
        _sys.path.insert(0, str(BASE / 'scripts' / 'core'))
        from target_companies_sync import csv_to_xlsx
        csv_to_xlsx()
    except Exception as e:
        print(f"  [xlsx] WARN: could not write xlsx: {e}")


def norm(s: str) -> str:
    return re.sub(r'\s+', ' ', (s or '').strip())


def norm_url(u: str) -> str:
    u = norm(u)
    if not u:
        return ''
    if not u.startswith('http'):
        u = 'https://' + u
    return u


def write_csv(path: Path, rows: List[Dict], header: List[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open('w', newline='', encoding='utf-8') as f:
        w = csv.DictWriter(f, fieldnames=header)
        w.writeheader()
        w.writerows(rows)


def _read_existing(path: Path) -> List[Dict]:
    if not path.exists():
        return []
    with path.open(encoding='utf-8') as f:
        return list(csv.DictReader(f))


def detect_industry(text: str) -> str:
    """Classify company industry from text. Customize for your domain."""
    # Override this with your own industry categories
    return 'Unknown'


def detect_tech_signals(text: str) -> str:
    t = text.lower()
    found = []
    for k in AI_KEYWORDS + TECH_KEYWORDS:
        if k in t and k not in found:
            found.append(k)
    return ', '.join(found[:6]) if found else 'None detected'


def gate_title(title: str, text: str) -> Tuple[bool, str]:
    t = title.lower()
    tx = text.lower()

    if any(re.search(p, t) for p in ROLE_EXCLUDE):
        # Business analyst exception if in strong context
        if re.search(r'business analyst', t):
            if any(re.search(p, tx) for p in BA_ALLOWED_CONTEXT):
                pass
            else:
                return False, 'title_excluded_business_analyst_generic'
        else:
            return False, 'title_excluded_irrelevant'

    if not any(re.search(p, t) for p in ROLE_INCLUDE):
        return False, 'title_miss_target_role_family'

    # tighten generic PM matches — add your domain keywords here
    # if re.search(r'product manager', t):
    #     if not any(k in tx for k in ['your', 'domain', 'keywords']):
    #         return False, 'title_excluded_generic_pm_outside_domain'

    return True, ''


def check_url(url: str) -> Tuple[bool, str]:
    if not url:
        return False, 'link_missing'
    h = {'User-Agent': 'Mozilla/5.0'}
    for _ in range(2):
        try:
            r = requests.get(url, timeout=10, allow_redirects=True, headers=h)
            code = r.status_code
            if code in (200, 301, 302, 307, 308, 401, 403):
                return True, ''
            return False, f'link_bad_{code}'
        except requests.Timeout:
            continue
        except Exception:
            return False, 'link_error'
    return False, 'link_timeout'


def discover(limit: int) -> List[Dict]:
    if not JOBSPY_AVAILABLE or not config_get("integrations.jobspy_enabled", False):
        print("[jobspy] Scraping skipped — disabled or not installed")
        return []
    rows: List[Dict] = []
    warned_locations: set = set()
    for family, queries in QUERY_PACKS.items():
        for q in queries:
            for loc in SEARCH_LOCATIONS:
                country_code = COUNTRY_INDEED_MAP.get(loc)
                sites = ['indeed', 'linkedin'] if country_code else ['linkedin']
                if not country_code and loc not in warned_locations:
                    print(f"[jobspy] No Indeed country code for '{loc}' — LinkedIn only")
                    warned_locations.add(loc)
                try:
                    kwargs = {
                        'site_name': sites,
                        'search_term': q,
                        'location': loc,
                        'results_wanted': limit,
                        'hours_old': 168,
                    }
                    if country_code:
                        kwargs['country_indeed'] = country_code
                    df = scrape_jobs(**kwargs)
                except Exception:
                    continue
                if df is None or len(df) == 0:
                    continue
                for _, r in df.iterrows():
                    company = norm(str(r.get('company') or ''))
                    title = norm(str(r.get('title') or ''))
                    url = norm_url(str(r.get('job_url') or ''))
                    desc = norm(str(r.get('description') or ''))[:2500]
                    row_loc = norm(str(r.get('location') or ''))
                    src = norm(str(r.get('site') or 'jobspy'))
                    if not company or not title or not url:
                        continue
                    rows.append({
                        'company': company,
                        'title': title,
                        'url': url,
                        'desc': desc,
                        'location': row_loc,
                        'source': src,
                        'role_family': QUERY_PACK_TO_PATH.get(family, family),
                    })
    return rows


def main() -> int:
    if _SEARCH_CONFIG is None:
        print("[search] Cannot run pipeline without search configuration.")
        print("[search] Run the onboarding skill to generate your search configuration.")
        return 1
    ap = argparse.ArgumentParser()
    ap.add_argument('--dry-run', action='store_true')
    ap.add_argument('--limit', type=int, default=35)
    ap.add_argument('--allow-global', action='store_true')
    ap.add_argument('--skip-eval', action='store_true', help='Skip LLM evaluation, discovery only')
    args = ap.parse_args()

    errors = 0
    try:
        discovered = discover(args.limit)
    except Exception as e:
        print(f"ERROR: Discovery failed: {e}", file=sys.stderr)
        return 1
    if not discovered:
        print("WARNING: Discovery returned 0 results", file=sys.stderr)
        errors = 1
    raw_rows: List[Dict] = []
    validated: List[Dict] = []
    reasons = Counter()
    seen = set()
    seen_company_title = set()
    today = datetime.now().strftime('%Y-%m-%d')

    for d in discovered:
        company, title, url, desc, source = d['company'], d['title'], d['url'], d['desc'], d['source']
        text = f"{title} {desc} {d.get('location', '')}"

        # Employer exclusion gate
        if EMPLOYER_EXCLUDE.search(company):
            reasons['employer_excluded'] += 1
            continue

        ok_title, title_reason = gate_title(title, text)
        if not ok_title:
            reason = title_reason
            link_ok = False
        else:
            location_ok = args.allow_global or (NON_US_PAT.search(text) is None)
            if not location_ok:
                reason = 'excluded_location'
                link_ok = False
            elif PLACEHOLDER_PAT.search(title):
                reason = 'placeholder_role'
                link_ok = False
            else:
                link_ok, reason = check_url(url)

        key = (company.lower(), title.lower(), url.lower())
        key2 = (company.lower(), title.lower())
        if not reason and (key in seen or key2 in seen_company_title):
            reason = 'duplicate_exact'

        industry = detect_industry(text)
        tech_signals = detect_tech_signals(text)
        is_agency = bool(AGENCY_DETECT.search(company))

        row = {
            'rank': '',
            'company': company,
            'website': '',
            'careers_url': url,
            'role_url': '',
            'industry': industry,
            'size': '',
            'stage': '',
            'recent_funding': '',
            'tech_signals': tech_signals,
            'open_positions': title,
            'last_checked': today,
            'notes': f"source={source}" + (" | is_agency=true" if is_agency else ""),
            'role_family': d.get('role_family', ''),
            'source': source,
            'location_detected': d.get('location', ''),
            'validation_status': 'pass' if not reason else 'fail',
            'exclusion_reason': reason or '',
        }
        raw_rows.append(row)

        if reason:
            reasons[reason] += 1
            continue

        seen.add(key)
        seen_company_title.add(key2)
        validated.append(row)

    # --- LLM evaluation export (Claude evaluates natively as part of the skill) ---
    scored = []
    if not args.skip_eval:
        try:
            from evaluate_jobs import export_pending
        except ImportError:
            import sys
            sys.path.insert(0, str(Path(__file__).parent))
            from evaluate_jobs import export_pending

        scored, validated = export_pending(validated, dry_run=args.dry_run)
    else:
        scored = validated  # skip_eval: write everything as before

    # final global ordering: llm_score descending
    def sort_key(r):
        llm = r.get('llm_score')
        try:
            return float(llm) if llm not in (None, '') else 0.0
        except (TypeError, ValueError):
            return 0.0

    write_csv(RAW_CSV, raw_rows, HEADER)
    if not args.dry_run:
        # Merge only SCORED new jobs into existing target CSV (dedup by company name)
        existing = _read_existing(TARGET_CSV)
        for s in scored:
            s['company'] = normalize_company(s.get('company', ''))
            match = find_existing(s.get('company', ''), existing)
            if match:
                merge_into_existing(match, s)
            else:
                existing.append(s)
        existing.sort(key=sort_key, reverse=True)
        for i, r in enumerate(existing, 1):
            r['rank'] = str(i)
        write_csv(TARGET_CSV, existing, HEADER)
        _sync_xlsx()

    report = DATA / f"job-search-run-report-{datetime.now().strftime('%Y-%m-%d')}.md"
    lines = [
        f"# Job Search Run Report ({datetime.now().strftime('%Y-%m-%d %H:%M')})",
        '',
        f"- discovered: {len(discovered)}",
        f"- validated_pass: {len(validated)}",
        f"- scored_ready: {len(scored)}",
        f"- rejected: {sum(reasons.values())}",
        f"- llm_eval: {'skipped' if args.skip_eval else 'enabled'}",
        '',
        '## Rejected by reason',
    ]
    for k, v in sorted(reasons.items(), key=lambda x: (-x[1], x[0])):
        lines.append(f"- {k}: {v}")

    lines += ['', '## Top 15 by score (new scored jobs)']
    for r in scored[:15]:
        llm_s = r.get('llm_score', '')
        lines.append(
            f"- #{r.get('rank')} {r.get('company')} — {r.get('open_positions')} "
            f"| score={llm_s} | {r.get('source')}"
        )

    report.write_text('\n'.join(lines), encoding='utf-8')

    print(json.dumps({
        'discovered': len(discovered),
        'validated_pass': len(validated),
        'rejected': sum(reasons.values()),
        'reasons': dict(reasons),
        'raw_csv': str(RAW_CSV),
        'target_csv': str(TARGET_CSV),
        'report': str(report),
        'dry_run': args.dry_run,
        'skip_eval': args.skip_eval,
    }))
    return errors


if __name__ == '__main__':
    raise SystemExit(main())
