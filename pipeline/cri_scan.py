#!/usr/bin/env python3
"""Corpus Readiness Index (CRI) — measurement instrument.

Seven dimensions, each computed from evidence rather than opinion:

  D1 Commitment coverage   Can a named party be held to this content?
  D2 Freshness             Is it within a declared review cadence?
  D3 Canonicity            Is there one source per topic, or several?
  D4 Decommission hygiene  Is disowned content actually gone?
  D5 Redundancy            How much of the corpus is the same thing again?
  D6 Coherence             Do documents on the same topic disagree?
  D7 Retrieval fitness     Is there anything here a retrieval system can use?

The instrument is deliberately source-agnostic: it consumes a normalised record
shape, so the same scan runs against a GOV.UK harvest, a Confluence export or a
SharePoint inventory. Only the adapter changes.

Pure standard library. No network. Deterministic.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import re
import statistics
import sys
from collections import Counter, defaultdict
from datetime import datetime, timezone

import numpy as np

# Bodies are truncated at load. The near-duplicate pass reads the first 1,500
# tokens and the claim extractor the first 20,000 characters, so retaining more
# costs several gigabytes of memory and buys nothing.
BODY_LIMIT = 40_000

# ---------------------------------------------------------------------------
# Normalised record shape
# ---------------------------------------------------------------------------
# id, title, url, description, updated (datetime|None), body (str),
# owners [{id,name,state,closed_state}], withdrawn (bool), doc_type (str),
# taxonomy (list[str]), era (str|None)


def parse_ts(value):
    if not value:
        return None
    v = value.strip()
    try:
        if v.endswith("Z"):
            v = v[:-1] + "+00:00"
        dt = datetime.fromisoformat(v)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except ValueError:
        return None


def adapt_govuk(rec: dict) -> dict:
    orgs = rec.get("organisations") or []
    body = rec.get("indexable_content") or ""
    full_length = len(body)
    return {
        "body_full_length": full_length,
        "id": rec.get("content_id") or rec.get("link"),
        "title": (rec.get("title") or "").strip(),
        "url": rec.get("link") or "",
        "description": (rec.get("description") or "").strip(),
        "updated": parse_ts(rec.get("public_timestamp")),
        "body": body[:BODY_LIMIT],
        "owners": [
            {
                "id": o.get("slug"),
                "name": o.get("title"),
                "state": o.get("organisation_state"),
                "closed_state": o.get("organisation_closed_state"),
            }
            for o in orgs
        ],
        "withdrawn": bool(rec.get("is_withdrawn")),
        "doc_type": rec.get("content_store_document_type") or rec.get("_harvest_document_type"),
        "taxonomy": rec.get("part_of_taxonomy_tree") or [],
        "era": rec.get("government_name"),
    }


ADAPTERS = {"govuk": adapt_govuk}

# ---------------------------------------------------------------------------
# Text utilities
# ---------------------------------------------------------------------------

_WORD = re.compile(r"[a-z0-9£%€$][a-z0-9£%€$'\-\.]*")
_TITLE_NOISE = re.compile(r"\b(20\d\d|19\d\d|updated|revised|version|v\d+|final|draft|part\s+\d+|no\.?\s*\d+)\b")
_PUNCT = re.compile(r"[^a-z0-9 ]+")


def normalise_title(title: str) -> str:
    t = title.lower()
    t = _TITLE_NOISE.sub(" ", t)
    t = _PUNCT.sub(" ", t)
    return " ".join(t.split())


def tokens(text: str, limit: int = 1500) -> list[str]:
    return _WORD.findall(text.lower())[:limit]


def simhash(text: str, bits: int = 64) -> int:
    """64-bit simhash over 3-word shingles.

    The shingle digests are accumulated as a bit matrix in numpy rather than a
    Python loop over 64 bits per shingle. At corpus scale that is the difference
    between a scan that finishes and one that does not.
    """
    toks = tokens(text)
    if len(toks) < 3:
        return 0
    digests = [
        hashlib.blake2b(
            " ".join(toks[i : i + 3]).encode("utf-8"), digest_size=8
        ).digest()
        for i in range(len(toks) - 2)
    ]
    raw = np.frombuffer(b"".join(digests), dtype=np.uint8).reshape(len(digests), 8)
    bit_matrix = np.unpackbits(raw, axis=1)  # (n_shingles, 64), big-endian
    column_sums = bit_matrix.sum(axis=0, dtype=np.int64)
    majority = column_sums * 2 > len(digests)
    return int(np.packbits(majority.astype(np.uint8)).tobytes().hex(), 16)


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


# Claims we can extract deterministically: money, percentages, and durations.
# Deliberately narrow. A wide extractor produces impressive counts and useless
# findings; the point is candidate pairs a human can adjudicate in seconds.
_MONEY = re.compile(r"£\s?([0-9][0-9,]*(?:\.[0-9]{1,2})?)(\s?(?:million|billion|m\b|bn\b))?", re.I)
# The trailing boundary must not be a \b after '%'. '%' is itself a non-word
# character, so "4.5% applies" has no word boundary between the sign and the
# space, and a trailing \b silently drops every percentage written with a sign.
_PCT = re.compile(r"\b([0-9]{1,3}(?:\.[0-9]+)?)\s?(?:%|per\s?cent\b|percent\b)", re.I)
_DAYS = re.compile(r"\b([0-9]{1,4})\s+(working\s+days?|days?|weeks?|months?|years?)\b", re.I)


def extract_claims(text: str, cap: int = 60) -> dict[str, set]:
    head = text[:20000]
    money = set()
    for m in _MONEY.finditer(head):
        amount = m.group(1).replace(",", "")
        scale = (m.group(2) or "").strip().lower()
        try:
            val = float(amount)
        except ValueError:
            continue
        if scale.startswith("m"):
            val *= 1_000_000
        elif scale.startswith("b"):
            val *= 1_000_000_000
        money.add(round(val, 2))
        if len(money) >= cap:
            break
    pct = {round(float(m.group(1)), 3) for m in _PCT.finditer(head)}
    dur = {(m.group(1), m.group(2).lower().rstrip("s")) for m in _DAYS.finditer(head)}
    return {"money": money, "pct": pct, "dur": dur}


# ---------------------------------------------------------------------------
# The scan
# ---------------------------------------------------------------------------


def score(pct_good: float) -> float:
    return round(max(0.0, min(100.0, pct_good)), 1)


def run(path: str, adapter: str, now: datetime,
        withdrawn_probe: dict | None = None) -> dict:
    adapt = ADAPTERS[adapter]
    docs: list[dict] = []
    with open(path, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                docs.append(adapt(json.loads(line)))
            except json.JSONDecodeError:
                continue

    n = len(docs)
    if not n:
        raise SystemExit("no documents loaded")

    findings: dict = {
        "corpus": os.path.basename(path),
        "documents": n,
        "scanned_at": now.isoformat(),
    }

    # ---------------- D1 Commitment coverage ------------------------------
    no_owner = [d for d in docs if not d["owners"]]
    all_dead = [
        d for d in docs
        if d["owners"] and all(o["state"] and o["state"] != "live" for o in d["owners"])
    ]
    gone_entirely = [
        d for d in docs
        if any(o.get("closed_state") == "no_longer_exists" for o in d["owners"])
    ]
    # A machine-readable maintenance commitment requires a cadence and a
    # verification date. Neither exists as a field anywhere in this source.
    with_cadence = 0
    with_verified = 0

    live_owned = n - len(no_owner) - len(all_dead)
    findings["D1_commitment_coverage"] = {
        "score": score(100.0 * live_owned / n),
        "documents_with_no_owning_organisation": len(no_owner),
        "documents_owned_only_by_non_live_organisations": len(all_dead),
        "documents_owned_by_an_organisation_that_no_longer_exists": len(gone_entirely),
        "documents_with_machine_readable_review_cadence": with_cadence,
        "documents_with_machine_readable_verification_date": with_verified,
        "note": (
            "Ownership here means an organisation is named, which is a weak proxy: "
            "no named individual, no cadence and no verification date is expressed "
            "anywhere in the public metadata."
        ),
    }
    findings["_orphan_examples"] = [
        {"title": d["title"], "url": d["url"],
         "owners": [o["name"] for o in d["owners"]],
         "updated": d["updated"].date().isoformat() if d["updated"] else None}
        for d in sorted(all_dead, key=lambda x: (x["updated"] or now))[:15]
    ]

    # ---------------- D2 Freshness ----------------------------------------
    ages = []
    for d in docs:
        if d["updated"]:
            ages.append((now - d["updated"]).days / 365.25)
    buckets = Counter()
    for a in ages:
        if a < 1:
            buckets["under_1y"] += 1
        elif a < 2:
            buckets["1_to_2y"] += 1
        elif a < 5:
            buckets["2_to_5y"] += 1
        elif a < 10:
            buckets["5_to_10y"] += 1
        else:
            buckets["over_10y"] += 1
    over_2 = buckets["2_to_5y"] + buckets["5_to_10y"] + buckets["over_10y"]
    findings["D2_freshness"] = {
        "score": score(100.0 * (buckets["under_1y"] + buckets["1_to_2y"]) / max(1, len(ages))),
        "documents_with_a_date": len(ages),
        "age_buckets": dict(buckets),
        "median_age_years": round(statistics.median(ages), 2) if ages else None,
        "mean_age_years": round(statistics.mean(ages), 2) if ages else None,
        "oldest_age_years": round(max(ages), 2) if ages else None,
        "unchanged_over_2y": over_2,
        "unchanged_over_5y": buckets["5_to_10y"] + buckets["over_10y"],
        "unchanged_over_10y": buckets["over_10y"],
        "note": (
            "This measures time since last change, not time since last verification. "
            "The two are routinely conflated and are not the same: a typo fix resets "
            "the first without touching the second. No source in this study publishes "
            "the second."
        ),
    }
    era = Counter(d["era"] for d in docs if d["era"])
    findings["D2b_publishing_era"] = {
        "documents_with_an_era_marker": sum(era.values()),
        "distribution": dict(era.most_common(15)),
    }

    # ---------------- D3 Canonicity ---------------------------------------
    by_title = defaultdict(list)
    for d in docs:
        if d["withdrawn"]:
            continue
        key = normalise_title(d["title"])
        if len(key) > 12:
            by_title[key].append(d)
    contested = {k: v for k, v in by_title.items() if len(v) > 1}
    contested_docs = sum(len(v) for v in contested.values())
    same_owner_contested = 0
    for group in contested.values():
        owners = [tuple(sorted(o["id"] or "" for o in d["owners"])) for d in group]
        if len(set(owners)) == 1:
            same_owner_contested += 1
    findings["D3_canonicity"] = {
        "score": score(100.0 * (len(by_title) - len(contested)) / max(1, len(by_title))),
        "distinct_normalised_titles": len(by_title),
        "titles_with_more_than_one_live_document": len(contested),
        "documents_in_a_contested_title_group": contested_docs,
        "contested_groups_under_a_single_owner": same_owner_contested,
        "largest_groups": sorted(
            ({"title": k, "documents": len(v),
              "urls": [d["url"] for d in v][:6]} for k, v in contested.items()),
            key=lambda x: -x["documents"],
        )[:15],
    }

    # ---------------- D4 Decommission hygiene ------------------------------
    withdrawn = [d for d in docs if d["withdrawn"]]
    d4 = {
        "withdrawn_documents_in_the_curated_search_index": len(withdrawn),
        "curated_index_share_percent": round(100.0 * len(withdrawn) / n, 2),
    }
    if withdrawn_probe:
        # The curated index and the crawlable surface are different corpora, and
        # D4 must be scored against the one a retrieval pipeline actually eats.
        rate = withdrawn_probe["withdrawn_rate_percent"]
        d4.update({
            "score": score(100.0 - rate),
            "measured_against": "crawlable surface (publisher sitemap)",
            "sitemap_urls_advertised": withdrawn_probe["sitemap_urls_advertised"],
            "search_index_documents": withdrawn_probe["search_index_documents"],
            "sampled_urls": withdrawn_probe["successfully_probed"],
            "withdrawn_in_sample": withdrawn_probe["withdrawn_documents_in_sample"],
            "withdrawn_rate_percent": rate,
            "withdrawn_still_serving_body_text": withdrawn_probe[
                "withdrawn_still_serving_body_text"],
            "median_years_since_withdrawal": withdrawn_probe[
                "median_years_since_withdrawal"],
            "oldest_withdrawal_years": withdrawn_probe["oldest_withdrawal_years"],
            "note": (
                "The publisher's own search index excludes withdrawn content entirely, "
                "which is better discipline than most estates manage. The withdrawn "
                "pages nonetheless remain live at their original addresses, listed in "
                "the public sitemap, and fully served with body text by the content "
                "API. A pipeline built the obvious way, by crawling the sitemap, "
                "ingests exactly what the curated index was careful to exclude."
            ),
        })
    else:
        d4.update({
            "score": score(100.0 * (n - len(withdrawn)) / n),
            "measured_against": "curated search index only",
            "note": (
                "Scored against the curated index because no crawlable-surface probe "
                "was supplied. If the source index excludes withdrawn content by "
                "design, this score is close to meaningless: run probe_withdrawn.py "
                "and pass its output with --withdrawn-probe."
            ),
        })
    findings["D4_decommission_hygiene"] = d4

    # ---------------- D5 Redundancy ---------------------------------------
    fps: list[tuple[int, int]] = []
    for i, d in enumerate(docs):
        body = d["body"]
        if len(body) < 400:
            continue
        fp = simhash(body)
        if fp:
            fps.append((fp, i))
    bands = defaultdict(list)
    for fp, i in fps:
        for b in range(4):
            bands[(b, (fp >> (16 * b)) & 0xFFFF)].append((fp, i))
    seen_pairs = set()
    near_dupes: list[tuple[int, int, int]] = []
    for bucket in bands.values():
        if len(bucket) < 2 or len(bucket) > 400:
            continue
        for x in range(len(bucket)):
            for y in range(x + 1, len(bucket)):
                i, j = bucket[x][1], bucket[y][1]
                key = (i, j) if i < j else (j, i)
                if key in seen_pairs:
                    continue
                seen_pairs.add(key)
                dist = hamming(bucket[x][0], bucket[y][0])
                if dist <= 3:
                    near_dupes.append((key[0], key[1], dist))
    parent = {}

    def find(x):
        parent.setdefault(x, x)
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    for i, j, _ in near_dupes:
        union(i, j)
    clusters = defaultdict(list)
    for node in list(parent):
        clusters[find(node)].append(node)
    multi = [c for c in clusters.values() if len(c) > 1]
    redundant_docs = sum(len(c) - 1 for c in multi)
    findings["D5_redundancy"] = {
        "score": score(100.0 * (len(fps) - redundant_docs) / max(1, len(fps))),
        "documents_compared": len(fps),
        "near_duplicate_pairs": len(near_dupes),
        "near_duplicate_clusters": len(multi),
        "redundant_documents": redundant_docs,
        "method": "64-bit simhash over 3-word shingles, 4x16-bit banding, Hamming distance <= 3",
        "largest_clusters": sorted(
            ({"size": len(c), "titles": [docs[i]["title"] for i in c][:5],
              "urls": [docs[i]["url"] for i in c][:5]} for c in multi),
            key=lambda x: -x["size"],
        )[:12],
    }

    # ---------------- D6 Coherence (contradiction candidates) --------------
    candidates = []
    for key, group in contested.items():
        if len(group) < 2 or len(group) > 12:
            continue
        claims = [(d, extract_claims(d["body"])) for d in group if len(d["body"]) > 200]
        for x in range(len(claims)):
            for y in range(x + 1, len(claims)):
                da, ca = claims[x]
                db, cb = claims[y]
                for field in ("money", "pct"):
                    a, b = ca[field], cb[field]
                    if a and b and not (a & b):
                        candidates.append({
                            "topic": key,
                            "field": field,
                            "a": {"url": da["url"], "values": sorted(a)[:6]},
                            "b": {"url": db["url"], "values": sorted(b)[:6]},
                        })
                        break
    findings["D6_coherence"] = {
        "score": score(100.0 * (len(contested) - len({c["topic"] for c in candidates}))
                       / max(1, len(contested))),
        "topics_examined": len(contested),
        "contradiction_candidate_pairs": len(candidates),
        "topics_with_at_least_one_candidate": len({c["topic"] for c in candidates}),
        "method": (
            "Documents sharing a normalised title are compared on deterministically "
            "extracted monetary and percentage values. Disjoint value sets on the same "
            "topic are flagged as candidates for human adjudication, never as confirmed "
            "contradictions."
        ),
        "examples": candidates[:15],
    }

    # ---------------- D7 Retrieval fitness ---------------------------------
    lengths = [d["body_full_length"] for d in docs]
    stubs = [d for d in docs if d["body_full_length"] < 500]
    no_desc = [d for d in docs if not d["description"]]
    no_tax = [d for d in docs if not d["taxonomy"]]
    fit_flags = []
    for d in docs:
        ok = bool(d["description"]) and bool(d["taxonomy"]) and d["body_full_length"] >= 500
        fit_flags.append(ok)
    findings["D7_retrieval_fitness"] = {
        "score": score(100.0 * sum(fit_flags) / n),
        "documents_with_no_description": len(no_desc),
        "documents_absent_from_the_browse_taxonomy": len(no_tax),
        "documents_with_under_500_characters_of_indexable_text": len(stubs),
        "median_body_characters": int(statistics.median(lengths)) if lengths else 0,
        "mean_body_characters": int(statistics.mean(lengths)) if lengths else 0,
        "note": (
            "A page with almost no indexable text is usually a wrapper around an "
            "attachment. The answer exists, but it is inside a document the retrieval "
            "layer sees as an opaque blob, which is the most common single reason an "
            "assistant cannot answer a question the organisation has demonstrably "
            "documented."
        ),
        "shortest_examples": [
            {"title": d["title"], "url": d["url"], "chars": d["body_full_length"]}
            for d in sorted(stubs, key=lambda x: x["body_full_length"])[:10]
        ],
    }

    dims = [
        findings["D1_commitment_coverage"]["score"],
        findings["D2_freshness"]["score"],
        findings["D3_canonicity"]["score"],
        findings["D4_decommission_hygiene"]["score"],
        findings["D5_redundancy"]["score"],
        findings["D6_coherence"]["score"],
        findings["D7_retrieval_fitness"]["score"],
    ]
    # Geometric mean: a corpus is only as usable as its worst dimension, and an
    # arithmetic mean lets a strong dimension hide a fatal one.
    findings["CRI"] = round(math.exp(sum(math.log(max(d, 1.0)) for d in dims) / len(dims)), 1)
    findings["dimension_scores"] = dict(zip(
        ["D1_commitment", "D2_freshness", "D3_canonicity", "D4_decommission",
         "D5_redundancy", "D6_coherence", "D7_retrieval"], dims))
    return findings


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--adapter", default="govuk", choices=sorted(ADAPTERS))
    ap.add_argument("--out", default="reports/cri_govuk.json")
    ap.add_argument("--as-of", default=None, help="ISO date; defaults to today (UTC)")
    ap.add_argument("--withdrawn-probe", default=None,
                    help="JSON from probe_withdrawn.py; required for a meaningful D4")
    args = ap.parse_args()

    now = parse_ts(args.as_of) if args.as_of else datetime.now(timezone.utc)
    probe = None
    if args.withdrawn_probe and os.path.exists(args.withdrawn_probe):
        with open(args.withdrawn_probe) as fh:
            probe = json.load(fh)
    findings = run(args.input, args.adapter, now, probe)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(findings, fh, indent=2, default=str)

    print(f"documents: {findings['documents']:,}")
    print(f"CRI (geometric mean): {findings['CRI']}")
    for k, v in findings["dimension_scores"].items():
        print(f"  {k:<18} {v}")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
