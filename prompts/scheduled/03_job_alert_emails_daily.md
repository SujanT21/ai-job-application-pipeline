# Scheduled task: job-alert email run (daily 18:10 UK)

Runs after the day's last alert email. Never applies, replies, sends email or contacts anyone.

## Prompt

Candidate: on a Graduate visa, needs a Skilled Worker-sponsored data role anywhere in the UK.
Spreadsheet ID `<SPREADSHEET_ID>`. Edit only "Jobs", "Agency leads", "Job search log", "Alert arrival times".

STEP 1 - Which emails. Process emails received after the latest run time in "Job search log".
Run all three Gmail searches and de-duplicate by message id:
- (a) known alert senders: LinkedIn job alerts and recruiter InMails, Totaljobs, CWJobs, SimplyHired, Reed,
  Indeed, NHS Jobs, jobs.ac.uk, Adzuna, Glassdoor, CV-Library, s1jobs, myjobscotland, Civil Service Jobs,
  hackajob, Otta, agency senders.
- (b) catch-all for new alert sites: subject contains jobs / job alert / vacancies / roles / new role /
  opportunities / recommended jobs, or the Updates category. Skip confirmations, rejections, GDPR,
  password and newsletter emails. Name any new alert sender in the report.
- (c) LinkedIn "X and N others are hiring for ... roles" digests, and employer talent-community alerts
  ("new job matching your profile"), excluding interview invites and reminders.

STEP 2 - Extract title, employer, location, salary, link, source, date posted.

STEP 3 - Filter:
- a) data role titles only; drop junior / graduate / intern and Head / Director / VP titles.
- b) drop explicit sponsorship refusals ("must have right to work" alone is NOT a reason), SC/DV, day-rate contracts.
- c) salary: top end below GBP 33,400 -> drop; GBP 33,400-38,599 -> keep with "near sponsorship minimum".
- d) recruitment agencies -> "Agency leads".
- e) sponsor check against today's GOV.UK register (found via the Content API, never a hard-coded URL):
  exact normalised match -> "yes"; partial -> "check"; otherwise drop.
- f) de-duplicate against existing rows (same link, or same employer + title).

STEP 4 - Write rows to the tabs; log the run and one row per alert email in "Alert arrival times".

STEP 5 - Report: emails per site with arrival times, new senders, top 10 jobs added, drops by reason,
anything broken (a site silent for 2+ days, an alert arriving after 18:00).
