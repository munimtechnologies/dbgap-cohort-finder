# Disease abbreviations: letting a SPARK need say "SCLC" or "HIV"

`abbrev_fix.py` 0.1.0 was checked on 2026-11-01 on NLM's SPARK dbGaP snapshot (3,578 studies) in a `python:3.12`
container (2 CPUs, 54 minutes, 0.35 GB peak). It was checked out of sample on 2026-11-02, and 0.1.1 adds a
sense check that was tested the same day on 75 fresh needs (both below). Made with AI agents working in MV2's
name (MV2, Munim, Inc.). No person has checked these readings. Reports:
[`report-2026-11-01.json`](report-2026-11-01.json), [`oos-report-2026-11-02.json`](oos-report-2026-11-02.json)
and [`sense-report-2026-11-02.json`](sense-report-2026-11-02.json) (CC BY 4.0).

## Why

[`disease_check/`](../disease_check/README.md) found that naming a need's disease by an abbreviation cost the
ranker about 0.16 NDCG@10 on the silver labels, in two ways. Abbreviations the ranker didn't know ("SCLC",
"CTCL", "AATD", "NETs") matched no study's disease fields. And the abbreviation table itself replaced "HIV" with
"human immunodeficiency virus", while the studies store their disease as "HIV".

## What it does

Only needs that contain a disease abbreviation change. Words that are data types, consent or ancestry codes,
measurements, or part of a "with X measured" phrase are skipped. Every other need gets exactly the padded
default's list.

1. An unknown abbreviation is replaced by a long form taken from the snapshot's own definitions.
   These are mined from study titles, descriptions and disease terms written as "long form (SHORT)", with the
   Schwartz & Hearst rule (Pac Symp Biocomput 2003). 3,256 short forms are mined in 0.3 s. Since 0.1.1 the
   long form is the most frequent one that the snapshot also stores as a disease term (see "Sense check"
   below); 0.1.0 took the most frequent one.
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
short form with the wrong long form. Three of the four losses are that case. That led to the sense check below.

## Sense check (0.1.1, tested on fresh needs on 2026-11-02)

`abbrev_fix.py` 0.1.1 changes one thing. When a short form has several mined long forms, it takes the most
frequent one that the snapshot also stores as a disease term: a study's main disease or MeSH name, with "b, a"
headings also read as "a b". If none is stored, it falls back to 0.1.0's pick. `plan(..., sense=False)` and
`answer(..., sense=False)` give 0.1.0's behaviour exactly.

The sense check was written after reading the 24 out-of-sample needs above, so it was tested on needs nobody
had read. `abbrev_sense.py` 0.1.0 builds a fresh silver set (`devset -n 1000 --seed 11`: 422 needs), drops every
need whose disease is in the earlier seed-7 set (111) or among the 39 hand-picked diseases (39), and applies
`abbrev_oos`'s pick rule to the rest. 75 needs got a short form (197 had none). Each was ranked written with
the disease as stored (d0) and with the short form, in both sentence frames. Three systems were compared:
base = the 0.2.0 padded default, a = `abbrev_fix` 0.1.0 (`sense=False`, the 0.3.0 default as first released),
and b = `abbrev_fix` 0.1.1. It ran on 2026-11-02 (`python:3.12`, 2 CPUs, 27 minutes, 0.30 GB peak, 33 tests OK).

NDCG@10 on the short-form rows (v0_short frame; the official frame is within 0.02 and moves the same way):

| rows | needs | d0 | base | a (0.1.0) | b (0.1.1) | b - a |
|---|---|---|---|---|---|---|
| all picked | 75 | 0.9623 | 0.6376 | 0.8283 | **0.8816** | +0.0533 |
| sense changed by the check | 6 | 1.0 | 0.3363 | 0.3333 | 1.0 | +0.6667 |
| sense unchanged | 69 | 0.9590 | 0.6638 | 0.8713 | 0.8713 | 0 (no need changed) |

- **Up (4):** CM 0 -> 1 ("cryptococcal meningoencephalitis" -> coccidioidomycosis), HSP 0 -> 1 ("Henoch-Schönlein
  purpura" -> hereditary spastic paraplegia), WT 0 -> 1 ("wild-type" -> Wilms tumor) and GEP 0 -> 1 ("gene
  expression profile" -> "gene expression profiling", the stored form). For HSP and WT, 0.1.0 had made the
  need worse than the 0.2.0 default (1.0 -> 0 and 0.39 -> 0); 0.1.1 brings both to 1.0.
- **Unchanged score (2):** HSC and TGCT, where the check only swapped a singular for a plural.
- **Down:** none. No need whose sense stayed the same changed at all, and no disease-as-stored need changed.
- **Still wrong (by design):** when the wrong sense is itself a stored disease, the check keeps it. MM (the need
  meant meningomyelocele; mined "myeloma"), DM (dermatomyositis; "diabetes mellitus") and CHD (congenital heart
  defects; "coronary heart disease").
- Short-form needs took 2.6 s each on average with 0.1.1 (2.7 s with 0.1.0, 1.1 s with the 0.2.0 default). The
  official example's study stays 2nd in both wordings.

**Pre-registered predictions: 10 of 10 held**, after a gate that passed (12 files fetched, 33 tests OK, at least
30 needs picked). The check changed no need whose sense stayed the same (held) and no disease-as-stored need
(held). It did no net harm (held). With 6 needs changed (3 or more were needed for the test to count), it gained
+0.67 on them (at least +0.10 predicted, held), picked the disease for all 6 (at least half, held) and lowered
none (at most 1, held). The 0.3.0 default with 0.1.1 still beats the 0.2.0 default by +0.24 (at least +0.02,
held). 0.1.0's most frequent sense was the disease for 80% of the picks (at least 60%, held). Speed (at most
3.5 s per row) and the example's rank (2nd) held. By the rule written before the run, 0.1.1 replaces 0.1.0 on
`main`, so `spark_submit.py`'s `abbrev` default now uses the sense check. The Docker image's code hash changes
with it, and its image check is being re-run under its own pre-registration.

## Limits

- Silver labels are circular: they come from `main_disease`, the field the matcher reads first. The sense check
  also reads stored disease terms, so on silver needs the right sense is always one of them. This favours 0.1.1,
  and real needs may name diseases the snapshot does not store.
- The 39 abbreviations were written by agents who had read the matcher. The fix was written after seeing which
  abbreviations failed, so that gain is in-sample. The two out-of-sample checks above cover 24 and 75 needs, all
  with short forms the snapshot itself defines.
- Mining can pick the wrong sense of an ambiguous short form. 0.1.1 fixes this only when the wrong sense is not a
  stored disease ("OS" -> overall survival). When it is one ("SCA" -> sickle cell anemia, "MM" -> myeloma), the
  wrong sense stays.
- The best-of fit can raise unrelated studies that use the short form in their titles.
- Gene symbols such as "APOE" also set it off (harmless so far, since none was defined as a disease).
- There is one official example need. NLM's wording of its ~1,000 evaluation needs is unknown.

## Run it

```
python abbrev_check.py --studies out/studies.jsonl --variables data/variables.jsonl.gz \
    --values data/var_values.jsonl.gz --devset devset.json --needs official_needs.jsonl --out out
python abbrev_oos.py --studies out/studies.jsonl --variables data/variables.jsonl.gz \
    --values data/var_values.jsonl.gz --devset devset.json --out out
python snapshot.py ... devset -n 150 --seed 7 --out dev7.json
python snapshot.py ... devset -n 1000 --seed 11 --out dev11.json
python abbrev_sense.py --studies out/studies.jsonl --variables data/variables.jsonl.gz \
    --values data/var_values.jsonl.gz --devset dev11.json --exclude-devset dev7.json --max-picks 150 --out out
```

These need `disease_check.py`, `wording_check.py`, `wording_fix.py`, `spark_submit.py`, `sentence_need.py`,
`snapshot.py` and `cohort_finder.py` from this repository. To run the tests:
`python -m unittest -v test_abbrev_fix test_abbrev_oos test_abbrev_sense`.
