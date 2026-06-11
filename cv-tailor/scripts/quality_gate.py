#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path
from docx import Document

REQUIRED_SECTIONS = [
    # Update these to match your resume's section headings
    'PROFESSIONAL EXPERIENCE',
    'EDUCATION',
]

BUZZWORD_BLOCKLIST = [
    'leveraging',
    'leveraged',
    'spearheading',
    'seamlessly',
    'seamless',
    'bespoke',
    'trusted advisor',
    'single point of contact',
    'audit-grade',
    'passionate about',
    'thrilled to',
    'operating against',
    'executing against',
    'held up under',
]

EM_DASH = '—'


def _check_buzzwords(text: str) -> list[str]:
    text_lower = text.lower()
    return [w for w in BUZZWORD_BLOCKLIST if w in text_lower]


def qc(resume_path: str, redline_path: str) -> dict:
    d = Document(resume_path)
    lines = [p.text.strip() for p in d.paragraphs if p.text.strip()]
    text = '\n'.join(lines)

    missing = [s for s in REQUIRED_SECTIONS if s not in text]
    ok = True
    reasons = []

    if len(lines) < 25:
        ok = False
        reasons.append(f'non-empty lines too low: {len(lines)}')
    if missing:
        ok = False
        reasons.append('missing sections: ' + ', '.join(missing))
    if not Path(redline_path).exists():
        ok = False
        reasons.append('missing redline file')

    found_buzzwords = _check_buzzwords(text)
    if found_buzzwords:
        ok = False
        reasons.append('blocked phrases found: ' + ', '.join(found_buzzwords))

    em_dash_found = EM_DASH in text
    if em_dash_found:
        ok = False
        reasons.append('em dash (—) found — use comma, period, or parentheses instead')

    all_bold_paras = []
    for p in d.paragraphs:
        non_empty = [r for r in p.runs if r.text.strip()]
        if len(non_empty) > 1 and all(r.bold for r in non_empty):
            all_bold_paras.append(p.text[:60])
    if len(all_bold_paras) > 2:
        ok = False
        reasons.append(f'bold bleed: {len(all_bold_paras)} paragraphs have all runs bold')
    elif all_bold_paras:
        reasons.append(f'bold bleed warning ({len(all_bold_paras)} paragraphs): ' + ' | '.join(all_bold_paras))

    return {
        'status': 'pass' if ok else 'fail',
        'non_empty_lines': len(lines),
        'missing_sections': missing,
        'buzzwords_found': found_buzzwords,
        'em_dash_found': em_dash_found,
        'bold_bleed_paragraphs': all_bold_paras,
        'reasons': reasons,
    }


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--resume', required=True)
    ap.add_argument('--redline', required=True)
    ap.add_argument('--out', required=True)
    args = ap.parse_args()

    result = qc(args.resume, args.redline)
    Path(args.out).write_text(json.dumps(result, indent=2))
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['status'] == 'pass' else 1)
