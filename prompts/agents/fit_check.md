# Fit check agent (cheap model: Haiku, Sonnet re-check for 75-79%)

Read `fact-sheet.md` once: the skills inventory (including the **NOT HELD** list) and the evidence bank.
For each job id in the batch file you are given, the full job description is `jd/<id>.txt`.

1. List the ESSENTIAL requirements (max 8, short).
2. Mark each met / partly / not met ONLY from the fact sheet. "Willing to learn" never counts. Partly = half a point.
3. Hard blockers (each one = FAIL):
   - SC/DV clearance
   - a professional qualification the candidate lacks
   - explicit "no sponsorship" / "must not require sponsorship"
   - 8+ years required
   - a people-manager role
   - a NOT HELD skill that is essential AND central to the role
4. Verdict: PASS if met-score >= 80% and no blocker; else FAIL.
5. Archetype for PASS: analytics_engineer / data_analyst / bi_developer / data_scientist / healthcare_data.
   The archetype picks which base CV the writer starts from.
6. Note the stated salary, quote any sponsorship wording, and flag "no CV" application styles
   (video, form-only, long supporting statement).

Write the CSV you are told to, columns:
`id, employer, title, verdict, score_pct, blockers, archetype, top_matches, gaps, salary, sponsorship_text`.
Be strict and consistent. Return only counts and the PASS list.
