#!/usr/bin/env python3
"""Mechanical checks on a tailored CV and cover letter. No LLM tokens.

Runs after the writer agent and before the review panel, so reviewers only see drafts that
already pass the cheap rules: no banned phrases, no unsupported tools, the right page count.

Usage:
    python3 check.py cv.json cover_letter.txt job_description.txt cv.pdf [--rules rules.json]

rules.json (see examples/check_rules.example.json):
    banned       - regexes that must never appear (clichés, tools the candidate does not have,
                   number formats the fact sheet forbids)
    allow_if     - {banned_regex: context_regex} - a banned hit is allowed when this text is nearby
                   (e.g. "Java" is fine inside "keen to learn Java")
    keywords     - advert keywords to report as hit / missing (informational only)
    max_pages    - maximum page count of the CV PDF (default 2)
    max_letter_words - cover-letter word limit (default 350)
"""
import argparse
import json
import re
import subprocess
from pathlib import Path

DEFAULT_RULES = Path(__file__).resolve().parents[2] / "examples" / "check_rules.example.json"


def pdf_pages(pdf: str) -> int | None:
    try:
        out = subprocess.run(["pdfinfo", pdf], capture_output=True, text=True).stdout
        m = re.search(r"Pages:\s+(\d+)", out)
        return int(m.group(1)) if m else None
    except FileNotFoundError:   # poppler-utils not installed
        return None


def run(cv_json: str, letter: str, jd: str, pdf: str, rules_path: str) -> dict:
    rules = json.loads(Path(rules_path).read_text(encoding="utf-8"))
    cv = json.loads(Path(cv_json).read_text(encoding="utf-8"))
    cl = Path(letter).read_text(encoding="utf-8")
    jd_text = Path(jd).read_text(encoding="utf-8").lower()
    text = json.dumps(cv, ensure_ascii=False) + "\n" + cl

    out = {"banned": [], "pages": pdf_pages(pdf), "cl_words": len(cl.split()),
           "keywords_hit": 0, "keywords_missing": [], "ok": True}
    for pattern in rules.get("banned", []):
        for m in re.finditer(pattern, text, re.I):
            ctx = text[max(0, m.start() - 40):m.end() + 40].replace("\n", " ")
            allow = rules.get("allow_if", {}).get(pattern)
            if allow and re.search(allow, ctx, re.I):
                continue
            out["banned"].append(f"{pattern} :: ...{ctx}...")

    cv_lower = text.lower()
    for k in rules.get("keywords", []):
        if k in jd_text:
            if k in cv_lower:
                out["keywords_hit"] += 1
            else:
                out["keywords_missing"].append(k)

    if out["banned"]:
        out["ok"] = False
    if out["pages"] is not None and out["pages"] > rules.get("max_pages", 2):
        out["ok"] = False
    if out["cl_words"] > rules.get("max_letter_words", 350):
        out["ok"] = False
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("cv_json")
    ap.add_argument("cover_letter")
    ap.add_argument("job_description")
    ap.add_argument("cv_pdf")
    ap.add_argument("--rules", default=str(DEFAULT_RULES))
    a = ap.parse_args()
    print(json.dumps(run(a.cv_json, a.cover_letter, a.job_description, a.cv_pdf, a.rules), indent=1))


if __name__ == "__main__":
    main()
