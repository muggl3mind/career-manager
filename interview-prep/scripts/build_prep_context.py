#!/usr/bin/env python3
"""Gather interview-prep context for one company. Pure Python — no LLM calls.

Sources (each optional; missing pieces become explicit MISSING markers):
  company-research/dossiers/<company>.md   research dossier
  job-tracker/data/applications.csv        tracker row(s) for the company
  job-search/data/opportunities.csv        open opportunities for the company
  cv-tailor/data/CV/                       newest base CV file (path reference only)

Writes interview-prep/preps/<slug>-context.md and prints a JSON summary to stdout.
"""
import argparse
import csv
import json
import re
import sys
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[2]


def slugify(name: str) -> str:
    return re.sub(r'-+', '-', re.sub(r'[^a-z0-9]+', '-', name.lower())).strip('-')


def _find_dossier(root: Path, company: str) -> Path | None:
    dossiers = root / 'company-research' / 'dossiers'
    if not dossiers.is_dir():
        return None
    want = company.lower()
    want_slug = slugify(company)
    for p in sorted(dossiers.glob('*.md')):
        if p.stem.lower() == want or slugify(p.stem) == want_slug:
            return p
    return None


def _read_csv_rows(path: Path, company: str) -> list[dict]:
    if not path.is_file():
        return []
    want = company.lower()
    with path.open(encoding='utf-8', newline='') as f:
        return [r for r in csv.DictReader(f)
                if (r.get('company') or '').strip().lower() == want]


def _find_base_cv(root: Path) -> Path | None:
    cv_dir = root / 'cv-tailor' / 'data' / 'CV'
    if not cv_dir.is_dir():
        return None
    files = [p for p in cv_dir.iterdir() if p.is_file() and not p.name.startswith('.')]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def _rows_block(rows: list[dict]) -> str:
    lines = []
    for r in rows:
        pairs = [f"{k}: {v}" for k, v in r.items() if (v or '').strip()]
        lines.append('- ' + '; '.join(pairs))
    return '\n'.join(lines)


def build_context(company: str, root: Path | None = None) -> dict:
    root = root or REPO_ROOT
    dossier = _find_dossier(root, company)
    tracker_rows = _read_csv_rows(root / 'job-tracker' / 'data' / 'applications.csv', company)
    opp_rows = _read_csv_rows(root / 'job-search' / 'data' / 'opportunities.csv', company)
    base_cv = _find_base_cv(root)

    parts = [f"# Interview Prep Context: {company}", ""]

    parts.append("## Company Dossier")
    parts.append(dossier.read_text(encoding='utf-8') if dossier
                 else "MISSING — no dossier found. Run the company-research skill first for a stronger prep.")
    parts.append("")

    parts.append("## Tracker Status")
    parts.append(_rows_block(tracker_rows) if tracker_rows
                 else "MISSING — no application row in the tracker for this company.")
    parts.append("")

    parts.append("## Open Opportunities / Job Description Signals")
    parts.append(_rows_block(opp_rows) if opp_rows
                 else "MISSING — no rows in opportunities.csv for this company.")
    parts.append("")

    parts.append("## Base CV")
    parts.append(f"Path: {base_cv}" if base_cv
                 else "MISSING — no file found in cv-tailor/data/CV/.")
    parts.append("")

    out_dir = root / 'interview-prep' / 'preps'
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"{slugify(company)}-context.md"
    out_path.write_text('\n'.join(parts), encoding='utf-8')

    return {
        'company': company,
        'found': {
            'dossier': dossier is not None,
            'tracker': bool(tracker_rows),
            'opportunities': bool(opp_rows),
            'base_cv': base_cv is not None,
        },
        'base_cv_path': str(base_cv) if base_cv else None,
        'output_path': str(out_path),
    }


def main() -> int:
    ap = argparse.ArgumentParser(description='Build interview-prep context for a company')
    ap.add_argument('company', help='Company name as tracked (e.g. "Allvue Systems")')
    ap.add_argument('--root', type=Path, default=REPO_ROOT, help='Repo root (tests only)')
    args = ap.parse_args()
    summary = build_context(args.company, args.root)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == '__main__':
    sys.exit(main())
