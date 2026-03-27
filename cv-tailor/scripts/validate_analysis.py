#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

REQUIRED = [
    'company','role','base_resume_path','summary_edits','bullet_edits',
    'keyword_targets','cover_letter_paragraphs','claims_guardrail'
]


def validate(obj: dict) -> list[str]:
    errs: list[str] = []
    for k in REQUIRED:
        if k not in obj:
            errs.append(f'missing required key: {k}')
    if errs:
        return errs

    if not str(obj.get('company','')).strip(): errs.append('company empty')
    if not str(obj.get('role','')).strip(): errs.append('role empty')

    p = Path(obj.get('base_resume_path',''))
    if not p.exists(): errs.append(f'base_resume_path not found: {p}')
    if p.suffix.lower() != '.docx': errs.append('base_resume_path must be .docx')

    for k in ['summary_edits','bullet_edits']:
        v = obj.get(k)
        if not isinstance(v,list):
            errs.append(f'{k} must be array'); continue
        for i,e in enumerate(v):
            if not isinstance(e,dict) or not e.get('old') or not e.get('new'):
                errs.append(f'{k}[{i}] invalid old/new')

    if not isinstance(obj.get('cover_letter_paragraphs'), list) or len(obj['cover_letter_paragraphs']) < 3:
        errs.append('cover_letter_paragraphs must have at least 3 paragraphs')
    if not isinstance(obj.get('claims_guardrail'), list) or len(obj['claims_guardrail']) < 1:
        errs.append('claims_guardrail must be non-empty')

    return errs


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        raise SystemExit('Usage: validate_analysis.py <analysis.json>')
    p = Path(sys.argv[1])
    obj = json.loads(p.read_text())
    errs = validate(obj)
    if errs:
        print('ANALYSIS_INVALID')
        for e in errs:
            print('-', e)
        raise SystemExit(1)
    print('ANALYSIS_VALID')
