# The Corpus Readiness Index

**Version 0.1. A measurement instrument for organisational knowledge corpora.**

## Why this exists

Every organisation now has a programme to make its knowledge available to AI
systems, and almost none of them can answer the first question a serious
engineer should ask: *is the knowledge any good?*

The market answers that question with adjectives. Content is "trusted",
"curated", "single source of truth", "AI-ready". None of these are testable.
Vendors publish product claims about freshness and authority; no vendor
publishes an open method by which a buyer could check the claim against their
own estate.

The Corpus Readiness Index is that method. It is a set of seven measurements
that can be computed from a content estate's own metadata and text, with no
access to the vendor's index and no cooperation from the vendor. It produces
numbers that can be tracked over time, compared between departments, and argued
with.

It is deliberately unflattering. A corpus that scores well on the CRI is one
where somebody has done unglamorous work for a sustained period.

## The thesis the instrument encodes

Authority is not a property of content. It is a property of a **maintenance
commitment** attached to that content: a named accountable owner, a named
maintainer, a declared review cadence, a recorded date of last verification,
and a declared scope.

This is the load-bearing claim, and it has a sharp consequence. The distinction
between a working document and a knowledge asset is not about quality, length,
formatting or where the file lives. An excellent, thorough, beautifully written
analysis with nobody committed to maintaining it is a working document. A
three-line page that a named person re-verifies every quarter is a knowledge
asset. Retrieval systems get this exactly backwards, because they rank on
textual signals, and a working document written by a strong writer outranks a
maintained stub every time.

The full vocabulary is in [`ontology/eko-core.ttl`](../ontology/eko-core.ttl);
the publish gate that enforces it is in [`shapes/`](../shapes/).

## The seven dimensions

Each dimension yields a score from 0 to 100. Each is defined so that a higher
score is better and so that the underlying counts, not just the score, are
reported. **The counts matter more than the score.** A single number is useful
for tracking a trend and useless for deciding what to do on Monday.

### D1: Commitment coverage

*Can a named party be held to this content?*

Measured as the share of the corpus for which a live, identifiable owner
exists. The strict form of the measure requires all four commitment elements
(owner, maintainer, cadence, last-verified date). Most estates cannot be
measured in the strict form at all, because the fields do not exist. That is
itself the finding, and it should be reported as a null result rather than
quietly relaxed into something more flattering.

Sub-measures worth reporting separately:

- documents with no owner of any kind
- documents whose only owner is a team, rota, mailbox or org unit that no
  longer exists
- documents carrying a machine-readable review cadence
- documents carrying a machine-readable verification date

### D2: Freshness

*Is the content within its own declared review cadence?*

The honest version of this measure requires a declared cadence per document.
Where none exists, freshness degrades to **age since last modification**, which
is a substantially weaker proxy and must be labelled as such. Last-modified and
last-verified are different quantities: a typo fix resets the first without
touching the second, and content systems record only the first.

Report the age distribution, not the mean. Knowledge estates have long tails
and the tail is where the damage is.

### D3: Canonicity

*Is there one authoritative source per topic, or several?*

Measured as the share of topics for which exactly one live asset is designated
canonical. Where formal designation does not exist, approximate topics by
normalised title and count the groups containing more than one live document.

The sub-measure that matters most: **contested groups under a single owner**.
Two departments publishing on the same subject is a coordination problem. One
department publishing four live pages on the same subject is a maintenance
problem, and it is the one that produces confidently wrong retrieval answers,
because all four sources look equally legitimate to the ranker.

### D4: Decommission hygiene

*Is content the organisation has disowned actually gone?*

Measured as the share of retrievable content that has been withdrawn,
superseded or decommissioned but remains addressable and ingestible.

The critical subtlety, and the one that catches well-run estates: the curated
search index and the crawlable surface are not the same corpus. A publisher can
do withdrawal correctly in its own search product while continuing to serve the
withdrawn content at its original address, in its sitemap, and through its
content API. A retrieval pipeline built the obvious way, crawl the sitemap,
fetch the content endpoint, chunk, embed, ingests everything the curated index
was careful to exclude.

So D4 must be measured **against the surface the retrieval pipeline actually
consumes**, not against the surface the publisher curates. Measuring the wrong
one produces a perfect score and a false sense of safety.

### D5: Redundancy

*How much of the corpus is the same thing again?*

Measured by near-duplicate detection over document bodies. The reference
implementation uses 64-bit simhash over three-word shingles with banded
candidate generation and a Hamming threshold of 3.

Redundancy is not automatically a defect. Annual series, per-jurisdiction
variants and translations are legitimate. What matters is whether the near
identical copies are **distinguished by scope**: if six documents differ only
in a year and none of them declares which year it governs in a machine-readable
way, a retrieval system will pick one at random and present it as the answer.

### D6: Coherence

*Do documents on the same topic contradict each other?*

Measured as the share of topics with at least one contradiction candidate,
where a candidate is a pair of documents on the same topic asserting disjoint
values for the same class of fact.

This dimension must be reported as **candidates, not contradictions**.
Automated contradiction detection over natural language has a false positive
rate that makes unreviewed output actively harmful to a governance programme:
publish a list of two thousand "contradictions" and the domain owners will
correctly ignore all of them. A narrow, deterministic extractor that produces
a hundred candidates a human can adjudicate in an afternoon is worth more than
a broad one that produces thousands nobody will read.

### D7: Retrieval fitness

*Is there anything here a retrieval system can actually use?*

Measured as the share of documents that carry a description, are reachable
through the estate's own navigation, and contain enough indexable text to
answer anything.

The dominant failure is not poor chunking strategy. It is that the answer is
inside an attachment. A page that is a title, a paragraph of preamble and a
link to a spreadsheet is a fully documented answer that no retrieval system can
reach. Estates routinely discover that a large minority of their content is
this shape, and that no amount of embedding-model tuning will fix it.

## Scoring

The headline CRI is the **geometric mean** of the seven dimension scores.

This is deliberate. An arithmetic mean lets a strong dimension conceal a fatal
one, and a corpus is only as usable as its worst dimension. An estate that is
immaculately owned, perfectly deduplicated and entirely locked inside PDF
attachments is not 85% useful; it is unusable, and the score should say so.

Scores should never be compared between organisations without comparing the
underlying counts and the adapter used. The instrument is designed for
longitudinal use on one estate, and for argument, not for a league table.

## Applying it to a private estate

The reference implementation ships a GOV.UK adapter because GOV.UK is the
largest content estate whose metadata is public enough to audit openly. The
scanner consumes a normalised record shape, so an adapter is the only new code
required for a private corpus:

```
id, title, url, description, updated, body, owners[], withdrawn,
doc_type, taxonomy[], era
```

Adapters for Confluence, SharePoint and Notion are a few dozen lines each. The
harder problem is never the adapter. It is that the source system has no field
for cadence, no field for verification date, and an "owner" field populated
with whoever created the page in 2019.

Which is the point.
