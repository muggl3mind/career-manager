> **Example:** This terminology map is for the accounting/finance domain. Replace with your industry's terms when you run onboarding.

# Terminology Rules

Two sections: (1) words and phrases that must never appear in tailored output, (2) preferred practitioner equivalents for JD marketing language.

---

## Section 1: Buzzword Blocklist

These words and phrases are hard-blocked in tailored resume and cover letter output. `quality_gate.py` scans for them and fails the run if any are present.

| Blocked phrase | Why |
|---|---|
| leveraging / leveraged | AI-sounding generic verb |
| spearheading | AI-sounding, overused |
| seamlessly / seamless | AI-sounding filler |
| bespoke | reads as buzzword |
| trusted advisor | generic, overused |
| single point of contact | overstates ownership |
| audit-grade (anything) | Claude-invented buzzword |
| passionate about | AI-sounding |
| thrilled to | AI-sounding |
| operating against | meaningless filler |
| executing against | meaningless filler |
| held up under (any) scrutiny | filler |

### Role Verb Accuracy

Verbs describing candidate work must match the actual function of the role.

- Auditors **audit**, **review**, **test**, **evaluate** — they do not manage clients, advise clients, or challenge clients
- domain operators **manage fund accounting for**, **run the books for**, **support** — they do not advise
- If the candidate's `role_verb_map` in user-profile.yaml has an entry for an employer, use that verb exactly
- If no entry exists, default to the most conservative accurate verb for the role type

---

## Section 2: JD-to-Practitioner Terminology Map

JD postings use marketing language. Resumes should use the terms practitioners actually use. When tailoring, always prefer the practitioner equivalent that matches the candidate's real experience.

### Core Rule

If the JD describes a function the candidate performed under a different name, use the candidate's actual role language. Example: JD says "onboarding" but candidate did "post-deployment support" → use "post-deployment support."

### Mapping Table

| Domain | JD Term | Practitioner Equivalents |
|--------|---------|------------------------|
| FX | multi-currency accounting | foreign currency translation, FX remeasurement, ASC 830 / IAS 21 |
| Consolidation | multi-entity | intercompany eliminations, multi-jurisdictional audits, consolidation across reporting frameworks (US GAAP / IFRS / local GAAP) |
| Client ops | customer onboarding | client implementation, post-deployment support, BAU transition (use whichever matches actual experience) |
| Client ops | trusted advisor | client relationship management, engagement management |
| Controls | internal controls | SOX compliance, COSO framework, control testing, ITGC |
| Audit | financial reporting | statutory reporting, regulatory filings, financial statement preparation under US GAAP/IFRS |
| Compliance | regulatory compliance | SEC reporting, PCAOB standards, local regulatory filings |
| domain operations | fund accounting | NAV calculation, investor allocations, capital activity processing |
| domain operations | portfolio reconciliation | prime broker reconciliation, custodian reconciliation, break resolution |
| domain operations | treasury management | cash management, liquidity forecasting, bank reconciliation |
| Tech | process automation | RPA, workflow automation, Python scripting for operational efficiency |
| Tech | data analytics | financial data modeling, management reporting, KPI dashboards |
| Tech | financial systems integration | ERP implementation, system migration, data mapping |
| Standards | accounting standards | ASC 606 (revenue), ASC 842 (leases), ASC 820 (fair value), IFRS 9, IFRS 15, IFRS 16 |
| Close | month-end close | close cycle, period-end close, GL reconciliation, trial balance review |
| Valuation | fair value measurement | ASC 820, mark-to-market, Level 1/2/3 inputs, independent price verification |

### Usage Notes

- If multiple practitioner terms exist, pick the one closest to the candidate's actual experience and seniority level.
- When the JD term has no practitioner equivalent (e.g., it's already precise), use it as-is.
- Never insert a JD buzzword into the resume if a more precise practitioner term exists and matches the candidate's experience.
- Prefer specific standard references (e.g., "ASC 830") only when the candidate demonstrably worked under that standard.
