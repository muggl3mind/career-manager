Subject: ☀️ Morning Digest - {{DATE}}

## 📋 Yesterday's Progress
{{#YESTERDAY_ITEMS}}
- {{ITEM}}
{{/YESTERDAY_ITEMS}}
{{^YESTERDAY_ITEMS}}
No logged progress from yesterday.
{{/YESTERDAY_ITEMS}}

## ✅ Today's Task Plan
{{#TASKS}}
**{{PRIORITY_ICON}} {{TASK}}**
{{/TASKS}}

## 🎯 Companies to Look Into
{{#NEW_COMPANIES}}
**{{COMPANY}}** — {{ROLE}}
- Score: {{SCORE}}/100
- Why: {{RATIONALE}}
- URL: {{URL}}
{{/NEW_COMPANIES}}
{{^NEW_COMPANIES}}
No new companies to surface today. Monitoring continues.
{{/NEW_COMPANIES}}

## ⚠️ Follow-Ups Needed
| Company | Role | Days Silent | Suggested Action |
|---------|------|-------------|-----------------|
{{#FOLLOWUPS}}
| **{{COMPANY}}** | {{ROLE}} | {{DAYS}}d | {{ACTION}} |
{{/FOLLOWUPS}}
{{^FOLLOWUPS}}
All active applications are on track. ✅
{{/FOLLOWUPS}}

## 🤖 Top 5 AI Headlines
{{#AI_NEWS}}
{{INDEX}}. **{{HEADLINE}}** — {{SUMMARY}} ({{SOURCE}})
{{/AI_NEWS}}

## 📊 Pipeline Health
- Applied: {{APPLIED_COUNT}} | Researching: {{RESEARCHING_COUNT}} | Interviewing: {{INTERVIEWING_COUNT}}
- Declined: {{DECLINED_COUNT}} | Rejected: {{REJECTED_COUNT}}
- Total tracked: {{TOTAL_COUNT}}

## 🧠 Portfolio Project Update
{{#TOP_PROJECTS}}
- **{{NAME}}** (Score: {{SCORE}}/10) — {{DESCRIPTION}}
{{/TOP_PROJECTS}}

## 🚫 AI Free Zone (Needs the Human)
{{#HUMAN_ITEMS}}
- {{ITEM}}
{{/HUMAN_ITEMS}}

---
— Your AI partner ✨
