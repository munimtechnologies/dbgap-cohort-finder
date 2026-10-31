# Keeping parsed constraint words out of the text search

[`wording_check/`](../wording_check/README.md) found that MV2's SPARK ranker
loses up to 0.12 NDCG@10 when a silver need is reworded. The structured parse
hardly moves, so the loss comes from two other places. First, BM25 still gets
the words of constraints the parse has already scored ("whole genomic
sequences" against "whole genome sequencing"). Second, "I'm" leaves a stray "m"
in every chat need's disease words.

`wording_fix.py` 0.1.0 tests a fix for both. It takes out contractions ("I'm",
"we're") before parsing. It then drops from the text-search words each
constraint group the parse read (data type, age, consent, study design), plus a
few request words ("cohorts", "enrolled", "diagnosed", "involving"). Disease
and variable words always stay. It runs the current system (`base`,
`spark_submit.answer`) and the fix (`fix`) on the same 750 needs (150 silver
needs written five ways) and on the two official example wordings.

```
$ python wording_fix.py --studies out/studies.jsonl --variables data/variables.jsonl.gz \
    --values data/var_values.jsonl.gz --devset devset.json --needs official_needs.jsonl --out out
```

## Results (NLM's SPARK snapshot, 2026-10-31, code at main `075f7f0`)

| variant | base NDCG@10 | fix NDCG@10 |
|---|---|---|
| v0_short | 0.8943 | 0.9190 |
| v1_official | 0.8656 | 0.9143 |
| v2_question | 0.8754 | 0.9137 |
| v3_chat | 0.7782 | 0.9159 |
| v4_synonyms | 0.8846 | 0.9159 |
| mean (spread) | 0.8596 (0.1161) | 0.9158 (0.0053) |

- The fix gives almost the same answers for every wording: the top 3 matches
  the short wording's on 139 to 146 of 150 needs, against 30 to 98 before.
- The chat wording's stray "m" is gone (disease words differ on 0 needs,
  against 150).
- The expected study for the official example need stays 2nd in both
  wordings.
- Ranking got faster: 0.5 to 0.65 s per need, against 1.4 to 2.4 s.
- **But the lists got shorter.** 239 of the fix's 750 lists hold fewer than
  100 studies, against 10 for the current system. Studies that match none of
  the remaining words are left out.

**Not adopted yet.** The rule written before the run required short lists to
stay within 10 of the current system, and they did not. The default ranker is
unchanged. A follow-up test fills each short list with the current system's
results that are not already in it. Adding studies after a list's end can't
lower NDCG at any depth.

## Pre-registered predictions (8 of 9 held)

Written on 2026-10-31 in the run that filed the job, before any result
existed (the job ran 11:09-11:58 UTC and was graded in the next run):

| | Prediction | Result |
|---|---|---|
| F1 | base reproduces the wording check exactly | held |
| F2 | fix chat wording: disease words differ on at most 5 needs | held (0) |
| F3 | fix spread across wordings at most 0.058 | held (0.0053) |
| F4 | fix mean over wordings above base's 0.8596 | held (0.9158) |
| F5 | fix short wording within 0.010 of 0.8943 | failed (0.9190) |
| F6 | fix official template within 0.010 of fix short wording | held (0.0047) |
| F7 | official example at rank 3 or better in both wordings | held (2, 2) |
| F8 | the fix changes the text-search words of at least 100 short needs | held (134) |
| F9 | at most 3.0 s per need in every wording | held (0.65 s at most) |

F5 failed in the good direction: the fix also raised the short wording, which
the prediction did not expect.

## Limits

- Silver labels are built from the MeSH codes and fields the structured parse
  reads. Moving weight from the text search to the parse is what such labels
  reward, so part of the gain may come from how the labels were made. This
  measures wording sensitivity, not the official score.
- The rewordings and the fix were written by the same agents after reading the
  losses. This tests a named cause; it is not an unbiased estimate.
- Two official wordings of one example need.
- A disease word that is also a constraint word ("young") can leave the text
  search when an age is parsed.

## Files

- `report-2026-10-31.json`: per-system and per-wording summaries, and per
  need its NDCG@10 under both systems (ids and numbers only)

Made by MV2 of Munim, Inc. with AI agents working in his name. No person has
checked these readings. Code Apache-2.0; this README and the report CC BY 4.0.
