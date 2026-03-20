---
name: job-search
description: "Run job discovery and target-list maintenance workflows for career-manager. Use when finding new target companies, scoring opportunities, syncing target-companies data, running job-search preflight/audits, or maintaining job-search source-of-truth data files."
---

# Job Search

Data hub and scripts for the job search pipeline. Three-phase workflow: Python exports, Claude agent research, Python merges.

## Data Files (source of truth)
- `{baseDir}/data/target-companies.csv` — Researched companies with scores (0-100)
- `{baseDir}/data/cv-index.json` — Maps role types to resume versions
- Note: `applications.csv` is owned by sibling `job-tracker` skill

## Scripts

### `scripts/core/` (utilities)
| Script | Purpose |
|--------|---------|
| `scripts/core/send_email.py` | Gmail API sender (OAuth2, config.yaml) |
| `scripts/core/todoist_client.py` | Todoist API client wrapper |
| `scripts/core/cv_index_resolver.py` | Portable CV index path resolution |

### `scripts/ops/` (pipeline operations)
| Script | Purpose |
|--------|---------|
| `scripts/ops/run_pipeline.py` | Orchestrator — runs full pipeline |
| `scripts/ops/discovery_pipeline.py` | JobSpy discovery, filter, eval export |
| `scripts/ops/evaluate_jobs.py` | Cache check + pending-eval export |
| `scripts/ops/apply_eval_results.py` | Merge eval-results.json into CSV |
| `scripts/ops/web_prospecting.py` | Company discovery — export context + merge |
| `scripts/ops/monitor_watchlist.py` | Re-check known companies for new roles |
| `scripts/ops/pipeline_health.py` | Pipeline quality checks |
| `scripts/ops/pipeline_followup_top3.py` | Follow-up shortlist generation |

---

# Execution Playbook

Run all phases continuously. Do not pause between phases or ask the user to run commands.

## Phase 1 — Python exports + discovery

```
uv run job-search/scripts/ops/run_pipeline.py phase1
uv run job-search/scripts/ops/run_pipeline.py phase1 --skip-jobspy   # faster, skip job board scrape
```

## Agent Work — parallel sub-agent dispatch

Use the **Agent tool** to launch **three sub-agents in parallel**. Each agent gets its own context window and writes its own result file. Do not run them sequentially.

**Location targeting (all agents):** Read `search_locations` from `data/search-config.json` to focus on companies hiring in those markets.

**Scoring (monitor + prospecting agents):** Read `references/criteria.md`. Score each of the 10 dimensions 0-10. Total = sum (0-100). If fewer than 5 dimensions evaluable, set `llm_flags: "needs_research"` and skip scoring.

### Monitor Agent

1. Read `data/monitor-context.json`
2. WebFetch each company's careers page (use `careers_url` if provided, otherwise WebSearch)
3. Score using 0-10 per dimension from `references/criteria.md`
4. If Tavily configured (`tavily_enabled: true` in config.yaml), use Tavily Map on `careers_url` to capture direct `role_url` links
5. Report progress every 5 companies (e.g., "8/18 done, 2 new roles found")
6. Write `data/monitor-results.json`

**Output fields** (flat — consumed by `monitor_watchlist.py`):
`company`, `website`, `careers_url`, `role_url`, `open_positions`, `status` (REQUIRED: `active_role|no_change|watch_list`), `path`, `path_name`, `notes`, `llm_score` (0-100), `llm_dimensions_evaluated` (0-10), `llm_rationale`, `role_family`, `llm_flags` (pipe-separated string)

### Eval Agent

1. Read `data/pending-eval.json` (descriptions pre-truncated to 3KB by evaluate_jobs.py; ~114 jobs is ~400-500KB total)
2. Score from the inline `description`, `title`, `company`, and `location` fields — do **NOT** WebFetch job URLs
3. **Exception:** WebFetch only if `is_agency: true` (to find real employer) or `description` is empty/missing
4. **Agency handling:** Visit job URL, find actual hiring company, set `actual_company`. If not found, set `actual_company: null` and add `agency_unresolved` to `red_flags`
5. **Checkpoint:** Every 30 jobs, overwrite `data/eval-results.json` with the full array of all results processed so far (not append — always a valid JSON array)
6. **Resume:** On restart, read existing `eval-results.json` and skip jobs whose `careers_url` is already present
7. Report progress at each checkpoint (e.g., "30/114 evaluated, 8 hard-passed so far")
8. Write `data/eval-results.json`

**Output fields** (nested — consumed by `apply_eval_results.py`):
`careers_url`, `actual_company`, `path`, `path_name`, `scores` (object: `background_asset`, `ai_central`, `can_influence`, `non_traditional_welcome`, `comp_200k_path`, `growth_path`, `funding_supports_comp`, `problems_exciting`, `culture_public_voice`, `global_leverage` — each 0-10), `total_score` (0-100), `fit_summary`, `hard_pass` (bool), `hard_pass_reason`, `red_flags` (array of strings)

### Prospecting Agent

1. Read `data/prospecting-context.json` for skip list
2. Read `references/criteria.md` for profile
3. WebSearch queries across career paths. Examples:
   - `"AI [industry] software startup Series B 2025 2026 hiring"`
   - `"[domain] technology AI automation startup"`
   - `"enterprise [industry] AI transformation hiring"`
   - `"AI product manager [industry] enterprise"`
   - `"[industry] AI innovation lab hiring product"`
   - `"enterprise [industry] software AI product manager solutions architect"`
   - `"[domain] technology AI 2025 funding"`
   - `"AI company solutions engineer [industry] hiring"`
4. For each company: check skip list, WebFetch careers page, match role patterns (PM, Solutions Architect/Engineer, AI Enablement, Innovation Lead, DevRel, Implementation, Transformation)
5. If Tavily configured, use Tavily Map on `careers_url` to capture `role_url`
6. Score using 0-10 per dimension
7. Report progress after each career path (e.g., "Path 3/8 done, 7 companies found")
8. Write `data/prospecting-results.json`

**Output fields** (flat — consumed by `web_prospecting.py`):
`company`, `website`, `careers_url`, `role_url`, `industry`, `size`, `stage`, `recent_funding`, `tech_signals`, `open_positions`, `prospect_status` (`active_role|watch_list`), `fit_rationale`, `path`, `path_name`, `notes`, `llm_score` (0-100), `llm_dimensions_evaluated` (0-10), `llm_rationale`, `role_family`, `llm_flags` (pipe-separated string)

## Phase 2 — Preview and merge

```
uv run job-search/scripts/ops/run_pipeline.py phase2 --dry-run
```
Present summary to user: "About to merge: X new companies, Y updated scores. Proceed?"

On confirmation:
```
uv run job-search/scripts/ops/run_pipeline.py phase2
```

## Phase 3 — Generate action list

Run immediately after Phase 2. Do not ask user.
```
uv run job-search/scripts/ops/run_pipeline.py phase3
```
Overwrites `data/action-list.csv`. After completion, read it, identify top 3 companies, and suggest: "Top 3 are [names]. Want me to research them?"

---

# Reference

## target-companies.csv columns (added by pipeline)

| Column | Description |
|--------|-------------|
| `llm_score` | Fit score 0-100 (sum of 10 dimension scores) |
| `role_family` | Path label |
| `llm_rationale` | 2-3 sentence fit explanation |
| `llm_flags` | Pipe-separated flags |
| `llm_hard_pass` | true = excluded |
| `llm_hard_pass_reason` | Reason if hard_pass |
| `llm_evaluated_at` | ISO timestamp |

## Cache behavior
- `seen-jobs.json` — Already-evaluated jobs skipped on re-run
- `seen-companies.json` — Tracks `first_seen` and `last_checked` per company. Companies checked within 7 days are skipped; stale companies (>7 days) re-checked. Named targets always checked regardless of cache

## Recommended cadence
- Monitor: 2-3x/week (Tuesday, Thursday, optionally Saturday)
- Web Prospecting: 1x/week (finds new companies)
- JobSpy Discovery: 1x/week (scrapes job boards)

## Scope boundary
- This skill owns job-search discovery + target-company pipeline operations
- Digest/notification automation is handled separately and not included in this repo
- Portfolio ideation is handled separately and not included in this repo

## References
- `{baseDir}/references/criteria.md` — Search criteria and scoring dimensions
