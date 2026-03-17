---
name: job-search
description: "Run job discovery and target-list maintenance workflows for career-manager. Use when finding new target companies, scoring opportunities, syncing target-companies data, running job-search preflight/audits, or maintaining job-search source-of-truth data files."
---

# Job Search

Data hub and scripts for the job search pipeline. This is NOT a workflow skill — it holds the shared data and utilities that other skills (cv-tailor, job-tracker, company-research) depend on.

## Data Files (source of truth)
- `{baseDir}/data/target-companies.csv` — Researched companies with scores (0-100)
- `{baseDir}/data/cv-index.json` — Maps role types → resume versions
- Note: `applications.csv` is owned by sibling `job-tracker` skill

## Scripts (modular layout)

The script folder is now decomposed by responsibility:

### `scripts/core/` (source of truth utilities)
| Script | What It Does |
|--------|--------------|
| `scripts/core/send_email.py` | Gmail API sender (OAuth2, addresses configured in `config.yaml`) |
| `scripts/core/score_companies.py` | Weighted 6-factor company scoring |
| `scripts/core/todoist_client.py` | Todoist API client wrapper |
| `scripts/core/cv_index_resolver.py` | Portable CV index path resolution |
Note: `tracker_commands.py` and `add_to_tracker.py` moved to `../job-tracker/scripts/`

### `scripts/ops/` (job-search operations)
| Script | What It Does |
|--------|--------------|
| `scripts/ops/run_pipeline.py` | **Orchestrator** — runs full pipeline in two phases |
| `scripts/ops/discovery_pipeline.py` | JobSpy discovery → filter → LLM evaluation → CSV write |
| `scripts/ops/evaluate_jobs.py` | Cache check + pending-eval export (Claude does the evaluation) |
| `scripts/ops/apply_eval_results.py` | Merges Claude's eval-results.json into target-companies.csv |
| `scripts/ops/web_prospecting.py` | Claude-driven company discovery — export context + merge results |
| `scripts/ops/monitor_watchlist.py` | Re-check known companies for new roles (run 2-3x/week) |
| `scripts/ops/pipeline_health.py` | Pipeline quality checks |
| `scripts/ops/pipeline_followup_top3.py` | Follow-up shortlist generation |

### Full Pipeline Run (when user says "run job search")

This is a 3-phase workflow. Phase 1 and 2 are Python scripts. Between them, YOU (Claude) do the research work.

**IMPORTANT:** Phase 1 will exit after exporting context files. This is expected — not an error. Continue to the agent work step below.

**Phase 1 — Python exports + discovery:**
```
uv run scripts/ops/run_pipeline.py phase1
uv run scripts/ops/run_pipeline.py phase1 --skip-jobspy   # faster, skip job board scrape
```
Runs: monitor export → JobSpy discovery → web prospecting export.
Produces context files for you to process next.

**Agent work (YOU do this) — read context files, do research, AND score:**
1. Read `data/monitor-context.json` → visit stale companies' careers pages → **score each against criteria.md** → write `data/monitor-results.json`
2. Read `data/pending-eval.json` (if exists) → evaluate each job against `references/criteria.md` → write `data/eval-results.json`
3. Read `data/prospecting-context.json` → search for new companies, check named targets → **score each against criteria.md** → write `data/prospecting-results.json`

**Scoring instructions (for steps 1 and 3):**
When visiting each company, also evaluate it against your `references/criteria.md` rubric:
1. Read `references/criteria.md` for your 10 scoring dimensions
2. For each dimension, assess: yes (fits), no (doesn't fit), or unknown (can't determine)
3. Score = (yes count / evaluated count) * 100, rounded to nearest integer
4. If you can't evaluate at least 5 dimensions, set `llm_flags: "needs_research"` and skip scoring
5. Include these fields in each result entry:
   - `llm_score`: integer 0-100
   - `llm_dimensions_evaluated`: how many of 10 you could assess
   - `llm_rationale`: 1-2 sentence fit summary
   - `llm_path_name`: which career path this company maps to
   - `llm_flags`: comma-separated flags (e.g. `comp_unknown,growth_unknown`)
   - `dimension_scores`: (recommended) object with per-dimension results, e.g. `{"domain_fit": true, "ai_centrality": true, "comp_path": null}`

**Role URL capture (for steps 1 and 3):**
If Tavily is configured (`tavily_enabled: true` in config.yaml), capture direct links to specific job postings:
1. After identifying roles on a company's careers page, call Tavily Map on the `careers_url`
2. Match each role title to a URL from the Tavily results (look for the role title or a slug version in the URL path)
3. If a match is found, include `role_url` in the result entry — this is the direct link to the job posting
4. If no match or Tavily unavailable, omit `role_url` — the `careers_url` is the fallback
5. Never fabricate a role_url — only use URLs that Tavily actually discovered

**Phase 2 — Merge all results:**
```
uv run scripts/ops/run_pipeline.py phase2
uv run scripts/ops/run_pipeline.py phase2 --dry-run
```
Runs whichever merges have result files: monitor merge → eval merge → prospecting merge.
Updates `target-companies.csv` with everything.

**Phase 3 — Generate action list:**
```
uv run scripts/ops/run_pipeline.py phase3
```
Overwrites `data/action-list.csv` from updated target-companies.csv. Always use this fixed filename (no date suffix).

---

### Individual Scripts (can also run standalone)

### Discovery + Evaluation workflow
No API key required — Claude Code is the evaluator.

**Step 1 — Discovery (Python):**
```
uv run scripts/ops/discovery_pipeline.py --dry-run --limit 5   # preview, no writes
uv run scripts/ops/discovery_pipeline.py --limit 10            # discover + export pending-eval.json
uv run scripts/ops/discovery_pipeline.py --skip-eval           # discovery only, skip eval export
```

**Step 2 — Evaluation (Claude reads pending-eval.json and scores each job):**

When `data/pending-eval.json` exists, Claude reads it and evaluates each job against `references/criteria.md`.
For each job, output a JSON object with this structure:
```json
{
  "careers_url": "<url>",
  "path": <1-8 or null>,
  "path_name": "<label>",
  "scores": {
    "background_asset": 0-10, "ai_central": 0-10, "can_influence": 0-10,
    "non_traditional_welcome": 0-10, "comp_200k_path": 0-10, "growth_path": 0-10,
    "funding_supports_comp": 0-10, "problems_exciting": 0-10,
    "culture_public_voice": 0-10, "global_leverage": 0-10
  },
  "total_score": <0-100>,
  "fit_summary": "<2-3 sentences>",
  "hard_pass": true/false,
  "hard_pass_reason": "<reason or null>",
  "red_flags": ["flag1"],
  "confidence": "high|medium|low"
}
```
Write all results as a JSON array to `data/eval-results.json`.

**Step 3 — Merge (Python):**
```
python3 scripts/ops/apply_eval_results.py       # merge eval-results.json → CSVs
python3 scripts/ops/apply_eval_results.py --dry-run
```

### LLM Evaluation Layer
- Evaluates each new job against 10 rubric dimensions (0–10 each, total 0–100)
- Maps jobs to one of 8 target paths (see `references/criteria.md`)
- Hard-pass jobs excluded from `target-companies.csv`, retained in `raw-discovery.csv`
- Caches results in `data/seen-jobs.json` — already-evaluated jobs are skipped on re-run

New columns added to `target-companies.csv`:

| Column | Description |
|--------|-------------|
| `llm_score` | LLM fit score 0–100 (sum of 10 rubric scores) |
| `llm_path` | Target path 1–8 |
| `llm_path_name` | Path label |
| `llm_rationale` | 2–3 sentence fit explanation |
| `llm_flags` | Pipe-separated red flags |
| `llm_hard_pass` | true = excluded |
| `llm_hard_pass_reason` | Reason if hard_pass |
| `llm_evaluated_at` | ISO timestamp |

---

## Web Prospecting Workflow (run weekly or 2x/week)

Claude-driven company discovery. Finds companies that fit the profile across all 8 paths — broader than JobSpy which only scrapes job boards.

**Two output lanes:**
- Company with a relevant open role → `target-companies.csv` (validation_status=pass, source=web_prospecting)
- Company with no open role → `target-companies.csv` as watch list entry (validation_status=watch_list) for cold outreach

**Step 1 — Export context (Python):**
```
python3 scripts/ops/web_prospecting.py export
```
Writes `data/prospecting-context.json` containing the list of already-known companies to skip.

**Step 2 — Prospect (Claude):**

Read `data/prospecting-context.json` for the skip list, then read `references/criteria.md` for the full profile.

Run targeted WebSearch queries across all 8 paths. Examples:
- `"AI [your industry] software startup Series B 2025 2026 hiring"`
- `"[your domain] technology AI automation startup"`
- `"enterprise [industry] AI transformation hiring"`
- `"AI product manager [industry] enterprise"`
- `"[industry] AI innovation lab hiring product"`
- `"enterprise [industry] software AI product manager solutions architect"`
- `"[your domain] technology AI 2025 funding"`
- `"AI company solutions engineer [industry] hiring"`

For each promising company found:
1. Check if it's in the skip list — if yes, skip it
2. WebFetch their careers page
3. Look for open roles matching target role patterns (PM, Solutions Architect/Engineer, AI Enablement, Innovation Lead, DevRel, Implementation, Transformation)
4. Assess fit against criteria.md profile

Write ALL results (with and without open roles) to `data/prospecting-results.json` as a JSON array:
```json
[
  {
    "company": "DataCo",
    "website": "dataco.com",
    "careers_url": "https://dataco.com/careers",
    "role_url": "https://dataco.com/careers/head-of-enablement",
    "industry": "AI Industry Software",
    "size": "50-100",
    "stage": "Series B",
    "recent_funding": "$28M Series B, Jan 2026",
    "tech_signals": "AI workflow automation, data pipeline, API integration",
    "open_positions": "Senior Product Manager",
    "prospect_status": "active_role",
    "fit_rationale": "2-3 sentences on why this fits the profile.",
    "path": 1,
    "path_name": "AI Industry Startup",
    "notes": "Cold outreach angle: their reconciliation product maps directly to [YOUR_EMPLOYER] fund accounting experience.",
    "llm_score": 91,
    "llm_dimensions_evaluated": 10,
    "llm_rationale": "Perfect domain fit. AI-central product. PM role matches targets. Strong funding.",
    "llm_path_name": "AI Industry Startup",
    "llm_flags": ""
  },
  {
    "company": "StartupXYZ",
    "website": "startupxyz.com",
    "careers_url": "https://startupxyz.com/careers",
    "role_url": "",
    "industry": "Workflow Automation Software",
    "size": "20-50",
    "stage": "Series A",
    "recent_funding": "",
    "tech_signals": "workflow automation, task management",
    "open_positions": "",
    "prospect_status": "watch_list",
    "fit_rationale": "Workflow automation for mid-market companies. No open roles now but strong domain fit.",
    "path": 1,
    "path_name": "AI Industry Startup",
    "notes": "No roles currently. Worth monitoring — could cold outreach to head of product.",
    "llm_score": 65,
    "llm_dimensions_evaluated": 7,
    "llm_rationale": "Good domain fit but early stage, no relevant role open. AI centrality unclear.",
    "llm_path_name": "AI Industry Startup",
    "llm_flags": "comp_unknown,ai_centrality_unknown,no_open_role"
  }
]
```

**Step 3 — Merge (Python):**
```
python3 scripts/ops/web_prospecting.py merge
python3 scripts/ops/web_prospecting.py merge --dry-run
```
Merges results into `target-companies.csv`, updates `data/seen-companies.json`, cleans up working files.

**Cache:** `data/seen-companies.json` — tracks `first_seen` and `last_checked` per company. Companies checked within the last 7 days are skipped for new discovery; stale companies (>7 days) are eligible for re-check. Named targets are always checked regardless of cache status.

---

## Monitor Watchlist Workflow (run 2-3x/week)

Re-checks ALL known target companies for new role openings. This is the most important workflow to run regularly — it catches new roles at companies you already know are a fit (your named targets).

**What it monitors:**
- All `named_targets` from every path (as defined in search-config.json)
- All companies in `target-companies.csv`
- All active companies from `applications.csv`
- All companies in `seen-companies.json`

**Step 1 — Export context (Python):**
```
python3 scripts/ops/monitor_watchlist.py export
python3 scripts/ops/monitor_watchlist.py export --stale-days 3   # tighter window
```
Identifies companies not checked in 7+ days and writes `data/monitor-context.json`.

**Step 2 — Check careers pages (Claude):**

Read `data/monitor-context.json`. For EACH company in the `checklist`:
1. Visit their careers page (use `careers_url` if provided, otherwise WebSearch `"[company] careers"`)
2. Search for roles matching the `role_patterns` and `check_instructions`
3. Report findings — even "no_change" to update `last_checked`

Write ALL results to `data/monitor-results.json` as a JSON array:
```json
[
  {
    "company": "Acme Corp",
    "website": "acme.com",
    "careers_url": "https://acme.com/careers",
    "role_url": "https://acme.com/careers/ai-strategy-manager-12345",
    "open_positions": "AI Strategy Manager; Innovation Lead",
    "status": "active_role",
    "path": 5,
    "path_name": "Professional Services",
    "notes": "Found 2 AI roles in Technology Consulting practice.",
    "llm_score": 82,
    "llm_dimensions_evaluated": 9,
    "llm_rationale": "Strong domain fit, AI practice growing. Comp data unavailable.",
    "llm_path_name": "Professional Services",
    "llm_flags": "comp_unknown"
  },
  {
    "company": "Beta Inc",
    "website": "betainc.com",
    "careers_url": "https://betainc.com/careers",
    "open_positions": "",
    "status": "no_change",
    "path": 5,
    "path_name": "Professional Services",
    "notes": "No relevant AI/innovation roles currently posted."
  }
]
```

**Step 3 — Merge (Python):**
```
python3 scripts/ops/monitor_watchlist.py merge
python3 scripts/ops/monitor_watchlist.py merge --dry-run
```
Updates existing rows in `target-companies.csv` (new roles, last_checked), promotes `watch_list` → `pass` when roles found, adds new companies, updates `seen-companies.json` with `last_checked` timestamps.

**Recommended cadence:**
- Monitor: 2-3x/week (Tuesday, Thursday, optionally Saturday)
- Web Prospecting: 1x/week (finds NEW companies)
- JobSpy Discovery: 1x/week (scrapes job boards)

---

### Scope Boundary
- This skill owns job-search discovery + target-company pipeline operations.
- Digest/notification automation is handled separately and not included in this repo.
- Portfolio ideation is handled separately and not included in this repo.

## References
- `{baseDir}/references/criteria.md` — Search criteria and scoring dimensions
- `{baseDir}/templates/follow-up-email.md` — 4 recruiter follow-up templates

## CVs (external — portable path)
- Base path resolved from `config.yaml` (`paths.cv_base`)
- Optional override via environment variable: `CV_BASE_PATH`
- Default: `cv-tailor/data/CV/`

## Email Credentials
- Configured in `config.yaml` (`credentials.gmail_token`)
- Gmail can be disabled via `integrations.gmail_enabled: false`

## Error Handling
- If digest validation fails (required section missing), block send and surface missing sections.
- If Todoist or CSV load fails, continue with partial data only when safe and label degraded mode.
- If email send fails, log attempt details and alert with actionable error context.
