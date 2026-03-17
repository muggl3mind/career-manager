Subject: 🌙 Evening Digest - {{DATE}}

## ⚠️ Follow-Ups Needed ({{FOLLOWUP_COUNT}})
{{#FOLLOWUPS}}
**{{COMPANY}}** — {{ROLE}} ({{DAYS_SINCE}} days since last contact)
- Last action: {{LAST_ACTION}}
- Contact: {{CONTACT}}
{{#HAS_DRAFT}}

**Draft email:**
> Subject: {{DRAFT_SUBJECT}}
>
> {{DRAFT_BODY}}

Send this? Reply YES / EDIT / SKIP
{{/HAS_DRAFT}}
{{/FOLLOWUPS}}
{{^FOLLOWUPS}}
✅ No follow-ups needed today. All active applications are on track.
{{/FOLLOWUPS}}

## 📈 Pipeline Health Check
{{#GOOD_MOMENTUM}}
**✓ Good momentum:**
{{#MOMENTUM_ITEMS}}
- {{ITEM}}
{{/MOMENTUM_ITEMS}}
{{/GOOD_MOMENTUM}}

{{#WATCH_AREAS}}
**⚠️ Watch areas:**
{{#WATCH_ITEMS}}
- {{ITEM}}
{{/WATCH_ITEMS}}
{{/WATCH_AREAS}}

{{#STALE_RESEARCH}}
{{STALE_COUNT}} companies in "researching" for {{STALE_DAYS}}+ days → {{STALE_ACTION}}
{{/STALE_RESEARCH}}

## 📊 Today's Summary
- Tasks completed: {{COMPLETED_COUNT}}
- Applications updated: {{UPDATED_COUNT}}
- New companies added: {{NEW_COMPANIES_COUNT}}

## 🧠 Portfolio Ideas (Full Summary)
{{#ALL_PROJECTS}}
{{INDEX}}. **{{NAME}}** ({{SCORE}}/10) — {{DESCRIPTION}}
{{/ALL_PROJECTS}}

## 🔔 Tomorrow's Priorities
{{#TOMORROW_PRIORITIES}}
- {{PRIORITY_ICON}} {{TASK}}
{{/TOMORROW_PRIORITIES}}

## 🚫 AI Free Zone (Needs the Human)
{{#HUMAN_ITEMS}}
- {{ITEM}}
{{/HUMAN_ITEMS}}

---
— Your AI partner ✨
