#!/usr/bin/env python3
"""Daily check of the UK Home Office "Register of licensed sponsors: workers".

Run from anywhere (paths are relative to the project root, the folder holding CLAUDE.md):

    python3 sponsors/sponsor_check.py                  # normal daily run
    python3 sponsors/sponsor_check.py --file X.csv     # use a local CSV (testing / manual download)

Steps
1. Find today's CSV link through the GOV.UK Content API (never hard-coded).
2. Download and validate it: exact header, complete body, minimum rows, and no
   sudden >5% drop in Skilled Worker rows versus the previous snapshot.
   A bad file is rejected and the last good snapshot is kept.
3. Save sponsors/snapshots/register-YYYY-MM-DD.csv and sponsors/register-latest.csv.
4. Build sponsors/skilled-worker-a-rated.csv (Skilled Worker route, A-rated) with a
   normalised-name column for matching job adverts.
5. Diff against the previous snapshot (Skilled Worker rows only):
     sponsors/diffs/diff-YYYY-MM-DD.csv   and a summary block in sponsors/changes.md
6. Check every active employer in tracker.csv against today's A-rated list and alert
   if it is no longer there.
7. Write sponsors/last-run.json (read by the daily summary).

Standard library only. Exit 0 = success, 1 = failed (reason in last-run.json and changes.md).
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import io
import json
import os
import re
import shutil
import sys
import unicodedata
import urllib.request
from pathlib import Path
from urllib.parse import urljoin, urlparse

CONTENT_API = (
    "https://www.gov.uk/api/content/government/publications/"
    "register-of-licensed-sponsors-workers"
)
ASSET_HOST = "assets.publishing.service.gov.uk"
EXPECTED_HEADER = ["Organisation Name", "Town/City", "County", "Type & Rating", "Route"]
MIN_ROWS = 50_000           # the full register is far larger; much smaller means partial
MIN_SKILLED_ROWS = 30_000
MAX_SKILLED_DROP = 0.05     # reject if Skilled Worker rows fall >5% vs previous snapshot
KEEP_SNAPSHOTS = 14
ACTIVE_STATUSES = {"found", "ready-to-review", "applied", "interview", "offer"}

ROOT = Path(__file__).resolve().parent.parent
SPONSORS = ROOT / "sponsors"
SNAPSHOTS = SPONSORS / "snapshots"
ARCHIVE = SNAPSHOTS / "archive"
DIFFS = SPONSORS / "diffs"
CHANGES_MD = SPONSORS / "changes.md"
LAST_RUN = SPONSORS / "last-run.json"
A_RATED = SPONSORS / "skilled-worker-a-rated.csv"
TRACKER = ROOT / "tracker.csv"
CHANGES_HEADER = "# Sponsor register changes\n\nNewest first.\n"

# Kept deliberately short (same list as CLAUDE.md section 7) to avoid false matches.
_SUFFIXES = {"ltd", "limited", "plc", "llp", "uk", "group", "holdings", "the"}


# --------------------------------------------------------------------------- helpers

def clean(v: str | None) -> str:
    return re.sub(r"\s+", " ", (v or "")).strip()


def normalise_name(name: str) -> str:
    """Matching key for adverts vs register: ASCII-fold, lowercase, drop punctuation,
    bracketed text and common legal suffix words."""
    s = unicodedata.normalize("NFKD", name).encode("ascii", "ignore").decode()
    s = s.lower().replace("&", " and ")
    s = re.sub(r"\(.*?\)", " ", s)
    s = re.sub(r"[^a-z0-9 ]+", " ", s)
    return " ".join(w for w in s.split() if w not in _SUFFIXES)


def diff_name(name: str) -> str:
    """Stricter key for diffing (keeps 'Acme Holdings' and 'Acme Group' apart)."""
    return clean(name).casefold()


def rating_of(type_and_rating: str) -> str:
    """'Worker (A rating)' -> 'A rating'; 'Worker (UK Expansion Worker: Provisional )' -> 'UK Expansion Worker: Provisional'."""
    m = re.search(r"\((.*)\)", type_and_rating)
    return clean(m.group(1)) if m else clean(type_and_rating)


def is_a_rating(rating: str) -> bool:
    """True for 'A rating', 'A (SME+)', 'A (Premium)' etc. Takes a rating from rating_of()."""
    return bool(re.match(r"A\b", clean(rating), re.I))


def is_worker_a_rated(row: dict) -> bool:
    t = row["Type & Rating"]
    return t.lower().startswith("worker") and is_a_rating(rating_of(t))


def today() -> str:
    return dt.date.today().isoformat()


def atomic_write_bytes(path: Path, data: bytes) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_bytes(data)
    os.replace(tmp, path)


def atomic_write_text(path: Path, text: str) -> None:
    atomic_write_bytes(path, text.encode("utf-8"))


def http_get(url: str, timeout: int = 180) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": "job-search-sponsor-check/1.1"})
    with urllib.request.urlopen(req, timeout=timeout) as r:  # honours HTTPS_PROXY
        body = r.read()
        expected = r.headers.get("Content-Length")
    if expected and expected.isdigit() and len(body) != int(expected):
        raise RuntimeError(f"Incomplete download: got {len(body)} of {expected} bytes")
    return body


# --------------------------------------------------------------------------- download + parse

def find_csv_url() -> tuple[str, dict]:
    data = json.loads(http_get(CONTENT_API, timeout=60))
    atts = data.get("details", {}).get("attachments", []) or []
    csvs = [a for a in atts
            if a.get("content_type") == "text/csv"
            or urlparse(a.get("url", "")).path.lower().endswith(".csv")]
    if not csvs:
        raise RuntimeError("No CSV attachment found on the GOV.UK publication")
    worker = [a for a in csvs if "worker" in (a.get("title", "") + a.get("url", "")).lower()]
    if len(worker) > 1:
        raise RuntimeError(f"{len(worker)} candidate worker CSVs found; refusing to guess: "
                           + ", ".join(a.get("url", "") for a in worker))
    pick = (worker or csvs)[0]
    url = urljoin("https://www.gov.uk", pick["url"])
    if urlparse(url).hostname != ASSET_HOST:
        raise RuntimeError(f"Unexpected CSV host in {url}")
    meta = {"title": pick.get("title", ""), "public_updated_at": data.get("public_updated_at")}
    return url, meta


def decode(raw: bytes) -> tuple[str, str]:
    try:
        return raw.decode("utf-8-sig"), "utf-8"
    except UnicodeDecodeError:
        return raw.decode("cp1252"), "cp1252"


def parse_register(raw: bytes, strict: bool = True) -> tuple[list[dict], str]:
    text, enc = decode(raw)
    if strict and not text.endswith("\n"):
        raise RuntimeError("File does not end with a newline; download looks truncated")
    reader = csv.reader(io.StringIO(text))
    header = [clean(h) for h in next(reader, [])]
    if header != EXPECTED_HEADER:
        raise RuntimeError(f"Unexpected header {header!r}; expected {EXPECTED_HEADER!r}")
    rows = []
    for r in reader:
        if not any(c.strip() for c in r):
            continue
        r = (r + [""] * 5)[:5]
        rows.append(dict(zip(EXPECTED_HEADER, (clean(c) for c in r))))
    if strict:
        if len(rows) < MIN_ROWS:
            raise RuntimeError(f"Only {len(rows)} rows (minimum {MIN_ROWS}); file looks partial")
        sw = skilled_count(rows)
        if sw < MIN_SKILLED_ROWS:
            raise RuntimeError(f"Only {sw} Skilled Worker rows (minimum {MIN_SKILLED_ROWS})")
    return rows, enc


def skilled_count(rows: list[dict]) -> int:
    return sum(1 for r in rows if r["Route"] == "Skilled Worker")


# --------------------------------------------------------------------------- diff

def skilled_index(rows: list[dict]) -> dict:
    """(diff_name, town) -> {'row': first row, 'ratings': set of ratings}. Handles several rows per org/town."""
    idx: dict = {}
    for r in rows:
        if r["Route"] != "Skilled Worker":
            continue
        k = (diff_name(r["Organisation Name"]), r["Town/City"].casefold())
        e = idx.setdefault(k, {"row": r, "ratings": set()})
        e["ratings"].add(rating_of(r["Type & Rating"]))
    return idx


def _ratings(e: dict) -> str:
    return "; ".join(sorted(e["ratings"]))


def diff(old_rows: list[dict], new_rows: list[dict]) -> list[dict]:
    old, new = skilled_index(old_rows), skilled_index(new_rows)
    out = []
    for k in sorted(new.keys() - old.keys()):
        out.append(_change("added", new[k]["row"], "", _ratings(new[k])))
    for k in sorted(old.keys() - new.keys()):
        out.append(_change("removed", old[k]["row"], _ratings(old[k]), ""))
    for k in sorted(old.keys() & new.keys()):
        o, n = _ratings(old[k]), _ratings(new[k])
        if o != n:
            out.append(_change("rating_changed", new[k]["row"], o, n))
    return out


def _change(kind: str, r: dict, old_rating: str, new_rating: str) -> dict:
    return {
        "change": kind,
        "organisation": r["Organisation Name"],
        "normalised": normalise_name(r["Organisation Name"]),
        "town": r["Town/City"],
        "county": r["County"],
        "old_rating": old_rating,
        "new_rating": new_rating,
    }


# --------------------------------------------------------------------------- outputs

def read_csv_rows(path: Path) -> list[dict]:
    with path.open(encoding="utf-8-sig", newline="") as f:
        return [{k: clean(v) for k, v in r.items()} for r in csv.DictReader(f)]


def previous_snapshot(before: str) -> Path | None:
    """Latest snapshot strictly older than the given file name (e.g. 'register-2026-10-04.csv')."""
    snaps = sorted(p for p in SNAPSHOTS.glob("register-*.csv") if p.name < before)
    return snaps[-1] if snaps else None


def rotate_snapshots() -> None:
    ARCHIVE.mkdir(parents=True, exist_ok=True)
    for p in sorted(SNAPSHOTS.glob("register-*.csv"))[:-KEEP_SNAPSHOTS]:
        target = ARCHIVE / p.name
        if not target.exists():
            shutil.move(str(p), str(target))  # archive, never delete


def write_a_rated(rows: list[dict]) -> tuple[int, set[str]]:
    buf = io.StringIO()
    w = csv.writer(buf)
    w.writerow(["normalised_name", "organisation", "town", "county", "rating"])
    seen, names = set(), set()
    for r in rows:
        if r["Route"] != "Skilled Worker" or not is_worker_a_rated(r):
            continue
        k = (diff_name(r["Organisation Name"]), r["Town/City"].casefold())
        if k in seen:
            continue
        seen.add(k)
        n = normalise_name(r["Organisation Name"])
        names.add(n)
        w.writerow([n, r["Organisation Name"], r["Town/City"], r["County"], rating_of(r["Type & Rating"])])
    atomic_write_text(A_RATED, buf.getvalue())
    return len(seen), names


def tracker_alerts(a_rated_names: set[str]) -> list[str]:
    """Every active tracker employer must still be on today's A-rated Skilled Worker list."""
    if not TRACKER.exists():
        return []
    alerts = []
    for row in read_csv_rows(TRACKER):
        if row.get("status", "").lower() not in ACTIVE_STATUSES:
            continue
        names = {normalise_name(row.get("company", "")), normalise_name(row.get("legal_entity", ""))} - {""}
        if names and not (names & a_rated_names):
            alerts.append(f"{row.get('company')} ({row.get('role')}): not found on today's A-rated "
                          f"Skilled Worker list (removed, downgraded, suspended, or name mismatch - check)")
    return alerts


def prepend_changes_md(date: str, block: str) -> None:
    body = CHANGES_MD.read_text(encoding="utf-8") if CHANGES_MD.exists() else CHANGES_HEADER
    if body.startswith(CHANGES_HEADER):
        body = body[len(CHANGES_HEADER):]
    body = re.sub(rf"(?ms)^## {re.escape(date)}\b.*?(?=^## |\Z)", "", body)  # idempotent re-runs
    atomic_write_text(CHANGES_MD, CHANGES_HEADER + "\n" + block.rstrip() + "\n\n" + body.lstrip("\n"))


def save_last_run(status: dict) -> None:
    atomic_write_text(LAST_RUN, json.dumps(status, indent=2))


def summary_block(date: str, status: dict, changes: list[dict], alerts: list[str], prev: Path | None) -> str:
    counts = {k: status[k] for k in ("added", "removed", "rating_changed")}
    lines = [f"## {date}", ""]
    if alerts:
        lines += ["**⚠ Active applications to check:**", *[f"- {a}" for a in alerts], ""]
    lines += [
        f"- Source: {status['source']}" + (f" (GOV.UK updated {status['public_updated_at']})" if status.get("public_updated_at") else ""),
        f"- Rows: {status['rows']:,} total; {status['a_rated']:,} Skilled Worker A-rated organisation/town entries",
        f"- Compared with: {prev.name if prev else 'nothing (first snapshot)'}",
        f"- Added: {counts['added']} · Removed: {counts['removed']} · Rating changed: {counts['rating_changed']}",
        f"- Full list: `{status['diff_file']}`",
    ]
    for kind, label in (("added", "Added"), ("removed", "Removed"), ("rating_changed", "Rating changed")):
        sel = [c for c in changes if c["change"] == kind]
        if sel:
            lines += ["", f"### {label} ({len(sel)}{', first 40 shown' if len(sel) > 40 else ''})"]
            for c in sel[:40]:
                extra = f" ({c['old_rating']} → {c['new_rating']})" if kind == "rating_changed" else ""
                lines.append(f"- {c['organisation']}, {c['town']}{extra}")
    return "\n".join(lines) + "\n"


# --------------------------------------------------------------------------- main

def run(args) -> dict:
    status: dict = {"date": args.date, "ok": False, "stage": "download"}
    if args.file:
        raw = Path(args.file).read_bytes()
        status["source"] = f"local file {args.file}"
    else:
        url, meta = find_csv_url()
        status.update(source=url, **meta)
        raw = http_get(url)

    status["stage"] = "validate"
    rows, enc = parse_register(raw)
    status["encoding"] = enc
    snap_name = f"register-{args.date}.csv"
    prev = previous_snapshot(before=snap_name)
    prev_rows: list[dict] = []
    if prev:
        prev_rows, _ = parse_register(prev.read_bytes(), strict=False)
        old_sw, new_sw = skilled_count(prev_rows), skilled_count(rows)
        if old_sw and (old_sw - new_sw) / old_sw > MAX_SKILLED_DROP:
            raise RuntimeError(f"Skilled Worker rows fell from {old_sw:,} to {new_sw:,} "
                               f"(>{MAX_SKILLED_DROP:.0%}); treating file as bad")

    status["stage"] = "write"
    snap = SNAPSHOTS / snap_name
    atomic_write_bytes(snap, raw)
    atomic_write_bytes(SPONSORS / "register-latest.csv", raw)
    a_rated, a_names = write_a_rated(rows)

    changes = diff(prev_rows, rows) if prev else []
    diff_path = DIFFS / f"diff-{args.date}.csv"
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=["change", "organisation", "normalised", "town", "county", "old_rating", "new_rating"])
    w.writeheader()
    w.writerows(changes)
    atomic_write_text(diff_path, buf.getvalue())

    alerts = tracker_alerts(a_names)
    rotate_snapshots()
    status.update(
        ok=True, stage="done", rows=len(rows), a_rated=a_rated,
        previous=prev.name if prev else None,
        added=sum(c["change"] == "added" for c in changes),
        removed=sum(c["change"] == "removed" for c in changes),
        rating_changed=sum(c["change"] == "rating_changed" for c in changes),
        alerts=alerts, diff_file=str(diff_path.relative_to(ROOT)).replace("\\", "/"),
    )
    prepend_changes_md(args.date, summary_block(args.date, status, changes, alerts, prev))
    return status


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--file", help="Use a local register CSV instead of downloading")
    ap.add_argument("--date", default=today(), help="Snapshot date YYYY-MM-DD (default today)")
    args = ap.parse_args()
    for d in (SNAPSHOTS, DIFFS):
        d.mkdir(parents=True, exist_ok=True)
    save_last_run({"date": args.date, "ok": False, "stage": "started"})
    try:
        status = run(args)
    except Exception as e:  # noqa: BLE001 - any failure keeps the last good snapshot
        prev = previous_snapshot(before=f"register-{args.date}.csv~")
        status = {"date": args.date, "ok": False, "error": f"{type(e).__name__}: {e}",
                  "last_good_snapshot": prev.name if prev else None}
        save_last_run(status)
        prepend_changes_md(args.date, f"## {args.date}: REGISTER CHECK FAILED\n\n- {status['error']}\n"
                                      f"- Last good snapshot kept: {status['last_good_snapshot'] or 'none'}\n")
        print("REGISTER CHECK FAILED:", status["error"], file=sys.stderr)
        return 1
    save_last_run(status)
    print(json.dumps(status, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
