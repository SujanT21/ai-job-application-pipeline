# Google Sheet schema

| Tab | Written by | Columns |
|---|---|---|
| Jobs | alert run, employer agent | found_utc, source, title, employer, register_name, sponsor (yes / check), location, salary, salary_type, fit (strong / good / stretch), link, notes |
| Agency leads | alert run | found_utc, source, agency, title, location, salary, link, notes |
| Fit checks | CV run | id, link, employer, title, verdict, score_pct, blockers, archetype, top_matches, gaps, salary, sponsorship_text, status |
| Applications | CV run, mail sync, me | date_prepared, employer, job_title, location, salary, fit_score, sponsor_match, job_link, closing_date, folder, cv_file, cover_letter_file, review_verdict, gaps_and_notes, Applied (tick), Not applied (tick), applied_date, outcome, base_cv, pack_status |
| Closed adverts | live check | date_closed, employer, title, source, link, reason, removed_from |
| Tailoring usage | CV run | run_date, week_start, weekly_budget, jobs_done, tokens_used, limit_hit, week_total_used, notes |
| Job search log | alert run | run_time_utc, emails_processed, jobs_added, agency_leads_added |
| Alert arrival times | alert run | date, source_site, sender, received_utc |
| A-rated Skilled Worker, Status, Latest changes, Change history, Change log | Apps Script | register data; never edited by agents |
| Target employers, Ranked employers, Careers links (found), Careers to search | employer agent | ranking and job-board discovery |

## Status values

- `pack_status`: to do, in progress - <agent> - <time>, done - <agent>, skipped - below 80%,
  blocked - <reason>, parked - sponsor not confirmed, removed.
- `outcome`: Rejected YYYY-MM-DD, Interview YYYY-MM-DD, Assessment YYYY-MM-DD, Offer YYYY-MM-DD,
  optionally followed by " - <reason>". The latest status wins.
