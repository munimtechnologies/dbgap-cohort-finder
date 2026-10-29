# PhenX -> dbGaP study links, read from PhenX Toolkit's own protocol pages

An open copy of which dbGaP studies PhenX curators have linked to each PhenX protocol, taken from the
"Mapped dbGaP Studies" tables on the protocol pages of the [PhenX Toolkit](https://www.phenxtoolkit.org), and a
comparison with PhenX's downloadable `Variable_cross_reference.xlsx`. Built as labels for testing dbGaP study
search (practice for NIH's SPARK dbGaP challenge). Made with AI agents working in MV2's name (MV2, Munim, Inc.);
no person has checked these readings.

## Files
| File | What it holds |
|---|---|
| `qrels_pages.txt` | 9,654 lines `PX###### 0 phs###### 1`: protocol -> study, from the pages (TREC qrels format) |
| `qrels_union.txt` | 10,926 lines, same format: pages and xlsx combined, 321 protocols, kept to the 3,668 studies in dbGaP's public study list on 2026-10-29 (the labels scored below) |
| `per_protocol_counts.json` | For each of the 1,009 protocols: distinct dbGaP variables (phv) and studies (phs) on its page, in the xlsx, and on one side only |
| `crawl_report.json` | Totals and the parser sanity check |
| `scores-2026-10-29.json` | The scoring job's `report.json`, unchanged |

The crawler is `../phenx_crawl.py` (standard library only, offline tests in `../test_phenx_crawl.py`). The
scoring code is `../phenx_dev.py`, `../phenx_dev_v2.py` and `../phenx_dev_v3.py`, with offline tests next to them.
Ids and counts only; no page text or variable descriptions are copied here.

## How it was made
On 2026-10-29 (04:12-07:17 UTC) the crawler read PhenX's protocol list (1,009 protocols), downloaded
`Variable_cross_reference.xlsx` ("With mappings" sheet), then fetched every `/protocols/view/<id>` page once,
at least 10 seconds apart as PhenX's robots.txt asks. 0 fetch errors, 0 pages left. It parses each
"Mapping for PX..." table into study id, variable id and description, and counts per protocol. A sanity check
against three pages saved by an earlier probe job (PX030301, PX180801, PX161301) matched exactly.

## What it shows
- **The pages hold more than the download.** 257 current protocols show mapped studies on their pages:
  15,272 distinct dbGaP variables and 603 distinct studies. The xlsx has 10,014 variables, 508 studies and
  182 protocol ids in all.
- **139 protocols with mappings on their pages have no row in the xlsx.** For the 120 xlsx protocols still on
  the list, 66 (55%) are missing variables their pages show (e.g. Perceived Stress, PX180801: 13 variables in
  5 studies on the page, 3 variables in 3 studies in the xlsx); 54 match. Only 200 of the xlsx's 6,021
  variables for those protocols are absent from the pages, so the xlsx is mostly short, not different.
- **The xlsx also holds protocol ids the list no longer shows.** 62 of its 182 ids are not on PhenX's current
  protocol list, and they carry 3,993 of its 10,014 variables. One checked example: PX751501 now redirects to
  a sub-collection page listing PX751502 under the same name, and PX751502's page shows no mapped studies.
  Whether those variables reappear on the pages under newer ids was not measured.
- **The sheet ends at exactly 30,000 rows** (header included), sorted by protocol id, last id PX751501, while
  14 later protocols show mappings on their pages (e.g. PX810301, PX811301, PX820102). That is consistent with
  an export row limit; we do not know PhenX's process. Short protocols also occur well inside the file
  (191 protocols below PX751501 have page-only variables), so a row limit is not the whole story.
- **Neither source alone is complete.** For a study-retrieval test set, the union of both is the fullest
  label set we know of.

Seven predictions about these numbers were written down before the crawl ran; all seven held. Two of three
follow-up predictions about the row limit held; the third could not be tested (PX751501 is no longer listed).

## Scoring a study finder on these labels (2026-10-29)
Each protocol becomes one question, its name ("Current Age"), and its linked studies are the relevant ones.
`phenx_dev_v3.py` harvested dbGaP's public study list (3,668 studies, 19:30 UTC), ran dbgap-cohort-finder
(commit dfc1638) once per question, and scored it next to a question-blind baseline: every labelled study ranked
by how many *other* protocols link to it (leave-one-out popularity). Unlabelled studies count as not relevant;
"condensed" drops them from the finder's list first, which is the fairer finder number because the baseline only
ever ranks labelled studies.

| Labels | Questions | finder NDCG@10 | finder, condensed | popularity NDCG@10 |
|---|---|---|---|---|
| xlsx | 182 | 0.053 | 0.164 | 0.583 |
| pages | 257 | 0.046 | 0.142 | 0.557 |
| union | 321 | 0.050 | 0.149 | 0.566 |
| 118 shared protocols, xlsx labels | 118 | 0.044 | 0.130 | 0.575 |
| 118 shared protocols, page labels | 118 | 0.051 | 0.148 | 0.605 |

- **On PhenX labels, popularity wins by a wide margin.** A median question has 6 linked studies, but a few large
  cohorts are linked to hundreds of protocols, so a list that ignores the question finds them for almost every
  question (recall@100 0.80-0.91 against the finder's 0.10-0.13).
- **So a finder score on PhenX labels means little without the popularity score beside it.** We do not quote
  the finder's numbers alone.
- **The fuller page labels credit the finder slightly more** on the 118 protocols both sources cover
  (0.051 vs 0.044), as expected when labels are added for studies it already ranks.
- **Limits.** Bare protocol names are much shorter than SPARK's sentence-style needs, and PhenX links say a study
  measured something, not that the study is about it. These numbers describe the labels, not how the finder
  would score on SPARK's expert key.

Eight predictions were written down before the job ran (the gate check plus seven); all eight held.

## Limits
- Ids are compared per protocol id; renamed or re-versioned protocols are not matched to their predecessors.
- Pages change with each PhenX release; this is a 2026-10-29 snapshot.
- A study linked to a protocol means curators matched at least one of its variables, not that the study is
  about that topic.

## Prior work and credit
PhenX Toolkit: Hamilton CM et al., "The PhenX Toolkit: Get the Most From Your Measures", Am J Epidemiol 2011,
doi:10.1093/aje/kwr193. The PhenX-dbGaP links are the curators' work, described in Pan H et al.,
"Identifying Datasets for Cross-Study Analysis in dbGaP using PhenX", Sci Data 2022,
doi:10.1038/s41597-022-01660-4 (13,653 mapped variables from 521 studies at a 2017 freeze; no dataset
deposited). PhenX says its protocols are "freely available; permission not required for use". We found no
earlier public file of these links taken from the pages, and no public note that the xlsx is partial.

## Licence
Data files in this folder: CC BY 4.0, with the PhenX attribution above. Code: Apache-2.0.

MV2, Munim, Inc., mv2@munimtech.com
