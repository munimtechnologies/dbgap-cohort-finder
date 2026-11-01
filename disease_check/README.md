# Disease names: does the SPARK ranker still find the studies when a need names the disease the way people do?

`disease_check.py` 0.1.0, run 2026-11-01 on NLM's SPARK dbGaP snapshot (3,578 studies) in a `python:3.12`
container (2 CPUs, 27 minutes, 0.39 GB peak). Made with AI agents working in MV2's name (MV2, Munim, Inc.).
No person has checked these readings. Report: [`report-2026-11-01.json`](report-2026-11-01.json) (CC BY 4.0).

## Why

The 150 silver dev needs copy each study's `main_disease` as dbGaP stores it, often as an inverted heading
("carcinoma, hepatocellular") or a MeSH plural ("stomach neoplasms"). The one official Task 2 example says
"lung adenocarcinoma", the way a person writes it. `wording_check` moved the framing with the disease fixed; this
moves only the disease and keeps the framing fixed.

## What was run

Each need's disease is written four ways: `d0_as_is`; `d1_uninverted` (comma headings turned around, 25 needs);
`d2_natural` (73 everyday or clinical names, such as "gastric cancer", "high blood pressure", "Crohn's disease");
`d3_abbrev` (39 abbreviations: 13 that `cohort_finder`'s table spells out and 26 it does not). Each is written in
the short silver form and in the official sentence template, and only needs whose text changes are run (574
rows). Systems: `base` = `spark_submit.answer` 0.1.0 and `fix` = `wording_fix.answer` 0.1.0. "fit" is the share
of a need's relevant studies whose disease still meets the primary-disease tier with the parsed topic.

## Results (short silver form, NDCG@10 on silver labels)

| variant | needs | base: as is -> renamed (drop) | fix: as is -> renamed (drop) | needs losing their disease |
|---|---|---|---|---|
| un-inverted heading | 25 | 0.8649 -> 0.8649 (0) | 0.9025 -> 0.9025 (0) | 0 |
| everyday or clinical name | 73 | 0.9017 -> 0.8463 (0.056) | 0.9282 -> 0.8861 (0.042) | 3 |
| possessive (Parkinson's...) | 4 | 0.9077 -> 0.9077 (0) | 0.9077 -> 0.9077 (0) | 0 |
| abbreviation, all | 39 | 0.9170 -> 0.7546 (0.163) | 0.9166 -> 0.7622 (0.154) | 8 |
| abbreviation in the table | 13 | 0.8444 -> 0.7437 (0.101) | 0.8538 -> 0.7635 (0.090) | 2 |
| abbreviation not in the table | 26 | 0.9534 -> 0.7600 (0.193) | 0.9480 -> 0.7615 (0.187) | 6 |

In the official template the drops are similar: everyday names 0.033 (base) and 0.034 (fix), abbreviations
0.156 and 0.154. Un-inverting headings changed 3 of 25 needs there (2 up, 1 down).

- **Everyday names cost little** (0.03-0.06). Plural folding, the synonym table, word order not mattering and
  the MeSH entry terms in study records absorb most of them.
- **Abbreviations cost about 0.16.** "SCLC", "CTCL", "AATD", "HES" and "NETs" lose the disease entirely. Many
  others still work ("FSGS", "PCOS", "HCC", "GBM", "OCD", "IPF") because study records carry them.
- **Two failure modes are visible in the rows.** (a) The abbreviation table can hurt: it replaces "HIV" with
  "human immunodeficiency virus", but those studies store their main disease as "HIV", so fit falls from 1.0 to
  0 and NDCG@10 from 1.0 to 0.5. (b) An extra word breaks the topic match: "coronary artery disease" (and "CAD",
  which the table expands to "coronary artery") fails studies whose disease is "coronary disease" (NDCG@10 1.0 ->
  0.356).

## Pre-registered predictions: 2 of 10 held

The predictions (written before the run) expected everyday names to cost at least 0.10 and abbreviations in the
table to cost at most 0.10. Both were wrong: everyday names cost much less, and abbreviations in the table cost
0.1007. Held: the as-is rows reproduce the earlier run exactly, and every group ran under 3.5 s per need (2.5 s
at most). By the rule written before the run, the matcher stays as it is for everyday names. An abbreviation
fix (keep the short form next to its expansion; look up unknown abbreviations in the snapshot's own disease
terms) is the next candidate, to be tested under its own pre-registration.

## Limits

Silver labels are circular: they come from `main_disease`, the field the matcher reads first. The names and
abbreviations were written by agents who had read the matcher's code. 150 needs, one snapshot, one official
example need; NLM's wording of its ~1,000 evaluation needs is unknown.

## Run it

```
python disease_check.py --studies out/studies.jsonl --variables data/variables.jsonl.gz \
    --values data/var_values.jsonl.gz --devset devset.json --out out
```

Needs `wording_check.py`, `wording_fix.py`, `spark_submit.py`, `sentence_need.py`, `snapshot.py` and
`cohort_finder.py` from this repository. Tests: `python -m unittest -v test_disease_check`.
