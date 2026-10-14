# Census of public dbGaP studies, October 2026

How much of each computed-ancestry group in dbGaP sits in studies that a given
researcher can actually request, judged by the studies' consent groups.

- Built on 2026-10-14 by `cohort_finder.py harvest`, `dictionaries` and
  `census` (version 0.2.0) from dbGaP's public FHIR API and public data
  dictionaries. Files: [`census.md`](census.md), [`census.json`](census.json).
- 3,612 public studies; 3,611 report consent groups; 742 report dbGaP's
  computed (GRAF-pop) ancestry counts; 1,880 have a subject table with sex.

## What it shows

Each study enrolment was counted under the most open consent group of its
study. The share columns are the shares of each group's enrolments that sit in
studies with a general research use (GRU) group, with at least a
health/medical/biomedical (HMB) group, and with a group that allows for-profit
use (no `NPU`).

| Ancestry (GRAF-pop code) | Enrolments | Share of all | GRU | HMB or more open | For-profit allowed |
|---|---:|---:|---:|---:|---:|
| EUR | 1,717,435 | 70.8% | 55.5% | 75.1% | 74.3% |
| AFA | 334,592 | 13.8% | 43.4% | 76.5% | 74.5% |
| LEN | 111,452 | 4.6% | 31.7% | 67.0% | 76.7% |
| EAS | 90,603 | 3.7% | 56.9% | 67.2% | 70.4% |
| LAC | 52,148 | 2.1% | 43.7% | 75.7% | 75.5% |
| AFO | 44,106 | 1.8% | 63.3% | 78.5% | 84.7% |
| OTR | 28,336 | 1.2% | 48.5% | 71.9% | 76.5% |
| OAS | 27,584 | 1.1% | 65.6% | 78.1% | 58.5% |
| SAS | 20,858 | 0.9% | 50.7% | 74.8% | 71.6% |

- **General research use is less available for African American and Latin
  American enrolments.** 55.5% of European-ancestry (EUR) enrolments sit in
  studies with a GRU group, against 43.4% of African American (AFA), 43.7% of
  LAC and 31.7% of LEN (dbGaP's two Latin American codes) enrolments. East
  Asian (56.9%), African (AFO, 63.3%) and other Asian (OAS, 65.6%) enrolments
  are at or above the EUR share. Researchers whose project fits only general
  research use therefore reach a smaller share of these groups than of EUR.
- Most African American and Latin American enrolments are still reachable under
  an HMB use (AFA 76.5%, LAC 75.7%), so the gap is mostly about the GRU-only
  case. For LEN and East Asian (EAS) enrolments, a third sit in studies whose
  most open group is disease-specific or narrower (HMB or more open: 67.0% and
  67.2%).
- For-profit use is possible for 70-77% of most groups' enrolments, but only for
  58.5% of OAS enrolments.
- 3,083 of 3,611 studies (85.4%) have at least one consent group without `NPU`.
- Sex counts in shareable consent groups: 2,076,748 women and 1,765,220 men
  (54.1% women).

## Why this is new

dbGaP shows computed ancestry one study at a time. The closest earlier work
(Cell Genomics, 2023) mapped dbGaP consent groups to the GA4GH Data Use
Ontology from an October 2021 snapshot but did not cross them with ancestry. A
2024 bioRxiv paper on the representativeness of public RNA-seq data reviewed
publications for 312 dbGaP studies by hand. We found no published corpus-wide
table of computed ancestry by consent class.

## Limits

- **Study level, not consent-group level.** dbGaP reports computed ancestry for
  a whole study. A study is counted under its most open consent group even if
  only some of its participants consented to it, so the GRU, HMB and for-profit
  shares are upper bounds.
- **Enrolments, not people.** A person in several studies (for example a cohort
  and a TOPMed study built on it) is counted once per study.
- Only 742 of 3,612 studies report computed ancestry, mostly genotyped and
  sequenced studies; the table says nothing about the rest.
- GRAF-pop ancestry is computed from genotypes. It is not self-reported race or
  ethnicity, and its codes (EUR, AFA, AFO, LAC, LEN, EAS, SAS, OAS, OTR) are
  dbGaP's.
- Consent was read from the consent codes (for example `HMB-IRB-NPU`), not from
  the full data use limitation text. No study reported an `NRES` group in this
  harvest.

## Reproduce

```
python cohort_finder.py harvest --out studies.jsonl
python cohort_finder.py dictionaries --studies studies.jsonl --out studies_dict.jsonl --max-tables 40
python cohort_finder.py census --studies studies_dict.jsonl --out census
```

Made by MV2 of Munim, Inc. with AI agents. This text and the census files are
CC BY 4.0; the code is Apache-2.0. Built only from public dbGaP metadata; no
controlled-access data was used. Not an NIH product.
