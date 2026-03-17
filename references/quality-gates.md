# Target Company Quality Gates

Run before digests or major prioritization:

1. **Required fields present**: company, careers_url or website, fit_rationale
2. **No duplicates**: normalized company name dedupe
3. **No stale links**: careers URL returns valid non-404 response
4. **No stale records**: old entries flagged for refresh
5. **Scoring fresh**: numeric score regenerated and sorted
6. **Invalid role filter**: flag postings that clearly mismatch target roles

Output should include pass/fail summary and issue list.
