# Fixer agent (Opus) - runs ONLY if the fact-checker vetoed or the reviewer raised a [MUST]

You get the panel's [MUST] / [SHOULD] items for one folder in `out/`.

Rules:
- Every [MUST] from the fact-checker is applied.
- Any other suggestion is applied only if the fact sheet supports it; otherwise skip it and say why.
- Write the reviewer's verdict at the top of `fit-notes.md` as `PANEL VERDICT: ...`.
- Edit `cv.json`, `cover_letter.txt` and `changes.md`, then rebuild and re-run `check.py` (writer step 5).
- The CV must be 2 pages; the letter max 350 words.

Return max 120 words: applied / skipped, pages, words, check results.
