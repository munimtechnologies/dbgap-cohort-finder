# A checked SPARK Task 2 submission run (2026-10-30)

`spark_submit.py` 0.1.0 writes a SPARK dbGaP Task 2 submission with the best
ranker measured so far (`sentence_need.rank(index, sentence_need.parse_need(text), tier=0.6)`)
and checks it against the format in the Task 2 description (one UTF-8 JSON
object per line; `metadata` with `team_id`, `submission_id`, `info_need_id` and
the original `info_need`; `results`, an ordered list of study accessions).

This folder reports its first full run on NLM's SPARK snapshot (3,578 studies),
with the predictions written before the run. Made with AI agents working in
MV2's name. No person has checked these readings.

## What ran

192 needs: the task's own example sentence and the submission-example wording
(2), eight short needs reworded into the task's sentence template (8), eight
short example needs (8), 24 hand-written needs and 150 silver needs from
`snapshot.py devset -n 150`. Code: this repository's main branch at 87978e7
(`sentence_need.py` 0.2.0). Python 3.12 in a container with 2 CPUs and a
2 GB memory limit, on 2026-10-30.

## Measured ([`stats-2026-10-30.json`](stats-2026-10-30.json))

- Load the snapshot index: 15.8 s.
- Rank one need: 2.24 s on average, 5.41 s at most; 431 s for all 192.
- Peak memory of the ranking process: 313 MB. The container peaked at
  0.84 GB, which includes `snapshot_survey.py` reading the archive.
- `check -k 100`: 192 needs, 0 problems.
- 191 needs got 100 results. One silver need ("Studies of alcoholism including
  at least 100 Latino participants ...") got 94, because the ranker leaves out
  studies that match no word of the need in their text or data dictionary.
  A short list is allowed by the format.
- On both official wordings the expected answer, phs001954.v2.p1, is 2nd.
  On all 11 lung and sentence needs the top 10 equals the earlier sandbox
  report ([`sentence_need/scaffold-report-2026-10-30.json`](../sentence_need/scaffold-report-2026-10-30.json)),
  so the submission path gives the same answers as the measured ranker.

## Pre-registered predictions: 5 of 7 held

| | Prediction | Result |
|---|---|---|
| C1 | `run` and `check -k 100` report 0 problems | held |
| C2 | every line has exactly 100 results | **failed**: 191 of 192 (one has 94) |
| C3 | phs001954.v2.p1 2nd on both official wordings | held |
| C4 | top 10 of the 11 lung and sentence needs equal the earlier report | held (11 of 11) |
| C5 | mean <= 2.0 s and max <= 10 s per need | **failed**: mean 2.24 s (max 5.41 s held) |
| C6 | peak memory <= 1,500 MB | held (313 MB) |
| C7 | load <= 120 s | held (15.8 s) |

Both gates held as well: the 43 unit tests passed, and the needs file had
192 needs, 150 of them silver.

## Limits

- The format check follows the one example record in the Task 2 description.
  Any later guidance from NIH may add rules.
- The times are from 2 shared CPUs, not from the hardware NIH will use.
- This run measures format, time and memory only. It says nothing about NDCG
  against the official expert judgments.

CC BY 4.0.
