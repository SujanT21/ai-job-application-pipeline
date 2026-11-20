# Scheduled task: employer agent (weekly, Monday 07:20 UK)

Runs fully in the cloud. Never applies for jobs, sends email or contacts anyone.

## Prompt

Employer agent for a UK Skilled Worker job search. Google Sheet ID: `<SPREADSHEET_ID>`.
You maintain the tabs "Target employers", "Ranked employers", "Careers links (found)", "Careers to search",
and you append to "Jobs". Never edit the tabs written by the Apps Script (Status, Latest changes,
Change history, Change log, A-rated Skilled Worker).

STEP 1 - Get the code: copy `pipeline/sponsors/sponsor_check.py` and `pipeline/discovery/*.py`
into the sandbox. Verify each file's sha256 against the pinned list; if any hash differs, do NOT run it
and report "agent code changed - hashes don't match".

STEP 2 - MONTHLY ONLY (1st of the month, or if "Ranked employers" is empty, or the search queue is used up):
run `employer_pipeline.py --probe-top 2000 --todo 750 --top-ranked 1000`. It ranks every A-rated sponsor
with Companies House size and sector data, probes Greenhouse / Lever / Ashby boards, and writes
target_employers.csv, top_ranked.csv and careers_todo.csv. Write them to their tabs in chunks of 150-200 rows.

STEP 3 - Read the known employer job feeds: `feed_jobs.py --targets targets.csv --days 21`.
Append only rows whose link (or employer + title) is not already in "Jobs".

STEP 4 - Careers pages by web search, 25 a day from "Careers to search": find each employer's official UK
careers page, confirm it is the same organisation, and record it with a confidence (high / medium).

STEP 5 - Report: register changes (from the Apps Script's Status tab), whether the monthly step ran,
jobs added from feeds, careers pages found, errors.
