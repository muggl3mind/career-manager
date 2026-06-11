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

### Phase 1 -- Prep (Python)

Get the job description from the user. If they provide a URL, fetch it via WebFetch. If they paste text, use it directly. Write the JD text to a temp file yourself. The user should never create temp files.

```bash
# Write JD to temp file (you do this, not the user)
# Then run prep:
uv run cv-tailor/scripts/run_pipeline.py --phase prep --company "Acme" --role "AI PM" --jd-path /path/you/created.txt
```
Selects base CV, reads it, writes `data/pending-analysis.json`.

### Phase 2 -- Analysis (Claude)

Report progress: "Reading JD... Analyzing against your resume..."

Read `data/pending-analysis.json`. It contains:
- `base_cv_paragraphs` -- exact strings from the base resume
- `jd_text` -- job description
- `instructions` -- what to do
- `output_schema` -- required output format

Produce targeted edits where `old` is an exact match to a paragraph in `base_cv_paragraphs`.
Write results to `data/analysis.json`.

Report: "Planning X bullet edits, summary rewrite, Y-paragraph cover letter."

### Preview Before Apply

Before running the apply phase, present a summary to the user:

"I'll edit X bullets, rewrite your summary, and write a Y-paragraph cover letter. Here's what changes:
- [Brief summary of each bullet edit]
- [Summary change]
- [Cover letter approach]

Apply?"

Wait for confirmation before proceeding.

**Page count pre-check:** Estimate whether the edits will push the resume past 2 pages. If the number of added/expanded bullets is high, flag it: "These edits might push past 2 pages. Want me to trim before applying?" Suggest specific cuts if needed.

### Phase 3 -- Apply (Python)
```bash
uv run cv-tailor/scripts/run_pipeline.py --phase apply --company "Acme" --role "AI PM"
```
Validates schema, patches resume, generates cover letter + redline + QC + manifest.

**Next step:** After producing artifacts, suggest: "Want me to add this to your tracker?"

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

## After Completion

After producing artifacts:
1. Suggest adding to tracker: "Want me to add this to your tracker?"
2. If user confirms, hand off to job-tracker skill with company + role.

## Writing Quality Rules

- **Never use em dashes (—).** Use commas, periods, or parentheses instead.
- **Never sound like AI.** No "leveraging", "spearheading", "passionate about", "thrilled to". Write like a human.
- **Resume must stay within 2 pages.** If edits push it to page 3, cut or condense. Check page count before finalizing.
- **Cover letter must stay within 1 page.** 3-4 paragraphs max.

## Core Strengths Validation

Before writing `core_strengths` edits, apply these checks to each proposed strength:

1. Is it a noun-phrase competency (e.g., "PE Fund Accounting"), not a verb-phrase task (e.g., "Managing PE funds")?
2. Is it already obvious from the job titles in the experience section? If yes, drop it.
3. Can the candidate point to a specific project or metric in the CV that proves it? If not, it is a buzzword.
4. Is it specific enough that another applicant could not honestly claim the same thing? "Senior communication skills" does not differentiate.

If 2 or more checks fail, regenerate the strength. Aim for 4-5 strengths. Fewer than 4 looks thin; more than 5 dilutes.

## Summary Structure

A professional summary must have exactly 3 sentences. Never present a partial summary:

- **Sentence 1 (Identity):** Who the candidate is and the career through-line or pivot.
- **Sentence 2 (Proof):** Concrete credentials with numbers and scope.
- **Sentence 3 (Value):** What the candidate specifically brings to this role, using language from the JD.

Word count: 75-100. Below 60 is bland; above 110 is bloated. Sentence 3 must contain at least one phrase that pattern-matches the JD responsibilities section.

## Cover Letter Rules

- Must include a wedge paragraph: name the gap between the candidate's background and the JD's stated ideal, then bridge it explicitly. The cover letter does the work the CV cannot.
- Never frame the gap defensively ("the value I bring is not X but Y"). Lead with what the candidate brings.
- If `user_profile.projects.poc_disclaimer` is true, frame AI projects as prototypes: "built to demonstrate" or "proof of concept showing" — never "runs autonomously" or implies production-grade deployment.

## Error Handling

- If style/layout drifts, switch to micro-edit mode.
- If dependency error (`docx` missing), run via workspace venv python.
- If base CV unavailable, stop with remediation steps.
- If analysis.json validation fails, surface errors and stop before patching.
