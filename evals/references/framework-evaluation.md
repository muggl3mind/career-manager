# Eval Framework Evaluation

Completed 2026-03-12. Assessed whether to adopt established eval frameworks or extend the custom eval system.

## What We Had

| Script | Level | What It Does | Checks |
|--------|-------|-------------|--------|
| code_review.py | 1 - Static | AST + regex pattern matching on source files | 5 checks across 4 files |
| runtime_verify.py | 2 - Output | Post-run file/data validation | 6 check groups, ~10 individual |
| health_monitor.py | 3 - Ongoing | Freshness, coverage, distribution, consistency | 8 check groups, ~12 individual |

Also: cv-tailor `quality_gate.py` (DOCX validation), `analysis.schema.json` (JSON schema contract), `quality-gates.md` (reference doc)

Properties: Zero external dependencies, no test runner, runs against live data, human-readable reports + exit codes

## Frameworks Evaluated

### pytest + hypothesis — HIGH VALUE, LOW COST (adopted)

Gap: Pure functions like `score_company()`, `keyword_score()`, CSV merge logic had no isolated tests with controlled inputs. Pattern-matching catches known bugs but not regressions.

- pytest: single `pip install`, sub-second runs, catches regressions in scoring math
- hypothesis: property-based testing finds edge cases (empty inputs, boundary scores) — deferred until needed
- Complements existing evals (they check real data; pytest checks pure functions)

### pandera / Great Expectations / pydantic — MEDIUM VALUE (partially adopted)

Gap: No schema enforcement on CSVs (31 columns could silently change) or JSON interchange files.

| Framework | Fit | Why |
|-----------|-----|-----|
| pydantic | Good | Lightweight models for JSON interchange. Deferred until adding new interchange formats. |
| pandera | Marginal | Requires pandas. Pipeline uses csv.DictReader everywhere. |
| Great Expectations | No | Web UI, data docs, checkpoint infra — overkill for solo CLI. |

Decision: JSON Schema (matching existing `analysis.schema.json` pattern) for eval-results.json. Skip pandera/GE. Pydantic later if needed.

### promptfoo / Braintrust / LangSmith / LangFuse — LOW VALUE (rejected)

Gap: No way to detect LLM scoring drift, rationale quality regression, or consistency across runs.

Fundamental mismatch: All these frameworks assume you programmatically call an LLM API. In this pipeline, Claude Code IS the runtime — there's no Python function calling the Anthropic API to wrap with an eval framework. Adopting these means restructuring the entire architecture.

| Framework | Fit | Why Not |
|-----------|-----|---------|
| promptfoo | Closest | Requires extracting prompts to files, Node.js, API keys, billable per-test |
| Braintrust | No | Requires API integration in code |
| LangSmith/LangFuse | No | Requires agent instrumentation |
| RAGAS | No | RAG-specific, not applicable |

Decision: Custom drift detection (20 lines of Python) fills the actual gap.

### Prefect / Dagster / OpenTelemetry — LOW VALUE (rejected)

Gap: No run history, timing, retry logic, or data lineage.

Fundamental mismatch: These are production team tools. This is one person running a 3-phase pipeline from CLI on a laptop. The overhead (servers, DSLs, config) far exceeds the benefit.

Decision: Simple JSONL run log in run_pipeline.py (10 lines) gives 80% of the benefit.

## What We Built Instead

| Pattern | Value | What It Does |
|---------|-------|-------------|
| pytest tests | HIGH | 22 tests on `keyword_score()` and `score_company()` with controlled inputs |
| Schema contract | HIGH | JSON Schema for eval-results.json, validated before merge |
| Drift detection | HIGH | Score distribution stats appended to history JSONL, flags if avg shifts >10 points |
| Run log | MEDIUM | Timestamp + phase + duration + exit code to run-log.jsonl after each phase |

## Key Insight

The gaps were not about missing frameworks:

1. **Missing test isolation** — pure functions weren't tested with known inputs (solved with pytest)
2. **Missing temporal awareness** — no memory of previous runs (solved with drift detection + run log)
3. **Missing schema contracts** — implicit contracts between Claude output and Python processing (solved with JSON Schema)

All three filled with lightweight custom code. The LLM eval frameworks are architecturally mismatched because Claude Code is both runtime and evaluator.

## Future Considerations

| What | When |
|------|------|
| pydantic for JSON interchange | When adding new interchange formats |
| Snapshot/golden tests | After pytest stabilizes, to detect scoring output changes from refactoring |
| hypothesis property-based tests | When scoring logic gets more complex |
| promptfoo / LLM eval frameworks | Only if architecture changes to direct API calls |
| Prefect/Dagster/OTel | Never for this project |
