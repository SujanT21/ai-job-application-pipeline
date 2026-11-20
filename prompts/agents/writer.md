# Writer agent (Opus)

Inputs: a job id `<ID>`, its archetype `<ARCH>` and a folder slug `<SLUG>`.

Read ONLY: `fact-sheet.md`, `cv-playbook.md`, `base/<ARCH>.json`, `jd/<ID>.txt` and the job's fit-check row.
Work in `out/<SLUG>/`.

1. `job-description.md` - copy of the JD text, with the link and today's date.
2. `fit-notes.md` - must-haves -> evidence (fact-sheet reference) -> met / partly / gap. State gaps plainly.
   If the salary is known, note the likely SOC code and whether it clears the sponsorship minimum.
3. `cv.json` - copy `base/<ARCH>.json`, then change ONLY:
   - summary sentences 2-3 (sentence 1 stays as in the base),
   - the ORDER of current-role bullets, and swaps to approved alternatives from the fact-sheet bullet library,
   - skills order, so the advert's tools come first (add an item only if the fact sheet supports it),
   - light wording to mirror the advert where the meaning is identical.
   Never touch earlier-role bullets, titles, dates, education or certifications. Nothing from NOT HELD.
   Numbers exactly as listed under "Approved numbers".
4. `cover_letter.txt` - max 350 words, UK English:
   - para 1: the role + one specific reason for THIS employer, taken from the JD (never invent company facts),
   - para 2: two achievements mapped to the advert's top two requirements,
   - para 3: domain / tools link and an honest line about the biggest gap,
   - close: the standard visa and notice-period sentence from the playbook.
5. Build and check:
   ```bash
   node pipeline/tailoring/build_cv.js out/<SLUG>/cv.json out/<SLUG>/CV.docx
   soffice --headless --convert-to pdf --outdir out/<SLUG> out/<SLUG>/CV.docx
   python3 pipeline/tailoring/check.py out/<SLUG>/cv.json out/<SLUG>/cover_letter.txt jd/<ID>.txt out/<SLUG>/CV.pdf
   ```
   Fix any banned hit and get the page count to 2. `keywords_missing` is informational: add only what the fact sheet supports.
6. `changes.md` - a short diff list against the base (old -> new). Reviewers read THIS, not the whole CV.

Return max 120 words: pages, letter word count, check result, and any line you were unsure about.
