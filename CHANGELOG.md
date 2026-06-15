# Changelog

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
