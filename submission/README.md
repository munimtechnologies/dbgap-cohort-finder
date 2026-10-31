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

## Rebuilding to the same hashes (2026-10-31)

NIH may ask for hashes of a system's software, indexes and data, and the
artifacts must later match them. To test whether this pipeline rebuilds to the
same bytes, it was built twice in one container (Python 3.12, 2 CPUs, 2 GB),
from main at ed6620d and NLM's `dbgap.tar.gz`. Each build ran
`snapshot_survey.py`, `snapshot.py devset -n 150`, `make_needs.py` and
`spark_submit.py run` on the same 192 needs, the first with `PYTHONHASHSEED=1`
and the second with `PYTHONHASHSEED=2`. `spark_manifest.py` recorded build A
([`manifest-2026-10-31.json`](manifest-2026-10-31.json)) and checked build B
against it ([`repro-2026-10-31.json`](repro-2026-10-31.json)).

| | Prediction | Result |
|---|---|---|
| R1 | `out/studies.jsonl` byte-identical | held |
| R2 | both `.gz` files equal in content, with bytes differing only in the gzip header time | held |
| R3 | `submission.jsonl` byte-identical (192 needs) | held |
| R4 | `devset.json` byte-identical | held |
| R5 | `out/census.json` equal once parsed | held (also byte-identical) |
| R6 | `out/age_candidates.jsonl` and `out/field_coverage.json` byte-identical | held |

Both gates held: the 48 unit tests passed, and every step of both builds
exited 0. Build A ranked a need in 2.62 s on average (5.70 s at most) and build
B in 2.47 s (5.96 s); both peaked at 313 MB.

Before the run, the census was flagged as a risk, because it counts
`sample_use` values through a Python set and ties keep insertion order. It came
out byte-identical in this pair of builds. One pair of seeds doesn't prove it
always will.

## The Docker system's commands (2026-10-31)

`Dockerfile.spark` builds the index at image build time and keeps only the
code and four index files. Its commands were run in a `python:3.12-slim`
container (2 CPUs, 2 GB, `PYTHONHASHSEED=0`), on a different machine from the
rebuild test above: `spark_system.py build`, `verify`, the same 192 needs,
`run` under `noegress.py`, `check -k 100` and `verify --strict`. The image
itself was not built with `docker build`.
[`image-2026-10-31.json`](image-2026-10-31.json) has each step's exit code,
time and memory and the sizes. [`image-manifest-2026-10-31.json`](image-manifest-2026-10-31.json)
is the image's own manifest.

| | Prediction | Result |
|---|---|---|
| I1 | 3 index and 7 code files in the manifest; both checks "10 files, 0 not matching" | held |
| I2 | `run`: 192 needs, 0 problems; 0 network attempts | held |
| I3 | `check -k 100`: 192 needs, 0 problems | held |
| I4 | 3,578 studies; 1.5-3.5 s per need on average, <= 10 s at most; load <= 60 s; <= 600 MB | held (1.58 s, 2.76 s, 10.6 s, 313 MB) |
| I5 | top 10 of the 11 lung and sentence needs equal the 2026-10-30 run; one need with 94 results | held |
| I6 | build peak <= 1,500 MB | held (860 MB) |
| I7 | `studies.jsonl`, both `.gz` contents and `submission.jsonl` hash the same as build A above | held |

Both gates held: the 54 unit tests passed, and all seven steps exited 0. The
image would hold a 29 MB index and 158 KB of code.

## Limits

- The format check follows the one example record in the Task 2 description.
  Any later guidance from NIH may add rules.
- The times are from 2 shared CPUs, not from the hardware NIH will use.
- The rebuild tests used two machines, two Python 3.12 images and one copy of
  the snapshot. They test process-level determinism, not other platforms or
  Python versions.
- These runs measure format, time, memory and reproducibility only. They say
  nothing about NDCG against the official expert judgments.

CC BY 4.0.
