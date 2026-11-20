#!/usr/bin/env python3
"""Find careers links / public job feeds for the top-ranked sponsors (Greenhouse, Lever, Ashby).

Runs in Claude's cloud sandbox. Input: ranked.csv from rank_sponsors.py. Output: careers.csv with one
row per probed organisation. Same matching rules as the earlier Apps Script version:
  - Greenhouse: board name must match the sponsor name (high) or overlap >= 50% (medium)
  - Lever/Ashby: no company name in the feed, so the board must list UK jobs (high on the full-name
    slug, medium on a shortened slug); a board with no UK jobs is 'low'
  - very short names (<5 letters) are never trusted fully
Only 'high'/'medium' matches should be used by the job search.

Usage: python3 probe_careers.py --ranked ranked.csv --top 3000 --out careers.csv [--workers 12]
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sponsors"))
from sponsor_check import normalise_name  # noqa: E402

UK_RE = re.compile(r"\b(united kingdom|uk|u\.k\.|england|scotland|wales|northern ireland|london|glasgow|edinburgh|"
                   r"manchester|birmingham|leeds|bristol|cambridge|oxford|belfast|cardiff|aberdeen|dundee|newcastle|"
                   r"liverpool|sheffield|nottingham|reading|remote)\b", re.I)
DATA_RE = re.compile(r"\b(data|analytics?|analyst|scientist|machine learning|ml|bi|business intelligence|insights?|"
                     r"statistic\w*|quantitative|looker|dbt)\b", re.I)
GENERIC_LAST = re.compile(r"^(bank|technologies|technology|tech|software|services|solutions|systems|international|"
                          r"global|digital|labs|health|healthcare|consulting|partners|capital|financial|europe|corp|"
                          r"corporation|company|services|operations)$")
ATS = ("greenhouse", "lever", "ashby")


def slug_candidates(name: str) -> list[str]:
    words = [w for w in normalise_name(re.split(r"\b(?:t/a|trading as)\b", name, flags=re.I)[0]).split() if w != "and"]
    if not words:
        return []
    out = ["".join(words), "-".join(words)]
    w = list(words)
    while len(w) > 1 and GENERIC_LAST.match(w[-1]):
        w = w[:-1]
        out += ["".join(w), "-".join(w)]
    seen, res = set(), []
    for s in out:
        if len(s) >= 3 and s not in seen:
            seen.add(s)
            res.append(s)
    return res[:4]


def feed_url(ats: str, slug: str) -> str:
    return {"greenhouse": f"https://boards-api.greenhouse.io/v1/boards/{slug}/jobs",
            "lever": f"https://api.lever.co/v0/postings/{slug}?mode=json",
            "ashby": f"https://api.ashbyhq.com/posting-api/job-board/{slug}"}[ats]


def careers_url(ats: str, slug: str) -> str:
    return {"greenhouse": f"https://boards.greenhouse.io/{slug}", "lever": f"https://jobs.lever.co/{slug}",
            "ashby": f"https://jobs.ashbyhq.com/{slug}"}[ats]


def get(url: str, tries: int = 3):
    for i in range(tries):
        try:
            req = urllib.request.Request(url, headers={"User-Agent": "job-search-careers-probe/1.0"})
            with urllib.request.urlopen(req, timeout=20) as r:
                return r.status, r.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as e:
            if e.code == 404:
                return 404, ""
            if e.code == 429 or e.code >= 500:
                time.sleep(2 * (i + 1))
                continue
            return e.code, ""
        except Exception:  # noqa: BLE001 - network hiccup
            time.sleep(1 + i)
    return 0, ""


def token_overlap(sponsor: str, board: str) -> float:
    """Share of the sponsor's name words found in the board name (generic words like 'bank' count too).
    'Metro Bank' vs board 'Metro' = 0.5, so a one-word board can't fully match a two-word sponsor."""
    A, B = normalise_name(sponsor).split(), set(normalise_name(board).split())
    if not A or not B:
        return 0.0
    return sum(1 for w in A if w in B) / len(A)


def probe_one(ats: str, slug: str) -> dict | None:
    """Returns None if no board, {'error':code} on a temporary failure, else counts."""
    if ats == "greenhouse":
        code, body = get(f"https://boards-api.greenhouse.io/v1/boards/{slug}")
        if code == 404:
            return None
        if code != 200:
            return {"error": code}
        board_name = json.loads(body).get("name", "")
        code, body = get(feed_url(ats, slug))
        jobs = json.loads(body).get("jobs", []) if code == 200 else []
        locs = [(j.get("location") or {}).get("name", "") for j in jobs]
        titles = [j.get("title", "") for j in jobs]
    else:
        code, body = get(feed_url(ats, slug))
        if code == 404:
            return None
        if code != 200:
            return {"error": code}
        data = json.loads(body)
        board_name = ""
        if ats == "lever":
            if not isinstance(data, list):
                return None
            jobs = data
            locs = [" ".join(filter(None, [(j.get("categories") or {}).get("location"),
                                           " ".join((j.get("categories") or {}).get("allLocations") or []),
                                           j.get("country"), j.get("workplaceType")])) for j in jobs]
            titles = [j.get("text", "") for j in jobs]
        else:
            jobs = data.get("jobs") or []
            locs = [" ".join(filter(None, [j.get("location"),
                                           " ".join(l.get("location", "") for l in (j.get("secondaryLocations") or [])),
                                           ((j.get("address") or {}).get("postalAddress") or {}).get("addressCountry"),
                                           "remote" if j.get("isRemote") else ""])) for j in jobs]
            titles = [j.get("title", "") for j in jobs]
    uk = [bool(UK_RE.search(l or "")) for l in locs]
    data_jobs = sum(1 for u, t in zip(uk, titles) if u and DATA_RE.search(t or ""))
    return {"ats": ats, "slug": slug, "board_name": board_name, "open": len(jobs), "uk": sum(uk), "data": data_jobs}


def choose(name: str, results: list[dict], full_slug: str) -> tuple[dict, str] | None:
    best = None
    short = len(normalise_name(name).replace(" ", "")) < 5
    for r in results:
        if not r or "error" in r:
            continue
        if r["ats"] == "greenhouse":
            ov = token_overlap(name, r["board_name"])
            if ov >= 0.99:
                conf = "high"
            elif ov >= 0.5:
                conf = "medium"
            else:
                continue
            if r["open"] and not r["uk"]:
                conf = "medium" if conf == "high" else "low"
        else:
            conf = ("high" if r["slug"] == full_slug else "medium") if r["uk"] else "low"
        if short:
            conf = "medium" if (r["ats"] == "greenhouse" and conf == "high") else "low"
        rank = {"high": 3, "medium": 2, "low": 1}[conf]
        if not best or rank > best[2] or (rank == best[2] and r["uk"] > best[0]["uk"]):
            best = (r, conf, rank)
    return (best[0], best[1]) if best else None


def process(row: dict) -> dict:
    name = row["organisation"]
    slugs = slug_candidates(name)
    results, transient = [], False
    for s in slugs:
        for ats in ATS:
            r = probe_one(ats, s)
            if r and "error" in r:
                transient = True
            results.append(r)
    m = choose(name, results, slugs[0] if slugs else "")
    out = {"rank": row["rank"], "tier": row["tier"], "organisation": name, "normalised_name": row["normalised_name"],
           "careers_url": "", "ats": "", "job_feed_url": "", "open_jobs": "", "uk_jobs": "", "data_jobs": "",
           "confidence": "", "status": "retry" if (transient and not m) else ("found" if m else "not detected")}
    if m:
        r, conf = m
        out.update(careers_url=careers_url(r["ats"], r["slug"]), ats=r["ats"], job_feed_url=feed_url(r["ats"], r["slug"]),
                   open_jobs=r["open"], uk_jobs=r["uk"], data_jobs=r["data"], confidence=conf)
    return out


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--ranked", required=True)
    ap.add_argument("--top", type=int, default=3000)
    ap.add_argument("--max-tier", type=int, default=2)
    ap.add_argument("--out", required=True)
    ap.add_argument("--workers", type=int, default=12)
    a = ap.parse_args()
    rows = [r for r in csv.DictReader(open(a.ranked, encoding="utf-8")) if int(r["tier"]) <= a.max_tier][: a.top]
    t0 = time.time()
    with ThreadPoolExecutor(a.workers) as ex:
        res = list(ex.map(process, rows))
    cols = list(res[0].keys()) if res else []
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(res)
    from collections import Counter
    print(f"probed {len(res)} in {time.time() - t0:.0f}s;", Counter(r["status"] for r in res),
          Counter(r["confidence"] for r in res if r["confidence"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
