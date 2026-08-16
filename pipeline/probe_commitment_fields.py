#!/usr/bin/env python3
"""Test the central claim of D1 at scale.

The Corpus Readiness Index says a knowledge asset is only authoritative if a
maintenance commitment is attached to it: a named accountable person, a named
maintainer, a declared review cadence, and a date of last verification.

This probe asks whether the metadata to express any of that exists at all in a
mature, well-run, publicly documented content platform. It samples documents
across the guidance family via the GOV.UK Content API and looks for any field,
anywhere in the returned JSON, that could carry a commitment.

A null result here is the finding, and it needs to be measured rather than
asserted.
"""
from __future__ import annotations

import argparse
import json
import random
import sys
import time
import urllib.request
from collections import Counter

CONTENT_API = "https://www.gov.uk/api/content"
UA = "eko-corpus-audit/0.1 (research; https://gov.tesseract.academy; contact fabio@thetesseractacademy.com)"

# Field names that would carry a maintenance commitment if one existed.
COMMITMENT_KEYS = [
    "review", "next_review", "review_date", "review_by", "reviewed_at",
    "last_verified", "verified", "valid_until", "expiry", "expires",
    "expiry_date", "owner", "content_owner", "maintainer", "steward",
    "accountable", "freshness", "cadence", "retention", "supersed",
]


def walk_keys(node, acc):
    if isinstance(node, dict):
        for k, v in node.items():
            acc[k] += 1
            walk_keys(v, acc)
    elif isinstance(node, list):
        for v in node:
            walk_keys(v, acc)


def fetch(base_path: str):
    url = CONTENT_API + base_path
    req = urllib.request.Request(url, headers={"User-Agent": UA})
    with urllib.request.urlopen(req, timeout=45) as resp:
        return json.loads(resp.read().decode("utf-8"))


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", default="data/raw/govuk_guidance.jsonl")
    ap.add_argument("--sample", type=int, default=300)
    ap.add_argument("--seed", type=int, default=20260816)
    ap.add_argument("--out", default="reports/commitment_field_probe.json")
    args = ap.parse_args()

    paths = []
    with open(args.input, encoding="utf-8") as fh:
        for line in fh:
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            link = rec.get("link")
            if link and link.startswith("/"):
                paths.append((link, rec.get("content_store_document_type")))

    random.seed(args.seed)
    sample = random.sample(paths, min(args.sample, len(paths)))

    key_counts: Counter = Counter()
    hits = []
    by_type: Counter = Counter()
    fetched = 0
    errors = 0

    for i, (path, doc_type) in enumerate(sample, 1):
        try:
            doc = fetch(path)
        except Exception:  # noqa: BLE001
            errors += 1
            continue
        fetched += 1
        by_type[doc_type] += 1
        local: Counter = Counter()
        walk_keys(doc, local)
        key_counts.update(local)
        matched = sorted(
            {k for k in local if any(c in k.lower() for c in COMMITMENT_KEYS)}
        )
        if matched:
            hits.append({"path": path, "document_type": doc_type, "fields": matched})
        if i % 50 == 0:
            print(f"  {i}/{len(sample)}", file=sys.stderr, flush=True)
        time.sleep(0.15)

    matched_keys = sorted(
        {k for k in key_counts if any(c in k.lower() for c in COMMITMENT_KEYS)}
    )

    result = {
        "sampled": len(sample),
        "fetched": fetched,
        "errors": errors,
        "documents_by_type": dict(by_type),
        "distinct_json_keys_observed": len(key_counts),
        "keys_matching_commitment_vocabulary": {k: key_counts[k] for k in matched_keys},
        "documents_with_any_commitment_field": len(hits),
        "examples": hits[:20],
        "most_common_keys": key_counts.most_common(40),
    }
    with open(args.out, "w") as fh:
        json.dump(result, fh, indent=2)

    print(f"\nfetched {fetched} documents, {len(key_counts)} distinct JSON keys observed")
    print(f"documents carrying any commitment-shaped field: {len(hits)}")
    print(f"matching keys: {matched_keys or 'NONE'}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
