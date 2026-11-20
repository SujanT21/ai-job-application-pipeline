#!/usr/bin/env python3
"""Rank every A-rated Skilled Worker sponsor from large/relevant employers down to micro firms.

Runs in Claude's cloud sandbox (no PC, no Google Apps Script). Free data only:
  - GOV.UK "Register of licensed sponsors: workers" (latest CSV)
  - Companies House "Free Company Data Product" (monthly bulk CSV, ~500 MB zipped)

Signals per sponsor organisation
  - size_band  from Companies House Accounts.AccountCategory
               (GROUP/FULL = large, MEDIUM/subsidiary exemptions = medium, SMALL/... = small,
                MICRO = micro, DORMANT/none = inactive); public bodies (NHS, universities, councils)
               are not companies and are treated as large.
  - sector     from SIC codes (data-relevant sectors score high, care/food/construction low)
  - locations  number of register entries (multi-site employers are usually larger)
  - region     Scotland > London > other UK hubs > elsewhere

Output: ranked CSV (all organisations) with tier 1-5 and a score.

Usage:
  python3 rank_sponsors.py --register register.csv --ch-dir ./ch --out ranked.csv
"""
from __future__ import annotations

import argparse
import csv
import glob
import io
import math
import os
import re
import sys
import zipfile
from collections import defaultdict

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "sponsors"))
from sponsor_check import normalise_name, rating_of, is_worker_a_rated, clean  # noqa: E402

LARGE = {"GROUP"}
FULL = {"FULL"}   # full accounts: medium or large, not micro/small
MEDIUM = {"MEDIUM", "AUDIT EXEMPTION SUBSIDIARY", "FILING EXEMPTION SUBSIDIARY", "AUDITED ABRIDGED"}
SMALL = {"SMALL", "TOTAL EXEMPTION FULL", "TOTAL EXEMPTION SMALL", "UNAUDITED ABRIDGED", "PARTIAL EXEMPTION"}
MICRO = {"MICRO ENTITY"}
INACTIVE = {"DORMANT", "NO ACCOUNTS FILED", "ACCOUNTS TYPE NOT AVAILABLE"}

SIZE_SCORE = {"large": 4, "public": 4, "medium-large": 3.5, "medium": 3, "small": 1.5, "new/unknown": 1, "micro": 0, "inactive": -2,
              "not found": 0.5}

PUBLIC_RE = re.compile(r"\b(nhs|university|universities|council|college|police|fire and rescue|"
                       r"government|ministry|authority|health board|foundation trust|hospital trust)\b", re.I)


def sector_of(sics: list[str]) -> tuple[str, float]:
    """Return (sector label, score) from 5-digit SIC codes. Highest-scoring code wins."""
    best = ("other", 1.0)
    for s in sics:
        c = s[:5]
        if not c.isdigit():
            continue
        n2, n3 = c[:2], c[:3]
        if c in ("64209", "64205", "64203", "64204", "70100"):
            cand = ("holding company / head office", 1.5)   # sector unknown: don't count as finance
        elif n2 in ("62", "63") or n3 == "582":
            cand = ("software / IT / data", 4.0)
        elif n2 in ("64", "65", "66"):
            cand = ("finance / insurance", 4.0)
        elif c in ("70221", "70229", "73200", "69201", "69202", "69203"):
            cand = ("consulting / research / accounting", 3.5)
        elif n2 == "72" or n2 == "21" or c.startswith("86101"):
            cand = ("R&D / pharma / hospitals", 3.5)
        elif c == "85421" or n2 == "84":
            cand = ("university / public sector", 3.5)
        elif n2 in ("61", "26", "35", "71", "58", "59", "60") or c == "47910":
            cand = ("telecom / tech / energy / engineering / media / online retail", 3.0)
        elif n2 in ("49", "50", "51", "52", "53", "46", "10", "11", "20", "29", "30", "32"):
            cand = ("logistics / manufacturing / wholesale", 2.0)
        elif n2 == "86":
            cand = ("primary care / health services", 1.0)
        elif n2 in ("87", "88", "55", "56", "96", "41", "42", "43", "45", "81", "97", "01"):
            cand = ("care / hospitality / construction / personal services", -1.0)
        elif c == "99999":
            cand = ("dormant", -2.0)
        else:
            cand = ("other", 1.0)
        if cand[1] > best[1]:
            best = cand
    return best


NAME_SECTORS = [
    (re.compile(r"\b(care|nursing|residential|domiciliary|homecare|home care|takeaway|restaurant|cafe|hotel|salon|"
                r"builders?|construction|roofing|cleaning|catering)\b", re.I),
     ("care / hospitality / construction / personal services", -1.0)),
    (re.compile(r"\b(bank|banking|capital|insurance|assurance|investments?|asset management|securities|payments?|"
                r"financial|fintech|reinsurance)\b", re.I), ("finance / insurance", 4.0)),
    (re.compile(r"\b(software|technolog\w*|digital|analytics|data|cloud|cyber|computing|ai|systems)\b", re.I),
     ("software / IT / data", 4.0)),
    (re.compile(r"\b(consult\w*|advisory|accountants?|chartered|audit|deloitte|kpmg|pricewaterhouse|ernst|"
                r"mckinsey|accenture|partners llp|llp)\b", re.I), ("consulting / research / accounting", 3.5)),
    (re.compile(r"\b(pharma\w*|therapeutics|biotech\w*|biosciences?|diagnostics|clinical research|laboratories)\b", re.I),
     ("R&D / pharma / hospitals", 3.5)),
]


def name_sector(names) -> tuple[str, float] | None:
    text = " ".join(names)
    for rx, sec in NAME_SECTORS:   # first match wins; care/hospitality checked first on purpose
        if rx.search(text):
            return sec
    return None


def region_score(towns: list[str]) -> tuple[str, float]:
    t = " ".join(towns).lower()
    if re.search(r"glasgow|edinburgh", t):
        return "Glasgow/Edinburgh", 2.0
    if re.search(r"aberdeen|dundee|stirling|livingston|paisley|inverness|falkirk|perth|fife|lanark|lothian|cumbernauld|east kilbride", t):
        return "Scotland (other)", 1.5
    if "london" in t:
        return "London", 1.2
    if re.search(r"manchester|leeds|bristol|cambridge|oxford|birmingham|reading|belfast|cardiff|newcastle|nottingham|sheffield|liverpool|milton keynes|slough|guildford", t):
        return "UK hub", 0.8
    return "Other UK", 0.0


def base_name(name: str) -> str:
    """Strip 'T/A ...' trading names so 'X LTD T/A Y' matches company 'X LTD'."""
    return re.split(r"\b(?:t/a|t\.a\.|trading as)\b", name, flags=re.I)[0].strip(" -,")


def load_register(path: str) -> dict:
    """normalised base name -> {'names': set, 'towns': set, 'entries': int}"""
    orgs: dict = defaultdict(lambda: {"names": set(), "towns": set(), "entries": 0})
    with open(path, encoding="utf-8-sig", newline="") as f:
        for r in csv.DictReader(f):
            r = {k: clean(v) for k, v in r.items()}
            if r["Route"] != "Skilled Worker" or not is_worker_a_rated(r):
                continue
            k = normalise_name(base_name(r["Organisation Name"])) or normalise_name(r["Organisation Name"])
            o = orgs[k]
            o["names"].add(r["Organisation Name"])
            o["towns"].add(r["Town/City"])
            o["entries"] += 1
    return orgs


def load_companies(ch_dir: str, wanted: set) -> dict:
    """normalised company name -> list of candidate dicts (only names present in the register)."""
    out: dict = defaultdict(list)
    files = sorted(glob.glob(os.path.join(ch_dir, "*.zip")))
    if not files:
        raise SystemExit(f"No Companies House zip files in {ch_dir}")
    for zp in files:
        with zipfile.ZipFile(zp) as z:
            for member in z.namelist():
                with z.open(member) as fh:
                    rd = csv.reader(io.TextIOWrapper(fh, encoding="utf-8", errors="replace"))
                    header = [h.strip() for h in next(rd)]
                    ix = {h: i for i, h in enumerate(header)}
                    for row in rd:
                        if len(row) < len(header):
                            continue
                        names = [row[ix["CompanyName"]]] + [row[ix[f"PreviousName_{i}.CompanyName"]] for i in range(1, 3)]
                        for j, nm in enumerate(names):
                            k = normalise_name(nm) if nm else ""
                            if k and k in wanted:
                                out[k].append({
                                    "number": row[ix["CompanyNumber"]],
                                    "name": row[ix["CompanyName"]],
                                    "status": row[ix["CompanyStatus"]],
                                    "category": row[ix["CompanyCategory"]],
                                    "accounts": row[ix["Accounts.AccountCategory"]].upper(),
                                    "post_town": row[ix["RegAddress.PostTown"]],
                                    "postcode": row[ix["RegAddress.PostCode"]],
                                    "incorporated": row[ix["IncorporationDate"]],
                                    "sics": [row[ix[f"SICCode.SicText_{i}"]] for i in range(1, 5) if row[ix[f"SICCode.SicText_{i}"]]],
                                    "previous_name_match": j > 0,
                                })
    return out


def pick(cands: list, towns: set) -> dict | None:
    if not cands:
        return None
    tl = {t.lower() for t in towns}

    def key(c):
        active = c["status"].lower() == "active"
        town = c["post_town"].lower() in tl
        size = {**{a: 3 for a in LARGE | FULL}, **{a: 2 for a in MEDIUM}, **{a: 1 for a in SMALL}}.get(c["accounts"], 0)
        return (active, not c["previous_name_match"], town, size)
    return sorted(cands, key=key, reverse=True)[0]


def size_band(c: dict | None, names: set) -> str:
    if c is None:
        return "public" if any(PUBLIC_RE.search(n) for n in names) else "not found"
    if c["status"].lower() not in ("active", "active - proposal to strike off"):
        return "inactive"
    a = c["accounts"]
    if a in LARGE:
        return "large"
    if a in FULL:
        return "medium-large"
    if a in MEDIUM:
        return "medium"
    if a in SMALL:
        return "small"
    if a in MICRO:
        return "micro"
    if a in INACTIVE:
        return "inactive" if a == "DORMANT" else "new/unknown"
    return "new/unknown"


def tier_of(size: str, sector_score: float) -> int:
    big = size in ("large", "public", "medium-large")
    relevant = sector_score >= 3.0
    if big and relevant:
        return 1
    if big or (size == "medium" and relevant):
        return 2
    if size == "medium" or (size in ("small", "new/unknown", "not found") and relevant):
        return 3
    if size in ("small", "new/unknown", "not found"):
        return 4
    return 5


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--register", required=True)
    ap.add_argument("--ch-dir", required=True)
    ap.add_argument("--out", required=True)
    a = ap.parse_args()

    orgs = load_register(a.register)
    comps = load_companies(a.ch_dir, set(orgs))
    rows = []
    for k, o in orgs.items():
        c = pick(comps.get(k, []), o["towns"])
        size = size_band(c, o["names"])
        sector, sec_score = sector_of(c["sics"] if c else [])
        if c is None and size == "public":
            sector, sec_score = "university / public sector", 3.5
        else:
            ns = name_sector(o["names"])
            # Name overrides when SIC says nothing useful (LLPs have no SIC; holding companies),
            # and care/hospitality names always override (e.g. care-home groups filed as finance holdings).
            if ns and (sec_score <= 1.5 or ns[1] < 0):
                sector, sec_score = ns
        plc = any(re.search(r"\bplc\b", n, re.I) for n in o["names"])
        region, reg_score = region_score(sorted(o["towns"]))
        score = (SIZE_SCORE[size] * 10 + sec_score * 4 + reg_score * 3 + math.log2(o["entries"] + 1) * 2
                 + (4 if plc and size in ("large", "medium-large") else 0))
        rows.append({
            "tier": max(1, tier_of(size, sec_score) - (1 if plc and size == "large" else 0)),
            "score": round(score, 1),
            "organisation": sorted(o["names"], key=len)[0],
            "normalised_name": k,
            "towns": "; ".join(sorted(o["towns"]))[:200],
            "register_entries": o["entries"],
            "region": region,
            "size_band": size,
            "accounts_category": c["accounts"] if c else "",
            "sector": sector,
            "sic_codes": "; ".join(c["sics"]) if c else "",
            "company_number": c["number"] if c else "",
            "companies_house_name": c["name"] if c else "",
            "company_status": c["status"] if c else "",
        })
    rows.sort(key=lambda r: (r["tier"], -r["score"]))
    for i, r in enumerate(rows, 1):
        r["rank"] = i
    cols = ["rank", "tier", "score", "organisation", "normalised_name", "towns", "register_entries", "region",
            "size_band", "accounts_category", "sector", "sic_codes", "company_number", "companies_house_name",
            "company_status"]
    with open(a.out, "w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=cols)
        w.writeheader()
        w.writerows(rows)
    from collections import Counter
    print("organisations:", len(rows))
    print("tiers:", sorted(Counter(r["tier"] for r in rows).items()))
    print("size bands:", Counter(r["size_band"] for r in rows).most_common())
    return 0


if __name__ == "__main__":
    sys.exit(main())
