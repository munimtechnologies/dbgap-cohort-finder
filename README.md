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
$ python snapshot.py ... devset -n 150 --out devset.json && python snapshot.py ... bench --devset devset.json --out bench.json
```

`example_needs.jsonl` holds eight example needs. The `devset` labels come
from the same snapshot fields the ranker reads, so `bench` catches
regressions but does not predict the official score. Snapshot mode is new
and hasn't been released yet. Its first full run on the snapshot
(2026-10-15, 150 `devset` needs) gave NDCG@10 0.614 for text-only BM25,
0.779 for conjunctive ranking without the disease check, 0.827 with it, and
0.879 when the variable score counts only for needs that name a variable.
Because these labels are circular, the numbers compare versions of the
ranker; they are not an estimate of the official score.

**Needs written as full sentences.** SPARK's own example need is one sentence
("Find dbGaP studies involving adult participants with lung adenocarcinoma as
the primary disease, where participant-level data include a history of smoking
or smoking exposure and whole genomic sequences."). `snapshot.py` alone ranks
the expected answer 37th on it, against 3rd on the short wording.
`sentence_need.py` reads that template (the disease from "X as the primary
disease", "data include ..." lists as variable needs, "whole genomic sequences"
as WGS) and leaves every other need as it was. It moves the expected answer to
2nd, with no change on 150 silver needs and 32 short needs. Since 0.2.0 it
also keeps the template's own words ("involving", "as the primary disease",
"participant-level") out of the text search. Eight short needs reworded into
the template now return exactly the same top 10 as their short forms, and the
expected answer on the submission-example wording moves from 3rd to 2nd. Use
`sentence_need.rank(index, sentence_need.parse_need(text), tier=0.6)`.
Results, limits and the pre-registered predictions:
[`sentence_need/`](sentence_need/README.md).

**Other wordings.** `wording_check.py` rewrites the 150 silver needs four more
ways with the disease unchanged (the official template, a question, a chat
line, synonyms such as "WGS" and "aged 18 or older"). NDCG@10 falls from
0.8943 to 0.8656, 0.8754, 0.7782 and 0.8846. The structured parse hardly
moves (at most 3 of 150 needs per wording). The loss comes from the text
search, which still gets the words of constraints that are already parsed,
and from "I'm", which leaves a stray "m" in every chat need's disease words. 4
of 7 pre-registered predictions held. Details:
[`wording_check/`](wording_check/README.md).

`wording_fix.py` takes contractions out and keeps the words of parsed
constraints out of the text search. On the same 750 needs it scores 0.9190,
0.9143, 0.9137, 0.9159 and 0.9159 (mean 0.9158, spread 0.0053, against 0.8596
and 0.1161), runs about three times faster, and keeps the official example's
expected study at 2nd. But 239 of its 750 lists hold fewer than 100 studies
(10 for the current system), so by the rule written before the run it is not
the default yet. A version that fills short lists is being tested. 8 of 9
pre-registered predictions held. Details: [`wording_fix/`](wording_fix/README.md).

**A local re-ranker (negative result).** `rerank_check.py` re-scored each
need's top 30 with NCBI's open-weight MedCPT cross-encoder on CPU and fused it
with the rule score. No weight beat the rules on 150 silver needs (0.8943 at
w = 0, 0.8928 at 0.25, 0.8178 with the cross-encoder alone), and it took about
20 s per need against 1.4 s. The rules stay the default. 5 of 6 pre-registered
predictions held. Details: [`rerank/`](rerank/README.md).

### Writing a submission

`spark_submit.py` writes a Task 2 submission with that ranker and checks it
against the format in the Task 2 description: one UTF-8 JSON object per line,
`metadata` with `team_id`, `submission_id`, `info_need_id` and the original
`info_need`, and `results`, an ordered list of study accessions that must all
be in the snapshot. `snapshot.py run` still works, but it uses `snapshot.py`'s
own parser and ranking, not the best measured one.

```
$ python make_needs.py --needs official_needs.jsonl sentence_needs.jsonl --devset devset.json --out needs.jsonl
$ python spark_submit.py --studies out/studies.jsonl --variables data/variables.jsonl.gz \
    --values data/var_values.jsonl.gz run --needs needs.jsonl --out submission.jsonl \
    --team-id <team> --submission-id <team>-run-01 --stats stats.json
$ python spark_submit.py --studies out/studies.jsonl check --needs needs.jsonl --submission submission.jsonl -k 100
```

On the full snapshot (192 needs, 2 CPUs, 2026-10-30) it loaded in 16 s,
ranked a need in 2.2 s on average (5.4 s at most) and peaked at 313 MB, with
0 format problems. One need got 94 results instead of 100, because studies
that match no word of a need are left out. Details and the pre-registered
predictions (5 of 7 held): [`submission/`](submission/README.md).

### Recording and checking hashes

The Task 2 description says NIH may ask for "cryptographic hashes or other
verifiable records" of software, indexes and data artifacts, and that these
must later match the versions documented at the deadline. `spark_manifest.py`
writes a SHA-256 manifest of a build and checks a rebuild against it:

```
$ python spark_manifest.py make --root . --out manifest.json out/studies.jsonl \
    data/variables.jsonl.gz data/var_values.jsonl.gz submission.jsonl
$ python spark_manifest.py verify --root rebuild --manifest manifest.json
```

The `.gz` files that `snapshot_survey.py` writes keep their write time in the
gzip header. A rebuild therefore changes their file hash even when the content
is the same. For those files the manifest also records the hash of the
uncompressed content, and `verify` reports them as "same content". With
`--strict`, "same content" counts as a mismatch.

On 2026-10-31 the whole pipeline (survey, `devset -n 150`, a 192-need
submission) was built twice from NLM's snapshot in one container, with
`PYTHONHASHSEED` set to 1 and then 2. All nine outputs matched. Seven were
byte-identical, including the 192-need submission. The two `.gz` files matched
by content; their bytes differed only in the header time. All 6 pre-registered
predictions held. This shows the build doesn't depend on Python's hash seed
on one machine and one image. It doesn't test other platforms or Python
versions. Hashes and the report: [`submission/`](submission/README.md).

### Docker system for SPARK Task 2

The Task 2 description asks for "a Docker-based system" that NIH can
reproduce and run "in a completely isolated environment with all external
network calls blocked", with an estimate of the compute and storage it needs.
`Dockerfile.spark` builds one in two stages on `python:3.12-slim`. The build
stage indexes NLM's `dbgap.tar.gz` with `spark_system.py build` and writes
`/index/MANIFEST.json`, the SHA-256 hashes of the index and of the seven code
files. The final image keeps only the code and four index files, not the
snapshot tarball.

```
$ docker build -f Dockerfile.spark -t munim-spark-dbgap .     # with dbgap.tar.gz next to the Dockerfile
$ docker run --rm --network none -v "$PWD/io:/io" munim-spark-dbgap run --needs /io/needs.jsonl \
    --out /io/submission.jsonl --team-id <team> --submission-id <team>-run-01 --stats /io/stats.json
$ docker run --rm --network none munim-spark-dbgap verify --strict
```

`noegress.py` runs a Python script with socket connects, sends and name
lookups refused and counted. Use it where `--network none` isn't available.

On 2026-10-31 the image's commands were run in a `python:3.12-slim`
container with 2 CPUs on the full snapshot. The build took 195 s and peaked
at 860 MB. A 192-need submission under `noegress.py` took 316 s: 1.6 s per
need on average, 2.8 s at most, 313 MB. It made 0 network attempts and had 0
format problems, and both manifest checks matched all 10 files. The index the
image holds is 29 MB; the code is 158 KB. The index and the submission were
byte-identical to the earlier builds made in `python:3.12` on another machine
with other hash seeds (the `.gz` files by content). All 7 pre-registered
predictions held. Limits: `docker build` itself has not been run yet, so the
Dockerfile's syntax and `COPY` steps are untested. `noegress.py` blocks only
Python-level calls; `--network none` is the real guarantee. Report and
hashes: `submission/image-2026-10-31.json` and
`submission/image-manifest-2026-10-31.json`.

A second, independent label set comes from PhenX curators' links between
PhenX measures and dbGaP studies: [`phenx_dev/`](phenx_dev/README.md). On it
a question-blind popularity list beats this finder by a wide margin, so read
any score on those labels next to the popularity score.

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

On the October 2026 harvest (3,612 studies, 300 silver questions) the
baseline scores NDCG@10 0.929 from metadata alone. Adding data-dictionary text
for the 2,098 studies that have it lowered that to 0.918 at the default weight
and 0.852 at weight 0.4. The silver questions never ask for a variable, so this
shows the dictionary score adds noise to condition-only questions, not that it
fails at "with X measured" questions. Snapshot mode also adds a variable score
to every need (weight 0.3), so its own benchmark has to show whether that score
should be limited to needs that name a variable.

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

**Results, October 2026: [`census/2026-10/`](census/2026-10/README.md).** Of
the enrolments with computed ancestry, 55.5% of European-ancestry (EUR) ones
sit in studies with a general research use group, against 43.4% of African
American (AFA) and 31.7% of Latin American (LEN) ones. Read the limits there
before quoting a share: they are study-level upper bounds.

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
no GPU and makes no network calls after the harvest. For the SPARK Task 2
system, use `Dockerfile.spark` (see above).

## Limitations

- These are rules and BM25, not a language model. Paraphrases the rules don't
  cover ("genome-scale") fall back to text matching. One local open-weight
  re-ranker (MedCPT) has been measured and did not help on the silver labels
  ([`rerank/`](rerank/README.md)).
- `sentence_need.py` was written for the one sentence template SPARK has
  published. Other wordings lose up to 0.12 NDCG@10 on the silver labels
  ([`wording_check/`](wording_check/README.md)); a measured fix is not the
  default yet ([`wording_fix/`](wording_fix/README.md)).
- `spark_submit.py check` follows the one example record in the Task 2
  description. NIH's later technical guidance may add rules.
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
and synthetic studies. They make no network calls and need no model.

## Changes

- Unreleased: snapshot mode (`snapshot_survey.py`, `snapshot.py`) for the
  official SPARK corpus, with participant age, reported race/ethnicity,
  data-dictionary needs, conjunctive ranking and SPARK submission output.
  Census results for October 2026 (`census/2026-10/`) and the first silver
  benchmark on the full harvest. PhenX labels (`phenx_dev/`, `phenx_crawl.py`)
  and their scoring code (`phenx_dev.py`, `phenx_dev_v2.py`, `phenx_dev_v3.py`).
  Sentence-style needs and primary-disease tiering (`sentence_need.py`, with
  `official_needs.jsonl`, `sentence_needs.jsonl` and the 2026-10-30 report in
  `sentence_need/`). `sentence_need.py` 0.2.0 leaves the sentence template's
  words out of text scoring (`scaffold_check.py` and
  `sentence_need/scaffold-report-2026-10-30.json`). `spark_submit.py` 0.1.0
  writes and checks a Task 2 submission with that ranker and reports time and
  memory; `make_needs.py` builds a test needs file (`submission/`).
  `spark_manifest.py` 0.1.0 records SHA-256 hashes of a build (with content
  hashes for `.gz` files) and checks a rebuild against them; two builds of the
  full pipeline matched (`submission/repro-2026-10-31.json`).
  `Dockerfile.spark`, `spark_system.py` 0.1.0 and `noegress.py`: the Task 2
  Docker system, its manifest checks and a Python-level network block, measured
  in `submission/image-2026-10-31.json`. `wording_check.py` 0.1.0 and its
  report (`wording_check/`); `rerank_check.py` 0.1.0 and its report
  (`rerank/`). `wording_fix.py` 0.1.0 and its report (`wording_fix/`), not
  yet the default.
- 0.2.0: public data dictionaries and sex counts (`dictionaries`, with
  `--budget-minutes`), abbreviations, conversational follow-ups (`chat`),
  silver dev set (`devset`), `bench`, `census`, better plural folding,
  Dockerfile. Relicensed from MIT to Apache-2.0.
- 0.1.0: harvest, search, run and evaluate.

## About

Made by MV2 of Munim, Inc. The code and this README were made with AI agents
working in his name. Issues and corrections are welcome.

Apache-2.0 license (see `LICENSE`). The census results in `census/` and the
reports in `sentence_need/`, `submission/`, `wording_check/`, `wording_fix/`
and `rerank/` are CC BY 4.0.
