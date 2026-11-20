# Costs and lessons

## Where the tokens go

| Step | Model | Approximate tokens |
|---|---|---|
| Fit check, batch of 10 adverts | Haiku | 80-150k |
| Sonnet re-check (75-79% scores) | Sonnet | ~70k each |
| Writer | Opus | ~90k per pack |
| Fact-checker | Opus | ~70k per pack |
| Combined reviewer | Sonnet | ~60k per pack |
| Fixer (only when needed) | Opus | ~60k |
| **Whole pack** | | **~250k** |

Before the October peer review, a pack used three separate reviewers and always ran the fixer: up to ~330k.

## Lessons

1. **Put free checks first.** A regex or HTTP request that removes an advert saves a fit check and maybe a
   whole pack.
2. **The fact sheet is the product.** Most review vetoes were wording drift ("led" for "contributed",
   rounded numbers). Approved wordings and a forbidden-variants column fixed most of them at the source.
3. **Reviewers read diffs.** Base CVs are reviewed once; each pack's reviewers see only `changes.md`.
4. **Never trust a cached reference file.** The sponsor register changes daily.
5. **Don't schedule the expensive job.** An hourly CV run burned the usage limit on empty runs and broke
   the cheap daily jobs that feed it.
6. **Keep unknowns.** If a site blocks a live check, the advert stays; deleting on uncertainty loses jobs.
