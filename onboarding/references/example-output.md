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
  "query_packs": {
    "ml_infrastructure": {
      "label": "ML Infrastructure & Platform Engineering",
      "queries": [
        "ML infrastructure engineer",
        "MLOps platform engineer",
        "senior data engineer ML platform",
        "machine learning platform engineer"
      ],
      "locations": ["Remote", "United States"],
      "job_type": "fulltime"
    },
    "data_platform_ml": {
      "label": "Data Platform with ML Focus",
      "queries": [
        "data platform engineer machine learning",
        "senior data engineer feature store",
        "streaming data engineer ML pipeline"
      ],
      "locations": ["Remote", "United States"],
      "job_type": "fulltime"
    },
    "mlops_devops": {
      "label": "MLOps & ML DevOps",
      "queries": [
        "MLOps engineer senior",
        "ML deployment engineer",
        "model serving infrastructure engineer"
      ],
      "locations": ["Remote", "United States"],
      "job_type": "fulltime"
    }
  },
  "role_include_patterns": [
    "ml.*infra", "mlops", "ml.*platform", "machine.*learn.*engineer",
    "data.*engineer.*ml", "feature.*store", "model.*serv"
  ],
  "role_exclude_patterns": [
    "data.*analyst", "business.*intelligence", "junior", "intern",
    "marketing", "sales.*engineer"
  ],
  "employer_exclude_patterns": [
    "staffing", "recruiting", "talent.*agency"
  ],
  "location_exclude_patterns": [
    "india", "philippines", "nigeria"
  ],
  "keywords": {
    "domain": ["feature store", "ML pipeline", "model serving", "experiment tracking"],
    "ai": ["MLOps", "Kubeflow", "MLflow", "model registry", "inference"],
    "tech": ["Spark", "Airflow", "Kubernetes", "Terraform", "Docker"]
  },
  "gold_companies": [
    "Databricks", "Anyscale", "Tecton", "Weights & Biases",
    "Modal", "Replicate", "Hugging Face", "Scale AI",
    "Netflix", "Stripe", "Airbnb", "Uber"
  ],
  "prospecting_paths": [
    {
      "path": 1,
      "name": "ML Infrastructure & Platform Engineering",
      "search_queries": [
        "companies hiring ML infrastructure engineers 2026",
        "ML platform engineering teams scaling"
      ],
      "named_targets": ["Databricks", "Anyscale", "Modal", "Replicate", "Netflix"],
      "new_targets_goal": 3
    },
    {
      "path": 2,
      "name": "Data Platform with ML Focus",
      "search_queries": [
        "data platform companies adding ML features",
        "feature store companies hiring engineers"
      ],
      "named_targets": ["Tecton", "Feast", "Confluent", "Fivetran", "dbt Labs"],
      "new_targets_goal": 3
    },
    {
      "path": 3,
      "name": "MLOps & ML DevOps",
      "search_queries": [
        "MLOps platform companies hiring",
        "ML deployment infrastructure companies"
      ],
      "named_targets": ["Weights & Biases", "Neptune.ai", "Comet ML", "Seldon", "BentoML"],
      "new_targets_goal": 3
    }
  ],
  "path_check_instructions": {
    "1": "Search for ML infrastructure and platform engineering roles. Look for companies building internal ML platforms or developer tools for ML teams.",
    "2": "Search for data platform roles with ML focus. Prioritize companies building feature stores, real-time data pipelines for ML, or data infrastructure with ML integrations.",
    "3": "Search for MLOps, model deployment, and ML DevOps roles. Focus on companies building ML deployment tooling or running large-scale model serving infrastructure."
  },
  "role_patterns": [
    "ML Infrastructure Engineer",
    "MLOps Engineer",
    "Senior Data Engineer - ML Platform",
    "Platform Engineer - Machine Learning"
  ],
  "scoring": {
    "domain_keywords": {"feature store": 8, "ML pipeline": 7, "model serving": 8},
    "ai_keywords": {"MLOps": 6, "Kubeflow": 5, "MLflow": 5},
    "role_keywords": {"infrastructure": 7, "platform": 7, "MLOps": 8},
    "comp_indicators": {"senior": 5, "staff": 7, "principal": 8},
    "growth_indicators": {"series b": 4, "series c": 5, "ipo": 3}
  },
  "path_aliases": {
    "ml infra": "ML Infrastructure & Platform Engineering",
    "ml platform": "ML Infrastructure & Platform Engineering",
    "data platform ml": "Data Platform with ML Focus",
    "mlops": "MLOps & ML DevOps",
    "ml devops": "MLOps & ML DevOps"
  },
  "company_path_overrides": {
    "Databricks": "ML Infrastructure & Platform Engineering",
    "Anyscale": "ML Infrastructure & Platform Engineering",
    "Tecton": "Data Platform with ML Focus",
    "Weights & Biases": "MLOps & ML DevOps",
    "Netflix": "ML Infrastructure & Platform Engineering"
  },
  "company_aliases": {
    "W&B": "Weights & Biases",
    "wandb": "Weights & Biases"
  }
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
