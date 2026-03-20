---
name: career-manager
description: "Orchestrate the complete career-manager system across job-search, company-research, job-tracker, and cv-tailor. Use when coordinating multi-step job hunt workflows, routing requests to the right sub-skill, and enforcing shared data ownership boundaries."
---

# Career Manager Orchestrator

Use this parent skill as the orchestration layer for the career-manager domain.

> This is intentionally a **router skill** (thin coordinator), not a heavy execution skill. Execution lives in sub-skills below.

## Route by Intent
- **Target list scoring / hygiene / dedupe / stale checks / broken links** → `job-search`
- **Single company deep research dossier** → `company-research`
- **Application pipeline CRUD + follow-up reporting** → `job-tracker`
- **First-time setup / profile update / regenerate config** → `onboarding`

## Source of Truth
- `job-search/data/target-companies.csv`
- `job-tracker/data/applications.csv`

## Boundaries
- Keep non-career work out of this skill.
- Use `company-research` for one-company analysis, not bulk pipeline operations.
- Use `job-tracker` for application status operations, not market/company research.

## Compound Intent Examples
- "Research Anthropic and prep my CV" → run `company-research`, then handoff to `cv-tailor`
- "Score targets, then show follow-ups" → run `job-search` scoring, then `job-tracker followup`
- "Research X, add to tracker, draft follow-up template" → `company-research` -> `job-tracker add` -> template from `job-search`

## Error Handling
- If a sub-skill path or file is missing, stop and report the missing dependency.
- If requested action spans multiple skills, show the exact handoff steps before writing data.
- If data sources conflict, prefer canonical owners (`job-search` for target companies, `job-tracker` for applications) and log the discrepancy.

## Reference
- `references/apply-workflow.md` — end-to-end research → tailor → apply → track → follow-up flow
