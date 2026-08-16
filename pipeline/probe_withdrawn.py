#!/usr/bin/env python3
"""Measure the gap between what a publisher's search index serves and what a
crawler-based retrieval pipeline actually ingests.

GOV.UK removes withdrawn content from its search index. That is correct
behaviour and better than most enterprise estates manage. But the withdrawn
pages remain live at their original addresses, remain listed in the public
sitemap, and remain fully served by the Content API, complete with body text.

So the question is not "does the publisher manage withdrawal properly" — it
does. The question is whether a retrieval pipeline built the obvious way, by
crawling the sitemap or the content endpoint rather than consuming the curated
search index, silently ingests content the publisher has formally disowned.

This probe measures that, on a random sample of the publisher's own sitemap.
"""
from __future__ import annotations

import argparse
import json
import random
import re
import sys
import time
import urllib.parse
import urllib.request
from collections import Counter
from datetime import datetime, timezone

UA = "eko-corpus-audit/0.1 (research; https://gov.tesseract.academy; contact fabio@thetesseractacademy.com)"
SITEMAP_INDEX = "https://www.gov.uk/sitemap.xml"
CONTENT_API = "https://www.gov.uk/api/content"
SEARCH = "https://www.gov.uk/api/search.json"

LOC = re.compile(r"<loc>([^<]+)</loc>")


def get(url: str, timeout: int = 60) -> bytes:
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


def sitemap_urls() -> list[str]:
    index = get(SITEMAP_INDEX).decode("utf-8")
    subs = LOC.findall(index)
    print(f"sitemap index lists {len(subs)} sub-sitemaps", file=sys.stderr)
    urls: list[str] = []
    for i, sub in enumerate(subs, 1):
        try:
            body = get(sub).decode("utf-8")
        except Exception as exc:  # noqa: BLE001
            print(f"  {sub}: {exc}", file=sys.stderr)
            continue
        found = LOC.findall(body)
        urls.extend(found)
        print(f"  [{i}/{len(subs)}] {sub.rsplit('/', 1)[-1]}: {len(found):,}", file=sys.stderr)
        time.sleep(0.2)
    return urls


def probe(path: str) -> dict | None:
    try:
        raw = get(CONTENT_API + path, timeout=45)
    except Exception:  # noqa: BLE001
        return None
    try:
        doc = json.loads(raw.decode("utf-8"))
    except json.JSONDecodeError:
        return None
    notice = doc.get("withdrawn_notice") or {}
    details = doc.get("details") or {}
    body = details.get("body")
    if isinstance(body, list):
        body = json.dumps(body)
    body = body or ""
    return {
        "path": path,
        "document_type": doc.get("document_type"),
        "withdrawn": bool(notice),
        "withdrawn_at": notice.get("withdrawn_at"),
        "body_characters": len(body),
        "public_updated_at": doc.get("public_updated_at"),
        "first_published_at": doc.get("first_published_at"),
    }


def in_search_index(path: str) -> bool:
    url = f"{SEARCH}?count=1&filter_link={urllib.parse.quote(path)}"
    try:
        data = json.loads(get(url, timeout=30).decode("utf-8"))
    except Exception:  # noqa: BLE001
        return False
    return bool(data.get("results"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--sample", type=int, default=400)
    ap.add_argument("--seed", type=int, default=20260816)
    ap.add_argument("--out", default="reports/withdrawn_probe.json")
    ap.add_argument("--urls-out", default="data/raw/sitemap_urls.txt")
    args = ap.parse_args()

    urls = sitemap_urls()
    with open(args.urls_out, "w") as fh:
        fh.write("\n".join(urls))
    print(f"\nsitemap advertises {len(urls):,} URLs", file=sys.stderr)

    # What the curated search index claims to hold, for comparison.
    search_total = json.loads(get(f"{SEARCH}?count=0").decode("utf-8"))["total"]
    withdrawn_in_search = json.loads(
        get(f"{SEARCH}?count=0&filter_is_withdrawn=true").decode("utf-8")
    )["total"]

    random.seed(args.seed)
    paths = []
    for u in urls:
        p = u.replace("https://www.gov.uk", "", 1)
        if p.startswith("/") and p not in ("/", ""):
            paths.append(p)
    sample = random.sample(paths, min(args.sample, len(paths)))

    results = []
    errors = 0
    for i, p in enumerate(sample, 1):
        r = probe(p)
        if r is None:
            errors += 1
        else:
            results.append(r)
        if i % 50 == 0:
            wd = sum(1 for x in results if x["withdrawn"])
            print(f"  {i}/{len(sample)}  withdrawn so far: {wd}", file=sys.stderr, flush=True)
        time.sleep(0.12)

    withdrawn = [r for r in results if r["withdrawn"]]
    now = datetime.now(timezone.utc)
    ages = []
    for r in withdrawn:
        if r["withdrawn_at"]:
            try:
                dt = datetime.fromisoformat(r["withdrawn_at"].replace("Z", "+00:00"))
                ages.append((now - dt).days / 365.25)
            except ValueError:
                pass

    served_chars = sum(r["body_characters"] for r in withdrawn)
    out = {
        "scanned_at": now.isoformat(),
        "sitemap_urls_advertised": len(urls),
        "search_index_documents": search_total,
        "withdrawn_documents_returned_by_search_index": withdrawn_in_search,
        "sampled": len(sample),
        "successfully_probed": len(results),
        "fetch_errors": errors,
        "withdrawn_documents_in_sample": len(withdrawn),
        "withdrawn_rate_percent": round(100.0 * len(withdrawn) / max(1, len(results)), 2),
        "withdrawn_still_serving_body_text": sum(
            1 for r in withdrawn if r["body_characters"] > 500
        ),
        "total_body_characters_served_by_withdrawn_pages_in_sample": served_chars,
        "median_years_since_withdrawal": (
            round(sorted(ages)[len(ages) // 2], 2) if ages else None
        ),
        "oldest_withdrawal_years": round(max(ages), 2) if ages else None,
        "withdrawn_by_document_type": dict(
            Counter(r["document_type"] for r in withdrawn).most_common()
        ),
        "examples": sorted(
            withdrawn, key=lambda r: -r["body_characters"]
        )[:20],
    }
    with open(args.out, "w") as fh:
        json.dump(out, fh, indent=2)

    print(f"\nsitemap URLs:                 {len(urls):,}")
    print(f"search index documents:       {search_total:,}")
    print(f"withdrawn per search index:   {withdrawn_in_search:,}")
    print(f"sample probed:                {len(results):,}")
    print(f"withdrawn in sample:          {len(withdrawn)} ({out['withdrawn_rate_percent']}%)")
    print(f"  still serving body text:    {out['withdrawn_still_serving_body_text']}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
