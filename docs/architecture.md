# Architecture

Four scheduled or on-demand jobs share one Google Sheet. Each stage writes to a tab the next stage reads.

## 1. Sponsor register (daily, Google Apps Script)

`apps-script/SponsorRegister.gs`, mirrored in Python by `pipeline/sponsors/sponsor_check.py`.

1. Find today's register CSV through the GOV.UK Content API.
2. Validate: exact header, at least 50k rows, at least 30k Skilled Worker rows, no drop of more than 5%.
   A bad file is rejected and yesterday's data is kept.
3. Write the "A-rated Skilled Worker" tab with a normalised name for matching
   (lowercase, `&` -> `and`, punctuation and `ltd / limited / plc / group / holdings` removed).
4. Diff against the previous run and log new and removed sponsors.

## 2. Employer discovery (weekly, Claude scheduled task)

`pipeline/discovery/`:

- `rank_sponsors.py` joins the register to Companies House bulk data and scores each sponsor on size,
  sector (SIC codes) and region. Tier 1 = large employers in data-heavy sectors.
- `probe_careers.py` tries Greenhouse, Lever and Ashby board slugs for the top sponsors and keeps only
  boards whose name matches and that list UK jobs.
- `feed_jobs.py` reads those boards and keeps UK data roles posted in the last 21 days.
- Employers with no detectable board go to a web-search queue, 25 a day.

## 3. Job-alert emails (daily 18:10, Claude scheduled task)

Parses alert emails into the "Jobs" tab, applies the salary and sponsorship rules, routes recruiter
adverts to "Agency leads", and logs each email's arrival time so a silent alert source is noticed.

## 4. CV + cover-letter run (on demand)

1. **Check state** with no agents: sheet rows, application folders, the second agent's handover queue.
2. **Mail sync:** applied dates and outcomes from Gmail.
3. **Live check** the backlog (`live_check.py`).
4. **Pre-filter** new adverts (`prefilter.py`).
5. **Fit check** 10 at a time (`prompts/agents/fit_check.md`).
6. **Packs**, one job at a time, max 5 per run:
   writer -> fact-checker (veto) + reviewer -> fixer if needed -> `build_cv.js` -> `check.py` -> sheet updated.

## Why one job at a time

A run can stop at the usage limit. Claiming one row, finishing it and writing it back means a cut-off run
leaves at most one half-done job, which the next run resets after 6 hours.

## Two agents, one queue

ChatGPT/Codex runs the same queue from the PC. Both write a claim before starting, and a handover file
lets the agent without Sheet access record its results for the other to sync.
