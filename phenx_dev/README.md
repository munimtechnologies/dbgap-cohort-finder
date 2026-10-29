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
| `per_protocol_counts.json` | For each of the 1,009 protocols: distinct dbGaP variables (phv) and studies (phs) on its page, in the xlsx, and on one side only |
| `crawl_report.json` | Totals and the parser sanity check |

The crawler is `../phenx_crawl.py` (standard library only, offline tests in `../test_phenx_crawl.py`).
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
