# Example Onboarding Output

Fictional example: Alex Chen, data engineer with 6 years experience, targeting ML infrastructure and MLOps roles.

## Generated: criteria.md

```markdown
# Job Evaluation Criteria

## Must-Haves
- Role focuses on ML infrastructure, MLOps, or data platform engineering
- Works with Python and at least one of: Spark, Airflow, Kubeflow, MLflow
- Base compensation >= $170k (or equivalent total comp)
- Remote or hybrid in Seattle metro area
- Team size >= 5 engineers

## Strong Preferences
- Building or scaling ML pipelines and feature stores
- Kubernetes-based deployment and orchestration
- Opportunity to work directly with ML/AI researchers
- Series B+ startup or established tech company
- ...

## Nice-to-Haves
- Rust or Go for performance-critical components
- Open-source contribution encouraged
- Conference talk or publication support
- ...

## Dealbreakers
- Pure data analyst or BI-focused role
- Requires 5 days/week onsite
- Contract or corp-to-corp only
- Company has fewer than 20 employees
- ...

## Evaluation Rubric

| Signal | Strong Fit | Moderate | Weak Fit |
|--------|-----------|----------|----------|
| ML infra focus | Core to role | Partial overlap | Tangential |
| Tech stack match | 3+ tools match | 1-2 match | None match |
| Comp range | >= $180k | $160-180k | < $160k |
| ...| ... | ... | ... |
```

## Generated: background-context.md

```markdown
# Background Context — Alex Chen

## Professional Summary
6 years in data engineering, transitioning from batch ETL pipelines toward
real-time ML infrastructure. Currently senior data engineer at Contoso Analytics
building Spark-based feature pipelines serving 12 production ML models.

## Key Skills & Tools
- Python, SQL, Spark, Airflow, dbt
- AWS (EMR, SageMaker, S3, Glue), some GCP (BigQuery, Vertex AI)
- Docker, Kubernetes basics, Terraform
- Feature store design (Feast), experiment tracking (MLflow)

## Career Trajectory
- 2020-present: Senior Data Engineer, Contoso Analytics
- 2018-2020: Data Engineer, Northwind Data Systems
- Background: BS Computer Science, University of Washington

## What Sets Alex Apart
- Led migration from batch to streaming feature pipeline (reduced latency 40x)
- Built internal ML model registry adopted by 3 teams
- Active contributor to Apache Airflow (12 merged PRs)

## Current Job Search Context
Seeking ML infrastructure or MLOps roles where the primary focus is enabling
ML teams at scale rather than building dashboards or ad-hoc analysis.
```

## Generated: search-config.json

```json
{
  "job_titles": [
    "ML Infrastructure Engineer",
    "MLOps Engineer",
    "Senior Data Engineer - ML Platform",
    "Platform Engineer - Machine Learning",
    "ML Platform Engineer"
  ],
  "keywords": [
    "feature store",
    "ML pipeline",
    "MLOps",
    "model serving",
    "Kubeflow",
    "MLflow"
  ],
  "locations": ["Seattle, WA", "Remote"],
  "exclude_terms": [
    "data analyst",
    "business intelligence",
    "junior",
    "intern"
  ],
  "salary_min": 170000,
  "company_size_min": 20,
  "sources": [
    {
      "name": "LinkedIn",
      "url_template": "https://www.linkedin.com/jobs/search/?keywords={title}&location={location}"
    },
    {
      "name": "Greenhouse boards",
      "notes": "Check target company career pages directly"
    }
  ]
}
```

## Generated: config.yaml

```yaml
user:
  name: Alex Chen
  target_roles:
    - ML Infrastructure Engineer
    - MLOps Engineer
    - Senior Data Engineer - ML Platform
  location: Seattle, WA
  remote_ok: true
  min_compensation: 170000

preferences:
  update_frequency: weekly
  auto_search: true
  notify_strong_matches: true

files:
  criteria: criteria.md
  background: background-context.md
  search_config: search-config.json
```
