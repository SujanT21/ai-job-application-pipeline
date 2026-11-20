#!/usr/bin/env python3
"""Free pre-filter: drop adverts that can never pass, before any LLM sees them.

Every advert this script removes is one fewer fit check (each fit check costs ~10-15k tokens).

Checks, in order (first failing check wins):
  1. duplicate        - same normalised link, or same employer + title, already queued / screened / applied
  2. not a data role  - title has no data / analytics / BI keyword
  3. seniority        - head of / director / principal / VP / staff / senior / lead (configurable)
  4. no sponsorship   - advert text says it cannot sponsor
  5. clearance        - SC / DV / "British nationals only"
  6. salary           - top of the stated range is below the sponsorship floor
  7. sponsor          - employer not on the A-rated Skilled Worker register

Usage:
    python3 prefilter.py jobs.csv register_a_rated.csv out.csv [--seen seen.csv] [--floor 33400] [--allow-senior]

jobs.csv columns: employer, title, link, salary, location, jd_text (optional)
register_a_rated.csv: output of pipeline/sponsors/sponsor_check.py (needs normalised_name)
seen.csv (optional): rows already screened or applied to (employer, title, link)
out.csv adds: prefilter (keep | skip), prefilter_reason, sponsor_match
"""
from __future__ import annotations

import argparse
import csv
import os
import re
import sys
import urllib.parse

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sponsors"))
from sponsor_check import normalise_name  # noqa: E402

DATA_TITLE = re.compile(r"\b(data|analytics?|analyst|insight|business intelligence|\bbi\b|reporting|looker|dbt|"
                        r"snowflake|power bi|machine learning|scientist|statistic)", re.I)
SENIOR = re.compile(r"\b(head of|director|principal|vp|vice president|chief|staff|senior|lead|manager)\b", re.I)
NO_SPONSOR = re.compile(r"(no|not able to|unable to|cannot|can't|do not|does not|will not) (offer |provide )?"
                        r"(visa )?sponsor(ship)?|sponsorship (is )?not (available|offered)|"
                        r"must (already )?have (the )?(full |unrestricted )?right to work.{0,40}without sponsorship", re.I)
CLEARANCE = re.compile(r"\b(sc|dv|security) clearance\b|\bbritish nationals? only\b|\bdeveloped vetting\b", re.I)
MONEY = re.compile(r"£\s?(\d{2,3}(?:,\d{3})|\d{2,3}(?:\.\d)?\s?k)", re.I)


def norm_link(value: str) -> str:
    value = (value or "").strip()
    if not value:
        return ""
    u = urllib.parse.urlsplit(value)
    q = [(k, v) for k, v in urllib.parse.parse_qsl(u.query, keep_blank_values=True)
         if not k.lower().startswith("utm_") and k.lower() not in ("trk", "trackingid", "ref", "source")]
    if u.netloc.lower().endswith("linkedin.com"):
        q = []
    return urllib.parse.urlunsplit((u.scheme.lower(), u.netloc.lower(), u.path.rstrip("/"), urllib.parse.urlencode(q), ""))


def pair(employer: str, title: str) -> tuple[str, str]:
    return (re.sub(r"\s+", " ", (employer or "").strip().casefold()),
            re.sub(r"\s+", " ", (title or "").strip().casefold()))


def top_salary(text: str) -> int | None:
    vals = []
    for m in MONEY.finditer(text or ""):
        s = m.group(1).lower().replace(",", "").replace(" ", "")
        vals.append(int(float(s[:-1]) * 1000) if s.endswith("k") else int(s))
    vals = [v for v in vals if 10_000 <= v <= 500_000]
    return max(vals) if vals else None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("jobs")
    ap.add_argument("register")
    ap.add_argument("out")
    ap.add_argument("--seen", default="")
    ap.add_argument("--floor", type=int, default=33_400, help="lowest salary a sponsored role can pay")
    ap.add_argument("--allow-senior", action="store_true")
    a = ap.parse_args()

    register = {r["normalised_name"] for r in csv.DictReader(open(a.register, encoding="utf-8-sig"))}
    seen_links, seen_pairs = set(), set()
    if a.seen:
        for r in csv.DictReader(open(a.seen, encoding="utf-8-sig")):
            seen_links.add(norm_link(r.get("link", "")))
            seen_pairs.add(pair(r.get("employer", ""), r.get("title", "")))

    rows = list(csv.DictReader(open(a.jobs, encoding="utf-8-sig")))
    from collections import Counter
    counts = Counter()
    for r in rows:
        link, p = norm_link(r.get("link", "")), pair(r.get("employer", ""), r.get("title", ""))
        text = " ".join([r.get("title", ""), r.get("salary", ""), r.get("jd_text", "")])
        emp = normalise_name(r.get("employer", ""))
        sponsor = "yes" if emp in register else ("check" if any(emp and emp in n for n in register) else "no")
        reason = None
        if (link and link in seen_links) or p in seen_pairs:
            reason = "duplicate"
        elif not DATA_TITLE.search(r.get("title", "")):
            reason = "not a data role"
        elif not a.allow_senior and SENIOR.search(r.get("title", "")):
            reason = "seniority"
        elif NO_SPONSOR.search(text):
            reason = "no sponsorship"
        elif CLEARANCE.search(text):
            reason = "clearance / nationality"
        elif (s := top_salary(r.get("salary", "") or r.get("jd_text", ""))) and s < a.floor:
            reason = f"salary below floor ({s})"
        elif sponsor == "no":
            reason = "employer not on A-rated register"
        r["prefilter"] = "skip" if reason else "keep"
        r["prefilter_reason"] = reason or ""
        r["sponsor_match"] = sponsor
        counts[reason or "keep"] += 1
        seen_links.add(link)
        seen_pairs.add(p)

    fields = list(rows[0].keys()) if rows else ["prefilter", "prefilter_reason", "sponsor_match"]
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        w.writerows(rows)
    print(dict(counts))
    return 0


if __name__ == "__main__":
    sys.exit(main())
