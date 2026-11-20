# Scheduled task: advert live-check (daily 17:45 UK)

No AI agents: a plain Python script does the checking. Runs before the 18:10 alert run.

## Prompt

Purpose: remove scraped adverts that are no longer live from the "Jobs" tab, so the CV run doesn't spend
tokens on them. Do NOT touch the "Applications" tab or any job already in it.

1. Read 'Jobs'!A1:L3000 and 'Applications'!H2:H3000. Write in.csv with the Jobs columns plus sheet_row,
   skipping rows whose link is in Applications or is empty.
2. Run `python3 pipeline/screening/live_check.py in.csv out.csv` (5-20 minutes; LinkedIn is rate-limited
   to one request at a time).
3. For every row with live_status = closed:
   a) append it to the "Closed adverts" tab with the reason,
   b) re-read the Jobs links and confirm each closed link is still on the same row (other runs may have
      added or removed rows),
   c) delete those rows from the BOTTOM up so row numbers stay valid,
   d) in "Fit checks", mark queued / needs-JD rows for those links as "closed <date> (advert gone)".
   Rows with live_status = unknown (sites that block checks, temporary errors) are KEPT.
4. Report: rows checked, live / closed / unknown counts, closed jobs removed, errors.
