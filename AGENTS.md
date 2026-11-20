# AGENTS.md

Rules for AI coding agents (Claude, Codex, ChatGPT) working in this repository.

## Never

- Commit personal data: a real fact sheet, CVs, cover letters, job descriptions, emails, phone numbers,
  spreadsheet IDs or API keys. `.gitignore` covers the usual paths; check `git diff --cached` anyway.
- Add a step that applies for a job, sends an email or contacts anyone. The pipeline prepares; a person applies.
- Let a writer agent claim anything that is not in the fact sheet. The fact-checker's veto is not optional.

## Conventions

- Python: standard library only, 3.10+. Each script runs on its own with `python script.py --help`-style usage
  in its docstring.
- Free steps first. If a check can be done with a regex or an HTTP request, it must not use a model.
- Scripts never delete data they cannot see is closed: an advert whose status is unknown is kept.
- Sheet writes are verified by reading the cells back.
- Two agents can work the same queue. Claim a row ("in progress - <agent> - <UTC time>") before working it,
  and never take a row someone else claimed less than 6 hours ago.

## Before you push

```bash
python -m unittest discover -s tests -v
grep -rniE "@gmail|07[0-9]{3} ?[0-9]{6}|spreadsheets/d/" . --include=*.py --include=*.md --include=*.js
```

The grep should print nothing.
