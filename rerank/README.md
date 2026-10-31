# Does a local cross-encoder improve the SPARK ranking? (negative result)

SPARK dbGaP Task 2 allows only open-weight models, run with no network. MV2's
ranker is rules plus BM25 (`sentence_need` 0.2.0, tiering 0.6). The main README
had listed "a local open-weight re-ranker" as the planned next layer.
`rerank_check.py` measures one: NCBI's MedCPT cross-encoder
([`ncbi/MedCPT-Cross-Encoder`](https://huggingface.co/ncbi/MedCPT-Cross-Encoder)),
run on CPU with torch 2.5.1 and transformers 4.46.3.

For each need, the ranker's top 30 studies are re-scored on "title.
Conditions: ... description" (up to 384 tokens), and

    fused = (1 - w) * minmax(rule score) + w * minmax(cross-encoder score)

reorders them only within the same group of (needs failed, weak disease
match). A study that fails a stated need never jumps above one that meets it.
At w = 0 the rule order must come back exactly, and it did on every need.

```
$ pip install torch transformers
$ python rerank_check.py --studies out/studies.jsonl --variables data/variables.jsonl.gz \
    --values data/var_values.jsonl.gz --devset devset.json --needs official_needs.jsonl --out out
```

## Results (NLM's SPARK snapshot, 150 silver needs, 2 CPUs, 2026-10-31)

| w | NDCG@10 | needs higher / lower than w = 0 |
|---|---|---|
| 0 (rules) | 0.8943 | - |
| 0.25 | 0.8928 | 16 / 16 |
| 0.5 | 0.8746 | 17 / 26 |
| 1.0 (cross-encoder only) | 0.8178 | 17 / 44 |

On both official wordings of the Task 2 example, the expected study
(phs001954.v2.p1) stays 2nd at every w. The cross-encoder took 19.8 s per need
on average (25.1 s at most) for 30 pairs, against 1.4 s for the rules. The
process peaked at 1.2 GB.

**The rules stay the default.** No weight beat them, and at about 20 s per
need, 1,000 evaluation needs would take about 6 hours on 2 CPUs (rules plus
cross-encoder) against about 23 minutes for the rules alone.

## Pre-registered predictions (5 of 6 held)

| | Prediction | Result |
|---|---|---|
| P1 | w = 0 gives 0.8943 +- 0.002 | held |
| P2 | w = 0.25 is within 0.02 of w = 0 | held (-0.0015) |
| P3 | w = 1.0 is below w = 0 | held (0.8178) |
| P4 | at w = 0.25 the expected study is in the top 3 on both official wordings | held (2nd, 2nd) |
| P5 | at most 8 s per need on average and 20 s at most | failed (19.8 s, 25.1 s) |
| P6 | peak memory at most 2,000 MB | held (1,223 MB) |

## Limits

- Silver labels come from the MeSH codes the rules read directly, so they
  favour the rules. A cross-encoder that helps on real needs could still lose
  here. This result says "no gain on these labels, at this cost", not "the
  model hurts".
- MedCPT was trained on PubMed queries and articles, not dbGaP study records.
- Two official wordings are one example.
- CPU times come from 2 shared CPUs.

## Files

- `report-2026-10-31.json`: settings, per-weight summaries, the official
  ranks and, per need, NDCG@10 and top 3 accessions per weight (ids and
  numbers only)

Made by MV2 of Munim, Inc. with AI agents working in his name. No person has
checked these readings. Code Apache-2.0; this README and the report CC BY 4.0.
MedCPT is NCBI's model; it is not included here.
