# Job Search Ownership Matrix

| Capability | Owner Skill | Notes |
|---|---|---|
| Target company storage/scoring | job-search | Owns `job-search/data/target-companies.csv` |
| Pipeline application tracking | job-tracker | Owns `job-tracker/data/applications.csv` |
| Single-company deep research | company-research | Can write findings back to target list |
| Data quality checks (dedupe/stale/links) | job-search | Quality gate for target companies |
| Follow-up queue | job-tracker | Derived from `applications.csv` |
