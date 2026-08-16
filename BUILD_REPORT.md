# Build report

A scrupulous record of what was actually fetched, computed, sampled and
assumed, so that every figure in the README can be checked or contradicted.

**Build date:** 16 August 2026
**Machine:** macOS, Python 3.13, rdflib 7.6.0, pyshacl, numpy 2.4.6

## What was fetched

| Source | Endpoint | Method | Result |
|---|---|---|---|
| GOV.UK Search API | `https://www.gov.uk/api/search.json` | Paged, 100 per request, 0.25s between requests, custom User-Agent | 54,222 documents across 10 guidance-family document types |
| GOV.UK Content API | `https://www.gov.uk/api/content{path}` | 300 random paths from the harvest | 300 full documents, 133 distinct JSON keys observed |
| GOV.UK Content API | same | 500 random paths from the sitemap | 499 fetched, 1 error |
| GOV.UK sitemap | `https://www.gov.uk/sitemap.xml` plus 35 sub-sitemaps | Full enumeration | 864,397 URLs |

All endpoints are public, documented, unauthenticated. `robots.txt` was checked
and permits everything used here; the only disallowed paths are `/search/all*`
and `/*/print$`, neither of which was fetched. Content is Crown copyright under
the Open Government Licence v3.0.

## Corpus definition

The "guidance family" is a judgement call and should be treated as one. It is
the set of GOV.UK document types whose purpose is to be an authoritative answer
someone acts on, as opposed to news, transcripts, statistical releases or
case-by-case decisions:

| Document type | Documents |
|---|---|
| `guidance` | 25,253 |
| `detailed_guide` | 10,302 |
| `notice` | 6,235 |
| `form` | 4,924 |
| `manual_section` | 2,676 |
| `international_treaty` | 1,703 |
| `statutory_guidance` | 1,296 |
| `guide` | 857 |
| `regulation` | 801 |
| `manual` | 175 |
| **Total** | **54,222** |

Harvested count matched the API's own reported total exactly, which is the
check that the pagination did not silently truncate.

Whole-estate total at time of harvest: **708,433** documents.

Including `international_treaty` is what produces the 81-year maximum age. That
is real rather than an artefact — historic treaties genuinely are live guidance
pages — but anyone uncomfortable with it can rerun with `--types` restricted
and the headline numbers barely move, because treaties are 3.1% of the corpus.

## What is a sample rather than an enumeration

Two of the seven findings rest on samples, and are reported with that
uncertainty rather than as corpus facts:

- **Finding 1 (commitment fields):** 300 documents, random, seed 20260816.
  The result was an exact zero, so no confidence interval is quoted; a zero in
  300 gives a 95% upper bound of roughly 1% on the true rate.
- **Finding 3 (withdrawn content):** 500 URLs, random, seed 20260816, of which
  499 fetched successfully. 32 withdrawn, 6.41%, 95% CI 4.26% to 8.56% by
  normal approximation. The extrapolation to ~55,000 URLs across the sitemap is
  a point estimate carrying that interval, and is stated as such.

Everything else (D1 ownership counts, D2 ages, D3 title groups, D5 clusters,
D6 candidates, D7 lengths) is a full enumeration over all 54,222 documents.

## Known limitations, stated plainly

**D2 measures the wrong thing, and has to.** `public_timestamp` is time since
last modification, not since last verification. These are different quantities.
The corpus does not publish the second, which is Finding 1. Every freshness
number in this study is therefore an upper bound on how well-maintained the
corpus is.

**D3 approximates topics by normalised title.** Real canonicity requires formal
designation, which no corpus in this study performs. Title normalisation strips
years, version markers and part numbers, so it groups annual series together
deliberately. It will also occasionally group genuinely distinct documents that
happen to share a stripped title. The 935 contested groups should be read as an
upper bound needing human triage, not a defect count.

**D5's threshold is a choice.** Hamming distance ≤ 3 on a 64-bit simhash over
three-word shingles, with the first 1,500 tokens of each body. A different
threshold gives a different cluster count. The banding step skips buckets with
more than 400 members to bound the pair comparison, which means a small number
of very large clusters may be under-counted; this makes the redundancy figure
conservative.

**D6 produces candidates, not contradictions.** The extractor compares only
monetary values and percentages between documents sharing a normalised title.
It cannot tell that two figures differ legitimately because they govern
different years — indeed the Local Housing Allowance example almost certainly
is legitimate variation across years, and is included precisely to show what a
candidate looks like before adjudication. The number is a triage queue length,
not a defect count.

**D7 conflates two things.** A page with little indexable text is usually an
attachment wrapper, but may also be a genuine stub or a redirect-like landing
page. No attempt was made to separate these, so the 29.7% figure is an upper
bound on the attachment-wrapper problem.

**Bodies are truncated at 40,000 characters on load**, because the near-
duplicate pass reads the first 1,500 tokens and the claim extractor the first
20,000 characters. Full body length is retained separately and is what D7
reports, so no length statistic is affected by the truncation.

**GOV.UK is close to a best case.** It has a dedicated content profession,
published standards, an explicit withdrawal workflow, and a search index that
correctly excludes withdrawn material. Findings here should be read as a floor
for a typical enterprise estate, not a representative sample of one. Nothing in
this study licenses a claim about what a specific private corpus scores.

## What could not be obtained

- **Any maintenance commitment metadata.** This is Finding 1 and the reason the
  strict form of D1 is reported as a null result rather than a percentage.
- **A machine-readable enumeration of withdrawn content.** GOV.UK's search API
  returns zero for `filter_is_withdrawn=true`, because withdrawn documents are
  removed from the index rather than flagged within it. Withdrawn content is
  therefore only reachable by sampling the sitemap, which is what
  `probe_withdrawn.py` does, and is why D4 is a sampled estimate.
- **`first_published_at` at corpus scale.** The field exists on the Content API
  but not the Search API, so obtaining it for all 54,222 documents would mean
  54,222 individual requests. Not attempted. All age figures use
  `public_timestamp` from the Search API.
- **Outbound link graphs.** The Search API returns indexable text, not links,
  so "withdrawn content still linked from live pages" could not be measured.
  This would have been the strongest form of D4 and remains open.
- **FCA Handbook.** Considered as a financial-services corpus and not pursued
  in this build. No verified machine-readable access route was established.
  Any future claim about it must be preceded by an actual successful fetch.

## Defects found in this build, and fixed

Recorded because a build report that lists no mistakes is not a build report.

1. **The percentage extractor silently matched nothing.** `_PCT` ended in `\b`
   after an alternation containing `%`. Since `%` is itself a non-word
   character, "4.5% applies" has no word boundary between the sign and the
   space, so every percentage written with a sign was dropped. Caught by a unit
   test, not by inspection. The full scan was rerun after the fix; D6 candidates
   rose from 141 to 181.

2. **The staleness rule was inert, then over-fired, then was correct.** In
   rdflib 7.6.0 both `xsd:dateTime(?due) < NOW()` and `?due < xsd:date(NOW())`
   return no rows rather than raising, producing a SHACL rule that appears to
   pass and never fires. The uncast form `?due < NOW()` compares xsd:date to
   xsd:dateTime and flagged every asset including future-dated ones. The
   working form is lexicographic `STR(?due) < STR(NOW())`, which is correct for
   ISO-8601 and is guarded by two regression tests using a known-overdue and a
   known-future date.

3. **D4 initially scored a perfect 100 and was measuring nothing.** The GOV.UK
   search index excludes withdrawn content entirely, so `is_withdrawn` is false
   for every document it returns. Scoring decommission hygiene against the
   curated index gives a flawless result and a false sense of safety. D4 is now
   scored against the crawlable surface, and the scanner says so explicitly in
   its output when no crawlable-surface probe is supplied.

4. **The first harvest appeared to stop at 9,399 documents.** It had not; the
   background process was still running and the file was being read mid-write.
   Recorded because it nearly led to a wrong conclusion about a pagination cap
   that does not exist.

## Verification performed

- All four Turtle files parse under rdflib (`ontology` 314 triples, `skos` 253,
  `shapes` 234, `examples` 102).
- The SHACL gate was run against a worked example built to contain seven
  specific defects and one compliant asset. It reports exactly those seven
  violations and four warnings, and does not flag the compliant asset.
- 18 unit tests pass, covering the date-comparison regression, simhash
  behaviour on identical, near-duplicate and unrelated text, the claim
  extractors, the adapter, and internal consistency of the committed report.
- Harvested document count reconciles exactly with the API's reported total.

## Reproducing

```bash
pip install rdflib pyshacl numpy pytest
python3 pipeline/harvest_govuk.py --out data/raw/govuk_guidance.jsonl
python3 pipeline/probe_commitment_fields.py --sample 300
python3 pipeline/probe_withdrawn.py --sample 500
python3 pipeline/cri_scan.py --input data/raw/govuk_guidance.jsonl \
    --withdrawn-probe reports/withdrawn_probe.json --out reports/cri_govuk.json
python3 pipeline/validate.py
python3 -m pytest tests/ -q
```

Random seeds are fixed at 20260816 in both probes. Counts will drift from the
published figures as GOV.UK publishes, withdraws and reorganises; the
directional findings should not.
