# CV Tailoring Lessons

Lessons extracted from user revisions to AI-generated tailored resumes. Apply these rules during Phase 2 (Analysis) to produce output closer to what the user actually wants.

## Lesson 1: Match language to actual scope — don't inflate

**Rule:** Use "tools" or "prototypes" for personal/open-source projects, not "systems" or "platforms." Reserve "systems" for production-grade work at an employer.

**Why:** The user values credibility over impressiveness. Calling a prototype a "system" signals resume inflation, which undermines trust with technical interviewers who will ask follow-up questions.

**How to apply:** Before writing `new` text for technical projects, check whether the project is production or prototype. Scale the language accordingly.

---

## Lesson 2: Cut explanatory tails — let strong accomplishments land on their own

**Rule:** If the core accomplishment (the build, the number, the action) is strong enough to stand alone, do not append "ensuring X" / "to deliver Y" / "resulting in Z" outcome phrases.

**Why:** Trailing outcome phrases often read as resume padding. The user's editing pattern consistently trims these. A bullet that ends on the hard fact is punchier than one that explains why it mattered.

**How to apply:** After drafting each bullet edit, read the last clause. If it restates an obvious outcome or adds boilerplate compliance/quality language, cut it. Only keep outcome phrases when the outcome is surprising or non-obvious.

---

## Lesson 3: Name specific competencies instead of catch-all phrases

**Rule:** Prefer listing the actual skills ("financial statement audit and financial reporting") over breadth qualifiers ("end-to-end financial statement audit expertise").

**Why:** "End-to-end" is vague and overused on resumes. Naming both competencies separately signals the candidate actually knows they're distinct and has done both.

**How to apply:** When tempted to use "end-to-end," "comprehensive," or "full-lifecycle" as modifiers, check whether you can instead name the specific components. If so, name them.

---

## Lesson 4: Don't editorialize about AI design philosophy on the resume

**Rule:** Do not add sentences that explain *why* the AI architecture was designed a certain way. Let the technical description speak for itself.

**Why:** The resume should show what was built, not narrate the design rationale. Design philosophy is interview conversation material, not resume bullet material. Adding it reads as the AI trying to sound impressive rather than the candidate describing their work.

**How to apply:** After drafting technical project edits, check for any sentence that explains the thinking behind the build rather than the build itself. Remove it. The interviewer will ask if they're curious.

---

## Lesson 5: Always disclose partial JD extraction — never assume you have the full picture

**Rule:** When WebFetch returns a careers landing page, partial content, or a JS-rendered shell instead of the full job description, explicitly tell the user what you got and what's missing. Never proceed with tailoring on an incomplete JD without flagging it.

**Why:** If the first fetch returns only partial content, the user may assume the AI had the full JD. They only discover the gaps after reviewing the tailored output, wasting a revision cycle.

**How to apply:** After any WebFetch for a JD, compare what you got against what a typical full posting contains (responsibilities, required qualifications with specifics, bonus qualifications, comp, benefits). If sections are thin or missing specifics, say so and ask the user to paste the full text. Do this before Phase 1 prep, not after.

---

## Lesson 6: Map every specific JD qualification to a resume bullet — checkbox coverage

**Rule:** Before writing analysis.json, list every specific qualification from the JD and confirm each one is addressed somewhere in the resume. If a qualification has no matching bullet, either add language to an existing bullet or flag the gap to the user.

**Why:** Detailed JDs often list distinct checkboxes a hiring manager will scan for. If the tailored resume misses them, the user catches it instead of the AI.

**How to apply:** During Phase 2 analysis, create an explicit checklist of JD requirements before drafting edits. For each item, note which existing bullet it maps to. If an item has no match, draft a micro-edit to an existing bullet (don't add new bullets unless necessary). Include this checklist in the analysis output so the user can verify coverage.
