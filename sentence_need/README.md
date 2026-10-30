# Needs written as full sentences (sentence_need.py, 2026-10-30)

SPARK dbGaP Task 2 writes its one worked example need as a sentence:

> Find dbGaP studies involving adult participants with lung adenocarcinoma as
> the primary disease, where participant-level data include a history of
> smoking or smoking exposure and whole genomic sequences.

The task's submission example words the last part as "whole-genome sequencing
data". Both name phs001954.v2.p1 as an expected answer.

`snapshot.py` was built and tested on short needs ("Adults with lung
adenocarcinoma as the primary disease, with smoking variables and whole genome
sequencing"), where it ranks phs001954.v2.p1 3rd. On the two official sentences
it ranks it **37th** and **19th**. Its parser gets three things wrong there:

1. "whole genomic sequences" is not read as whole genome sequencing.
2. "include a history of smoking or smoking exposure" is not read as a need for
   smoking variables.
3. The disease topic takes in "involving", "smoking", "exposure" and
   "genomic", so no study's primary disease can match it.

`sentence_need.py` fixes only these cases. It takes the disease from "X as the
primary disease" (or "primary disease is X"), reads the items of a "data
include ..." list as variable needs (an item's "or" alternatives count as one
need, met by the best of them), and reads "whole genomic sequences" as WGS.
A need without those cues parses exactly as before. `rank(..., tier=0.6)` also
sorts studies whose primary disease only mentions the asked disease after the
rest.

Since 0.2.0, the same sentences also keep their template words out of the
text-scoring (BM25) tokens: "involving", "as the primary disease",
"participant-level" and the like. `parse_need(text, strip=False)` gives the
0.1.0 parse.

## Result (0.1.0)

The test was pre-registered with eight predictions before it ran. Six held.
The job ran on the official SPARK snapshot (3,578 studies) on 2026-10-30.

Rank of phs001954.v2.p1 (lower is better):

| Wording | old parser | new parser | new parser + tier 0.6 |
|---|---|---|---|
| short (`example_needs.jsonl` ex1) | 3 | 3 | 2 |
| official sentence, task text | 37 | **2** | **2** |
| official sentence, submission example | 19 | **6** | **3** |

- **No change elsewhere:** the parse is the same on all 150 silver needs and on
  all 32 short example and hand-written needs. Silver NDCG@10 stays 0.888
  (0.8943 with tiering).
- **Wording stability:** eight short needs were reworded into the official
  template (`sentence_needs.jsonl`). The mean top-10 overlap between each short
  need and its sentence went from 0.825 to 0.9125 (0.8125 to 0.9375 with
  tiering). The pre-registered target was a rise of at least 0.10 for both, so
  the first half of that prediction failed (+0.0875). Most of the gain comes
  from one pair (asthma: 0.3 to 0.9).
- **Failed as expected:** a prediction that the 10-15 silver score (0.8791)
  would reproduce. `snapshot_survey.py` changed on 10-21, which changed the
  silver set.

Full output: [`report-2026-10-30.json`](report-2026-10-30.json) (both parses,
top 10 and reasons for every need).

## Result (0.2.0: template words left out of text scoring)

After 0.1.0, two of the eight sentence rewrites still shared only 8 of their
top 10 studies with their short forms, although they parsed the same. The
suspected cause was that `cohort_finder`'s stopwords cover "find", "dbgap",
"studies", "data" and "where", but not "involving", "primary", "disease" or
"level". So the template added those four words to every sentence's text
search. This was pre-registered with a gate and six predictions before the
job ran. The gate held (36 unit tests pass; the 0.1.0 numbers reproduce
exactly) and **all six predictions held**.

| | 0.1.0 | 0.2.0 | 0.1.0 + tier 0.6 | 0.2.0 + tier 0.6 |
|---|---|---|---|---|
| mean top-10 overlap, 8 short/sentence pairs | 0.9125 | **1.0** | 0.9375 | **1.0** |
| phs001954.v2.p1, official task text | 2 | 2 | 2 | 2 |
| phs001954.v2.p1, official submission example | 6 | **4** | 3 | **2** |

- Every one of the eight sentence rewrites now returns exactly the same top 10
  as its short form.
- The tokens change on all 10 sentence needs and on one short need (ex1, which
  says "as the primary disease"; its ranking is unchanged). The parse summary
  changes on none, and the 150 silver needs are untouched (NDCG@10 0.888 and
  0.8943 as before).
- On the submission-example wording, the tokens dropped were exactly
  "disease", "involving", "level" and "primary".

Full output: [`scaffold-report-2026-10-30.json`](scaffold-report-2026-10-30.json).
The script is `scaffold_check.py`.

## Limits

- There is **one** official example with a named answer, so this shows the
  parser no longer breaks on the official template. It does not show the
  ranker is good. The study ranked first on both official sentences
  (phs000488.v2.p1: lung adenocarcinoma in the title, WGS, smoking variables)
  may or may not count as relevant to NIH's experts.
- The silver labels come from the same fields the ranker reads, so they only
  catch regressions.
- The eight sentence rewrites were written by the same AI agents as the parser
  (before any run). Real SPARK needs may use other templates. Identical top
  10s show the parser is robust to this template, not that the ranking is
  right.

## Reproduce

```
python snapshot_survey.py --data data --out out
python snapshot.py --studies out/studies.jsonl --variables data/variables.jsonl.gz \
    --values data/var_values.jsonl.gz devset -n 150 --out out/devset.json
python sentence_need.py --studies out/studies.jsonl --variables data/variables.jsonl.gz \
    --values data/var_values.jsonl.gz --devset out/devset.json \
    --needs example_needs.jsonl hand_needs.jsonl official_needs.jsonl sentence_needs.jsonl \
    --out out/sentence_report.json
```

Run `scaffold_check.py` with the same arguments (and `--out
out/scaffold_report.json`) to compare 0.1.0 and 0.2.0. Each takes 10 to 30
minutes on 2 CPUs and under 0.7 GB of memory.

Made by MV2 of Munim, Inc. with AI agents working in his name. No person has
checked these readings. Code Apache-2.0; these reports and the JSON are CC BY 4.0.
