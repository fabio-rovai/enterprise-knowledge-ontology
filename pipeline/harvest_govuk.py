#!/usr/bin/env python3
"""Harvest a defined slice of the GOV.UK corpus via the public Search API.

GOV.UK is used here as a proxy for an enterprise knowledge estate. It is the
largest publicly measurable managed content estate in the UK, it is run by
people who take content lifecycle seriously, and — critically — it publishes
the metadata that an audit needs: when content was last changed, which
organisation owns it, whether that organisation still exists, and whether the
content has been withdrawn.

Everything here uses documented public endpoints under the Open Government
Licence. No authentication, no scraping of rendered HTML, no circumvention.

Usage:
    python3 harvest_govuk.py --counts                 # corpus sizing only
    python3 harvest_govuk.py --slice guidance --out data/raw/guidance.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import sys
import time
import urllib.parse
import urllib.request
from typing import Any, Iterator

SEARCH = "https://www.gov.uk/api/search.json"
UA = "eko-corpus-audit/0.1 (research; https://gov.tesseract.academy; contact fabio@thetesseractacademy.com)"

# Fields the Search API will return. Verified working 2026-08-16.
FIELDS = [
    "title",
    "link",
    "description",
    "public_timestamp",
    "updated_at",
    "content_store_document_type",
    "organisations",
    "is_withdrawn",
    "content_id",
    "format",
    "government_name",
    "part_of_taxonomy_tree",
    "indexable_content",
]

# Document types that make up the guidance family: content whose whole purpose
# is to be an authoritative answer someone acts on. These are the GOV.UK
# document types most analogous to an enterprise knowledge corpus, as opposed
# to news, transcripts, statistics releases or case-by-case decisions.
GUIDANCE_TYPES = [
    "guidance",
    "detailed_guide",
    "statutory_guidance",
    "regulation",
    "notice",
    "manual",
    "manual_section",
    "form",
    "international_treaty",
    "guide",
]

PAUSE = 0.25  # seconds between requests


def _get(params: dict[str, Any], retries: int = 4) -> dict:
    url = SEARCH + "?" + urllib.parse.urlencode(params, doseq=True)
    last = None
    for attempt in range(retries):
        req = urllib.request.Request(url, headers={"User-Agent": UA})
        try:
            with urllib.request.urlopen(req, timeout=60) as resp:
                return json.loads(resp.read().decode("utf-8"))
        except Exception as exc:  # noqa: BLE001 - network layer, report and retry
            last = exc
            time.sleep(2 ** attempt)
    raise RuntimeError(f"GET failed after {retries} attempts: {url}\n{last}")


def corpus_counts() -> dict:
    """Report real corpus sizes so the study's denominator is never guessed."""
    out: dict[str, Any] = {}
    total = _get({"count": 0})
    out["govuk_total_documents"] = total["total"]

    agg = _get({"count": 0, "aggregate_content_store_document_type": 200})
    opts = agg["aggregates"]["content_store_document_type"]["options"]
    out["document_types_total"] = agg["aggregates"]["content_store_document_type"].get("total")
    out["document_type_counts"] = {
        o["value"]["slug"]: o["documents"] for o in opts
    }

    sup = _get({"count": 0, "aggregate_content_purpose_supergroup": 30})
    out["content_purpose_supergroup"] = {
        o["value"].get("slug"): o["documents"]
        for o in sup["aggregates"]["content_purpose_supergroup"]["options"]
    }

    guidance_family = {
        t: out["document_type_counts"].get(t, 0) for t in GUIDANCE_TYPES
    }
    out["guidance_family_counts"] = guidance_family
    out["guidance_family_total"] = sum(guidance_family.values())
    return out


def harvest_type(doc_type: str, page_size: int = 100, cap: int | None = None) -> Iterator[dict]:
    """Page through every document of one type.

    The Search API is paged with start/count. Deep offsets are permitted
    (verified working past start=9900), but each document type is harvested
    separately anyway so that no single scan needs an unbounded offset.
    """
    start = 0
    seen = 0
    while True:
        page = _get(
            {
                "count": page_size,
                "start": start,
                "filter_content_store_document_type": doc_type,
                "fields": FIELDS,
            }
        )
        results = page.get("results", [])
        if not results:
            return
        for r in results:
            r["_harvest_document_type"] = doc_type
            yield r
            seen += 1
            if cap and seen >= cap:
                return
        total = page.get("total", 0)
        start += page_size
        if start >= total:
            return
        time.sleep(PAUSE)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--counts", action="store_true", help="write corpus sizing only")
    ap.add_argument("--types", nargs="*", default=GUIDANCE_TYPES)
    ap.add_argument("--cap-per-type", type=int, default=None)
    ap.add_argument("--out", default="data/raw/govuk_guidance.jsonl")
    ap.add_argument("--counts-out", default="data/raw/corpus_counts.json")
    args = ap.parse_args()

    os.makedirs(os.path.dirname(args.counts_out) or ".", exist_ok=True)

    counts = corpus_counts()
    with open(args.counts_out, "w") as fh:
        json.dump(counts, fh, indent=2)
    print(f"GOV.UK total documents: {counts['govuk_total_documents']:,}")
    print(f"Guidance family total:  {counts['guidance_family_total']:,}")
    for t, n in sorted(counts["guidance_family_counts"].items(), key=lambda kv: -kv[1]):
        print(f"  {n:>8,}  {t}")
    if args.counts:
        return 0

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    written = 0
    with open(args.out, "w") as fh:
        for doc_type in args.types:
            n = counts["guidance_family_counts"].get(doc_type, 0)
            if not n:
                print(f"skip {doc_type}: 0 documents", file=sys.stderr)
                continue
            print(f"harvesting {doc_type} ({n:,})...", file=sys.stderr, flush=True)
            got = 0
            for rec in harvest_type(doc_type, cap=args.cap_per_type):
                fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
                written += 1
                got += 1
                if got % 1000 == 0:
                    print(f"  {doc_type}: {got:,}", file=sys.stderr, flush=True)
            print(f"  {doc_type}: {got:,} done", file=sys.stderr, flush=True)
    print(f"wrote {written:,} records to {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
