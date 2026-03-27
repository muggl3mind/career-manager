---
name: evals
description: "Evaluate job-search pipeline code and outputs for correctness. Use when running code reviews, verifying pipeline outputs after a run, or checking ongoing pipeline health. Handles static analysis, runtime verification, and health monitoring."
---

# Evals

Independent evaluation suite for the job-search pipeline. Lives outside the pipeline it evaluates.

## Evaluation Levels

| Level | Script | When to Run |
|-------|--------|-------------|
| 1. Code Review | `scripts/code_review.py` | After building or changing pipeline code |
| 2. Runtime Verify | `scripts/runtime_verify.py` | After a pipeline run completes |
| 3. Health Monitor | `scripts/health_monitor.py` | Recurring — every pipeline run or 2-3x/week |

## Process

1. Run the relevant eval script for your situation
2. Review the report output
3. Fix issues (or flag for user approval if touching shared data)
4. Re-run the eval to verify fixes

## Usage

```bash
# Level 1: Static code review of job-search pipeline
python3 scripts/code_review.py

# Level 2: Validate outputs after a pipeline run
python3 scripts/runtime_verify.py

# Level 3: Ongoing health monitoring
python3 scripts/health_monitor.py
python3 scripts/health_monitor.py --json
```

## Scope

- Evaluates: `career-manager/job-search/` (scripts, data, caches)
- Does NOT evaluate: itself, other career-manager skills, or non-pipeline code
- References: `workflow-standards/references/evaluation.md` for methodology

## Output Format

Each script prints a check-by-check report with pass/warn/fail status and returns non-zero exit code if critical checks fail.
