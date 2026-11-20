#!/usr/bin/env python3
"""Fetch full job-description text for each row of the Jobs tab (CSV in), no LLM needed.
Greenhouse/Lever/Ashby via their public APIs; LinkedIn via the public guest page; other sites via plain HTML.
Usage: python3 fetch_jd.py jobs.csv outdir   -> outdir/<id>.txt + outdir/index.csv (id,status,words)"""
import csv, hashlib, html, json, os, re, sys, urllib.request

UA = {"User-Agent": "Mozilla/5.0 (job-search-jd-reader)"}
def get(url, t=25):
    with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=t) as r:
        return r.read().decode("utf-8", "replace")
def clean(s):
    s = re.sub(r"(?is)<(script|style|noscript).*?</\1>", " ", s)
    s = re.sub(r"(?i)<br\s*/?>|</p>|</li>|</h\d>", "\n", s)
    s = html.unescape(re.sub(r"<[^>]+>", " ", s))
    return re.sub(r"[ \t]+", " ", re.sub(r"\n\s*\n+", "\n", s)).strip()

def jd(url):
    m = re.search(r"greenhouse\.io/(?:embed/job_app\?for=)?([\w-]+)/jobs/(\d+)", url) or re.search(r"gh_jid=(\d+)", url)
    if "greenhouse" in url and m and len(m.groups()) == 2:
        d = json.loads(get(f"https://boards-api.greenhouse.io/v1/boards/{m.group(1)}/jobs/{m.group(2)}"))
        return clean(d.get("content", "")), d.get("title", "")
    m = re.search(r"jobs\.ashbyhq\.com/([^/]+)/([0-9a-f-]{36})", url)
    if m:
        d = json.loads(get(f"https://api.ashbyhq.com/posting-api/job-board/{m.group(1)}?includeCompensation=true"))
        for j in d.get("jobs", []):
            if j.get("id") == m.group(2) or m.group(2) in j.get("jobUrl", ""):
                comp = (j.get("compensation") or {}).get("compensationTierSummary") or ""
                return (j.get("descriptionPlain") or clean(j.get("descriptionHtml", ""))) + (f"\nCompensation: {comp}" if comp else ""), j.get("title", "")
        return "", ""
    m = re.search(r"jobs\.lever\.co/([^/]+)/([0-9a-f-]{36})", url)
    if m:
        d = json.loads(get(f"https://api.lever.co/v0/postings/{m.group(1)}/{m.group(2)}"))
        lists = "\n".join(l.get("text", "") + "\n" + clean(l.get("content", "")) for l in d.get("lists", []))
        return d.get("descriptionPlain", "") + "\n" + lists + "\n" + d.get("additionalPlain", ""), d.get("text", "")
    m = re.search(r"reed\.co\.uk/jobs/(?:[^/]+/)?(\d+)", url)
    if m:
        import base64
        req = urllib.request.Request(f"https://www.reed.co.uk/api/1.0/jobs/{m.group(1)}", headers={**UA, "Authorization": "Basic " + base64.b64encode((os.environ.get("REED_API_KEY", "") + ":").encode()).decode()})
        with urllib.request.urlopen(req, timeout=25) as r:
            d = json.loads(r.read().decode("utf-8", "replace"))
        sal = f"\nSalary: {d.get('minimumSalary')}–{d.get('maximumSalary')}" if d.get('maximumSalary') else ""
        return clean(d.get("jobDescription", "")) + sal + f"\nEmployer: {d.get('employerName','')}", d.get("jobTitle", "")
    page = get(url)
    m = re.search(r'(?is)<div[^>]+class="[^"]*(show-more-less-html__markup|description__text)[^"]*"[^>]*>(.*?)</div>\s*</(section|div)>', page)
    if "linkedin.com" in url and m:
        return clean(m.group(2)), ""
    return clean(page)[:20000], ""

def main():
    rows = list(csv.DictReader(open(sys.argv[1], encoding="utf-8")))
    out = sys.argv[2]; os.makedirs(out, exist_ok=True)
    idx = []
    for r in rows:
        link = r.get("link", "")
        jid = hashlib.md5(link.encode()).hexdigest()[:10]
        try:
            text, _ = jd(link)
            status = "ok" if len(text.split()) >= 120 else "too short"
        except Exception as e:
            text, status = "", f"error: {type(e).__name__}"
        if text:
            open(f"{out}/{jid}.txt", "w").write(f"TITLE: {r.get('title')}\nEMPLOYER: {r.get('employer')}\nLOCATION: {r.get('location')}\nLINK: {link}\n\n{text}")
        idx.append({"id": jid, "title": r.get("title"), "employer": r.get("employer"), "fit_label": r.get("fit"), "link": link, "status": status, "words": len(text.split())})
    with open(f"{out}/index.csv", "w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(idx[0].keys())); w.writeheader(); w.writerows(idx)
    from collections import Counter; print(Counter(i["status"] for i in idx))
if __name__ == "__main__":
    main()
