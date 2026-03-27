#!/usr/bin/env python3
"""
CV analysis context builder.

Reads the base CV and JD, then writes data/pending-analysis.json for Claude
to analyze. Claude produces the targeted edits and writes data/analysis.json.
run_pipeline.py --phase apply then reads analysis.json and executes the pipeline.

No heuristics here — Claude does the judgment.
"""
from __future__ import annotations

import json
from pathlib import Path
from docx import Document

SCRIPT_DIR = Path(__file__).resolve().parent
DATA_DIR = SCRIPT_DIR.parent / 'data'
PENDING_PATH = DATA_DIR / 'pending-analysis.json'
ANALYSIS_PATH = DATA_DIR / 'analysis.json'
TERM_MAP_PATH = SCRIPT_DIR.parent / 'references' / 'terminology-map.md'

CLAIMS_GUARDRAIL = [
    'Do not invent employers, titles, dates, or certifications.',
    'Do not remove company names/dates unless explicitly requested.',
    'Preserve factual claims and quantified results from base resume.',
]

ANALYSIS_INSTRUCTIONS = """You are a CV tailoring specialist. Your task:

1. Read `base_cv_paragraphs` — these are the exact strings in the base resume.
2. Read `jd_text` to understand what the role requires.
3. Identify 5–10 targeted edits to tailor the resume for this specific role:
   - Professional summary / positioning statement
   - Core strengths line
   - Key bullet points that can be reframed toward the JD requirements
4. For each edit, `old` MUST be an exact substring of one of the `base_cv_paragraphs` entries
   (copy-paste from the list — do not paraphrase).
5. `new` must preserve quantified results, dates, and company names.
6. Write 3 tailored cover letter paragraphs for this company + role.
7. Write all results to data/analysis.json using the output_schema format.

Rules:
- `old` must exactly match text in base_cv_paragraphs.
- Do not invent experience, certifications, or titles.
- Keep edits focused: summary + strengths + 3–6 bullet points max.
- Do not restructure or reorder sections.
- Before writing any `new` text, consult `terminology_map`. Replace JD marketing
  language with proper industry/practitioner terminology. If the JD term maps
  to a specific standard (e.g., ASC 830), use the standard reference only when the
  candidate's experience supports it. If the JD describes a function the candidate
  performed under a different name, use the candidate's actual role language
  (e.g., JD says "onboarding" but candidate did "post-deployment support" → use
  "post-deployment support").
- Never insert a JD buzzword into the resume if a more precise practitioner term
  exists in the terminology map and matches the candidate's actual experience.
"""

OUTPUT_SCHEMA = {
    "company": "string — copy from context unchanged",
    "role": "string — copy from context unchanged",
    "base_resume_path": "string — copy from context unchanged",
    "summary_edits": [{"old": "exact string from base_cv_paragraphs", "new": "replacement text"}],
    "bullet_edits": [{"old": "exact string from base_cv_paragraphs", "new": "replacement text"}],
    "keyword_targets": ["list of 5–15 keywords from the JD to incorporate"],
    "cover_letter_paragraphs": ["paragraph 1", "paragraph 2", "paragraph 3"],
    "claims_guardrail": "KEEP AS-IS — copy from context unchanged",
}


def build(company: str, role: str, base_resume_path: str, jd_text: str) -> Path:
    """Read base CV paragraphs, write pending-analysis.json for Claude."""
    d = Document(base_resume_path)
    paragraphs = [p.text.strip() for p in d.paragraphs if p.text.strip()]

    term_map = TERM_MAP_PATH.read_text(encoding='utf-8') if TERM_MAP_PATH.exists() else ''

    payload = {
        'company': company,
        'role': role,
        'base_resume_path': base_resume_path,
        'base_cv_paragraphs': paragraphs,
        'jd_text': jd_text[:5000],
        'instructions': ANALYSIS_INSTRUCTIONS,
        'terminology_map': term_map,
        'output_schema': OUTPUT_SCHEMA,
        'claims_guardrail': CLAIMS_GUARDRAIL,
        'output_path': str(ANALYSIS_PATH),
    }

    DATA_DIR.mkdir(parents=True, exist_ok=True)
    PENDING_PATH.write_text(json.dumps(payload, indent=2), encoding='utf-8')
    print(f'[build_analysis] wrote {PENDING_PATH}')
    print(f'[build_analysis] Claude must read pending-analysis.json and write {ANALYSIS_PATH}')
    return PENDING_PATH


if __name__ == '__main__':
    import argparse
    ap = argparse.ArgumentParser()
    ap.add_argument('--company', required=True)
    ap.add_argument('--role', required=True)
    ap.add_argument('--base-resume-path', required=True)
    ap.add_argument('--jd-path', required=True)
    args = ap.parse_args()

    jd = Path(args.jd_path).read_text(encoding='utf-8')
    out = build(args.company, args.role, args.base_resume_path, jd)
    print(out)
