#!/usr/bin/env python3
from __future__ import annotations

import json
from pathlib import Path

REQUIRED = [
    'company', 'role', 'base_resume_path', 'summary_edits', 'bullet_edits',
    'keyword_targets', 'cover_letter_paragraphs', 'claims_guardrail',
]

TASK_VERB_PREFIXES = (
    'managing', 'leading', 'running', 'executing', 'coordinating',
    'overseeing', 'handling', 'driving', 'supporting', 'delivering',
)

_KNOWN_INSTITUTIONS = [
    'morgan stanley', 'goldman sachs', 'jpmorgan', 'jp morgan', 'blackrock',
    'blackstone', 'kkr', 'carlyle', 'apollo', 'citadel', 'two sigma',
    'bridgewater', 'deloitte', 'ernst & young', 'pricewaterhousecoopers', 'pwc',
    'kpmg', 'eqt', 'ares', 'warburg pincus',
]


def _check_core_strengths(strengths: list[str]) -> list[str]:
    warnings = []
    for s in strengths:
        if any(s.lower().startswith(v) for v in TASK_VERB_PREFIXES):
            warnings.append(
                f'Core Strengths warning: "{s}" reads as a task phrase. '
                'Use a noun-phrase competency instead (e.g. "PE Fund Operations" not "Managing PE funds").'
            )
    return warnings


def _check_confidentiality(obj: dict) -> list[str]:
    conf = obj.get('confidentiality', {})
    if not isinstance(conf, dict) or not conf.get('redact_clients', True):
        return []
    approved = [n.lower() for n in conf.get('approved_names', [])]

    all_edits = (
        obj.get('summary_edits', []) +
        obj.get('bullet_edits', []) +
        obj.get('tailored_edits', []) +
        obj.get('shared_edits', [])
    )

    errors = []
    for edit in all_edits:
        new_text = (edit.get('new') or '').lower()
        for institution in _KNOWN_INSTITUTIONS:
            if institution in new_text and institution not in approved:
                errors.append(
                    f'Confidentiality: edit names unapproved client "{institution}". '
                    'Add to approved_names in user-profile.yaml to allow.'
                )
    return errors


def validate(obj: dict) -> tuple[list[str], list[str]]:
    """Return (errors, warnings). Errors stop the pipeline; warnings are advisory."""
    errs: list[str] = []
    warns: list[str] = []

    for k in REQUIRED:
        if k not in obj:
            errs.append(f'missing required key: {k}')
    if errs:
        return errs, warns

    if not str(obj.get('company', '')).strip():
        errs.append('company empty')
    if not str(obj.get('role', '')).strip():
        errs.append('role empty')

    p = Path(obj.get('base_resume_path', ''))
    if not p.exists():
        errs.append(f'base_resume_path not found: {p}')
    if p.suffix.lower() != '.docx':
        errs.append('base_resume_path must be .docx')

    for k in ['summary_edits', 'bullet_edits']:
        v = obj.get(k)
        if not isinstance(v, list):
            errs.append(f'{k} must be array')
            continue
        for i, e in enumerate(v):
            if not isinstance(e, dict) or not e.get('old') or not e.get('new'):
                errs.append(f'{k}[{i}] invalid old/new')

    clp = obj.get('cover_letter_paragraphs')
    if not isinstance(clp, list) or len(clp) < 3:
        errs.append('cover_letter_paragraphs must have at least 3 paragraphs')
    elif any(not str(p).strip() for p in clp):
        errs.append('cover_letter_paragraphs must not contain empty or whitespace-only paragraphs')
    if not isinstance(obj.get('claims_guardrail'), list) or len(obj['claims_guardrail']) < 1:
        errs.append('claims_guardrail must be non-empty')

    strengths = obj.get('core_strengths', [])
    if isinstance(strengths, list):
        warns.extend(_check_core_strengths(strengths))

    errs.extend(_check_confidentiality(obj))

    return errs, warns


if __name__ == '__main__':
    import sys
    if len(sys.argv) < 2:
        raise SystemExit('Usage: validate_analysis.py <analysis.json>')
    p = Path(sys.argv[1])
    obj = json.loads(p.read_text())
    errs, warns = validate(obj)
    if warns:
        print('WARNINGS:')
        for w in warns:
            print('-', w)
    if errs:
        print('ANALYSIS_INVALID')
        for e in errs:
            print('-', e)
        raise SystemExit(1)
    print('ANALYSIS_VALID')
