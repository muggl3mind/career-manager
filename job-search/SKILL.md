---
name: job-search
description: "Run job discovery and target-list maintenance workflows for career-manager. Use when finding new target companies, scoring opportunities, syncing target-companies data, running job-search preflight/audits, or maintaining job-search source-of-truth data files."
---

# Job Search

Data hub and scripts for the job search pipeline. Three-phase workflow: Python exports, Claude agent research, Python merges.

## Data Files (source of truth)
- `{baseDir}/data/target-companies.csv` — Researched companies with scores (0-100) and company lifecycle
- `{baseDir}/data/opportunities.csv` — Actionable role-level opportunities generated from target companies
- `{baseDir}/data/cv-index.json` — Maps role types to resume versions
- Note: `applications.csv` is owned by sibling `job-tracker` skill

## Scripts

### `scripts/core/` (utilities)
| Script | Purpose |
|--------|---------|
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

**Wave 1:** Use the **Agent tool** to launch sub-agents in parallel: one Eval agent, one Monitor agent, and **one Prospecting agent per career path** (one per `prospecting-context-{path_key}.json` file in the data directory). Make all Agent tool calls in a single response so they run concurrently.

**Between waves:** After all Wave 1 prospecting agents complete and write their result files, run:
```
uv run job-search/scripts/ops/web_prospecting.py export-expansion --expand
```
Wave 2 is opt-in. Pass `--expand` only on intentional expansion cycles; expansion agents cost roughly 500K tokens per run.
This generates expansion context files from pass 1 results.

**Wave 2:** Launch one **Expansion Prospecting agent** per `prospecting-context-{path_key}-expansion.json` file, all in parallel. These agents follow a graph-based protocol to find companies that pass 1 missed.

**Location targeting (all agents):** Use the `search_locations` array embedded in your context JSON. Do not read `data/search-config.json` for this. Only report companies with roles available in those locations (including Remote within those countries). If a company's only roles are outside `search_locations`, set status to `watch_list` and note the location mismatch. Do not mark location-mismatched roles as `active_role`.

**Scoring (all agents):** Read `references/criteria.md`. Assess each of the 10 dimensions as yes (fits), no (does not fit), or unknown (cannot determine). Unknown dimensions are null, never 0, and are excluded from the score. Score = (yes count / evaluated count) * 100, rounded down (7 yes of 8 evaluated = 87). If fewer than 5 of 10 dimensions are evaluable, set `llm_flags: "needs_research"` and omit the score. The canonical implementation is `scripts/core/scoring.py`; the keyword scorer is a fallback only and never overrides an `llm_score`.

### Monitor Agent

1. Read `data/monitor-context.json`
2. Check each company's careers page (use `careers_url` if provided, otherwise WebSearch). **ATS-API first** for Ashby/Lever/Greenhouse boards (JSON API, never the HTML page). Before reporting `no_change` or downgrading to `watch_list`, confirm with one role-title web search — a partial or empty board fetch is not evidence of absence
3. Score using the yes/no/unknown ratio method from `references/criteria.md` (see Scoring above)
4. If Tavily configured (`tavily_enabled: true` in config.yaml), use Tavily Map on `careers_url` to capture direct `role_url` links
5. Report progress every 5 companies (e.g., "8/18 done, 2 new roles found")
6. Write `data/monitor-results.json`

**Output fields** (flat — consumed by `monitor_watchlist.py`):
`company`, `website`, `careers_url`, `role_url`, `open_positions`, `status` (REQUIRED: `active_role|no_change|watch_list`), `path`, `path_name`, `notes`, `llm_score` (0-100), `llm_dimensions_evaluated` (0-10), `llm_rationale`, `role_family`, `llm_flags` (comma-separated string; canonical separator is defined in `scripts/core/flags.py`, readers also accept legacy `|`)

### Eval Agent

1. Read your assigned shard: `data/pending-eval-shard-N.json` (1-based, up to 40 jobs each). Batches of 40 or fewer jobs still ship as the legacy single file `data/pending-eval.json`. Descriptions are pre-truncated to 3KB by evaluate_jobs.py.
2. Score from the inline `description`, `title`, `company`, and `location` fields — do **NOT** WebFetch job URLs
3. **Exception:** WebFetch only if `is_agency: true` (to find real employer) or `description` is empty/missing
4. **Agency handling:** Visit job URL, find actual hiring company, set `actual_company`. If not found, set `actual_company: null` and add `agency_unresolved` to `red_flags`
5. **Output file:** Write to `data/eval-results-shard-N.json` matching your input shard's N (e.g., `pending-eval-shard-2.json` → `eval-results-shard-2.json`). If you were handed the legacy single file `pending-eval.json`, write to `data/eval-results.json`. Never write to another shard's file — parallel eval agents each own their own file so there is no race.
6. **Checkpoint:** Every 30 jobs, overwrite your output file with the full array of results processed so far (not append — always a valid JSON array).
7. **Resume:** On restart, read your own output file and skip jobs whose `careers_url` is already present.
8. Report progress at each checkpoint (e.g., "30/40 evaluated, 8 hard-passed so far")

**Output fields** (nested — consumed by `apply_eval_results.py`):
`careers_url`, `actual_company`, `path`, `path_name`, `scores` (object: `background_asset`, `ai_central`, `can_influence`, `non_traditional_welcome`, `comp_200k_path`, `growth_path`, `funding_supports_comp`, `problems_exciting`, `culture_public_voice`, `global_leverage`; each `1` if it fits, `0` if it does not; omit dimensions you cannot assess, never score unknowns as 0), `total_score` (0-100: yes count / evaluated count * 100, rounded down; if fewer than 5 dimensions are assessable set `total_score: 0` and add `needs_research` to `red_flags`, which the merge stores as "not scored"), `fit_summary`, `hard_pass` (bool), `hard_pass_reason`, `red_flags` (array of strings)

### Prospecting Agents (per-path)

Phase 1 generates one `prospecting-context-{path_key}.json` file per career path. Launch one Agent per context file, all in parallel.

For each path context file:

1. Read the context file to get `path_label`, `path_description`, `known_companies_skip`, `known_companies`, and `instructions`
2. Read `references/criteria.md` for scoring rubric
3. **MANDATORY:** Execute EVERY query in the context file's `suggested_queries` list before concluding. For each query, run the search, review results, evaluate candidates. Then use remaining budget for follow-ups:
   a. **Competitor expansion** — for the most promising finds, search for competitors and alternatives
   b. **Funding sweep** — search for recently funded companies in the space
   c. **Careers check** — check each company's careers page, classify as `active_role` or `watch_list`. **ATS-API first:** for Ashby/Lever/Greenhouse boards fetch the JSON API (`api.ashbyhq.com/posting-api/job-board/{org}`, `api.lever.co/v0/postings/{org}?mode=json`, `boards-api.greenhouse.io/v1/boards/{org}/jobs`), never the HTML page — JS-rendered boards return partial or empty listings and produce false negatives. A **negative verdict** (`no_matching_roles`, `no_careers_page`, `unable_to_verify`) requires TWO independent negative sources: the board check AND one role-title web search (e.g. "[company] forward deployed OR implementation OR solutions job"). If `watch_list`, you MUST provide `watch_reason` (one of: no_careers_page, no_matching_roles, roles_wrong_location, company_too_early, domain_mismatch, unable_to_verify) and `watch_evidence` (specific evidence supporting the reason). Vague reasons like "ambiguous" are not accepted.
4. Budget: up to the query cap in the context file. You MUST use at least the number of suggested queries from your budget. NO minimum-companies requirement. Report companies scoring at or above `discover_min_score` as normal results. Companies scoring 60 to `discover_min_score - 1` are **near-misses**: return them as `watch_list` with `below_threshold` added to `llm_flags` — the scoring guide's 60-69 LOW band and the dashboard's Worth Exploring section exist for exactly these rows, and a silently discarded near-miss can never be re-checked. Path-relevant companies with fewer than 5 verifiable dimensions are returned as `watch_list` with `watch_reason: unable_to_verify` and `llm_flags: needs_research`, score omitted. Do not return companies scoring below 60. If nothing qualifies after all queries, return an empty results array.
5. Score using the 10-dimension rubric from criteria.md
6. Write results to `data/prospecting-results-{path_key}.json` using the wrapper format:

```json
{
  "_meta": {
    "path": "path label",
    "path_key": "path_key",
    "queries_executed": 12,
    "companies_found": 14,
    "active_roles": 9,
    "watch_list": 5,
    "top_3": ["Company A (92)", "Company B (85)", "Company C (78)"]
  },
  "results": [...]
}
```

**Output fields** (in each result): `company`, `website`, `careers_url`, `role_url`, `industry`, `size`, `stage`, `recent_funding`, `tech_signals`, `open_positions`, `prospect_status` (`active_role|watch_list`), `fit_rationale`, `path` (path_key from the context file, e.g. `ai_finance_accounting_tech`), `path_name` (path_label from the context file, e.g. `AI in Finance / Accounting Tech` — copy verbatim, do NOT paraphrase), `notes`, `llm_score` (0-100), `llm_dimensions_evaluated` (0-10), `llm_rationale`, `role_family` (**MUST equal `path_name` verbatim**; do not put role titles like "Solutions Architect" here — those go in `open_positions`), `llm_flags` (comma-separated; canonical separator is defined in `scripts/core/flags.py`), `queries_used` (array), `watch_reason` (required if watch_list: `no_careers_page|no_matching_roles|roles_wrong_location|company_too_early|domain_mismatch|unable_to_verify`), `watch_evidence` (required if watch_list: specific evidence string)

### Expansion Prospecting Agents (per-path, Wave 2)

After Wave 1 prospecting completes, Phase 1 generates `prospecting-context-{path_key}-expansion.json` files. Launch one Agent per expansion context file, all in parallel.

For each expansion context file:

1. Read the context file to get `path_label`, `seed_companies`, `known_companies_skip`, and `instructions`
2. Read `references/criteria.md` for scoring rubric
3. Follow the 3-step expansion protocol in the context file's `instructions`:
   a. **Competitor mining** — for each seed company, search competitors and alternatives
   b. **Investor portfolio mining** — for funded seed companies, search investor portfolios
   c. **Community/list mining** — search for curated startup lists, batches, awesome-lists
4. Budget: up to the query cap in the context file. NO minimum-companies requirement. Return only NEW (not in skip list) companies. Same reporting bands as pass 1: >= `discover_min_score` as normal results, 60 to `discover_min_score - 1` as `watch_list` with `below_threshold` flag, fewer than 5 verifiable dimensions as `watch_list` with `needs_research` (score omitted), below 60 not returned. If nothing qualifies, return an empty results array.
5. Score using the 10-dimension rubric from criteria.md
6. Write results to `data/prospecting-results-{path_key}-expansion.json` using the same wrapper format as pass 1
7. If setting `prospect_status: watch_list`, provide `watch_reason` and `watch_evidence` (same rules as pass 1). Careers checks follow the same ATS-API-first and two-source negative-verdict rules as pass 1

## Phase 2 — Preview and merge (automatic)

Run dry-run then merge immediately. Do not ask the user for confirmation.
```
uv run job-search/scripts/ops/run_pipeline.py phase2 --dry-run
uv run job-search/scripts/ops/run_pipeline.py phase2
```
Present dry-run summary as FYI after merging: "Merged: X new companies, Y updated scores."

## Phase 3 — Generate action list

Run immediately after Phase 2. Do not ask user.
```
uv run job-search/scripts/ops/run_pipeline.py phase3
```
Overwrites `data/action-list.csv`.

**Next step — Dashboard + action menu:**

After phase 3 completes:

1. Open the dashboard in the user's browser:
   ```
   open job-search/data/dashboard.html
   ```

2. Present the action menu:
   ```
   Pipeline complete! Dashboard opened in your browser.

   What would you like to do next?
     1. Research a specific company
     2. Tailor CV for a role
     3. Start an application
     4. Run another pipeline
     5. Done for now

   Pick a number:
   ```

3. Route based on selection:
   - **1** — Ask which company, then invoke company-research skill
   - **2** — Ask which role/company, then invoke cv-tailor skill
   - **3** — Ask which company/role, then invoke job-tracker skill
   - **4** — Ask which pipeline (monitor, prospecting, full), then re-run
   - **5** — End the workflow

After completing any action (1-4), return to the menu so the user can take multiple actions without restarting.

---

# Reference

## target-companies.csv columns (added by pipeline)

| Column | Description |
|--------|-------------|
| `llm_score` | Fit score 0-100: (yes dimensions / evaluated dimensions) * 100. Empty when fewer than 5 of 10 dimensions were evaluable (`needs_research`). A `0` is a real score (0 yes of 5+ evaluated), never written as an empty cell. Canonical formula: `scripts/core/scoring.py` |
| `llm_dimensions_evaluated` | Confidence: how many of the 10 dimensions were assessed yes or no for this score. A 90 on 10 dimensions is stronger evidence than a 90 on 5 |
| `role_family` | Path label |
| `llm_rationale` | 2-3 sentence fit explanation |
| `llm_flags` | Comma-separated flags (canonical: `scripts/core/flags.py`; legacy pipe separator still accepted by readers) |
| `llm_hard_pass` | true = excluded |
| `llm_hard_pass_reason` | Reason if hard_pass |
| `llm_evaluated_at` | ISO timestamp |

## Cache behavior
- `seen-jobs.json` — Already-evaluated jobs skipped on re-run. Cached verdicts expire after 30 days (`EVAL_CACHE_TTL_DAYS` in `scripts/ops/evaluate_jobs.py`): a job re-posted at the same URL after that window gets a fresh evaluation instead of keeping its old score forever. Hard-passed jobs stay excluded while their cached verdict is fresh (they are skipped entirely, never restored to the active list) and are re-evaluated only after the TTL expires.
- `seen-companies.json` — Tracks `first_seen` and `last_checked` per company. Companies checked within 7 days are skipped; stale companies (>7 days) re-checked. Named targets always checked regardless of cache. Hard-passed companies (moved to `raw-discovery.csv`) are always on the prospecting skip list, and the expansion-pass skip list contains every known company regardless of staleness.

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
