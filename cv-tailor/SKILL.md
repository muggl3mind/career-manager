---
name: cv-tailor
description: "Customize resumes and cover letters for specific job applications with deterministic CV selection and formatting-safe edits. Use when a user asks to tailor a CV for a role/company/JD URL, generate role-matched resume+cover letter, compare against prior versions, or produce a Word redline/change summary."
---

# CV Tailor

Generate tailored application materials in a repeatable, review-first workflow.

## Required Inputs

- Company
- Role title
- Job description URL or pasted JD text

If JD text is thin, fetch it via URL or request pasted text before continuing.

## Execution Standard

Follow `references/repeatable-sop.md`.

Key defaults:
1. Two-phase pipeline: Python prep → Claude analysis → Python apply.
2. Select base CV via `scripts/select_base_cv.py` (closest prior or Master CV fallback).
3. Validate analysis schema before generation (hard fail on invalid input).
4. Prefer formatting-safe in-place edits; do not full-rebuild resume by default.
5. Preserve dates/company names and core structure unless user asks otherwise.
6. Output artifacts + explicit change summary every run.

## Workflow

### Phase 1 — Prep (Python)
```
python3 scripts/run_pipeline.py --phase prep --company "Acme" --role "AI PM" --jd-path /tmp/jd.txt
```
Selects base CV, reads it, writes `data/pending-analysis.json`.

### Phase 2 — Analysis (Claude)
Read `data/pending-analysis.json`. It contains:
- `base_cv_paragraphs` — exact strings from the base resume
- `jd_text` — job description
- `instructions` — what to do
- `output_schema` — required output format

Produce targeted edits where `old` is an exact match to a paragraph in `base_cv_paragraphs`.
Write results to `data/analysis.json`.

### Phase 3 — Apply (Python)
```
python3 scripts/run_pipeline.py --phase apply --company "Acme" --role "AI PM"
```
Validates schema, patches resume, generates cover letter + redline + QC + manifest.

## Scripts

| Script | Role |
|--------|------|
| `scripts/run_pipeline.py` | Pipeline orchestrator — `--phase prep` and `--phase apply` |
| `scripts/build_analysis.py` | Reads base CV + JD, writes pending-analysis.json for Claude |
| `scripts/select_base_cv.py` | Deterministic base CV selection from registry |
| `scripts/validate_analysis.py` | Schema + contract validation gate |
| `scripts/docx_safe_patch.py` | Phrase-level docx edits preserving run-level formatting |
| `scripts/generate_redline.py` | Change-log / redline artifact generation |
| `scripts/quality_gate.py` | Final quality checks before deliverables |
| `scripts/index_store.py` | CV registry builder — maps all CV files |
| `scripts/reindex_cv_assets.py` | Manual registry rebuild utility |

## Output Artifacts (always)

- Tailored resume `.docx`
- Tailored cover letter `.docx`
- Word redline/change-log `.docx`
- Chat summary: what changed and why

## Integration

- After tailoring materials for a role, update the application tracker via the sibling `job-tracker` skill (e.g., add application or update status to "applied").

## Writing Quality Rules

- **Never use em dashes (—).** Use commas, periods, or parentheses instead.
- **Never sound like AI.** No "leveraging", "spearheading", "passionate about", "thrilled to". Write like a human.
- **Resume must stay within 2 pages.** If edits push it to page 3, cut or condense. Check page count before finalizing.
- **Cover letter must stay within 1 page.** 3-4 paragraphs max.
- **Apply tailoring lessons.** Read `references/tailoring-lessons.md` before writing any edits. These are patterns learned from user revisions.

## Error Handling

- If style/layout drifts, switch to micro-edit mode.
- If dependency error (`docx` missing), run via workspace venv python.
- If base CV unavailable, stop with remediation steps.
- If analysis.json validation fails, surface errors and stop before patching.
