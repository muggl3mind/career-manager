#!/usr/bin/env python3
"""
Weighted Scoring System for Target Companies
Scores companies 0-100 based on configurable keyword matching.

Weights:
  Domain Relevance (25%) - how well the company matches your industry background
  AI Centrality (20%) - how core is AI to their product/mission
  Comp Potential (20%) - likelihood of reaching target compensation
  Role Match (15%) - how well open roles match your target roles
  Growth Stage (10%) - funding/growth trajectory
  Culture Fit (10%) - builder culture, innovation mindset, remote-friendly

Usage:
  python score_companies.py                    # Score all companies, update CSV
  python score_companies.py --dry-run          # Preview scores without saving
  python score_companies.py --top 10           # Show top 10 only
"""

import csv
import sys
import re
from pathlib import Path
import json

sys.path.insert(0, str(Path(__file__).resolve().parent.parent.parent.parent / "scripts"))
from config_loader import get as config_get
sys.path.insert(0, str(Path(__file__).resolve().parent))
from search_config_loader import load_search_config

SKILL_DIR = Path(__file__).resolve().parent.parent.parent  # job-search/
CSV_PATH = SKILL_DIR / 'data' / 'target-companies.csv'
# applications.csv moved to sibling job-tracker skill
JOB_TRACKER_DIR = SKILL_DIR.parent / 'job-tracker'
TRACKER_PATH = JOB_TRACKER_DIR / 'data' / 'applications.csv'

# Load scoring config from search-config.json
_SEARCH_CONFIG = load_search_config(SKILL_DIR / 'data' / 'search-config.json')
_SCORING = _SEARCH_CONFIG.get('scoring', {}) if _SEARCH_CONFIG else {}

DOMAIN_KEYWORDS = _SCORING.get('domain_keywords', {})
AI_KEYWORDS = _SCORING.get('ai_keywords', {})
ROLE_KEYWORDS = _SCORING.get('role_keywords', {})
COMP_INDICATORS = _SCORING.get('comp_indicators', {})
GROWTH_INDICATORS = _SCORING.get('growth_indicators', {})
_CULTURE = _SCORING.get('culture_keywords', {})


def keyword_score(text, keywords, max_score=25):
    """Score text based on keyword matches. Returns 0-max_score."""
    if not text:
        return 0
    text_lower = text.lower()
    matches = []
    for kw, weight in keywords.items():
        if kw.lower() in text_lower:
            matches.append(weight)
    if not matches:
        return 0
    # Use top 3 matches, weighted average, scaled to max_score
    matches.sort(reverse=True)
    top = matches[:3]
    avg = sum(top) / len(top)  # 0-10 scale
    return round((avg / 10) * max_score, 1)


def score_company(row):
    """Score a single company. Returns dict with component scores and total."""
    # Combine all text fields for analysis
    all_text = ' '.join([
        row.get('company', ''), row.get('industry', ''),
        row.get('tech_signals', ''), row.get('fit_rationale', ''),
        row.get('open_positions', ''), row.get('notes', ''),
        row.get('recent_funding', ''), row.get('stage', ''),
        row.get('careers_url', ''),
    ])

    domain = keyword_score(all_text, DOMAIN_KEYWORDS, 25)
    ai = keyword_score(all_text, AI_KEYWORDS, 20)
    comp = keyword_score(all_text, COMP_INDICATORS, 20)
    role = keyword_score(row.get('open_positions', '') + ' ' + row.get('fit_rationale', ''), ROLE_KEYWORDS, 15)
    growth = keyword_score(all_text, GROWTH_INDICATORS, 10)

    # Culture fit heuristic
    culture_text = all_text.lower()
    culture = 0
    for group_keywords in _CULTURE.values():
        if any(w in culture_text for w in group_keywords):
            culture += 3
    culture = min(culture, 10)

    total = round(domain + ai + comp + role + growth + culture, 1)

    return {
        'domain': domain,
        'ai': ai,
        'comp': comp,
        'role': role,
        'growth': growth,
        'culture': culture,
        'total': total,
    }


def load_tracker_companies():
    """Load companies already applied to."""
    companies = set()
    if TRACKER_PATH.exists():
        with open(TRACKER_PATH) as f:
            for row in csv.DictReader(f):
                companies.add(row.get('company', '').lower().strip())
    return companies


def main():
    dry_run = '--dry-run' in sys.argv
    top_n = None
    if '--top' in sys.argv:
        idx = sys.argv.index('--top')
        top_n = int(sys.argv[idx + 1]) if idx + 1 < len(sys.argv) else 10

    # Load CSV
    with open(CSV_PATH) as f:
        reader = csv.DictReader(f)
        fieldnames = reader.fieldnames
        companies = list(reader)

    # Add numeric_score to fieldnames if not present
    if 'numeric_score' not in fieldnames:
        fieldnames = list(fieldnames) + ['numeric_score']

    tracker = load_tracker_companies()

    # Score each company
    results = []
    skipped_llm = 0
    for row in companies:
        llm_raw = row.get('llm_score', '')
        try:
            llm_val = float(llm_raw) if llm_raw not in (None, '') else None
        except (TypeError, ValueError):
            llm_val = None

        if llm_val is not None:
            # LLM already scored — don't re-score with keywords
            row['numeric_score'] = llm_val
            results.append((row, {'total': llm_val, '_source': 'llm'}))
            skipped_llm += 1
        else:
            # No LLM score — use keyword fallback
            scores = score_company(row)
            row['numeric_score'] = scores['total']
            scores['_source'] = 'keyword'
            results.append((row, scores))

    # Sort by total score (llm_score takes precedence via scores['total'] above)
    results.sort(key=lambda x: x[1]['total'], reverse=True)

    # Display
    if top_n:
        results = results[:top_n]

    print(f"\n  LLM-scored (skipped keyword scoring): {skipped_llm}")
    print(f"  Keyword-scored (fallback): {len(results) - skipped_llm}\n")
    print(f"{'#':<3} {'Score':<7} {'Src':<4} {'Company':<25} {'Domain':<8} {'AI':<6} {'Comp':<6} {'Role':<6} {'Growth':<7} {'Culture':<8} {'In Tracker'}")
    print("-" * 115)
    for i, (row, scores) in enumerate(results, 1):
        in_tracker = "✓" if row['company'].lower().strip() in tracker else ""
        src = scores.get('_source', 'kw')[:3]
        print(f"{i:<3} {scores['total']:<7} {src:<4} {row['company'][:24]:<25} {scores.get('domain', 0):<8} {scores.get('ai', 0):<6} {scores.get('comp', 0):<6} {scores.get('role', 0):<6} {scores.get('growth', 0):<7} {scores.get('culture', 0):<8} {in_tracker}")

    if not dry_run:
        # Write back with numeric scores
        sorted_rows = [r[0] for r in results]
        # Add back any not in results if top_n was used
        if top_n:
            all_results = []
            for row in companies:
                llm_raw = row.get('llm_score', '')
                try:
                    llm_val = float(llm_raw) if llm_raw not in (None, '') else None
                except (TypeError, ValueError):
                    llm_val = None
                if llm_val is not None:
                    row['numeric_score'] = llm_val
                else:
                    scores = score_company(row)
                    row['numeric_score'] = scores['total']
                all_results.append(row)
            sorted_rows = sorted(all_results, key=lambda x: float(x.get('numeric_score', 0)), reverse=True)

        with open(CSV_PATH, 'w', newline='') as f:
            writer = csv.DictWriter(f, fieldnames=fieldnames)
            writer.writeheader()
            writer.writerows(sorted_rows)
        print(f"\n✓ Updated {CSV_PATH} with numeric scores (sorted by score descending)")
    else:
        print("\n(Dry run — no changes saved)")


if __name__ == '__main__':
    main()
