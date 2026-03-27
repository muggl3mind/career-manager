# Apply Workflow (End-to-End)

Use this sequence for a full job-search cycle:

1. **Research** (`company-research`)
   - Build dossier with Overview, Signals, Fit, Risks.
   - Decide PURSUE / RESEARCH MORE / PASS.

2. **Target List Update** (`career-manager`)
   - Add or refresh company in `target-companies.csv`.
   - Re-score and rank target list.

3. **CV Tailoring** (`cv-tailor`)
   - Tailor resume/cover letter to role requirements.
   - Save outputs under CV company folder.

4. **Track Application** (`job-tracker`)
   - Add application record.
   - Update status transitions (researching -> applied -> interviewing -> offer/rejected/declined).

5. **Follow-Up Management** (`job-tracker` + templates)
   - Run stale follow-up scan (7+ days).
   - Draft recruiter/hiring manager follow-ups.

6. **Digest Integration** (`career-manager`)
   - Include updates in digest sections.
   - Ensure validation gate passes before send.

## Common Compound Intents
- "Research X and prep my CV" -> steps 1 + 3
- "Score targets then show follow-ups" -> steps 2 + 5
- "Add this role and draft follow-up plan" -> steps 4 + 5
