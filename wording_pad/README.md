# Filling wording_fix's short lists

[`wording_fix/`](../wording_fix/README.md) kept parsed constraint words out of
the text search. On 150 silver needs written five ways it raised mean NDCG@10
from 0.8596 to 0.9158 and made the five wordings agree. But 239 of its 750
lists held fewer than 100 studies (10 for the current system), because studies
that match none of the remaining words are left out. NLM has not published the
depth at which SPARK Task 2 is scored, and a short list can only lose there.

`wording_pad.py` 0.1.0 takes the fix's list and adds the current system's
results (`spark_submit.answer`) that are not already in it, up to 100. Adding
studies after a list's end can't lower NDCG at any depth. This run measured
whether the padded list also beats the current system at depth 100, and what
running both systems costs in time.

```
$ python wording_pad.py --studies out/studies.jsonl --variables data/variables.jsonl.gz \
    --values data/var_values.jsonl.gz --devset devset.json --needs official_needs.jsonl --out out
```

## Results (NLM's SPARK snapshot, 2026-11-01, code at main `f2b7d73` plus `wording_fix.py` 0.1.0)

| wording | base @10 | base @100 | pad @10 | pad @100 | pad short lists | pad s/need (max) |
|---|---|---|---|---|---|---|
| v0_short | 0.8943 | 0.9054 | 0.9190 | 0.9259 | 1 | 1.54 (4.32) |
| v1_official | 0.8656 | 0.8815 | 0.9143 | 0.9212 | 1 | 1.67 (4.54) |
| v2_question | 0.8754 | 0.8878 | 0.9137 | 0.9206 | 0 | 1.77 (3.89) |
| v3_chat | 0.7782 | 0.8001 | 0.9159 | 0.9258 | 0 | 1.73 (3.89) |
| v4_synonyms | 0.8846 | 0.8968 | 0.9159 | 0.9229 | 8 | 1.12 (3.96) |
| mean (spread) | 0.8596 (0.1161) | 0.8743 (0.1053) | 0.9158 (0.0053) | 0.9233 (0.0053) | 10 | 1.57 |

- Padding filled 236 of the fix's 239 short lists. It added 15,855 studies,
  at most 98 to one list. 10 lists stay short, the same number as the current
  system.
- On the 750 needs, at both depths, the padded list never scored below the fix.
- The official example need's expected study (phs001954.v2.p1) is 2nd under
  all three systems, in both official wordings.
- The padded list's NDCG@100 equals the fix's to four decimals in every
  wording. On these labels the studies taken from the current system add no
  measurable relevance (a relevant study added near rank 100 could still hide
  in the rounding). Padding keeps the lists full.
- Running both systems costs about 1.4 times the current system's time per
  need. Time only breaks ties in SPARK's scoring.

**Next default.** The rule written before the run said the padded system
becomes the system's answer if padding never lowers the fix, short lists
stay at 10 or fewer, NDCG@100 is at least the current system's, NDCG@10 is at
least 0.8796, the official example stays at rank 2 or better, and no need
takes more than 10 s. All of these held. Wiring it into `spark_submit.py` and
the Docker system is being checked under its own pre-registration. Until that
check passes, the published default is unchanged.

## Pre-registered predictions (9 of 9 held)

Written on 2026-10-31 in the run that filed the job, before any result
existed (the job ran 2026-11-01 05:20-05:56 UTC and was graded in a later run):

| | Prediction | Result |
|---|---|---|
| P1 | base and fix reproduce wording_fix's NDCG@10 exactly; short lists 10 and 239 | held |
| P2 | the padded list never scores below the fix | held (0) |
| P3 | padded short lists at most 10 | held (10) |
| P4 | padded mean NDCG@10 at least 0.9158 | held (0.9158) |
| P5 | padded mean NDCG@100 above the current system's | held (0.9233 vs 0.8743) |
| P6 | padded short-wording NDCG@100 at least the current system's | held (0.9259 vs 0.9054) |
| P7 | padded NDCG@10 spread across wordings at most 0.02 | held (0.0053) |
| P8 | official example at rank 2 or better in both official wordings | held (2, 2) |
| P9 | at most 3.5 s per need on average in every wording | held (1.77 s at most) |

## Limits

- Silver labels are built from the MeSH codes and fields the structured parse
  reads. The fix moves weight from the text search to the parse, which is
  what such labels reward, so part of the gain may come from how the labels
  were made. This compares systems on wording; it is not the official score.
- The rewordings and the fix were written by the same agents after reading the
  losses.
- One official example need, in two wordings.
- NDCG@100 here uses each silver need's full relevant set as the ideal. The
  official evaluation's depth is not published.

## Files

- `report-2026-11-01.json`: per-system and per-wording summaries, padding
  counts, official ranks, and for each need and wording its NDCG@10 and
  NDCG@100, list length and seconds under each system (ids and numbers only)

Made by MV2 of Munim, Inc. with AI agents working in his name. No person has
checked these readings. Code Apache-2.0; this README and the report CC BY 4.0.
