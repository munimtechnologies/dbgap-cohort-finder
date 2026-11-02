# Disease abbreviations: letting a SPARK need say "SCLC" or "HIV"

`abbrev_fix.py` 0.1.0, checked 2026-11-01 on NLM's SPARK dbGaP snapshot (3,578 studies) in a `python:3.12`
container (2 CPUs, 54 minutes, 0.35 GB peak), and checked out of sample on 2026-11-02 (below). Made with AI
agents working in MV2's name (MV2, Munim, Inc.). No person has checked these readings. Reports:
[`report-2026-11-01.json`](report-2026-11-01.json) and [`oos-report-2026-11-02.json`](oos-report-2026-11-02.json)
(CC BY 4.0).

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
By the rule written before the run, this fix became the default ranker in `spark_submit.py` 0.3.0, after its
own image and hash check in a `python:3.12-slim` container (10 of 10 pre-registered predictions held on
2026-11-02; `docker build` itself has not been run yet).

## Out of sample (2026-11-02)

The 39 abbreviations above were chosen by agents who had read the matcher, so the gain above is in-sample.
`abbrev_oos.py` 0.1.0 picks abbreviations with no human or agent choice. It takes every silver need whose
disease is not one of the 39 and finds the short form that the snapshot's own text defines most often with that
disease as its long form ("... uveal melanoma (UM) ..."). Each picked need is written with the disease as
stored (d0) and with the short form, in both sentence frames. Each is ranked by the 0.2.0 default (padded) and
by the 0.3.0 default (padded + `abbrev_fix`). The test ran on 2026-11-02, after 0.3.0 reached `main` (2 CPUs,
18 minutes, 0.31 GB peak, 31 tests OK).

Of 150 silver needs, 39 were excluded (their disease is one of the 39), 87 have no such short form, and 24
were picked. Both frames give the same figures:

| rows | needs | d0 | 0.2.0 default | 0.3.0 default | change |
|---|---|---|---|---|---|
| all picked | 24 | 0.9630 | 0.6284 | 0.7547 | **+0.1263** |
| most frequent mined sense is the disease | 18 | 0.9507 | 0.6712 | 0.9507 | +0.2795 (all of the loss) |
| most frequent mined sense is something else | 6 | 1.0 | 0.5000 | 0.1667 | -0.3333 |

- **Up (7):** AB (ameloblastoma) 0 -> 1, GEX 0 -> 1, CMs 0 -> 1, EHRs 0 -> 1, HB (hepatoblastoma) 0.63 -> 1,
  UM (uveal melanoma) 0.80 -> 1, FA (Fanconi anemia) 0.5 -> 1.
- **Down (4):** SCA 1 -> 0 (mined as "sickle cell anemia"; the need meant spinocerebellar ataxias), IA 0.39 -> 0
  ("islet autoantibody", not intracranial aneurysm), LD 0.61 -> 0 ("linkage disequilibrium", not Lyme disease),
  and HTN 0.146 -> 0.113 (the same as its d0 score).
- **Zero under both:** OS (mined as "overall survival", not osteosarcoma) and AD (in the table as Alzheimer
  disease; this need meant atopic dermatitis).
- No need that names its disease as stored changed. The official example's study stays 2nd. Abbreviated needs
  took about 3 s each (1.2 s with the 0.2.0 default).

**Pre-registered predictions: 6 of 8 held.** It does no net harm (held) and gains at least +0.02 (held).
It does not change disease-as-stored needs (held). For 18 of the 24 needs, at least 70% as predicted, the
most frequent mined sense is the disease (held). Needs where it is not gain less than the rest (held), and a
need takes at most 3.5 s (held). Two predictions failed. The 0.3.0 default was to win back at least half of
the 0.2.0 default's loss and won back 38%. At most 2 needs were to fall, and 4 did. The 0.3.0 default stays.

**What this shows.** When the snapshot's most frequent definition of a short form is the need's disease,
`abbrev_fix` wins back the whole loss. When it is another sense, it makes things worse, because it replaces the
short form with the wrong long form. Three of the four losses are that case. A sense check that prefers long
forms the snapshot stores as a disease term is being tested on fresh needs under its own pre-registration.
Until it has been graded, it is not in `abbrev_fix.py` on `main`.

## Limits

- Silver labels are circular: they come from `main_disease`, the field the matcher reads first.
- The 39 abbreviations were written by agents who had read the matcher. The fix was written after seeing which
  abbreviations failed, so that gain is in-sample. The out-of-sample check above covers 24 needs, all with short
  forms the snapshot itself defines.
- Mining picks the most frequent long form, which can be the wrong sense for an ambiguous short form. This
  happened for 6 of 24 out-of-sample needs ("OS", "LD", "IA", "SCA", "AD", "CFSs").
- The best-of fit can raise unrelated studies that use the short form in their titles.
- Gene symbols such as "APOE" also set it off (harmless so far, since none was defined as a disease).
- There is one official example need. NLM's wording of its ~1,000 evaluation needs is unknown.

## Run it

```
python abbrev_check.py --studies out/studies.jsonl --variables data/variables.jsonl.gz \
    --values data/var_values.jsonl.gz --devset devset.json --needs official_needs.jsonl --out out
python abbrev_oos.py --studies out/studies.jsonl --variables data/variables.jsonl.gz \
    --values data/var_values.jsonl.gz --devset devset.json --out out
```

These need `disease_check.py`, `wording_check.py`, `wording_fix.py`, `spark_submit.py`, `sentence_need.py`,
`snapshot.py` and `cohort_finder.py` from this repository. To run the tests:
`python -m unittest -v test_abbrev_fix test_abbrev_oos`.
