# dbgap-cohort-finder

Ask a cohort-feasibility question in plain English and get a ranked list of
public [dbGaP](https://www.ncbi.nlm.nih.gov/gap/) studies that may fit, with
the reason each one made the list. You can do this before you file a Data
Access Request.

```
$ python cohort_finder.py harvest            # about 1,400 public studies -> studies.jsonl
$ python cohort_finder.py search "whole genome sequencing on at least 1,000 African American adults with type 2 diabetes, general research use"
Studies that may fit: ...
1. phs00xxxx.v1.p1 <study title> (2,345 subjects)
   - 2,345 subjects (wanted at least 1,000)
   - has wgs data
   - 1,210 AFA subjects by computed ancestry
   - consent GRU fits (general research use)
...
```

It uses **public metadata only**. It reads dbGaP's open
[FHIR API](https://dbgap-api.ncbi.nlm.nih.gov/fhir/x1) (`ResearchStudy`
resources), which covers each study's title, description, conditions (MeSH),
study design, consent groups, subject and sample counts, molecular data types
and dbGaP's computed (GRAF-pop) ancestry counts. It never touches
controlled-access data. Everything uses the Python standard library (3.8+),
with no install and no API key.

## Why

The National Library of Medicine's **SPARK dbGaP Task 2: Conversational Cohort
Feasibility & Privacy-Preserving Discovery** asks for exactly this. Systems must
answer feasibility questions from public dbGaP documentation, metadata and
aggregate statistics, returning ranked studies scored by NDCG
([challenge page](https://repository.niddk.nih.gov/data-challenge/challenges/100)).
Registration closes January 2, 2027, and the scored window runs January 15 to
February 1, 2027. This repository is an open, reproducible **baseline** for
that task and for anyone who needs to find dbGaP studies. It is not an official
NIH tool and is not affiliated with NIH or NLM.

## How it ranks

1. **Parse the question** into search words plus structured constraints:
   - a minimum number of participants ("at least 1,000", "5k+ participants"; ages
     and percentages are ignored)
   - molecular data types (WGS, exome, genotypes/GWAS, imputed, RNA-seq,
     methylation, ATAC-seq, single-cell, miRNA, ChIP-seq, proteomics, metabolomics)
   - study design (case-control, cohort, longitudinal, cross-sectional, family,
     clinical trial, tumor vs. matched normal)
   - ancestry, mapped to dbGaP's computed ancestry codes (EUR, AFA, AFO, LAC,
     LEN, EAS, SAS, OAS)
   - consent needs: general research use (GRU), health/medical/biomedical (HMB),
     for-profit use allowed (no `NPU`), no IRB approval required (no `IRB`)
2. **Score text relevance** with BM25 over the study metadata. Title and
   conditions count three times and the primary phenotype twice.
3. **Score how well each study meets the constraints**, from 0 to 1 per
   constraint. A field the study doesn't report counts as partly met rather than
   zero.
4. **Combine the two** as `0.6 × text + 0.4 × constraints`, using bigger studies
   as the tie-break. Every result lists the reasons behind it.

## Commands

| Command | What it does |
|---|---|
| `harvest --out studies.jsonl` | Download and normalize every public `ResearchStudy` (follows FHIR paging, 0.5 s between pages) |
| `search "question" [-k 10] [--json]` | Answer one question as text or JSON |
| `run --queries q.jsonl --out run.txt` | Answer a file of `{"id", "query"}` lines and write a TREC run (`qid Q0 phs rank score tag`) |
| `evaluate --run run.txt --qrels qrels.txt` | Mean NDCG@10 against TREC qrels (`qid 0 phs label`) |

`dev_queries.jsonl` has 12 example questions. The official SPARK evaluation
questions are only released near the end of the challenge window, and no
relevance judgments have been published. So the next step is a small
hand-judged dev set, scored with `evaluate`.

## Limitations

- These are rules and BM25, not a language model. Paraphrases the rules don't
  cover ("genome-scale") fall back to text matching. A re-ranking step with a
  local or hosted model is the planned next layer, and it will be measured
  against this baseline.
- Counts are study-wide. The tool can't tell how many of a study's 5,000
  subjects have the disease or the data type you asked about. dbGaP's
  aggregate tables and data dictionaries are the next source to add.
- Consent matching reads the consent codes (for example `HMB-IRB-NPU`), not
  the full data use limitation text.

## Tests

```
python -m unittest -v
```

The tests use a fixture shaped like the real FHIR record for phs001218
(GeneSTAR) plus three synthetic studies. They make no network calls.

## About

Made by MV2 of Munim, Inc. The code and this README were made with AI agents
working in his name. Issues and corrections are welcome. MIT license.
