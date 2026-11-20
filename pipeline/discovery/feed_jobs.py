#!/usr/bin/env python3
"""Read open jobs from the known employer job feeds (Greenhouse / Lever / Ashby) and keep
UK data roles that fit the candidate's profile. Output rows match the "Jobs" tab columns.

Input:  CSV exported from the "Target employers" tab (needs: organisation, job_feed_url, ats)
Output: CSV with columns found_utc, source, title, employer, register_name, sponsor, location,
        salary, salary_type, fit, link, notes

Usage: python3 feed_jobs.py --targets targets.csv --out feed_jobs.csv [--days 21]
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

UK = re.compile(r"\b(united kingdom|uk|u\.k\.|england|scotland|wales|northern ireland|london|glasgow|edinburgh|"
                r"manchester|birmingham|leeds|bristol|cambridge|oxford|belfast|cardiff|aberdeen|dundee|newcastle|"
                r"liverpool|sheffield|nottingham|reading|milton keynes|guildford|salford|brighton)\b", re.I)  # "remote" alone is not UK
DATA = re.compile(r"\b(data\b|analytics|business intelligence|bi (developer|engineer|analyst)|looker|power bi|dbt|"
                  r"snowflake|machine learning|data scien\w*|"
                  r"(insight|product|reporting|operations|commercial|marketing|customer|people|healthcare|clinical|"
                  r"pricing|risk|growth|performance) analyst)", re.I)
EXCLUDE = re.compile(r"\b(junior|graduate|intern|internship|apprentice|placement|entry[- ]level|academy|programme|"
                     r"program|spring|summer|head of|director|principal|vp|vice president|chief|product manager|administrator|"
                     r"specialist|quality assurance)\b", re.I)
NOT_DATA = re.compile(r"\b(sales|account executive|recruiter|legal|counsel|nurse|designer|software engineer|"
                      r"frontend|backend|full[- ]stack|security engineer|data centre|data center)\b", re.I)
STRONG = re.compile(r"\b(analytics engineer|dbt|looker|snowflake|health|clinical|pharma)\b", re.I)
STRETCH = re.compile(r"\b(manager|data engineer|platform engineer|machine learning (engineer|researcher|scientist)|"
                     r"research engineer|researcher|quantitative|staff)\b", re.I)


def get(url: str):
    for i in range(3):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "job-search-feed-reader/1.0"})
            with urllib.request.urlopen(req, timeout=25) as r:
                return json.loads(r.read().decode("utf-8", "replace"))
        except urllib.error.HTTPError as e:
            if e.code in (429, 500, 502, 503):
                time.sleep(2 * (i + 1))
                continue
            return None
        except Exception:  # noqa: BLE001
            time.sleep(1 + i)
    return None


def parse_date(v) -> dt.datetime | None:
    if v is None or v == "":
        return None
    if isinstance(v, (int, float)):  # Lever: epoch ms
        return dt.datetime.fromtimestamp(v / 1000, dt.timezone.utc)
    try:
        return dt.datetime.fromisoformat(str(v).replace("Z", "+00:00"))
    except ValueError:
        return None


def jobs_from(ats: str, data) -> list[dict]:
    out = []
    if ats == "greenhouse":
        for j in (data or {}).get("jobs", []):
            out.append({"title": j.get("title", ""), "location": (j.get("location") or {}).get("name", ""),
                        "link": j.get("absolute_url", ""), "date": parse_date(j.get("updated_at"))})
    elif ats == "lever":
        for j in data or []:
            c = j.get("categories") or {}
            loc = " / ".join(filter(None, [c.get("location"), ", ".join(c.get("allLocations") or []),
                                           j.get("workplaceType")]))
            out.append({"title": j.get("text", ""), "location": loc, "link": j.get("hostedUrl", ""),
                        "date": parse_date(j.get("createdAt"))})
    elif ats == "ashby":
        for j in (data or {}).get("jobs", []):
            loc = " / ".join(filter(None, [j.get("location"),
                                           ", ".join(l.get("location", "") for l in (j.get("secondaryLocations") or [])),
                                           "Remote" if j.get("isRemote") else ""]))
            out.append({"title": j.get("title", ""), "location": loc, "link": j.get("jobUrl", ""),
                        "date": parse_date(j.get("publishedAt"))})
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--targets", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--days", type=int, default=21)
    a = ap.parse_args()
    targets = [r for r in csv.DictReader(open(a.targets, encoding="utf-8-sig")) if r.get("job_feed_url")]
    seen_feeds, uniq = set(), []
    for t in targets:  # several register entries can share one feed (e.g. Teya)
        if t["job_feed_url"] not in seen_feeds:
            seen_feeds.add(t["job_feed_url"])
            uniq.append(t)
    with ThreadPoolExecutor(10) as ex:
        feeds = list(ex.map(lambda t: (t, get(t["job_feed_url"])), uniq))
    now = dt.datetime.now(dt.timezone.utc)
    cutoff = now - dt.timedelta(days=a.days)
    rows, failed = [], []
    for t, data in feeds:
        if data is None:
            failed.append(t["organisation"])
            continue
        for j in jobs_from(t.get("ats", ""), data):
            title = j["title"]
            if not UK.search(j["location"] or "") or not DATA.search(title) or EXCLUDE.search(title) or NOT_DATA.search(title):
                continue
            if j["date"] and j["date"] < cutoff:
                continue
            fit = "stretch" if STRETCH.search(title) else ("strong" if STRONG.search(title) else "good")
            rows.append({"found_utc": now.strftime("%Y-%m-%d %H:%M"), "source": f"employer feed ({t.get('ats')})",
                         "title": title, "employer": t["organisation"], "register_name": t["organisation"],
                         "sponsor": "yes", "location": j["location"], "salary": "", "salary_type": "not stated",
                         "fit": fit, "link": j["link"], "notes": ""})
    cols = ["found_utc", "source", "title", "employer", "register_name", "sponsor", "location", "salary",
            "salary_type", "fit", "link", "notes"]
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    print(json.dumps({"feeds": len(uniq), "feeds_failed": failed, "jobs_kept": len(rows)}, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
