# Eval Agent Reliability — SKILL.md Restructure

> **Date:** 2026-03-20
> **Status:** Draft
> **Scope:** `job-search/SKILL.md` only — no Python changes

## Problem

The eval agent dies mid-run when processing ~114 jobs. Root cause: unnecessary WebFetch calls fill the context window. Contributing factors: no checkpointing (all-or-nothing writes), no explicit sub-agent dispatch (parallelization is left to chance), redundant/ambiguous instructions (eval described 3 times with 2 different scoring schemas), and irrelevant sections consuming context.

The SKILL.md is 364 lines mixing reference documentation with execution instructions. Claude has to reconcile conflicting descriptions and guess at behaviors that should be explicit.

## Solution

Restructure `job-search/SKILL.md` into two clear parts. Target ~180 lines (down from 364). All changes are SKILL.md-only — no Python code changes.

## Design

### Part 1: Execution Playbook

The top of the file. What Claude reads and follows when running the pipeline.

#### Phase 1 (unchanged)

```
uv run job-search/scripts/ops/run_pipeline.py phase1
```

Runs monitor export, JobSpy discovery, web prospecting export. Continue directly to agent work.

#### Agent Work — Explicit Sub-Agent Dispatch

Replace the current numbered list (lines 51-57) with an explicit instruction to use the Agent tool:

> Launch all three work streams as parallel sub-agents using the Agent tool. Each agent reads `references/criteria.md` independently. Wait for all three to complete before Phase 2.

**Monitor agent:**
- Read `data/monitor-context.json`
- WebFetch each company's careers page (use `careers_url` if provided, otherwise WebSearch `"[company] careers"`)
- Score against criteria.md using 0-10 per dimension schema
- Report progress every 5 companies
- Write `data/monitor-results.json`

**Eval agent:**
- Read `data/pending-eval.json`
- Score from inline `description`, `title`, `company`, and `location` fields — do NOT WebFetch job URLs
- Exception: WebFetch only if `is_agency: true` (to find real employer) or `description` is empty/missing
- Agency handling: visit job URL, find actual hiring company, set `actual_company` field. If not found, set `actual_company: null` and add `agency_unresolved` to red_flags
- Checkpoint: write partial results to `data/eval-results.json` every 30 jobs
- Resume: on restart, read existing `eval-results.json` and skip jobs whose `careers_url` is already present
- Write final `data/eval-results.json`

**Prospecting agent:**
- Read `data/prospecting-context.json` for skip list
- WebSearch targeted queries across all career paths (examples provided in skill)
- For each promising company: check skip list, WebFetch careers page, look for matching roles
- Score against criteria.md using 0-10 per dimension schema
- Report progress after each career path
- Write `data/prospecting-results.json`

#### Unified Scoring Schema (all three agents)

One schema everywhere, replacing the current two conflicting approaches:

```json
{
  "scores": {
    "background_asset": 0-10, "ai_central": 0-10, "can_influence": 0-10,
    "non_traditional_welcome": 0-10, "comp_200k_path": 0-10, "growth_path": 0-10,
    "funding_supports_comp": 0-10, "problems_exciting": 0-10,
    "culture_public_voice": 0-10, "global_leverage": 0-10
  },
  "total_score": 0-100,
  "fit_summary": "2-3 sentences",
  "hard_pass": true/false,
  "hard_pass_reason": "reason or null",
  "red_flags": ["flag1"],
  "confidence": "high|medium|low"
}
```

The yes/no/unknown percentage approach (current lines 59-71) is removed.

#### Phase 2 (unchanged)

Dry-run first, present summary, merge on confirmation.

#### Phase 3 (unchanged)

Generate action list, suggest top 3.

### Part 2: Reference

The bottom of the file. Lookup information, not execution instructions.

**Includes:**
- Data files & ownership (current lines 10-13)
- Script table (current lines 15-37)
- Output JSON schemas — compact, one per agent (monitor, eval, prospecting) with field names and types only, not full multi-line examples
- Column definitions for target-companies.csv (current lines 163-173)
- Cache behavior: seen-jobs.json, seen-companies.json
- Prospecting search query examples (current lines 195-203)
- Recommended cadence (monitor 2-3x/week, prospecting 1x/week, discovery 1x/week)

**Cut entirely:**
- Standalone Discovery+Eval workflow (lines 106-155) — redundant with pipeline
- LLM Evaluation Layer summary (lines 157-174) — third description of same thing
- Standalone Web Prospecting workflow (lines 177-268) — folded into pipeline
- Standalone Monitor Watchlist workflow (lines 272-338) — folded into pipeline
- CVs section (lines 351-354) — belongs to cv-tailor
- Email Credentials (lines 356-358) — belongs to other skills
- Error Handling for digest/Todoist/email (lines 360-364) — not pipeline-related
- Giant JSON examples (46+28 lines) — replaced with compact schemas

## What This Fixes

| Failure mode | Before | After |
|---|---|---|
| Eval agent context overflow | WebFetches all 114 URLs | Scores from inline descriptions |
| All progress lost on agent death | Writes eval-results.json only at end | Checkpoints every 30 jobs, resumes on restart |
| Inconsistent parallelization | Numbered list, Claude decides | Explicit Agent tool dispatch |
| Ambiguous scoring | Two schemas, three eval descriptions | One schema, one description per agent |
| Context bloat in SKILL.md | 364 lines with redundancy | ~180 lines, playbook + reference |

## Out of Scope

- Python script changes (evaluate_jobs.py, apply_eval_results.py, etc.)
- Changes to other SKILL.md files (SKILL.md router, company-research, etc.)
- Changes to criteria.md or search-config.json
- New features or workflows
