# CV Tailor Repeatable SOP

## Default Execution Contract

1. Collect inputs: company, role, JD URL or pasted JD text.
2. Fetch and normalize JD text (WebFetch if URL provided).
3. Save JD to a temp file (e.g., `/tmp/jd_{company}.txt`).
4. Run Phase 1 — Prep:
   ```
   python3 scripts/run_pipeline.py --phase prep --company "..." --role "..." --jd-path /tmp/jd.txt
   ```
   This selects the base CV deterministically and writes `data/pending-analysis.json`.
5. Read `data/pending-analysis.json`. Analyze the role against the base CV and produce:
   - Summary edit (professional positioning)
   - Core strengths line
   - 3–6 bullet point edits targeted to JD requirements
   - 3 cover letter paragraphs
   Write results to `data/analysis.json` using the output_schema in pending-analysis.json.
   **`old` values must be exact matches from `base_cv_paragraphs` — copy-paste, no paraphrasing.**
6. Run Phase 2 — Apply:
   ```
   python3 scripts/run_pipeline.py --phase apply --company "..." --role "..."
   ```
   Validates schema, patches resume, generates cover letter + redline + QC report + manifest.
7. Show user:
   - Manifest status (pass/fail)
   - File paths for all artifacts
   - Concise change summary (what changed and why)
8. Wait for explicit user approval before any finalization/sending.

## Quality Gates (must pass)

- No invented experience, titles, dates, or certifications.
- No dropped core sections.
- No unexplained formatting drift.
- Page/layout stability: do not expand page count unless user approves.
- `old` values must exactly match text in the base CV.
- No raw JD buzzwords where a practitioner equivalent exists in terminology-map.md.

## Safe Edit Rules

- Preserve existing template/layout — edit in-place only (no full document rebuild).
- Preserve run-level formatting (bold/italic/font/size).
- Use `scripts/docx_safe_patch.py` for phrase-level replacements.
- Keep dates and company names unless user explicitly asks otherwise.
- Keep all claims truthful and quantified.

## Failure Behavior

- If analysis.json validation fails: surface all errors, do not run apply phase.
- If style/layout drifts: stop and switch to micro-edit mode.
- If JD extraction is thin: ask for pasted JD text.
- If `.docx` dependencies fail under system python: run using workspace venv.
