"""Offline tests for the EKO publish gate and the CRI scanner.

No network. Every test asserts on behaviour that a silent failure would break:
the date comparison in the staleness rule is the obvious example, because both
standard SPARQL casts return no rows in rdflib rather than raising, producing a
rule that looks correct and never fires.
"""
from __future__ import annotations

import datetime as dt
import json
import pathlib
import sys

import pytest
from pyshacl import validate
from rdflib import Graph
from rdflib.namespace import RDF, SH

ROOT = pathlib.Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "pipeline"))

import cri_scan  # noqa: E402


def load(*paths: str) -> Graph:
    g = Graph()
    for p in paths:
        g.parse(str(ROOT / p), format="turtle")
    return g


@pytest.fixture(scope="module")
def shapes() -> Graph:
    return load("shapes/eko-shapes.ttl")


@pytest.fixture(scope="module")
def ontology() -> Graph:
    return load("ontology/eko-core.ttl", "skos/eko-schemes.ttl")


def messages(data: Graph, shapes: Graph, ontology: Graph) -> list[tuple[str, str]]:
    _, results, _ = validate(
        data_graph=data,
        shacl_graph=shapes,
        ont_graph=ontology,
        inference="rdfs",
        advanced=True,
        allow_warnings=True,
    )
    out = []
    for r in results.subjects(RDF.type, SH.ValidationResult):
        node = str(results.value(r, SH.focusNode) or "")
        msg = str(results.value(r, SH.resultMessage) or "")
        out.append((node.rsplit("/", 1)[-1], msg))
    return out


# --------------------------------------------------------------------------
# Graphs parse
# --------------------------------------------------------------------------

@pytest.mark.parametrize("path", [
    "ontology/eko-core.ttl",
    "skos/eko-schemes.ttl",
    "shapes/eko-shapes.ttl",
    "examples/worked_example.ttl",
])
def test_turtle_parses(path):
    g = load(path)
    assert len(g) > 0


# --------------------------------------------------------------------------
# The staleness rule fires on overdue content and stays silent on current
# content. This is the regression guard for the rdflib date-cast trap.
# --------------------------------------------------------------------------

STALE_TEMPLATE = """
@prefix eko:  <https://gov.tesseract.academy/def/knowledge#> .
@prefix ekos: <https://gov.tesseract.academy/def/knowledge/scheme#> .
@prefix ex:   <https://example.org/> .
@prefix xsd:  <http://www.w3.org/2001/XMLSchema#> .

ex:c a eko:MaintenanceCommitment ;
    eko:accountableOwner ex:someone ;
    eko:namedMaintainer ex:someone ;
    eko:reviewCadence "P1Y"^^xsd:duration ;
    eko:lastVerified "2020-01-01"^^xsd:date ;
    eko:nextReviewDue "{due}"^^xsd:date ;
    eko:scopeStatement "A scope statement long enough to satisfy the minimum length rule." ;
    eko:commitmentState ekos:commitment-active .

ex:asset a eko:KnowledgeAsset ;
    eko:underCommitment ex:c ;
    eko:authorityLevel ekos:authoritative ;
    eko:accessLabel ekos:internal ;
    eko:assetType ekos:policy ;
    eko:coversDomain ex:dom ;
    eko:lifecycleState ekos:published .

ex:dom a eko:Domain ;
    eko:domainExpert ex:someone ;
    eko:domainMaintainer ex:someone .
"""

STALE_MESSAGE = "past its own declared review date"


def _stale_graph(due: dt.date) -> Graph:
    g = Graph()
    g.parse(data=STALE_TEMPLATE.format(due=due.isoformat()), format="turtle")
    return g


def test_overdue_asset_is_flagged(shapes, ontology):
    due = dt.date.today() - dt.timedelta(days=400)
    found = messages(_stale_graph(due), shapes, ontology)
    assert any(STALE_MESSAGE in m for _, m in found), (
        "overdue asset was not flagged: the staleness rule is silently inert"
    )


def test_current_asset_is_not_flagged(shapes, ontology):
    due = dt.date.today() + dt.timedelta(days=400)
    found = messages(_stale_graph(due), shapes, ontology)
    assert not any(STALE_MESSAGE in m for _, m in found), (
        "an asset due in the future was flagged as overdue"
    )


# --------------------------------------------------------------------------
# The gate catches the defects the worked example was built to contain
# --------------------------------------------------------------------------

def test_worked_example_catches_expected_defects(shapes, ontology):
    data = load("examples/worked_example.ttl")
    found = messages(data, shapes, ontology)
    blob = " ".join(m for _, m in found)

    assert "working document is marked eligible for the retrieval index" in blob
    assert "holds a live canonical designation" in blob
    assert "names no successor" in blob
    assert "no named expert" in blob
    assert "Cite the instrument and provision" in blob
    assert "No outcome recorded" in blob


def test_compliant_asset_raises_no_violation(shapes, ontology):
    """The passing asset in the worked example must not appear as a violation."""
    data = load("examples/worked_example.ttl")
    _, results, _ = validate(
        data_graph=data, shacl_graph=shapes, ont_graph=ontology,
        inference="rdfs", advanced=True, allow_warnings=True,
    )
    violations = {
        str(results.value(r, SH.focusNode) or "").rsplit("/", 1)[-1]
        for r in results.subjects(RDF.type, SH.ValidationResult)
        if str(results.value(r, SH.resultSeverity) or "").endswith("Violation")
    }
    assert "eligibility-criteria" not in violations
    assert "commitment-eligibility" not in violations


# --------------------------------------------------------------------------
# Scanner internals
# --------------------------------------------------------------------------

def test_simhash_identical_text_matches():
    a = "the quick brown fox jumps over the lazy dog " * 40
    assert cri_scan.hamming(cri_scan.simhash(a), cri_scan.simhash(a)) == 0


def test_simhash_near_duplicate_is_close():
    base = "annual guidance on fee thresholds for the coming year " * 40
    variant = base.replace("coming year", "coming year 2026", 1)
    d = cri_scan.hamming(cri_scan.simhash(base), cri_scan.simhash(variant))
    assert d <= 3, f"near duplicate scored Hamming distance {d}"


def test_simhash_unrelated_text_is_far():
    a = "guidance on fee thresholds for regulated credit brokers " * 40
    b = "the maintenance schedule for rolling stock brake assemblies " * 40
    d = cri_scan.hamming(cri_scan.simhash(a), cri_scan.simhash(b))
    assert d > 10, f"unrelated documents scored Hamming distance {d}"


def test_simhash_short_text_returns_zero():
    assert cri_scan.simhash("two words") == 0


def test_normalise_title_strips_year_and_version_noise():
    assert cri_scan.normalise_title("Preston guidance: April 2016") == \
           cri_scan.normalise_title("Preston Guidance: April 2019")


def test_claim_extractor_reads_money_scales():
    claims = cri_scan.extract_claims("The threshold is £5 million and the fee is £250.")
    assert 5_000_000.0 in claims["money"]
    assert 250.0 in claims["money"]


def test_claim_extractor_reads_percentages():
    claims = cri_scan.extract_claims("A rate of 4.5% applies, or 12 per cent for others.")
    assert 4.5 in claims["pct"]
    assert 12.0 in claims["pct"]


def test_govuk_adapter_normalises_a_record():
    rec = {
        "content_id": "abc",
        "title": "Test",
        "link": "/test",
        "description": "d",
        "public_timestamp": "2024-01-01T00:00:00Z",
        "indexable_content": "x" * 1000,
        "organisations": [{"slug": "o", "title": "O", "organisation_state": "closed",
                           "organisation_closed_state": "no_longer_exists"}],
        "is_withdrawn": False,
        "content_store_document_type": "guidance",
        "part_of_taxonomy_tree": ["t"],
        "government_name": "g",
    }
    out = cri_scan.adapt_govuk(rec)
    assert out["owners"][0]["state"] == "closed"
    assert out["body_full_length"] == 1000
    assert out["updated"].year == 2024


def test_geometric_mean_penalises_a_single_bad_dimension():
    """A corpus is only as usable as its worst dimension."""
    import math
    strong = [100, 100, 100, 100, 100, 100, 5]
    geo = math.exp(sum(math.log(max(d, 1.0)) for d in strong) / len(strong))
    arithmetic = sum(strong) / len(strong)
    assert arithmetic > 86, "arithmetic mean conceals the failing dimension"
    assert geo < 70, "geometric mean must be dragged down by the worst dimension"
    assert geo < arithmetic - 20


# --------------------------------------------------------------------------
# Committed results are internally consistent
# --------------------------------------------------------------------------

def test_committed_cri_report_is_consistent():
    path = ROOT / "reports" / "cri_govuk.json"
    if not path.exists():
        pytest.skip("no committed CRI report")
    r = json.loads(path.read_text())
    d2 = r["D2_freshness"]
    assert sum(d2["age_buckets"].values()) == d2["documents_with_a_date"]
    assert d2["unchanged_over_5y"] >= d2["unchanged_over_10y"]
    assert d2["unchanged_over_2y"] >= d2["unchanged_over_5y"]
    assert 0 <= r["CRI"] <= 100
