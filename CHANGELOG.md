# Changelog

## 2026-09-30

### Security and repo hygiene

- Added an untrusted-content rule for agents that read web-derived text (`references/untrusted-content.md`), carried by the job-search, company-research, cv-tailor, and interview-prep skills. Suspected injection is flagged `injection_suspected` and ignored.
- Added `SECURITY.md` with the threat model, defenses, and residual risks.
- Narrowed the shared permission allowlist to the named pipeline scripts; blanket `uv run`, `python3`, and `uv pip install` rules are gone. `.claude/settings.local.json` is no longer tracked.
- `.gitignore` now covers `opportunities.csv`, run snapshots and reports, eval/monitor/prospecting shard files, `research-results.json`, and `.demo-archive/`.
- Added GitHub Actions CI: the test suite, a guard that the shipped `search-config.json` is the neutral stub, and a guard against tracked data files.
- Added `evals/tests/test_repo_hygiene.py` to pin the above.

### Docs

- README: new "Truthful by Construction" section (claims gate), `interview-prep` and dashboard entries, a Security section, and a CI badge.

### Demo optimization (#2)

- Added the `interview-prep` skill: context builder with graceful degradation, then a maker, an independent review, and one repair pass.
- Rewrote the dashboard as a self-contained interactive page (search, filters, sort, SVG charts) with no external requests.
- Routed bulk research agents to `sonnet` explicitly and added a model policy to the router skill.
- Wave 1 agents now launch automatically after phase 1, and the dashboard regenerates after tracker changes.
- `search-config.json` now ships as a neutral stub with a `setup_required` guard and a `.example` file.
- README leads with the Claude Code desktop app as the only prerequisite.

## 2026-06-15

### Phase 2 reliability fixes

- Added merge-time agent self-report validation and quarantine for unverifiable rows.
- Fixed eval merge behavior: newer evals win, null and zero scores stay distinct, and hard-pass status is applied both directions.
- Added a 30-day eval cache TTL and durable prospecting skip list from `seen-jobs.json`.
- Moved CSV writes to atomic `csv_io.write_csv_atomic`.
- Standardized scoring on the March 2026 ratio method across pipeline paths.
- Fixed M1, M6, M8, and M9 plumbing issues around flags, confidence, and lifecycle data.

### Phase 3 pipeline refactor

- Made Wave 2 expansion opt-in with `web_prospecting.py export-expansion --expand`.
- Added monitor cadence gating with applied companies always included and `fetch_empty` rows kept retryable.
- Sharded eval pending exports to 40 jobs per agent with `pending-eval-shard-N.json`.
- Parallelized careers URL validation with a bounded thread pool.
- Updated onboarding to default to 4 to 5 paths and regenerated its example output.
- Removed three orphaned digest templates and aligned orchestrator docs with embedded locations and eval shards.
