# Example Onboarding Output

Fictional example: Alex Chen, data engineer with 6 years experience, targeting ML infrastructure and MLOps roles. Onboarding derived 4 career paths (the default is 4-5; users add more later by re-running onboarding). The four files below match the schemas the pipeline actually reads: see `job-search/data/search-config.json.example` for the full search-config key reference and `config.yaml.example` for config keys.

## Generated: criteria.md

```markdown
## Unique Value Proposition

Alex pairs 6 years of production data engineering with hands-on ML platform work:
Spark feature pipelines serving 12 production models, a streaming migration that cut
feature latency 40x, and an internal model registry adopted by 3 teams. Few data
engineers have shipped ML infrastructure that ML teams actually depend on daily.

He also contributes upstream (12 merged Apache Airflow PRs), so he can represent a
company credibly in open source while building internal platforms.

## Target Roles

- **ML Infrastructure / ML Platform Engineer (senior):** building pipelines, feature
  stores, and serving infrastructure for ML teams.
- **MLOps Engineer (senior):** deployment, monitoring, and lifecycle tooling for models.
- **Senior Data Engineer, ML focus:** data platform roles where ML workloads are the
  primary customer, not BI dashboards.

## Target Company Types

### Path 1: ML Infrastructure & Platform Engineering
- **Description:** Companies building internal ML platforms or platform products for ML teams.
- **Example Companies:** Databricks, Weights & Biases
- **Role Types:** ML Infrastructure Engineer, ML Platform Engineer
- **Why You Fit:** 6 years of Spark/Airflow pipelines feeding production models.
- **Compensation Notes:** $170K-$220K base at senior level.

### Path 2: Data Platforms with ML Focus
- **Description:** Data infrastructure companies whose primary workloads are ML: feature stores, streaming pipelines, training data systems.
- **Example Companies:** Tecton, Confluent
- **Role Types:** Senior Data Engineer (ML Platform), Streaming Data Engineer
- **Why You Fit:** Led a batch-to-streaming feature pipeline migration (40x latency reduction).
- **Compensation Notes:** $170K-$210K base.

### Path 3: MLOps & Model Serving
- **Description:** Companies building model deployment, serving, or observability tooling, or running large-scale serving infrastructure in-house.
- **Example Companies:** Anyscale, Arize AI
- **Role Types:** MLOps Engineer, Model Serving Infrastructure Engineer
- **Why You Fit:** Built an internal model registry adopted by 3 teams; Kubernetes and Terraform experience.
- **Compensation Notes:** $170K-$215K base.

### Path 4: AI Developer Tools & Open Source
- **Description:** Companies whose product is developer tooling for ML/AI workflows, especially with an open-source core.
- **Example Companies:** Astronomer, dbt Labs
- **Role Types:** Senior Platform Engineer, Open Source Engineer (data/ML)
- **Why You Fit:** Active Apache Airflow contributor (12 merged PRs); credibility in OSS communities.
- **Compensation Notes:** $165K-$200K base; equity-heavy at earlier stages.

## Evaluation Framework

10 scoring dimensions, each assessed yes (fits), no (does not fit), or unknown (cannot
determine). Unknown dimensions are null, never 0, and are excluded from the score.
Total score = (yes count / evaluated count) * 100, rounded down. Canonical
implementation: `job-search/scripts/core/scoring.py`.

If you cannot find specific evidence, mark the dimension unknown rather than assuming
the best case. A company without disclosed comp is unknown (null), not a yes, and not a 0.

### Group 1: Core Fit (4 dimensions)

- **ml_infra_focus**: role centers on ML platform work. Yes = primary responsibilities are pipelines, feature stores, model serving, or ML platform. No = primarily BI, dashboarding, or ad-hoc analysis. Evidence for yes: responsibilities section of the job posting.
- **stack_overlap**: tooling matches Alex's stack. Yes = posting names 2+ of Spark, Airflow, Kubernetes, MLflow, Feast, Terraform. No = stack fully disjoint. Evidence for yes: requirements section of the job posting.
- **seniority_match**: senior-level IC scope. Yes = senior/staff IC role asking 5+ years experience. No = junior/mid role or management-only role. Evidence for yes: title and experience requirements in the posting.
- **location_fit**: workable location. Yes = US remote or hybrid within Seattle metro. No = 4-5 days onsite outside Seattle metro. Evidence for yes: location field of the posting or careers page.

### Group 2: Compensation & Career (3 dimensions)

- **comp_meets_floor**: pay clears the floor. Yes = posted band or Levels.fyi data showing $170K+ base at this level. No = posted band tops out below $170K. Evidence for yes: posted salary band, Levels.fyi, or pay-transparency filing. No data = unknown.
- **funding_runway**: company can sustain the role. Yes = Series B+ raised within 3 years, profitable, or public. No = pre-seed/seed, or layoffs in the last 12 months. Evidence for yes: funding announcement or financial press coverage.
- **growth_headroom**: room to grow as an IC. Yes = published staff+ IC track or a growing platform team (3+ open infra roles). No = single-engineer team with no senior IC path. Evidence for yes: careers page, engineering ladder posts, team-size statements.

### Group 3: Culture & Growth (3 dimensions)

- **engineering_culture**: engineering is visible and valued. Yes = active engineering blog or maintained open-source repos. No = no public engineering presence and reviews describe a feature factory. Evidence for yes: company blog, GitHub org, employee reviews.
- **ml_team_partnership**: ML practitioners are the internal customer. Yes = role explicitly partners with ML or research teams. No = no ML practitioners at the company. Evidence for yes: job posting, team page.
- **oss_participation**: open-source contribution supported. Yes = public statement supporting OSS contribution or employee conference talks. No = blanket IP policy forbidding outside contribution. Evidence for yes: published policy, employee GitHub activity, conference rosters.

## Scoring Guide

Thresholds align with `pipeline.action_list.*_min_score` in `config.yaml`:
- **85-100 (HIGH):** Pursue aggressively. Cold outreach or immediate apply.
- **70-84 (MED):** Strong fit with current evidence. Apply if role is open.
- **60-69 (LOW):** Moderate fit. Watch list or skip unless specific role matches.
- **<60:** Skip.

**Handling unknowns:** Unknown dimensions are null, never 0. They are excluded from the
ratio, so missing information never penalizes (or inflates) a company. If fewer than
5 of 10 dimensions are assessable, set `llm_flags: "needs_research"` and omit the
score. The keyword scorer is a fallback only, used for rows with no `llm_score`; it
never overrides one.

**Distributional check:** Expect roughly 20% at 85+, 30% at 70-84, 35% at 60-69, and
15% below 60. If the distribution skews high, tighten the yes conditions and evidence
requirements.
```

## Generated: background-context.md

```markdown
## Personal Information
Alex Chen. Seattle, WA. Open to remote (US) or hybrid in Seattle metro. Minimum base $170K.

## Technical Capabilities
- Python, SQL, Spark, Airflow, dbt
- AWS (EMR, SageMaker, S3, Glue), some GCP (BigQuery, Vertex AI)
- Docker, Kubernetes, Terraform
- Feature store design (Feast), experiment tracking (MLflow)

## Project Portfolio
- Streaming feature pipeline migration: batch to streaming, 40x latency reduction
- Internal ML model registry adopted by 3 teams
- Apache Airflow contributor: 12 merged PRs

## Professional Experience
- 2020-present: Senior Data Engineer, Contoso Analytics. Spark feature pipelines serving 12 production ML models.
- 2018-2020: Data Engineer, Northwind Data Systems. Batch ETL and warehouse modeling.

## Education & Certifications
- BS Computer Science, University of Washington

## Positioning Angles
- Data engineer who has shipped ML infrastructure ML teams depend on daily, not just ETL
- OSS credibility: upstream Airflow contributions back claims about platform expertise
- Migration stories (batch to streaming) map directly to platform-modernization roles

## Travel & Location Preferences
Remote-first preferred. Hybrid acceptable within Seattle metro. Occasional travel (quarterly onsites) fine. Not open to relocation.
```

## Generated: search-config.json

```json
{
  "setup_required": false,
  "search_locations": ["United States"],
  "query_packs": {
    "ml_infrastructure": {
      "label": "ML Infrastructure & Platform Engineering",
      "queries": [
        "ML infrastructure engineer",
        "MLOps platform engineer",
        "machine learning platform engineer"
      ],
      "locations": ["Remote", "United States"],
      "job_type": "fulltime"
    },
    "data_platform_ml": {
      "label": "Data Platforms with ML Focus",
      "queries": [
        "data platform engineer machine learning",
        "senior data engineer feature store",
        "streaming data engineer ML pipeline"
      ],
      "locations": ["Remote", "United States"],
      "job_type": "fulltime"
    },
    "mlops_serving": {
      "label": "MLOps & Model Serving",
      "queries": [
        "MLOps engineer senior",
        "ML deployment engineer",
        "model serving infrastructure engineer"
      ],
      "locations": ["Remote", "United States"],
      "job_type": "fulltime"
    },
    "ai_devtools": {
      "label": "AI Developer Tools & Open Source",
      "queries": [
        "platform engineer developer tools data",
        "open source engineer data infrastructure",
        "senior software engineer ML developer tools"
      ],
      "locations": ["Remote", "United States"],
      "job_type": "fulltime"
    }
  },
  "role_include_patterns": [
    "ml.*infra", "mlops", "ml.*platform", "machine.*learn.*engineer",
    "data.*engineer.*ml", "feature.*store", "model.*serv", "platform.*engineer"
  ],
  "role_exclude_patterns": [
    "data.*analyst", "business.*intelligence", "junior", "intern",
    "marketing", "sales.*engineer"
  ],
  "employer_exclude_patterns": [
    "staffing", "recruiting", "talent.*agency"
  ],
  "location_exclude_patterns": [
    "united kingdom", "\\buk\\b", "emea", "europe",
    "india", "canada", "australia", "singapore"
  ],
  "keywords": {
    "domain": ["feature store", "ml pipeline", "model serving", "experiment tracking"],
    "ai": ["mlops", "kubeflow", "mlflow", "model registry", "inference"],
    "tech": ["spark", "airflow", "kubernetes", "terraform", "docker"]
  },
  "path_check_instructions": {
    "1": "Search for ML infrastructure and platform engineering roles at companies building internal ML platforms or platform products for ML teams. Look for careers pages listing pipeline, feature store, or serving responsibilities and a stack overlapping Spark, Airflow, or Kubernetes. Disqualify companies where the role is actually BI or analytics. Roles must be available in the United States or Remote.",
    "2": "Search for data platform roles where ML workloads are the primary customer. Look for feature stores, streaming pipelines for ML, and training data systems on careers pages. Disqualify warehouse-only or dashboard-focused teams. Roles must be available in the United States or Remote.",
    "3": "Search for MLOps, model deployment, and model serving roles at tooling companies or teams running large-scale serving in-house. Look for deployment, monitoring, and lifecycle responsibilities. Disqualify pure research roles with no production component. Roles must be available in the United States or Remote.",
    "4": "Search for platform and open-source engineering roles at AI/ML developer tools companies. Look for an open-source core, public GitHub activity, and data or ML tooling products. Disqualify closed-source feature factories with no OSS participation. Roles must be available in the United States or Remote."
  },
  "role_patterns": [
    "ML Infrastructure Engineer",
    "MLOps Engineer",
    "Senior Data Engineer - ML Platform",
    "Platform Engineer - Machine Learning",
    "Model Serving Infrastructure Engineer"
  ],
  "scoring": {
    "domain_keywords": {"feature store": 8, "ml pipeline": 7, "model serving": 8, "experiment tracking": 6},
    "ai_keywords": {"mlops": 6, "kubeflow": 5, "mlflow": 5, "model registry": 6, "inference": 5},
    "role_keywords": {"infrastructure": 7, "platform": 7, "mlops": 8, "data engineer": 6},
    "comp_indicators": {"senior": 5, "staff": 7, "principal": 8, "$170k": 9, "$200k": 10},
    "growth_indicators": {"series b": 4, "series c": 5, "ipo": 3, "hypergrowth": 6}
  },
  "path_aliases": {
    "ml infra": "ML Infrastructure & Platform Engineering",
    "ml platform": "ML Infrastructure & Platform Engineering",
    "ml infrastructure": "ML Infrastructure & Platform Engineering",
    "data platform ml": "Data Platforms with ML Focus",
    "data platform": "Data Platforms with ML Focus",
    "feature store": "Data Platforms with ML Focus",
    "mlops": "MLOps & Model Serving",
    "ml devops": "MLOps & Model Serving",
    "model serving": "MLOps & Model Serving",
    "ai devtools": "AI Developer Tools & Open Source",
    "developer tools": "AI Developer Tools & Open Source",
    "open source ml": "AI Developer Tools & Open Source"
  },
  "display_groups": {
    "ML Platform": ["ML Infrastructure & Platform Engineering", "Data Platforms with ML Focus"],
    "MLOps": ["MLOps & Model Serving"],
    "Dev Tools": ["AI Developer Tools & Open Source"]
  }
}
```

## Generated: config.yaml

```yaml
paths:
  cv_base: /Users/alex/Documents/Resumes

integrations:
  todoist_enabled: false
  gmail_enabled: false
  jobspy_enabled: true
  tavily_enabled: false

email:
  from: your-email@gmail.com
  to: your-email@gmail.com
  bcc: ""

credentials:
  todoist_token: .credentials/todoist-token.json
  gmail_token: .credentials/gmail-token.pickle
  tavily_token: .credentials/tavily-token.json

pipeline:
  action_list:
    apply_min_score: 70
    watch_min_score: 85
    watch_max_rows: 20
  discovery:
    discover_min_score: 70
    per_agent_query_budget: 15
  lifecycle:
    archive_grace_runs: 2

query_templates:
  extra_patterns: []
```
