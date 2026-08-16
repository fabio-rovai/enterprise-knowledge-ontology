#!/usr/bin/env python3
"""Test the central claim of D2: that last-modified flatters a corpus.

The GOV.UK study reported freshness from time since last modification, and said
plainly that this is a weaker measure than time since last verification,
because a typo fix resets the first without anyone checking a fact. That was an
argument, not a measurement, because GOV.UK publishes no verification date.

A Microsoft Learn style docs-as-code estate publishes both. ``ms.date`` is
defined by the house style as the date the article was last reviewed for
accuracy. Git records, independently and unforgeably, when the file was last
changed. So the two quantities can finally be compared on the same documents.

Three questions:

  1. How far apart are declared verification and actual modification?
  2. Does measuring freshness by modification overstate it, and by how much?
  3. Is the declared date maintained, or stamped once and left?

Deterministic. No network. No language model.
"""
from __future__ import annotations

import argparse
import json
import math
import os
import statistics
from collections import Counter
from datetime import date, datetime, timezone


def iso_to_date(value: str | None) -> date | None:
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


def epoch_to_date(value) -> date | None:
    if not value:
        return None
    try:
        return datetime.fromtimestamp(int(value), tz=timezone.utc).date()
    except (ValueError, OSError, OverflowError):
        return None


def pct(part: int, whole: int) -> float:
    return round(100.0 * part / whole, 2) if whole else 0.0


def buckets(ages_years: list[float]) -> dict:
    b = Counter()
    for a in ages_years:
        if a < 1:
            b["under_1y"] += 1
        elif a < 2:
            b["1_to_2y"] += 1
        elif a < 5:
            b["2_to_5y"] += 1
        else:
            b["over_5y"] += 1
    return dict(b)


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--input", required=True)
    ap.add_argument("--corpus-name", default="corpus")
    ap.add_argument("--out", required=True)
    ap.add_argument("--as-of", default=None)
    ap.add_argument("--legacy-prefix", nargs="*", default=[],
                    help="path prefixes treated as deliberately frozen content; "
                         "reported separately so the headline is not a cheap shot "
                         "at documentation for closed technologies")
    args = ap.parse_args()

    today = date.fromisoformat(args.as_of) if args.as_of else datetime.now(timezone.utc).date()

    docs = []
    with open(args.input, encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if line:
                docs.append(json.loads(line))

    n = len(docs)
    paired = []
    for d in docs:
        declared = iso_to_date(d.get("declared_verified_date"))
        modified = epoch_to_date(d.get("git_last_commit_epoch"))
        if declared and modified:
            paired.append((d, declared, modified))

    declared_ages = [(today - dec).days / 365.25 for _d, dec, _m in paired]
    modified_ages = [(today - mod).days / 365.25 for _d, _dec, mod in paired]
    # Positive delta: the file was changed after it was last declared verified.
    deltas = [(mod - dec).days for _d, dec, mod in paired]

    lag_over_year = sum(1 for x in deltas if x > 365)
    lag_over_2y = sum(1 for x in deltas if x > 730)
    ahead = sum(1 for x in deltas if x < -1)
    future = sum(1 for _d, dec, _m in paired if dec > today)
    same_day = sum(1 for x in deltas if abs(x) <= 1)

    stale_declared_2y = sum(1 for a in declared_ages if a >= 2)
    stale_modified_2y = sum(1 for a in modified_ages if a >= 2)
    stale_declared_5y = sum(1 for a in declared_ages if a >= 5)
    stale_modified_5y = sum(1 for a in modified_ages if a >= 5)

    # The headline: how many documents look current by modification but are
    # stale by the publisher's own declared verification date.
    flattered = sum(
        1 for _d, dec, mod in paired
        if (today - mod).days / 365.25 < 2 <= (today - dec).days / 365.25
    )

    result = {
        "corpus": args.corpus_name,
        "source_file": os.path.basename(args.input),
        "as_of": today.isoformat(),
        "documents": n,
        "documents_with_both_dates": len(paired),
        "coverage": {
            "declared_verification_date": pct(
                sum(1 for d in docs if d.get("declared_verified_date")), n),
            "named_owner": pct(sum(1 for d in docs if d.get("declared_owner")), n),
            "strict_commitment_both": pct(
                sum(1 for d in docs
                    if d.get("declared_verified_date") and d.get("declared_owner")), n),
        },
        "age_by_declared_verification": {
            "median_years": round(statistics.median(declared_ages), 2) if declared_ages else None,
            "mean_years": round(statistics.mean(declared_ages), 2) if declared_ages else None,
            "buckets": buckets(declared_ages),
            "stale_over_2y": stale_declared_2y,
            "stale_over_2y_percent": pct(stale_declared_2y, len(paired)),
            "stale_over_5y": stale_declared_5y,
        },
        "age_by_git_modification": {
            "median_years": round(statistics.median(modified_ages), 2) if modified_ages else None,
            "mean_years": round(statistics.mean(modified_ages), 2) if modified_ages else None,
            "buckets": buckets(modified_ages),
            "stale_over_2y": stale_modified_2y,
            "stale_over_2y_percent": pct(stale_modified_2y, len(paired)),
            "stale_over_5y": stale_modified_5y,
        },
        "divergence": {
            "median_lag_days": int(statistics.median(deltas)) if deltas else None,
            "mean_lag_days": round(statistics.mean(deltas), 1) if deltas else None,
            "modified_after_declared_verification": sum(1 for x in deltas if x > 0),
            "modified_after_declared_verification_percent": pct(
                sum(1 for x in deltas if x > 0), len(paired)),
            "lag_over_1_year": lag_over_year,
            "lag_over_1_year_percent": pct(lag_over_year, len(paired)),
            "lag_over_2_years": lag_over_2y,
            "declared_date_after_last_commit": ahead,
            "declared_date_in_the_future": future,
            "declared_and_modified_same_day": same_day,
            "declared_and_modified_same_day_percent": pct(same_day, len(paired)),
        },
        "the_flattery_effect": {
            "documents_current_by_modification_but_stale_by_declared_verification": flattered,
            "percent_of_paired": pct(flattered, len(paired)),
            "note": (
                "These documents were changed within the last two years, so any "
                "freshness measure based on modification counts them as current. "
                "Their publisher's own declared verification date says nobody has "
                "checked them for accuracy in over two years."
            ),
        },
        "worst_lag_examples": sorted(
            (
                {
                    "path": d.get("id"),
                    "declared_verified": dec.isoformat(),
                    "last_commit": mod.isoformat(),
                    "lag_days": (mod - dec).days,
                }
                for d, dec, mod in paired
            ),
            key=lambda r: -r["lag_days"],
        )[:15],
        "oldest_declared_examples": sorted(
            (
                {
                    "path": d.get("id"),
                    "declared_verified": dec.isoformat(),
                    "last_commit": mod.isoformat(),
                    "declared_age_years": round((today - dec).days / 365.25, 2),
                }
                for d, dec, mod in paired
            ),
            key=lambda r: -r["declared_age_years"],
        )[:15],
    }

    # Frozen legacy content and actively developed content must be reported
    # apart. If the divergence only appeared in abandoned subtrees it would be
    # an artefact of documenting closed technologies rather than a finding.
    if args.legacy_prefix:
        segments: dict = {}
        for label in ("legacy", "active"):
            rows = [
                (d, dec, mod) for d, dec, mod in paired
                if (str(d.get("id", "")).startswith(tuple(args.legacy_prefix))
                    == (label == "legacy"))
            ]
            if not rows:
                continue
            d_ages = [(today - dec).days / 365.25 for _d, dec, _m in rows]
            m_ages = [(today - mod).days / 365.25 for _d, _dec, mod in rows]
            s2d = sum(1 for a in d_ages if a >= 2)
            s2m = sum(1 for a in m_ages if a >= 2)
            fl = sum(1 for _d, dec, mod in rows
                     if (today - mod).days / 365.25 < 2 <= (today - dec).days / 365.25)
            segments[label] = {
                "documents": len(rows),
                "median_declared_age_years": round(statistics.median(d_ages), 2),
                "median_git_age_years": round(statistics.median(m_ages), 2),
                "stale_over_2y_declared_percent": pct(s2d, len(rows)),
                "stale_over_2y_modification_percent": pct(s2m, len(rows)),
                "look_current_but_are_not": fl,
                "look_current_but_are_not_percent": pct(fl, len(rows)),
                "understatement_gap_percentage_points": round(
                    pct(s2d, len(rows)) - pct(s2m, len(rows)), 1),
            }
        result["segments"] = segments
        result["legacy_prefixes"] = list(args.legacy_prefix)

    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    with open(args.out, "w") as fh:
        json.dump(result, fh, indent=2)

    c = result["coverage"]
    dv = result["age_by_declared_verification"]
    gm = result["age_by_git_modification"]
    dvg = result["divergence"]
    print(f"{args.corpus_name}: {n:,} documents, {len(paired):,} with both dates\n")
    print(f"  declared verification date coverage : {c['declared_verification_date']}%")
    print(f"  named owner coverage                : {c['named_owner']}%")
    print(f"  strict commitment (both)            : {c['strict_commitment_both']}%\n")
    print(f"  median age by DECLARED VERIFICATION : {dv['median_years']} years")
    print(f"  median age by GIT MODIFICATION      : {gm['median_years']} years")
    print(f"  stale over 2y, declared             : {dv['stale_over_2y']:,} ({dv['stale_over_2y_percent']}%)")
    print(f"  stale over 2y, modification         : {gm['stale_over_2y']:,} ({gm['stale_over_2y_percent']}%)\n")
    print(f"  changed after last declared check   : {dvg['modified_after_declared_verification']:,} ({dvg['modified_after_declared_verification_percent']}%)")
    print(f"  ... by more than a year             : {dvg['lag_over_1_year']:,} ({dvg['lag_over_1_year_percent']}%)")
    print(f"  declared and changed same day       : {dvg['declared_and_modified_same_day']:,} ({dvg['declared_and_modified_same_day_percent']}%)\n")
    fl = result["the_flattery_effect"]
    print(f"  LOOK CURRENT BUT ARE NOT            : {fl['documents_current_by_modification_but_stale_by_declared_verification']:,} ({fl['percent_of_paired']}%)")
    print(f"\nwrote {args.out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
