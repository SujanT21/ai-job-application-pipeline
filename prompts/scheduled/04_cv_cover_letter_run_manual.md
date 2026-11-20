# Manual task: CV + cover-letter run ("Run now")

Started by hand, not on a schedule (an hourly schedule once burned the usage limit and starved the daily jobs).
Needs the candidate's PC for the working files; the mail-sync step runs even if the PC is offline.

## Prompt

Never apply for jobs, send email or contact anyone. Never invent experience: every claim must come from
`fact-sheet.md`, and the fact-checker agent has a veto.

1. CHECK FIRST (no agents): Applications tab, Fit checks tab and every application folder. Process the
   handover queue from the second agent (ChatGPT/Codex), respect its claims under 6 hours old, never redo a
   finished pack, reset rows stuck "in progress" for more than 6 hours.
1b. MAIL SYNC (no agents): fill `applied_date` from the employer's confirmation email and `outcome`
   (Rejected / Interview / Assessment / Offer + date) from Gmail, everywhere including Trash. Latest status
   wins; never overwrite with older news. Applications made directly (no row yet) get a new row.
2. PACK RULE: a CV + cover letter ONLY when the employer is a confirmed A-rated Skilled Worker sponsor
   AND the fit score is 80-100%.
3. NHS FIRST: NHS and NHS-adjacent adverts are fit-checked and packed first, even while the backlog is large.
4. BACKLOG FIRST: while 20+ rows meet the PACK RULE without a CV, don't fit-check new non-NHS adverts.
   Run `live_check.py` on the backlog links first.
5. Order: NHS -> closing within 2 days -> newest advert -> best fit.
6. Up to 5 packs per run, ONE JOB AT A TIME, claimed first:
   writer (Opus) -> fact-checker (Opus, veto) + combined reviewer (Sonnet) -> fixer (Opus) only if needed
   -> CV + cover letter as .docx and .pdf -> sheet updated.
7. Backlog below 20: newest 10 unchecked Jobs rows -> free pre-filter -> one Haiku fit-check agent
   (Sonnet re-check for 75-79%) -> packs only for PACK RULE jobs. Never fit-check more than 10 before
   writing that batch's packs.
8. On a real usage-limit error: put the current row back to "to do" and log limit_hit = TRUE.

Report: mail-sync results first (any interviews or offers), then packs made, queue left, new fit checks,
tokens used, adverts needing a manual JD paste, anything closing within 5 days, errors.
