#!/usr/bin/env python3
"""live_check.py - is a job advert still live?  No AI tokens: plain HTTP.

Usage: python3 live_check.py in.csv out.csv   (in.csv needs a "link" column; other columns pass through)

closed  = the site says so clearly (API 404, "no longer accepting", expired page, 404/410, validThrough passed).
unknown = the site blocks checks or the request fails. Unknown jobs are KEPT, never deleted.
"""
import csv, re, sys, json, time, threading, urllib.request, urllib.error
from concurrent.futures import ThreadPoolExecutor

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/126.0 Safari/537.36",
      "Accept-Language": "en-GB,en;q=0.9"}
BLOCKED = ("simplyhired.", "totaljobs.", "janestreet.com")   # sites that refuse automated checks
DEAD_TEXT = re.compile(
    r"no longer accepting applications|this job (?:is|has) (?:now )?(?:closed|expired)|"
    r"job (?:has )?expired|no longer available|position has been filled|"
    r"vacancy (?:is|has) (?:now )?closed|this (?:job|vacancy|role) is no longer|"
    r"job not found|posting (?:is )?closed|applications (?:are|have) (?:now )?closed|"
    r"the job you are looking for (?:is|has)|this advert has (?:closed|expired)", re.I)

_locks = {}


def _host_lock(url):
    """One request at a time to LinkedIn, four at a time to everything else."""
    h = re.sub(r"^https?://([^/]+).*", r"\1", url)
    return _locks.setdefault(h, threading.Semaphore(1 if "linkedin" in h else 4))


def _get1(url, timeout, limit):
    req = urllib.request.Request(url, headers=UA)
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.status, r.geturl(), r.read(limit).decode("utf-8", "ignore")
    except urllib.error.HTTPError as e:
        return e.code, url, ""
    except Exception as e:  # noqa: BLE001 - network hiccup
        return None, url, str(e)


def get(url, timeout=25, limit=8_000_000):
    with _host_lock(url):
        for attempt in range(4):
            st, final, body = _get1(url, timeout, limit)
            if st in (429, 403, 500, 502, 503, 504) or st is None:
                time.sleep(3 * (attempt + 1) + (2 if "linkedin" in url else 0))
                continue
            if "linkedin" in url:
                time.sleep(1.5)
            return st, final, body
        return st, final, body


def check(link):
    l = (link or "").strip()
    if not l.startswith("http"):
        return "unknown", "no link"
    if any(b in l for b in BLOCKED):
        return "unknown", "site blocks automated checks"
    m = re.search(r"greenhouse\.io/([^/]+)/jobs/(\d+)", l)
    if m:
        st, _, _ = get(f"https://boards-api.greenhouse.io/v1/boards/{m.group(1)}/jobs/{m.group(2)}")
        if st == 200: return "live", "greenhouse api"
        if st == 404: return "closed", "greenhouse api 404"
        return "unknown", f"greenhouse api {st}"
    m = re.search(r"jobs\.ashbyhq\.com/([^/?#]+)/([0-9a-f-]{36})", l)
    if m:
        st, _, body = get(f"https://api.ashbyhq.com/posting-api/job-board/{m.group(1)}")
        if st == 200:
            try:
                ids = {j.get("id") for j in json.loads(body).get("jobs", [])}
                return ("live", "ashby api") if m.group(2) in ids else ("closed", "not on ashby board")
            except Exception:  # noqa: BLE001
                return "unknown", "ashby api parse"
        return "unknown", f"ashby api {st}"
    m = re.search(r"jobs\.lever\.co/([^/]+)/([0-9a-f-]{36})", l)
    if m:
        st, _, _ = get(f"https://api.lever.co/v0/postings/{m.group(1)}/{m.group(2)}")
        if st == 200: return "live", "lever api"
        if st == 404: return "closed", "lever api 404"
        return "unknown", f"lever api {st}"
    m = re.search(r"linkedin\.com/jobs/view/(?:[^/]*-)?(\d{6,})", l)
    if m:
        st, _, body = get(f"https://www.linkedin.com/jobs-guest/jobs/api/jobPosting/{m.group(1)}")
        if st in (404, 410): return "closed", f"linkedin {st}"
        if st == 200:
            if re.search(r"No longer accepting applications", body, re.I):
                return "closed", "linkedin: no longer accepting"
            return "live", "linkedin guest page"
        return "unknown", f"linkedin {st}"
    m = re.search(r"reed\.co\.uk/jobs/(?:[^/?#]+/)?(\d{6,})", l)
    if m:
        l = f"https://www.reed.co.uk/jobs/job/{m.group(1)}"   # bare /jobs/<id> always 404s on Reed
    st, final, body = get(l)
    if st in (404, 410): return "closed", f"http {st}"
    if st is None: return "unknown", f"request failed: {body[:60]}"
    if st != 200: return "unknown", f"http {st}"
    if "adzuna" in l and "/details/" in l and "/details/" not in final:
        return "closed", "adzuna redirected away from advert"
    vt = re.search(r'"@type"\s*:\s*"JobPosting".{0,20000}?"validThrough"\s*:\s*"(\d{4}-\d{2}-\d{2})', body, re.S)
    if vt and vt.group(1) < time.strftime("%Y-%m-%d"):
        return "closed", f"advert validThrough {vt.group(1)} has passed"
    d = DEAD_TEXT.search(body[:300_000])
    if d:
        return "closed", "page says closed: " + d.group(0)[:50]
    return "live", "page loads"


def main(inp, out):
    rows = list(csv.DictReader(open(inp, encoding="utf-8")))
    with ThreadPoolExecutor(8) as ex:
        res = list(ex.map(lambda r: check(r.get("link", "")), rows))
    fields = (list(rows[0].keys()) if rows else ["link"]) + ["live_status", "live_reason"]
    with open(out, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=fields)
        w.writeheader()
        for r, (s, why) in zip(rows, res):
            r["live_status"], r["live_reason"] = s, why
            w.writerow(r)
    from collections import Counter
    print(dict(Counter(s for s, _ in res)))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
