#!/usr/bin/env python3
"""Harvest a docs-as-code estate into the normalised record shape.

Why this corpus class matters. The GOV.UK study returned a null result on the
most important dimension: no field anywhere expressed who maintains a document
or when anyone last verified it, so commitment coverage could only be measured
in a weak, organisation-level proxy form.

Docs-as-code estates are the exception. They carry, in the repository itself:

  * named owners, either in YAML front matter (``author`` / ``ms.author``) or
    in Kubernetes-style ``OWNERS`` files that apply to a directory subtree;
  * a declared verification date, in Microsoft Learn's ``ms.date``, which the
    house style defines as the date the article was last reviewed for accuracy
    rather than the date the file was last touched;
  * a complete, auditable modification history in git.

That combination makes two things possible for the first time. Commitment
coverage can be measured in its strict form. And, more interestingly, the
declared verification date can be checked against the file's actual git
history, which tests whether a freshness signal means anything or is simply
stamped and forgotten.

Usage:
    python3 harvest_docs_as_code.py --repo /tmp/dac/azure-docs \\
        --content articles --flavour microsoft --out data/raw/azure_docs.jsonl
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from collections import defaultdict

FRONT_MATTER = re.compile(r"\A---\r?\n(.*?)\r?\n---\r?\n", re.S)
# Deliberately a small hand-rolled reader rather than a YAML dependency: doc
# front matter is flat key/value in practice, and a real YAML parser chokes on
# the unquoted colons that are endemic in documentation titles.
KV = re.compile(r"^([A-Za-z0-9_.\-]+)\s*:\s*(.*?)\s*$")


def parse_front_matter(text: str) -> tuple[dict, str]:
    m = FRONT_MATTER.match(text)
    if not m:
        return {}, text
    meta: dict = {}
    last_key = None
    for line in m.group(1).split("\n"):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        # A YAML block sequence under the previous key. Ownership is routinely
        # expressed this way (Kubernetes `reviewers:`), so dropping list items
        # would silently zero out the very field being measured.
        if line[:1] in (" ", "\t", "-") and line.lstrip().startswith("- "):
            if last_key:
                item = line.lstrip()[2:].strip().strip("'\"")
                if item:
                    meta.setdefault(last_key, [])
                    if isinstance(meta[last_key], list):
                        meta[last_key].append(item)
                    elif not meta[last_key]:
                        meta[last_key] = [item]
            continue
        if line[:1] in (" ", "\t"):
            continue
        km = KV.match(line)
        if km:
            key, val = km.group(1).strip().lower(), km.group(2).strip()
            meta[key] = val.strip("'\"")
            last_key = key
    return meta, text[m.end():]



def as_scalar(value) -> str:
    """Front matter values may be a scalar or a YAML list; normalise to a string."""
    if value is None:
        return ""
    if isinstance(value, list):
        return value[0] if value else ""
    return str(value)


def git_last_commit_dates(repo: str, content_dir: str) -> dict[str, int]:
    """Epoch seconds of the most recent commit touching each path.

    One pass over the whole history, newest first, keeping the first sighting
    of each path. Far cheaper than one `git log` invocation per file, which is
    what makes this tractable at tens of thousands of documents.
    """
    cmd = [
        "git", "-C", repo, "log", "--format=@%ct", "--name-only",
        "--no-renames", "--diff-filter=AMRC", "--", content_dir,
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    dates: dict[str, int] = {}
    current = 0
    for line in proc.stdout.split("\n"):
        if not line:
            continue
        if line.startswith("@"):
            try:
                current = int(line[1:])
            except ValueError:
                current = 0
        elif current and line not in dates:
            dates[line] = current
    return dates


def load_owners_files(repo: str, content_dir: str) -> dict[str, dict]:
    """Kubernetes-style OWNERS: approvers and reviewers, inherited down a tree."""
    owners: dict[str, dict] = {}
    root = os.path.join(repo, content_dir)
    for dirpath, _dirnames, filenames in os.walk(root):
        if "OWNERS" not in filenames:
            continue
        path = os.path.join(dirpath, "OWNERS")
        try:
            with open(path, encoding="utf-8", errors="replace") as fh:
                text = fh.read()
        except OSError:
            continue
        approvers, reviewers, section = [], [], None
        for line in text.split("\n"):
            stripped = line.strip()
            if stripped.startswith("approvers:"):
                section = "a"
                continue
            if stripped.startswith("reviewers:"):
                section = "r"
                continue
            if stripped and not line.startswith((" ", "\t", "-")):
                section = None
            if stripped.startswith("- ") and section:
                name = stripped[2:].strip().strip("'\"")
                if name and not name.startswith("sig-"):
                    (approvers if section == "a" else reviewers).append(name)
        rel = os.path.relpath(dirpath, repo)
        owners[rel] = {"approvers": approvers, "reviewers": reviewers}
    return owners


def nearest_owners(rel_dir: str, owners: dict[str, dict]) -> dict | None:
    parts = rel_dir.split(os.sep)
    while parts:
        candidate = os.sep.join(parts)
        if candidate in owners:
            return owners[candidate]
        parts.pop()
    return owners.get(".")


DATE_ONLY = re.compile(r"(\d{4})[-/](\d{1,2})[-/](\d{1,2})")
US_DATE = re.compile(r"(\d{1,2})/(\d{1,2})/(\d{4})")


def parse_declared_date(value: str) -> str | None:
    """Return ISO date. Microsoft ``ms.date`` is written US-style (m/d/Y)."""
    if not value:
        return None
    value = value.strip().strip("'\"")
    m = US_DATE.match(value)
    if m:
        mo, da, yr = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= da <= 31:
            return f"{yr:04d}-{mo:02d}-{da:02d}"
    m = DATE_ONLY.match(value)
    if m:
        yr, mo, da = int(m.group(1)), int(m.group(2)), int(m.group(3))
        if 1 <= mo <= 12 and 1 <= da <= 31:
            return f"{yr:04d}-{mo:02d}-{da:02d}"
    return None


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--repo", required=True)
    ap.add_argument("--content", required=True, help="content dir relative to repo root")
    ap.add_argument("--flavour", choices=["microsoft", "kubernetes"], required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("--url-base", default="")
    args = ap.parse_args()

    print("reading git history...", file=sys.stderr, flush=True)
    dates = git_last_commit_dates(args.repo, args.content)
    print(f"  {len(dates):,} paths with commit dates", file=sys.stderr)

    owners_map: dict[str, dict] = {}
    if args.flavour == "kubernetes":
        owners_map = load_owners_files(args.repo, args.content)
        print(f"  {len(owners_map):,} OWNERS files", file=sys.stderr)

    root = os.path.join(args.repo, args.content)
    os.makedirs(os.path.dirname(args.out) or ".", exist_ok=True)
    written = 0
    skipped = 0

    with open(args.out, "w", encoding="utf-8") as out:
        for dirpath, _dirs, files in os.walk(root):
            for name in files:
                if not name.endswith(".md"):
                    continue
                full = os.path.join(dirpath, name)
                rel = os.path.relpath(full, args.repo)
                try:
                    with open(full, encoding="utf-8", errors="replace") as fh:
                        text = fh.read()
                except OSError:
                    skipped += 1
                    continue
                meta, body = parse_front_matter(text)

                declared = None
                declared_owner = None
                if args.flavour == "microsoft":
                    declared = parse_declared_date(as_scalar(meta.get("ms.date")))
                    owner_source = "front_matter_ms_author" if declared_owner else None
                    declared_owner = as_scalar(meta.get("ms.author")) or as_scalar(meta.get("author"))
                else:
                    # Per-document `reviewers` front matter is a genuine named
                    # commitment. OWNERS files are a fallback and are coarse:
                    # they sit at directory level and inherit down a whole tree.
                    fm_reviewers = meta.get("reviewers")
                    if isinstance(fm_reviewers, str) and fm_reviewers:
                        fm_reviewers = [fm_reviewers]
                    if fm_reviewers:
                        declared_owner = fm_reviewers[0]
                        owner_source = "front_matter_reviewers"
                    else:
                        od = nearest_owners(os.path.relpath(dirpath, args.repo), owners_map) or {}
                        approvers = od.get("approvers") or []
                        declared_owner = approvers[0] if approvers else None
                        owner_source = "owners_file" if declared_owner else None
                    # Kubernetes docs carry no declared verification date at all.
                    declared = None

                git_epoch = dates.get(rel)
                record = {
                    "id": rel,
                    "title": as_scalar(meta.get("title")) or name.rsplit(".", 1)[0].replace("-", " "),
                    "url": (args.url_base + "/" + rel) if args.url_base else rel,
                    "description": as_scalar(meta.get("description")),
                    "git_last_commit_epoch": git_epoch,
                    "declared_verified_date": declared,
                    "declared_owner": declared_owner,
                    "owner_source": owner_source,
                    "doc_type": as_scalar(meta.get("ms.topic")) or as_scalar(meta.get("content_type")),
                    "service": as_scalar(meta.get("ms.service")) or as_scalar(meta.get("ms.prod")),
                    "body_chars": len(body),
                    "body": body[:40000],
                    "front_matter_keys": sorted(meta.keys()),
                    "withdrawn": "deprecated" in as_scalar(meta.get("ms.custom")).lower(),
                }
                out.write(json.dumps(record, ensure_ascii=False) + "\n")
                written += 1

    print(f"wrote {written:,} records to {args.out} ({skipped} unreadable)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
