# Does the SPARK ranker give the same answers when a need is worded differently?

SPARK dbGaP Task 2 will judge about 1,000 natural-language needs nobody has
seen yet. MV2's ranker (`spark_submit.answer`: `sentence_need` 0.2.0's parse and
rank, primary-disease tiering at 0.6) was tuned on short silver needs and on the
one sentence template the Task 2 description shows. `wording_check.py` takes
the 150 silver needs of `snapshot.py devset -n 150` and writes each one four
more ways, with the disease copied unchanged:

| variant | example |
|---|---|
| v0_short | Studies of asthma in adults and with whole genome sequencing |
| v1_official | Find dbGaP studies involving adult participants with asthma as the primary disease, where participant-level data include whole genomic sequences. |
| v2_question | Which dbGaP studies enrolled adults diagnosed with asthma and have whole-genome sequencing data available? |
| v3_chat | I'm looking for asthma cohorts in adults that have WGS data. |
| v4_synonyms | Studies of asthma in participants aged 18 or older and with WGS |

```
$ python wording_check.py --studies out/studies.jsonl --variables data/variables.jsonl.gz \
    --values data/var_values.jsonl.gz --devset devset.json --out out
```

## Results (NLM's SPARK snapshot, 2026-10-31, code at main `ed6620d`)

| variant | NDCG@10 | needs lower / higher than v0 | constraint parse differs | disease topic differs |
|---|---|---|---|---|
| v0_short | 0.8943 | - | - | - |
| v1_official | 0.8656 | 18 / 5 | 3 | 3 |
| v2_question | 0.8754 | 24 / 12 | 3 | 3 |
| v3_chat | 0.7782 | 56 / 9 | 2 | 150 |
| v4_synonyms | 0.8846 | 17 / 17 | 0 | 4 |

The structured parse (data types, age, consent, race, variables) hardly moves:
at most 3 of 150 needs per wording read differently, and none for the
synonyms. Almost none of the loss comes from those needs (0.07 of 5.08 summed
NDCG for the official template). Two other causes show in the report:

- **The text search keeps constraint words.** BM25 still gets the words of
  constraints the parse has already scored, and each wording brings different
  ones: "whole genomic sequences" against "whole genome sequencing", "RNA
  sequencing data" against "RNA-seq", "pediatric" against "children". Exome
  needs fall from 0.9915 to 0.9412 in the template wording.
- **"I'm" leaves a stray letter.** The tokenizer splits "I'm" into "i" (a
  stopword) and "m" (not one), so "m" joins the disease words of every chat
  need.

A fix for both is being tested under its own pre-registration; until it is
graded the default ranker is unchanged.

## Pre-registered predictions (4 of 7 held)

Written on 2026-10-31 at about 00:50 UTC, before the job ran (08:00-08:20 UTC):

| | Prediction | Result |
|---|---|---|
| W1 | all 150 decompose and v0_short = 0.8943 | held |
| W2 | v1_official >= 0.8743 | failed (0.8656) |
| W3 | v2_question's topic differs on >= 75 needs | failed (3) |
| W4 | the worst variant is at least 0.03 below v0 | held (0.1161) |
| W5 | the worst variant is the question or the chat one | held (chat) |
| W6 | synonyms change the constraint parse on >= 15 needs | failed (0) |
| W7 | at most 3.0 s per need in every variant | held (1.47 s at most) |

The three failures share one cause: they expected the parser to be the weak
part, and it isn't.

## Limits

- Silver labels are built from the MeSH codes and fields the ranker reads, so
  they are circular. This measures how much the answers move with wording,
  not the official score.
- The four rewordings were written by the same agents who built the ranker,
  from one template each. Real needs will vary more.
- The disease phrase is never reworded here ("T2D" against "type 2 diabetes").

## Files

- `variants.jsonl`: the 750 needs (150 x 5), with the source id and constraint labels
- `report-2026-10-31.json`: per-variant summaries and, per need, NDCG@10, top 3
  accessions, parse and topic differences (ids, words and numbers only)

Made by MV2 of Munim, Inc. with AI agents working in his name. No person has
checked these readings. Code Apache-2.0; this README and the reports CC BY 4.0.
