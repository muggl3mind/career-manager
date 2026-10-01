#!/usr/bin/env python3
"""
Deterministic claims gate for cv-tailor output.

Diffs every numeric claim, credential, employer name, and date (year) in the
`new` text of ALL FOUR applied edit categories (summary_edits, bullet_edits,
tailored_edits, shared_edits) AND the cover letter paragraphs against the
base CV text plus the user profile. Any claim in the output that does not
exist in those sources fails the gate with a precise message, e.g.:

    "$500M" (number in bullet_edits[2].new) not found in base CV or profile

This is the enforcement layer behind the "no invention" rule. The prompt-text
guardrail in build_analysis.py asks the model not to invent; this gate proves
it did not.

Usage (standalone):
  python3 scripts/claims_gate.py --analysis data/analysis.json --base path/to/base.docx
"""
from __future__ import annotations

import json
import re
from pathlib import Path

EDIT_CATEGORIES = ('summary_edits', 'bullet_edits', 'tailored_edits', 'shared_edits')

# Numbers: $1.5B, 500M, 30%, 30 percent, 50 million, 2019, 10+, 1,200 ...
_NUMBER_RE = re.compile(
    r'\$?\s?\d[\d,]*(?:\.\d+)?\s?(?:%|percent\b|million\b|billion\b|thousand\b|[KMBkmb]\b)?\+?',
    re.IGNORECASE,
)

_YEAR_RE = re.compile(r'^(19|20)\d{2}$')

# Generic detection blocklist (labeled example, not a claim about any user):
# common professional credential acronyms the gate watches for. Matched
# case-sensitively on word boundaries ("PMP" is a claim; "pmp" inside a word
# is not).
_CREDENTIAL_ACRONYMS = [
    'CPA', 'CFA', 'CAIA', 'FRM', 'CMA', 'CIA', 'CISA', 'CISSP', 'PMP',
    'ACCA', 'CGMA', 'MBA', 'PhD', 'CFE', 'CFP', 'FMVA', 'RN',
]

# Credential full names are matched case-insensitively.
_CREDENTIAL_NAMES = [
    'certified public accountant',
    'chartered financial analyst',
    'chartered alternative investment analyst',
    'certified management accountant',
    'certified internal auditor',
    'certified fraud examiner',
    'financial risk manager',
    'project management professional',
    'registered nurse',
]

# Generic detection blocklist (labeled example, not a claim about any user):
# well-known public employers and institutions the gate watches for. Matched
# case-insensitively on word boundaries. If one of these appears in the output
# but not in the base CV, user profile, or the target company name, the gate
# fails.
_KNOWN_EMPLOYERS = [
    'morgan stanley', 'goldman sachs', 'jpmorgan', 'jp morgan', 'blackrock',
    'blackstone', 'kkr', 'carlyle', 'apollo', 'citadel', 'two sigma',
    'bridgewater', 'deloitte', 'ernst & young', 'pricewaterhousecoopers',
    'pwc', 'kpmg', 'eqt', 'ares', 'warburg pincus', 'state street',
    'northern trust', 'bny mellon', 'citco', 'ss&c', 'alter domus',
    'apex group', 'vistra', 'tmf group', 'ubs', 'credit suisse', 'barclays',
    'hsbc', 'wells fargo', 'fidelity', 'vanguard', 'mckinsey', 'accenture',
    'boston consulting', 'google', 'microsoft', 'amazon', 'nvidia',
    'openai', 'anthropic',
]


def _canon_number(token: str) -> str:
    """Normalize a numeric token so legitimate restatements compare equal.

    "$50M", "50 million", "$50 million", "50m" all canonicalize to "50m".
    "30%" and "30 percent" both canonicalize to "30%".
    """
    t = token.lower().replace(',', '').replace(' ', '').replace('\xa0', '')
    t = t.lstrip('$').rstrip('+')
    for word, suffix in (('percent', '%'), ('million', 'm'), ('billion', 'b'), ('thousand', 'k')):
        if t.endswith(word):
            t = t[: -len(word)] + suffix
    return t


def _extract_numbers(text: str) -> list[str]:
    return [m.group(0).strip() for m in _NUMBER_RE.finditer(text)]


def _flatten_text(value) -> str:
    """Flatten a nested dict/list (e.g. user profile) into searchable text."""
    if isinstance(value, dict):
        return '\n'.join(f'{k}\n{_flatten_text(v)}' for k, v in value.items())
    if isinstance(value, (list, tuple)):
        return '\n'.join(_flatten_text(v) for v in value)
    return '' if value is None else str(value)


def _word_present(needle: str, haystack: str, case_sensitive: bool = False) -> bool:
    flags = 0 if case_sensitive else re.IGNORECASE
    return re.search(r'(?<!\w)' + re.escape(needle) + r'(?!\w)', haystack, flags) is not None


def _output_segments(analysis: dict) -> list[tuple[str, str]]:
    """Every piece of generated text the gate must verify, with its location."""
    segments: list[tuple[str, str]] = []
    for cat in EDIT_CATEGORIES:
        for i, edit in enumerate(analysis.get(cat) or []):
            if isinstance(edit, dict):
                segments.append((f'{cat}[{i}].new', edit.get('new') or ''))
    for i, para in enumerate(analysis.get('cover_letter_paragraphs') or []):
        segments.append((f'cover_letter_paragraphs[{i}]', str(para)))
    return segments


def check_claims(analysis: dict, base_cv_text: str, user_profile: dict | None = None) -> dict:
    """Diff output claims against base CV + user profile.

    Returns {'status': 'pass'|'fail', 'violations': [...]}. Each violation has
    category (location), type (number|date|credential|employer), claim, and a
    precise human-readable message.
    """
    profile_text = _flatten_text(user_profile or {})
    # The target company and role are context, not claims about the candidate;
    # the cover letter legitimately names them.
    context = '\n'.join(str(analysis.get(k) or '') for k in ('company', 'role'))
    sources = '\n'.join([base_cv_text or '', profile_text, context])

    source_numbers = {_canon_number(t) for t in _extract_numbers(sources)}
    violations: list[dict] = []

    for location, text in _output_segments(analysis):
        if not text:
            continue

        for token in _extract_numbers(text):
            canon = _canon_number(token)
            if canon and canon not in source_numbers:
                claim_type = 'date' if _YEAR_RE.match(canon) else 'number'
                violations.append({
                    'category': location,
                    'type': claim_type,
                    'claim': token,
                    'message': f'"{token}" ({claim_type} in {location}) not found in base CV or profile',
                })

        for acronym in _CREDENTIAL_ACRONYMS:
            if _word_present(acronym, text, case_sensitive=True) and not _word_present(acronym, sources, case_sensitive=True):
                violations.append({
                    'category': location,
                    'type': 'credential',
                    'claim': acronym,
                    'message': f'"{acronym}" (credential in {location}) not found in base CV or profile',
                })

        for name in _CREDENTIAL_NAMES:
            if _word_present(name, text) and not _word_present(name, sources):
                violations.append({
                    'category': location,
                    'type': 'credential',
                    'claim': name,
                    'message': f'"{name}" (credential in {location}) not found in base CV or profile',
                })

        for employer in _KNOWN_EMPLOYERS:
            if _word_present(employer, text) and not _word_present(employer, sources):
                violations.append({
                    'category': location,
                    'type': 'employer',
                    'claim': employer,
                    'message': f'"{employer}" (employer in {location}) not found in base CV or profile',
                })

    return {
        'status': 'pass' if not violations else 'fail',
        'violations': violations,
        'checked_segments': len(_output_segments(analysis)),
    }


if __name__ == '__main__':
    import argparse
    from docx import Document

    ap = argparse.ArgumentParser(description='Deterministic claims gate for cv-tailor output')
    ap.add_argument('--analysis', required=True, help='Path to analysis.json')
    ap.add_argument('--base', required=True, help='Path to base resume .docx')
    ap.add_argument('--out', help='Optional path to write the result JSON')
    args = ap.parse_args()

    analysis_obj = json.loads(Path(args.analysis).read_text(encoding='utf-8'))
    doc = Document(args.base)
    base_text = '\n'.join(p.text for p in doc.paragraphs if p.text)

    try:
        from build_analysis import _load_user_profile
        profile = _load_user_profile()
    except Exception:
        profile = {}

    result = check_claims(analysis_obj, base_text, profile)
    if args.out:
        Path(args.out).write_text(json.dumps(result, indent=2), encoding='utf-8')
    print(json.dumps(result, indent=2))
    raise SystemExit(0 if result['status'] == 'pass' else 1)
