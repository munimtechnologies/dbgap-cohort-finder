# dbgap-cohort-finder

Ask a cohort-feasibility question in plain English and get a ranked list of
public [dbGaP](https://www.ncbi.nlm.nih.gov/gap/) studies that may fit, with
the reason each one made the list. You can do this before you file a Data
Access Request.

```
$ python cohort_finder.py harvest            # every public study -> studies.jsonl
$ python cohort_finder.py dictionaries       # optional: add public data dictionaries and sex counts
$ python cohort_finder.py search "whole genome sequencing on at least 1,000 African American adults with T2D, general research use, with HbA1c measured"
Studies that may fit: ...
1. phs00xxxx.v1.p1 <study title> (2,345 subjects)
   - 2,345 subjects (wanted at least 1,000)
   - has wgs data
   - 1,210 AFA subjects by computed ancestry
   - consent GRU fits (general research use)
   - data dictionary mentions: hba1c, glycated, hemoglobin
...
```

It uses **public metadata only**:

- dbGaP's open [FHIR API](https://dbgap-api.ncbi.nlm.nih.gov/fhir/x1)
  (`ResearchStudy` resources). This covers each study's title, description,
  conditions (MeSH, with entry terms), study design, consent groups, subject
  and sample counts, molecular data types and dbGaP's computed (GRAF-pop)
  ancestry counts.
- dbGaP's public phenotype **data dictionaries** and **variable summary
  reports** (`pheno_variable_summaries` on
  [ftp.ncbi.nlm.nih.gov/dbgap/studies](https://ftp.ncbi.nlm.nih.gov/dbgap/studies/)).
  These give variable names, descriptions and units, plus male and female counts
  in the shareable consent groups.
- Or, in **snapshot mode** (below), the fixed public snapshot that NLM
  published for the SPARK challenge.

It never touches controlled-access data. Everything uses the Python standard
library (3.8+), with no install and no API key.

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

## Snapshot mode (the official SPARK corpus)

SPARK judges answers only against a fixed snapshot,
[dbgap.tar.gz](https://ftp.ncbi.nlm.nih.gov/dbgap/NLM_Challenge/) (1.5 GB,
August 2026: 3,578 studies and 465,853 variables). A study counts as relevant
only if it meets **every** stated need, for example adults + lung
adenocarcinoma + smoking variables + WGS. Two files work on that snapshot:

- `snapshot_survey.py` streams the archive once, without unpacking it. It
  writes one compact record per study (`studies.jsonl`), every variable
  (`variables.jsonl.gz`), the coded values of enumerated variables
  (`var_values.jsonl.gz`) and a census. From each dataset's aggregate
  `var_summary.xml` it also reads:
  - **participant age**: the age variable with the most values, preferring
    age at enrollment, baseline or visit. Ages at diagnosis or onset, and the
    ages of parents, are skipped. Months and days are converted to years.
  - **reported race and ethnicity**: counts from the study's largest coded
    race or ethnicity variable, with labels from `data_dict.xml`, mapped to
    coarse groups.

  Many study records leave the population label empty (MESA's does), so
  these counts are often the only population evidence in the snapshot.
- `snapshot.py` ranks the studies for an information need. It reuses
  `cohort_finder`'s parser and BM25 index and adds four things:
  - age needs ("adults", "children", "aged 40-60", "65 and older")
  - race/ethnicity needs checked against those counts
  - "with X variables / X measured" needs checked against the data dictionary
  - conjunctive ranking: a study that clearly fails a need ranks below every
    study that doesn't

  It writes submissions in the SPARK Task 2 JSONL format.

```
$ python snapshot_survey.py --data data --out out          # downloads dbgap.tar.gz once
$ python snapshot.py --studies out/studies.jsonl --variables data/variables.jsonl.gz \
    --values data/var_values.jsonl.gz ask "adults with lung adenocarcinoma, smoking variables and WGS"
$ python snapshot.py ... run --needs needs.jsonl --out submission.jsonl --team-id <team>
$ python snapshot.py ... devset -n 150 --out devset.json && python snapshot.py ... bench --devset devset.json --out bench.json
```

`example_needs.jsonl` holds eight example needs. The `devset` labels come
from the same snapshot fields the ranker reads, so `bench` catches
regressions but does not predict the official score. Snapshot mode is new
and hasn't been released yet. Its first full run on the snapshot is
pending.

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
   - sex ("women", "female", "men", "male"), checked against the subject counts
     in the shareable consent groups
   - consent needs: general research use (GRU), health/medical/biomedical (HMB),
     for-profit use allowed (no `NPU`), no IRB approval required (no `IRB`)
   - about 50 common abbreviations are spelled out (T2D, CAD, COPD, AD, HbA1c,
     LDL, BMI, eGFR, MRI and others). Abbreviations of three letters or fewer
     only count in capitals, so "ad hoc" is not read as Alzheimer disease.
2. **Score text relevance** with BM25 over the study metadata. Title and
   conditions (including MeSH entry terms) count three times and the primary
   phenotype twice. Plurals are folded ("cohorts" -> "cohort"), but words that
   only look plural ("diabetes", "mellitus", "fibrosis", "species") are kept.
3. **Score how well each study meets the constraints**, from 0 to 1 per
   constraint. A field the study doesn't report counts as partly met rather than
   zero.
4. **Combine them** as `0.6 × text + 0.4 × constraints + 0.2 × dictionary`.
   The dictionary score is a second BM25 over the words in the study's variable
   names and descriptions, so "with LDL measured" favours studies that measured
   LDL. Bigger studies win ties. Every result lists the reasons behind it.

Counts from 1 to 10 are shown as "fewer than 11" in the explanations, following
the usual small-cell rule for aggregate health data.

## Conversation

`chat` reads one question per line. A line that starts like a follow-up
("only those with WGS", "and also European ancestry", "what about Hispanic
participants?", "what about asthma?") refines the previous question instead of
starting a new one:

- plain follow-ups add constraints
- "what about ..." or "... instead" replaces constraints of the same kind
- "what about <topic>?" with no constraints changes the topic and keeps the
  constraints
- `reset` starts over

```
$ python cohort_finder.py chat
type 2 diabetes studies
only those with whole genome sequencing
what about chronic kidney disease?
```

## Commands

| Command | What it does |
|---|---|
| `harvest --out studies.jsonl` | Download and normalize every public `ResearchStudy` (follows FHIR paging, 0.5 s between pages) |
| `dictionaries [--cache dictionary_cache] [--max-tables 200] [--budget-minutes 0]` | Add each study's public data dictionaries and sex counts to `studies.jsonl`, about 3 requests a second. Each study is cached, so an interrupted run resumes. With `--budget-minutes`, downloading stops after that time and the output is written from what is cached; run it again to continue. |
| `search "question" [-k 10] [--json]` | Answer one question as text or JSON |
| `chat` | Answer questions from standard input; follow-ups refine the last question |
| `run --queries q.jsonl --out run.txt` | Answer a file of `{"id", "query"}` lines and write a TREC run (`qid Q0 phs rank score tag`). Prints the time taken. |
| `evaluate --run run.txt --qrels qrels.txt` | Mean NDCG@10 against TREC qrels (`qid 0 phs label`) |
| `devset [-n 100] [--seed 7]` | Build silver questions and graded qrels from the harvested studies (see below) |
| `bench --queries q.jsonl --qrels qrels.txt [--out bench.json]` | NDCG@10, MRR and recall@10 for the baseline and nine variants (text only, no dictionary, other weights, other BM25 settings) on the same questions |
| `census [--out census]` | Aggregate counts over every harvested study, written to `census.json` and `census.md` (see below) |

### Silver development set

The official SPARK evaluation questions are only released near the end of the
challenge window, and no relevance judgments have been published. `devset`
builds a repeatable stand-in from the harvest. Each question names one MeSH
condition, by its preferred term or an entry term. It may add a data type, a
minimum size and an ancestry group, all taken from one study coded with that
condition, so at least one study fully meets the question. Every study coded
with the condition is judged 2 if it meets all the constraints, and 1 if not.

```
$ python cohort_finder.py devset -n 300
$ python cohort_finder.py bench --queries silver_queries.jsonl --qrels silver_qrels.txt
```

These labels come from metadata codes, not from experts. Studies of closely
related conditions that lack the exact MeSH code count as not relevant. Use the
score to compare versions of the ranker, not to predict the official score.
`dev_queries.jsonl` has 12 hand-written example questions without judgments.

## Census: who in dbGaP can be studied, and under which consent

`census` adds up, over every public study:

- consent groups by primary code (NRES, GRU, HMB, DS, other) and modifier
  (IRB, NPU, PUB, COL, MDS...), and each study's most open group
- how many studies have at least one consent group that allows for-profit use
  (no `NPU`)
- dbGaP's computed (GRAF-pop) ancestry counts, split by the most open consent
  in the same study and by whether for-profit use is possible
- studies by molecular data type, ancestry in studies with WGS, and (after
  `dictionaries`) sex counts in shareable consent groups

The question it answers is how much of each ancestry group in dbGaP sits in
studies that a given user can actually request. An earlier analysis
(Cell Genomics, 2023) mapped dbGaP consent groups to the GA4GH Data Use
Ontology from an October 2021 snapshot. It did not cross consent with computed
ancestry. Limits: ancestry is reported for a whole study, not per consent group,
and people enrolled in more than one study (for example a cohort and a TOPMed
study built on it) are counted once per study.

`snapshot_survey.py` writes a second census from the SPARK snapshot. It covers
consent classes, study-level population labels, data types, participant age
bands (children only, adults only, both, 65+ only) and reported race/ethnicity,
summed from the coded variables of top-level studies.

## Docker

```
$ docker build -t dbgap-cohort-finder .
$ docker run --rm -v "$PWD:/data" -w /data dbgap-cohort-finder harvest
$ docker run --rm -v "$PWD:/data" -w /data dbgap-cohort-finder search "COPD with WGS"
```

The image is `python:3.12-slim` plus one file. Ranking runs on a CPU, needs
no GPU and makes no network calls after the harvest.

## Limitations

- These are rules and BM25, not a language model. Paraphrases the rules don't
  cover ("genome-scale") fall back to text matching. A re-ranking step with a
  local open-weight model (SPARK allows no hosted model APIs at run time) is
  the planned next layer. It will be measured against this baseline with
  `devset` and `bench`.
- Counts are study-wide. The tool can't yet tell how many of a study's 5,000
  subjects have the disease or the data type you asked about.
- Consent matching reads the consent codes (for example `HMB-IRB-NPU`), not
  the full data use limitation text.
- Sex counts come from each study's subject table. Studies whose subject table
  has a different name get no sex counts, and those count as partly met.
- In snapshot mode, the participant-age and race/ethnicity readings are
  rule-based picks from variable names and labels. Each pick is written to
  `age_candidates.jsonl` and `studies.jsonl`, so it can be checked. Race and
  ethnicity are reported or study-assigned categories, not genetic ancestry.

## Tests

```
python -m unittest -v
```

The tests use fixtures shaped like the real FHIR record and the real data
dictionary files for phs001218 (GeneSTAR), a synthetic snapshot archive shaped
like the real `var_summary.xml` and `data_dict.xml` files of phs000001 (AREDS),
and synthetic studies. They make no network calls.

## Changes

- Unreleased: snapshot mode (`snapshot_survey.py`, `snapshot.py`) for the
  official SPARK corpus, with participant age, reported race/ethnicity,
  data-dictionary needs, conjunctive ranking and SPARK submission output.
- 0.2.0: public data dictionaries and sex counts (`dictionaries`, with
  `--budget-minutes`), abbreviations, conversational follow-ups (`chat`),
  silver dev set (`devset`), `bench`, `census`, better plural folding,
  Dockerfile. Relicensed from MIT to Apache-2.0.
- 0.1.0: harvest, search, run and evaluate.

## About

Made by MV2 of Munim, Inc. The code and this README were made with AI agents
working in his name. Issues and corrections are welcome.

Apache-2.0 license (see `LICENSE`).
