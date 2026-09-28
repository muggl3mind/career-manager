---
name: interview-prep
description: "Generate an interview prep document for a tracked company: gather dossier, tracker status, opportunities, and base CV into a context file, draft the prep doc, then run one independent review and at most one repair pass. Use when the user has an interview coming up or asks to prepare for one."
---

# Interview Prep

Workflow skill: work → independent review → revise once. Dispatches use the **Agent tool** like the repo's other skills. (This is the orchflows work/review pattern — when the orchflows plugin is installed, `orch-work` and `orch-review` may serve as the dispatch primitives; the plugin is not required.)

## Input

A company name as tracked in the pipeline (e.g. "Allvue Systems"). If no company is given, ask for one — that is the only fatal gap.

## Process

1. **Gather context (pure Python, no LLM):**
   ```
   uv run interview-prep/scripts/build_prep_context.py "<company>"
   ```
   Read the JSON summary it prints and the context file it wrote (`interview-prep/preps/<slug>-context.md`). Missing pieces (dossier, tracker row, opportunities, base CV) are NOT failures — the workflow degrades gracefully and the prep doc must surface every gap.

2. **Draft:** launch ONE Agent-tool subagent as the maker, **session-default model** (human-facing writing per the root SKILL.md Model Policy). Give it the context file, the base CV path from the JSON summary (it must read the CV file itself), and the acceptance criteria below. Output: `interview-prep/preps/<slug>.md` — same slug the context builder printed, without the `-context` suffix.

   Required sections:
   - **Company Brief** — from the dossier; only facts present in the context file
   - **Role Summary** — from tracker row + opportunities rows
   - **Likely Interview Themes** — inferred from role + company signals, labeled as inference
   - **Your Stories** — map experience from the base CV to the themes (STAR prompts)
   - **Questions to Ask Them** — grounded in dossier signals (funding, news, culture)
   - **Gaps & Logistics** — every MISSING context piece, and what to do about each (e.g. "no dossier — run /research <company> first")

3. **Review:** launch ONE independent Agent-tool subagent as reviewer, `model: sonnet` (structured checking, per Model Policy), with the prep doc, the context file, and the criteria above. Checks: no fabricated facts (every claim traceable to the context file or CV, or labeled as inference); every MISSING piece surfaced in Gaps & Logistics; all six sections present and substantive. The reviewer reports findings only — no edits.

4. **Repair:** at most ONE repair pass by the maker on the reviewer's findings, then done. Do not loop. Findings still unresolved after the repair pass are appended to the prep doc's Gaps & Logistics section and mentioned to the user.

## Stopping conditions

- Done when the prep doc exists with all six sections and the review (plus at most one repair) is complete.
- Missing context sources never block completion; a missing company argument does.

## Error Handling

- If `build_prep_context.py` itself errors (malformed CSV, permissions), stop and report the error — do not draft from a partial or absent context file.
- If the maker or reviewer fails to return, report what completed and where the artifacts live; do not silently retry in a loop.

## Constraints

- Never edit CSVs (tracker scripts own them).
- Never modify `interview-prep/scripts/build_prep_context.py` from this workflow.
- Prep docs and context files live only in `interview-prep/preps/`.
