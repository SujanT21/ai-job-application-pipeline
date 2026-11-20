# Build journal

Dated decisions, in the order they were made. Each one fixed a real problem.

## October 2026

- **4 Oct. Sponsor register first.** Every job search on a Graduate visa starts with "can this employer
  sponsor?". A daily Apps Script downloads the GOV.UK register (the link is found through the Content API,
  never hard-coded), validates it, and diffs it so new sponsors show up.
- **5 Oct. Fact sheet as the single source of truth.** Early drafts invented small things: "5 years"
  instead of "over five years", a tool used once listed as a core skill. Every claim now traces to a
  fact sheet with approved number wordings and a NOT HELD list.
- **7 Oct. Review panel.** A second model reads each draft only to fact-check it, and can veto.
  A reviewer reads it as a hiring manager would.
- **10 Oct. Fit checks on a cheap model.** Haiku scores adverts in batches; only 75-79% scores get a
  Sonnet second opinion.
- **12 Oct. Live check before anything else.** Queued adverts were closing before their packs were
  written. A plain HTTP script (`live_check.py`) now removes them for free.
- **25 Oct. Peer review of the whole pipeline.** Packs were costing up to ~330k tokens. Changes: backlog first
  (finish the queue before screening more), max 5 packs per run, a lean panel (one combined reviewer
  instead of three), and the fixer only when there is a MUST item. Cost settled at roughly 250k per pack.
- **25 Oct. Never use a stale register.** A local copy of the register said an employer was not licensed;
  the live register had added it a week earlier. Every sponsor check now downloads the current file.
- **29 Oct. NHS first.** NHS and NHS-adjacent adverts are fit-checked and packed before everything else.

## November 2026

- **11 Nov. Free pre-filter before fit checks.** Seniority, salary floor, "no sponsorship" wording and
  duplicates are caught by rules, so those adverts never reach a model.
- **13 Nov. Hourly runs were a mistake.** The CV run was set to fire every hour. Six runs in a row found
  nothing new, and the usage limit ran out, so the daily alert run failed. It is back to on-demand,
  after the alert run.
- **20 Nov. Mail sync.** The CV run reads confirmation and rejection emails and fills in applied dates and
  outcomes, so the tracker reflects reality without manual updates.
- **20 Nov. Wider alert coverage.** The alert parser missed LinkedIn "hiring posts" digests and employer
  talent-community emails; both are now searched.
