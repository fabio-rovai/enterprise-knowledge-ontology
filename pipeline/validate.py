#!/usr/bin/env python3
"""Run the EKO publish gate over an instance graph.

Loads the ontology, the concept schemes and the SHACL shapes, validates the
supplied data graph, and prints a grouped report. Exit status is non-zero if
any Violation-severity result is reported, so the gate can sit in CI in front
of a knowledge repository the way a linter sits in front of code.
"""
from __future__ import annotations

import argparse
import sys
from collections import defaultdict

from pyshacl import validate
from rdflib import Graph
from rdflib.namespace import SH, RDF

ONTOLOGY = ["ontology/eko-core.ttl", "skos/eko-schemes.ttl"]
SHAPES = ["shapes/eko-shapes.ttl"]


def load(paths: list[str]) -> Graph:
    g = Graph()
    for p in paths:
        g.parse(p, format="turtle")
    return g


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--data", default="examples/worked_example.ttl")
    ap.add_argument("--shapes", nargs="*", default=SHAPES)
    ap.add_argument("--ontology", nargs="*", default=ONTOLOGY)
    ap.add_argument("--advisory", action="store_true",
                    help="always exit 0, reporting only")
    args = ap.parse_args()

    data = load([args.data])
    shapes = load(args.shapes)
    onto = load(args.ontology)

    conforms, results_graph, _ = validate(
        data_graph=data,
        shacl_graph=shapes,
        ont_graph=onto,
        inference="rdfs",
        advanced=True,
        allow_warnings=True,
    )

    grouped: dict[str, list[tuple[str, str]]] = defaultdict(list)
    for result in results_graph.subjects(RDF.type, SH.ValidationResult):
        severity = str(results_graph.value(result, SH.resultSeverity) or "")
        node = str(results_graph.value(result, SH.focusNode) or "")
        message = str(results_graph.value(result, SH.resultMessage) or "")
        grouped[severity.rsplit("#", 1)[-1] or "Unknown"].append((node, message))

    order = ["Violation", "Warning", "Info", "Unknown"]
    total = sum(len(v) for v in grouped.values())
    print(f"data graph:   {args.data} ({len(data):,} triples)")
    print(f"shapes graph: {len(shapes):,} triples")
    print(f"results:      {total}\n")

    for sev in order:
        items = grouped.get(sev)
        if not items:
            continue
        print(f"--- {sev} ({len(items)}) ---")
        for node, message in sorted(items):
            short = node.rsplit("/", 1)[-1].rsplit("#", 1)[-1]
            print(f"  [{short}] {message}")
        print()

    violations = len(grouped.get("Violation", []))
    if args.advisory:
        return 0
    return 1 if violations else 0


if __name__ == "__main__":
    raise SystemExit(main())
