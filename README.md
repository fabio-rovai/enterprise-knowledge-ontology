# Enterprise Knowledge Ontology (EKO) and the Corpus Readiness Index

**An open vocabulary, a machine-checkable publish gate, and a measurement
instrument for organisational knowledge in the age of retrieval.**

Every large organisation is now wiring its documents into an AI assistant, and
almost none of them can answer the question a serious engineer should ask
first: *is the knowledge any good?*

The market answers with adjectives. Content is "trusted", "curated", a "single
source of truth", "AI-ready". None of these are testable. This repository makes
them testable.

- **[`ontology/`](ontology/)** — an OWL vocabulary that formalises the
  distinction between a working document and an authoritative knowledge asset.
- **[`shapes/`](shapes/)** — a SHACL publish gate that enforces it, runnable in
  CI in front of a knowledge repository the way a linter runs in front of code.
- **[`pipeline/`](pipeline/)** — the Corpus Readiness Index scanner, plus the
  harvesters and probes used to produce the study below.
- **[`docs/CRI_SPEC.md`](docs/CRI_SPEC.md)** — the measurement specification.
- **[`reports/`](reports/)** — real results from a real corpus.

## The idea the whole thing rests on

Authority is not a property of content. It is a property of a **maintenance
commitment** attached to that content: a named accountable owner, a named
maintainer, a declared review cadence, a recorded date of last verification,
and a declared scope.

This has a sharp consequence. Whether something is a working document or a
knowledge asset has nothing to do with quality, length, formatting or where the
file lives. An excellent, thorough, beautifully written analysis with nobody
committed to maintaining it is a working document. A three-line page that a
named person re-verifies every quarter is a knowledge asset.

Retrieval systems get this exactly backwards. They rank on textual signals, so
a well-written working document outranks a maintained stub every time.

## The study: what 54,222 real documents look like

To find out whether any of this is measurable in practice, the scanner was run
against the guidance corpus of GOV.UK — 54,222 documents from a total estate of
708,433, harvested through the public Search API on 16 August 2026 under the
Open Government Licence.

GOV.UK was chosen because it is the largest content estate in the UK whose
metadata is public enough to audit openly, and because it is run by people who
take content lifecycle seriously. It is close to a best case. That is the
point: findings here are a floor, not a ceiling.

**Corpus Readiness Index: 78.2** (geometric mean of seven dimensions)

| Dimension | Score | The number that matters |
|---|---|---|
| D1 Commitment coverage | 91.1 | **0** documents carry a review cadence or a verification date |
| D2 Freshness | 36.5 | **34,444 (63.5%)** unchanged in over two years |
| D3 Canonicity | 98.2 | **935** topics have more than one live document |
| D4 Decommission hygiene | 93.6 | **~55,000** withdrawn pages advertised in the public sitemap |
| D5 Redundancy | 96.9 | largest near-duplicate cluster: **109 documents** |
| D6 Coherence | 94.0 | **181** contradiction candidates across 56 topics |
| D7 Retrieval fitness | 64.5 | **16,131 (29.7%)** have under 500 characters of indexable text |

### Finding 1 — The metadata to express a maintenance commitment does not exist

300 documents were sampled at random and fetched in full through the GOV.UK
Content API. Across every one of them, **133 distinct JSON keys** were observed
in the response schemas.

Not one of those keys expresses a review date, a next-review date, an expiry, a
verification date, a content owner, a maintainer, a steward, or a retention
rule. Zero documents out of 300 carried any field of that shape.

This is not a criticism of GOV.UK, which manages its estate better than most
organisations manage theirs. It is a statement about the state of the field.
The most sophisticated public content platform in the country has no way to
record who is on the hook for a page being true, or when anyone last checked.
Neither does Confluence, SharePoint or Notion out of the box.

Everything downstream follows from that absence. You cannot measure freshness
against a cadence that was never declared, and you cannot route a stale page to
an owner who was never named.

Reproduce: `python3 pipeline/probe_commitment_fields.py --sample 300`

### Finding 2 — The corpus is much older than it looks

Median time since last change is **3.69 years**. The distribution:

| Age since last change | Documents | Share |
|---|---|---|
| Under 1 year | 12,728 | 23.5% |
| 1 to 2 years | 7,050 | 13.0% |
| 2 to 5 years | 11,498 | 21.2% |
| 5 to 10 years | 12,499 | 23.1% |
| Over 10 years | 10,447 | 19.3% |

And this measure flatters the corpus, because it records the last *modification*
rather than the last *verification*. A typo fix resets it without anyone
checking a single fact. The honest number is unobtainable, because as Finding 1
shows, nobody records it.

The vivid version comes from GOV.UK's own publishing-era metadata. **13,595
live guidance documents are still tagged to the 2010–2015 coalition
government** — more than the 7,946 tagged to the current administration. Twelve
documents are attributed to the 1940–1945 Churchill national government and are
still being served today.

### Finding 3 — The curated index and the crawlable surface are different corpora

This is the finding with the sharpest engineering consequence, and it is the
one a competent team is most likely to miss.

GOV.UK's search index excludes withdrawn content **completely**: a query
filtered to withdrawn documents returns exactly zero results across the whole
708,433-document estate. That is better discipline than most enterprise estates
manage.

The withdrawn pages are nonetheless still there. They remain live at their
original addresses, they remain listed in the public sitemap, `robots.txt`
explicitly permits crawling them, and the Content API serves them in full with
their body text intact.

A random sample of 500 URLs drawn from GOV.UK's own sitemap was fetched through
the Content API:

- the sitemap advertises **864,397 URLs**, against a search index of **708,433**
- **32 of 499** successfully probed URLs were withdrawn — **6.41%**
  (95% confidence interval 4.26% to 8.56%)
- **25 of those 32** were still serving substantive body text
- median time since withdrawal: **5.87 years**; oldest: **12.35 years**

Extrapolated across the sitemap, that is roughly **55,000 withdrawn pages**
(95% CI: 36,900 to 74,000) offered to any crawler that asks.

One concrete case: `/guidance/nhs-test-and-trace-how-it-works` was withdrawn on
24 February 2022. It is absent from the search index. The Content API still
returns **43,671 characters** of authoritative-looking guidance for it today.

So the defect is not in the publisher's content governance, which is working.
It is that a retrieval pipeline built the obvious way — crawl the sitemap,
fetch the content endpoint, chunk, embed — ingests precisely the content the
curated index was careful to exclude. Every organisation building RAG over its
own estate is doing the equivalent, against a document store whose withdrawal
discipline is considerably worse than this one.

Reproduce: `python3 pipeline/probe_withdrawn.py --sample 500`

### Finding 4 — Ownership decays quietly

**4,810 documents (8.9%)** are owned only by organisations that are no longer
live. A further **127** are owned by a body GOV.UK records as having ceased to
exist entirely. Four have no owning organisation at all.

The oldest examples are striking: a 1955 NATO status-of-forces agreement still
attributed to the Foreign & Commonwealth Office, which was merged out of
existence in 2020; a 1991 building regulations document attributed to a
department under a name it held between 2018 and 2021.

Note the failure mode. Nobody deleted the owner. The owner was a department,
the department was reorganised, and the commitment silently transferred to
nobody. This is why EKO models the commitment as a first-class object with its
own lifecycle rather than as an attribute of the document: **a commitment that
lapses is invisible unless lapsing is a state something can be in.**

### Finding 5 — Redundancy concentrates in annual series

334 near-duplicate clusters covering 1,245 documents, detected by 64-bit
simhash over three-word shingles at a Hamming distance of 3. The largest single
cluster contains **109 near-identical documents** ("Preston guidance", one per
year from 2014 onwards).

Annual series are legitimate. The problem is that the year is in the title and
nothing else. No document declares in machine-readable form which period it
governs, so a retrieval system asked "what are the Preston rules?" selects from
109 candidates on textual similarity alone and presents one as the answer.

This is what the ontology's scope model is for, and it is the cheapest fix in
the whole framework: one date-range field per document collapses a 109-way
ambiguity into a single lookup.

### Finding 6 — Contradiction is tractable if you keep the extractor narrow

181 contradiction candidates across 56 topics, from a deliberately narrow
deterministic extractor that compares only monetary values and percentages
between documents sharing a normalised title.

Example: four separate Local Housing Allowance rate publications, all live, all
on the same normalised topic, asserting different percentage figures.

The design decision matters more than the count. Automated contradiction
detection over natural language has a false positive rate that makes unreviewed
output actively harmful: publish two thousand "contradictions" and every domain
owner will correctly ignore all of them. A narrow extractor producing 181
candidates a human can adjudicate in an afternoon is worth more than a broad
one producing thousands nobody reads.

### Finding 7 — A third of the corpus has nothing to retrieve

**16,131 documents (29.7%)** contain under 500 characters of indexable text.
Median body length across the corpus is 2,012 characters. A further 4,086
documents are absent from the site's own browse taxonomy.

These are overwhelmingly wrappers around attachments. The answer exists and is
fully documented; it is inside a PDF or a spreadsheet that the retrieval layer
sees as an opaque blob.

This is the single most common reason an assistant cannot answer a question its
organisation has demonstrably answered, and no amount of embedding-model
tuning addresses it. It is a content-format problem wearing an AI costume.

## The publish gate

The SHACL layer turns the framework into something enforceable. Running it
against the worked example:

```
$ python3 pipeline/validate.py

--- Violation (7) ---
  [pricing-scratchpad]     A working document is marked eligible for the retrieval
                           index. This is the mechanism by which a draft becomes an
                           organisation's answer.
  [canon-market-note]      A withdrawn or decommissioned asset holds a live canonical
                           designation.
  [affordability-approach] Asset is past its own declared review date but still claims
                           the 'published' state.
  [old-fee-schedule]       Asset is marked superseded but names no successor.
  [market-intelligence]    Domain has no named expert.
  [market-intelligence]    Domain has no named maintainer.
  [retention-marketing]    Cite the instrument and provision the retention period rests on.

--- Warning (4) ---
  [learning-panel-change]  No outcome recorded.
  [learning-panel-change]  No counterfactual recorded.
  ...
```

Exit status is non-zero when any violation is found, so this sits in CI.

### Why the negative rules are in SHACL and not OWL

OWL is open-world. The absence of a maintenance commitment in a graph does not
entail that no commitment exists, so no OWL reasoner will ever classify
something as a working document by absence. Every rule that matters here is of
the form "is there no owner recorded?", which is a closed-world question.

So the ontology states the necessary condition and the disjointness, and every
negative, corpus-scoped judgement is delegated to SHACL. Getting this boundary
wrong is the most common way a knowledge-governance ontology ends up looking
rigorous and enforcing nothing.

## Running it

```bash
pip install rdflib pyshacl numpy pytest

# corpus sizing only
python3 pipeline/harvest_govuk.py --counts

# full harvest (~54k documents, roughly 15 minutes, polite rate limiting)
python3 pipeline/harvest_govuk.py --out data/raw/govuk_guidance.jsonl

# the probes
python3 pipeline/probe_commitment_fields.py --sample 300
python3 pipeline/probe_withdrawn.py --sample 500

# the index
python3 pipeline/cri_scan.py --input data/raw/govuk_guidance.jsonl \
    --withdrawn-probe reports/withdrawn_probe.json \
    --out reports/cri_govuk.json

# the publish gate, and the tests
python3 pipeline/validate.py
python3 -m pytest tests/ -q
```

## Pointing it at your own estate

The scanner consumes a normalised record shape, so an adapter is the only new
code required:

```
id, title, url, description, updated, body, owners[], withdrawn,
doc_type, taxonomy[], era
```

Adapters for Confluence, SharePoint and Notion are a few dozen lines each. The
hard part is never the adapter. It is that your source system has no field for
cadence, no field for verification date, and an owner field populated with
whoever created the page in 2019.

Which is the finding.

## What is deliberately not here

- No claim that a high CRI means a good corpus. It means the corpus is
  measurable and maintained, which is a precondition, not a guarantee.
- No cross-organisation league table. Scores are for longitudinal use on one
  estate, and for argument.
- No LLM in the measurement path. Every number here is deterministic and
  reproducible from the committed scripts. Language models are useful for
  adjudicating the candidates the scanner surfaces; they have no business
  producing the counts.

## Provenance and honesty

Every figure in this README was computed from data fetched on 16 August 2026
and is regenerable from the committed scripts. Totals will drift as GOV.UK
publishes. See [`BUILD_REPORT.md`](BUILD_REPORT.md) for exactly what was
fetched, what was computed, what was sampled rather than enumerated, and what
could not be obtained.

Source data is not committed. GOV.UK content is available under the
[Open Government Licence v3.0](https://www.nationalarchives.gov.uk/doc/open-government-licence/version/3/);
the harvest is reproducible from the scripts in a single command.

## Licence

Ontology, shapes and vocabularies: CC BY 4.0. Code: MIT. See
[`LICENSE`](LICENSE).

## Who built this

Fabio Rovai, [The Tesseract Academy](https://www.thetesseractacademy.com)
(Kampakis and Co Ltd).

We build knowledge architecture for organisations that have decided their
document estate is now an AI input and have realised nobody can say whether it
is fit to be one. If you want the CRI run against your own corpus, or a publish
gate your teams will actually pass, the fastest route is to run
`pipeline/cri_scan.py` against an export yourself and send us the seven numbers.

**fabio@thetesseractacademy.com**

Issues and pull requests welcome, particularly adapters for other content
platforms and counter-examples where a CRI dimension mis-scores a corpus you
know well.
