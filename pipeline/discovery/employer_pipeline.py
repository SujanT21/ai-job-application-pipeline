#!/usr/bin/env python3
"""Daily employer pipeline (cloud agent): rank sponsors, find careers links, build the target list.

Steps (all free data, runs in Claude's cloud sandbox in ~10-15 minutes):
  1. Download the latest GOV.UK sponsor register CSV.
  2. Download the latest Companies House bulk company data (cached per month in --work).
  3. Rank every A-rated Skilled Worker sponsor (rank_sponsors.py).
  4. Probe Greenhouse / Lever / Ashby for the top-ranked sponsors (probe_careers.py).
  5. Merge with careers links found earlier by web search (--found CSV, exported from the
     "Careers links (found)" tab) and write:
       target_employers.csv  - tier 1-2 employers with a usable careers link, best first
       top_ranked.csv        - top N ranked employers (for the "Ranked employers" tab)
       careers_todo.csv      - next highest-ranked employers with no link yet, for web search
       summary.json

Usage:
  python3 employer_pipeline.py --work /tmp/emp --found found.csv [--probe-top 2000] [--todo 25] [--top-ranked 1000]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import subprocess
import sys
import urllib.request

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, os.path.join(HERE, "..", "sponsors"))
sys.path.insert(0, HERE)
from sponsor_check import find_csv_url, http_get  # noqa: E402

CH_INDEX = "https://download.companieshouse.gov.uk/en_output.html"


def fetch(url: str, dest: str) -> None:
    tmp = dest + ".part"
    with urllib.request.urlopen(urllib.request.Request(url, headers={"User-Agent": "job-search/1.0"}), timeout=600) as r, \
            open(tmp, "wb") as f:
        while True:
            b = r.read(1 << 20)
            if not b:
                break
            f.write(b)
    os.replace(tmp, dest)


def ensure_companies_house(work: str) -> str:
    html = http_get(CH_INDEX, timeout=60).decode("utf-8", "replace")
    parts = sorted(set(re.findall(r"BasicCompanyData-(\d{4}-\d{2}-\d{2})-part\d+_\d+\.zip", html)))
    if not parts:
        raise RuntimeError("Companies House bulk files not found on the download page")
    date = parts[-1]
    names = sorted(set(re.findall(rf"BasicCompanyData-{date}-part\d+_\d+\.zip", html)))
    d = os.path.join(work, f"ch-{date}")
    os.makedirs(d, exist_ok=True)
    for n in names:
        p = os.path.join(d, n)
        if not os.path.exists(p):
            fetch("https://download.companieshouse.gov.uk/" + n, p)
    return d


def run(cmd: list[str]) -> str:
    out = subprocess.run(cmd, check=True, capture_output=True, text=True)
    return out.stdout.strip()


def read_csv(p: str) -> list[dict]:
    if not p or not os.path.exists(p):
        return []
    with open(p, encoding="utf-8-sig", newline="") as f:
        return list(csv.DictReader(f))


def write_csv(p: str, rows: list[dict], cols: list[str]) -> None:
    with open(p, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--work", required=True)
    ap.add_argument("--found", default="", help="CSV of links found by web search (normalised_name, careers_url, ats, confidence, status, ...)")
    ap.add_argument("--probe-top", type=int, default=2000)
    ap.add_argument("--todo", type=int, default=25)
    ap.add_argument("--top-ranked", type=int, default=1000)
    a = ap.parse_args()
    os.makedirs(a.work, exist_ok=True)

    url, meta = find_csv_url()
    reg = os.path.join(a.work, "register.csv")
    fetch(url, reg)
    ch = ensure_companies_house(a.work)

    ranked = os.path.join(a.work, "ranked.csv")
    rank_log = run([sys.executable, os.path.join(HERE, "rank_sponsors.py"), "--register", reg, "--ch-dir", ch, "--out", ranked])
    probed = os.path.join(a.work, "probed.csv")
    probe_log = run([sys.executable, os.path.join(HERE, "probe_careers.py"), "--ranked", ranked,
                     "--top", str(a.probe_top), "--out", probed])

    ranked_rows = read_csv(ranked)
    probe = {r["normalised_name"]: r for r in read_csv(probed)}
    found = {r["normalised_name"]: r for r in read_csv(a.found) if r.get("normalised_name")}

    targets, todo = [], []
    for r in ranked_rows:
        k = r["normalised_name"]
        p, f = probe.get(k), found.get(k)
        link = None
        if f and f.get("careers_url"):
            link = {"careers_url": f["careers_url"], "ats": f.get("ats", ""), "job_feed_url": f.get("job_feed_url", ""),
                    "confidence": f.get("confidence", "medium"), "link_source": "web search"}
        if p and p.get("status") == "found" and p.get("confidence") in ("high", "medium"):
            link = {"careers_url": p["careers_url"], "ats": p["ats"], "job_feed_url": p["job_feed_url"],
                    "confidence": p["confidence"], "link_source": "job-feed probe",
                    "uk_jobs": p["uk_jobs"], "data_jobs": p["data_jobs"]}
        if link and int(r["tier"]) <= 2:
            targets.append({**r, **link})
        elif not link and int(r["tier"]) <= 2 and not f and len(todo) < a.todo:
            todo.append(r)

    tcols = ["rank", "tier", "organisation", "towns", "size_band", "sector", "careers_url", "ats", "job_feed_url",
             "uk_jobs", "data_jobs", "confidence", "link_source", "company_number"]
    write_csv(os.path.join(a.work, "target_employers.csv"), targets, tcols)
    write_csv(os.path.join(a.work, "top_ranked.csv"), ranked_rows[: a.top_ranked],
              ["rank", "tier", "organisation", "towns", "size_band", "sector", "region", "register_entries", "company_number"])
    write_csv(os.path.join(a.work, "careers_todo.csv"), todo, ["rank", "tier", "organisation", "normalised_name", "towns", "sector"])
    summary = {"register_url": url, "register_updated": meta.get("public_updated_at"), "companies_house_dir": os.path.basename(ch),
               "rank_log": rank_log, "probe_log": probe_log, "targets": len(targets), "todo": len(todo),
               "targets_with_data_jobs": sum(1 for t in targets if str(t.get("data_jobs", "")).isdigit() and int(t["data_jobs"]) > 0)}
    with open(os.path.join(a.work, "summary.json"), "w") as f:
        json.dump(summary, f, indent=2)
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
