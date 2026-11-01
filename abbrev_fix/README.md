# Disease abbreviations: letting a SPARK need say "SCLC" or "HIV"

`abbrev_fix.py` 0.1.0, checked 2026-11-01 on NLM's SPARK dbGaP snapshot (3,578 studies) in a `python:3.12`
container (2 CPUs, 54 minutes, 0.35 GB peak). Made with AI agents working in MV2's name (MV2, Munim, Inc.).
No person has checked these readings. Report: [`report-2026-11-01.json`](report-2026-11-01.json) (CC BY 4.0).

## Why

[`disease_check/`](../disease_check/README.md) found that naming a need's disease by an abbreviation cost the
ranker about 0.16 NDCG@10 on the silver labels, in two ways. Abbreviations the ranker didn't know ("SCLC",
"CTCL", "AATD", "NETs") matched no study's disease fields. And the abbreviation table itself replaced "HIV" with
"human immunodeficiency virus", while the studies store their disease as "HIV".

## What it does

Only needs that contain a disease abbreviation change. Words that are data types, consent or ancestry codes,
measurements, or part of a "with X measured" phrase are skipped. Every other need gets exactly the padded
default's list.

1. An unknown abbreviation is replaced by its most frequent long form among the snapshot's own definitions.
   These are mined from study titles, descriptions and disease terms written as "long form (SHORT)", with the
   Schwartz & Hearst rule (Pac Symp Biocomput 2003). 3,256 short forms are mined in 0.3 s.
2. While the need is ranked, a study's disease fit is the best of three things: the parsed topic, the
   abbreviation itself, and the need's topic as written. A mined long form that differs from the table's is
   also tried.

Abbreviation mining is standard in biomedical text processing. This applies it to SPARK Task 2 and measures it
on NLM's snapshot. It is engineering with a measured result, not a new method.

## Results (NDCG@10 on silver labels; base = the padded default, `spark_submit.padded_answer` 0.2.0)

| rows (short silver form) | needs | base | with abbrev_fix | change |
|---|---|---|---|---|
| disease as stored (d0) | 150 | 0.9190 | 0.9190 | 0 (no need changed) |
| un-inverted heading | 25 | 0.9025 | 0.9025 | 0 |
| everyday or clinical name | 73 | 0.8861 | 0.8912 | +0.0051 (one need: "HIV infection") |
| abbreviation, all | 39 | 0.7622 | 0.8698 | **+0.1076** |
| abbreviation in the table | 13 | 0.7635 | 0.8019 | +0.0384 |
| abbreviation not in the table | 26 | 0.7615 | 0.9038 | +0.1423 |

The official sentence template gives the same abbreviation figures; there, d0 reads 0.9143 with and without
the fix. Eight abbreviation rows rose, and none fell: CTCL, AATD and NETs 0 -> 1.0; HIV 0.5 -> 1.0; GVHD 0.63 ->
1.0; GBM 0.89 -> 1.0; CRC 0.66 -> 0.87; AMD 0.99 -> 1.0. A long form was mined for 37 of the 39
abbreviations and for 24 of the 26 the table lacks. None of the 750 reworded needs from
[`wording_check/`](../wording_check/README.md) set it off. The official example's expected study stays 2nd.
Abbreviated needs took about 2 s each (2.5 s at most per group).

**What is left.** About 70% of the abbreviation loss is recovered (0.154 -> 0.047). The rest comes from:
- HES: "hypereosinophilic syndrome (HES)" is not written anywhere in the snapshot, so nothing is mined.
- SCLC: the long form "small cell lung cancer" is mined, but the study's disease is stored as "carcinoma, small
  cell".
- Two small drops already present in the padded default: AUD and NAFLD.

## Pre-registered predictions: 11 of 11 held

The predictions were written before the run and are summarized here. The base reproduced the earlier `disease_check` numbers. No disease-as-stored or un-inverted need set
the fix off. At most 5 of 750 reworded needs were to set it off, and 0 did. The predicted minimum gains were
+0.03 for all abbreviations and +0.04 for those not in the table. The forecast for HIV was at least 0.9. The
predictions also required no loss on everyday names, the example study at rank 2, and at most 3.5 s per need.
By the rule written before the run, this fix becomes the default ranker in `spark_submit.py` 0.3.0. That
change is checked first, with its own Docker-image and hash check, under its own pre-registration. Until that
check passes, the published default is still `pad`.

## Limits

- Silver labels are circular: they come from `main_disease`, the field the matcher reads first.
- The 39 abbreviations were written by agents who had read the matcher. The fix was written after seeing which
  abbreviations failed, so the gain is measured in-sample and is optimistic.
- Mining picks the most frequent long form, which can be the wrong sense for an ambiguous short form ("HD",
  "AD").
- The best-of fit can raise unrelated studies that use the short form in their titles.
- There is one official example need. NLM's wording of its ~1,000 evaluation needs is unknown.

## Run it

```
python abbrev_check.py --studies out/studies.jsonl --variables data/variables.jsonl.gz \
    --values data/var_values.jsonl.gz --devset devset.json --needs official_needs.jsonl --out out
```

This needs `disease_check.py`, `wording_check.py`, `wording_fix.py`, `spark_submit.py`, `sentence_need.py`,
`snapshot.py` and `cohort_finder.py` from this repository. To run the tests: `python -m unittest -v test_abbrev_fix`.
