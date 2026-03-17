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

    return {
        'status': 'pass' if ok else 'fail',
        'non_empty_lines': len(lines),
        'missing_sections': missing,
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
