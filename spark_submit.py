#!/usr/bin/env python3
"""spark_submit: write and check a SPARK dbGaP Task 2 submission with the current best ranker.

`snapshot.py run` writes the Task 2 JSONL format, but with snapshot.py's own
parser and ranking. This file runs MV2's best measured system over a file of
information needs and checks the result against the format in the Task 2
description ("dbGaP-Task2-Description-and-Evaluation.pdf", pages 4-5): one
UTF-8 JSON object per line, "metadata" with team_id, submission_id,
info_need_id and info_need (the original text), and "results", an ordered list
of study accessions. It also reports the time and memory used, which SPARK's
Phase 2 judges.

Systems (--system):
    pad   (default since 0.2.0) wording_fix's list (constraint words kept out of
          the text search), then base's results not already in it, up to k.
          On 150 silver needs written five ways it scored mean NDCG@10 0.9158 and
          NDCG@100 0.9233 against base's 0.8596 and 0.8743, with the official
          example at rank 2 (wording-pad-v1, 9 of 9 pre-registered predictions).
    base  (the 0.1.0 default) sentence_need.rank with sentence_need.parse_need
          and primary-disease tiering at 0.6. answer() is this system.

    python spark_submit.py --studies out/studies.jsonl --variables data/variables.jsonl.gz \
        --values data/var_values.jsonl.gz run --needs needs.jsonl --out submission.jsonl \
        --team-id <team> --submission-id <team>-run-01
    python spark_submit.py --studies out/studies.jsonl check --needs needs.jsonl --submission submission.jsonl

Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
"""

import argparse
import json
import re
import sys
import time

import cohort_finder as cf
import sentence_need as sen
import snapshot as sn
import wording_fix as wf

__version__ = "0.2.0"

ACCESSION_RE = re.compile(r"^phs\d{6}\.v\d+\.p\d+$")
METADATA_KEYS = ("team_id", "submission_id", "info_need_id", "info_need")
SYSTEMS = ("pad", "base")
SYSTEM = "pad"


def peak_memory_mb():
    """Peak resident memory of this process in MB, or None where the resource module is missing."""
    try:
        import resource
    except ImportError:
        return None
    kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return round(kb / (1024.0 * 1024.0 if sys.platform == "darwin" else 1024.0), 1)


def answer(index, text, k=sn.K, tier=sen.TIER):
    """Ranked accessions for one need with the base system: sentence_need's parse and rank, with tiering."""
    return [r["accession"] for r in sen.rank(index, sen.parse_need(text), k=k, tier=tier)]


def pad(first, second, k=sn.K):
    """first's list, then second's entries not already in it, up to k."""
    out = list(first[:k])
    seen = set(out)
    for acc in second:
        if len(out) >= k:
            break
        if acc not in seen:
            out.append(acc)
            seen.add(acc)
    return out


def padded_answer(index, text, k=sn.K, tier=sen.TIER):
    """Ranked accessions for one need with the pad system: wording_fix's list filled from answer()'s.

    Base is only run when the fix's list is short, which gives the same list as always running it."""
    first = wf.answer(index, text, k=k, tier=tier)
    if len(first) >= k:
        return first[:k]
    return pad(first, answer(index, text, k, tier), k)


ANSWERS = {"pad": padded_answer, "base": answer}


def run(index, needs, team_id, submission_id, k=sn.K, tier=sen.TIER, system=SYSTEM):
    """(submission lines, seconds per need) for a list of (info_need_id, info_need)."""
    ranker = ANSWERS[system]
    lines, seconds = [], []
    for need_id, text in needs:
        start = time.perf_counter()
        accessions = ranker(index, text, k, tier)
        seconds.append(time.perf_counter() - start)
        lines.append(sn.submission_line(team_id, submission_id, need_id, text,
                                        [{"accession": a} for a in accessions]))
    return lines, seconds


def check(lines, needs, known=None, k=None):
    """Problems with a submission, as strings (empty means it follows the Task 2 format).

    lines: the submission's lines; needs: (info_need_id, info_need) pairs it answers;
    known: the snapshot's study accessions, if given every result must be one of them."""
    problems = []
    wanted = dict(needs)
    seen = set()
    for n, line in enumerate(lines, 1):
        if isinstance(line, bytes):
            try:
                line = line.decode("utf-8")
            except UnicodeDecodeError:
                problems.append("line %d: not UTF-8" % n)
                continue
        if not line.strip():
            problems.append("line %d: empty" % n)
            continue
        try:
            rec = json.loads(line)
        except ValueError:
            problems.append("line %d: not JSON" % n)
            continue
        if not isinstance(rec, dict) or sorted(rec) != ["metadata", "results"]:
            problems.append("line %d: keys must be metadata and results" % n)
            continue
        meta, results = rec["metadata"], rec["results"]
        if not isinstance(meta, dict) or sorted(meta) != sorted(METADATA_KEYS):
            problems.append("line %d: metadata keys must be %s" % (n, ", ".join(METADATA_KEYS)))
            continue
        if not all(isinstance(meta[key], str) and meta[key] for key in METADATA_KEYS):
            problems.append("line %d: metadata values must be non-empty strings" % n)
        need_id = meta["info_need_id"]
        if need_id in seen:
            problems.append("line %d: info_need_id %s repeated" % (n, need_id))
        seen.add(need_id)
        if need_id not in wanted:
            problems.append("line %d: info_need_id %s is not in the needs file" % (n, need_id))
        elif meta["info_need"] != wanted[need_id]:
            problems.append("line %d: info_need differs from the original text of %s" % (n, need_id))
        if not isinstance(results, list):
            problems.append("line %d: results must be a list" % n)
            continue
        if k is not None and len(results) > k:
            problems.append("line %d: %d results, more than %d" % (n, len(results), k))
        if len(set(map(str, results))) != len(results):
            problems.append("line %d: repeated accessions" % n)
        bad = [a for a in results if not isinstance(a, str) or not ACCESSION_RE.match(a)]
        if bad:
            problems.append("line %d: %d results are not study accessions (first: %r)" % (n, len(bad), bad[0]))
        if known is not None:
            unknown = [a for a in results if isinstance(a, str) and a not in known]
            if unknown:
                problems.append("line %d: %d results are not in the snapshot (first: %s)"
                                % (n, len(unknown), unknown[0]))
    for need_id in wanted:
        if need_id not in seen:
            problems.append("need %s has no line" % need_id)
    return problems


def read_lines(path):
    with open(path, "rb") as f:
        return [line.rstrip(b"\r\n") for line in f]


def known_accessions(studies_path):
    with sn._open(studies_path) as f:
        return {json.loads(line)["accession"] for line in f if line.strip()}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--studies", required=True, help="studies.jsonl from snapshot_survey.py")
    ap.add_argument("--variables", help="variables.jsonl.gz from snapshot_survey.py")
    ap.add_argument("--values", help="var_values.jsonl.gz from snapshot_survey.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("run", help="write a submission, then check it")
    p.add_argument("--needs", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--team-id", default="munim")
    p.add_argument("--submission-id", default="munim-run-01")
    p.add_argument("-k", type=int, default=sn.K)
    p.add_argument("--tier", type=float, default=sen.TIER, help="0 turns primary-disease tiering off")
    p.add_argument("--system", choices=SYSTEMS, default=SYSTEM,
                   help="pad (default): wording_fix's list filled from base's; base: the 0.1.0 system")
    p.add_argument("--stats", help="write timing, memory and check results here as JSON")
    p = sub.add_parser("check", help="check an existing submission")
    p.add_argument("--needs", required=True)
    p.add_argument("--submission", required=True)
    p.add_argument("-k", type=int)
    args = ap.parse_args(argv)

    needs = sn.read_needs(args.needs)
    if args.cmd == "check":
        problems = check(read_lines(args.submission), needs, known_accessions(args.studies), args.k)
        for line in problems:
            print(line)
        print("%d needs, %d problems" % (len(needs), len(problems)))
        return 1 if problems else 0

    start = time.perf_counter()
    index = cf.Index(sn.load(args.studies, args.variables, args.values))
    load_seconds = time.perf_counter() - start
    lines, seconds = run(index, needs, args.team_id, args.submission_id, args.k, args.tier or None, args.system)
    with open(args.out, "w", encoding="utf-8", newline="\n") as f:
        for line in lines:
            f.write(line + "\n")
    problems = check(read_lines(args.out), needs, {s["accession"] for s in index.studies}, args.k)
    stats = {"version": __version__, "system": args.system, "sentence_need": sen.__version__,
             "wording_fix": wf.__version__, "needs": len(needs),
             "studies": len(index.studies), "k": args.k, "tier": args.tier or None,
             "load_seconds": round(load_seconds, 2), "total_need_seconds": round(sum(seconds), 2),
             "mean_need_seconds": round(sum(seconds) / len(seconds), 3) if seconds else None,
             "max_need_seconds": round(max(seconds), 3) if seconds else None,
             "peak_memory_mb": peak_memory_mb(), "problems": problems}
    if args.stats:
        with open(args.stats, "w", encoding="utf-8") as f:
            json.dump(stats, f, indent=1)
    for line in problems:
        print(line)
    print(json.dumps({key: v for key, v in stats.items() if key != "problems"}, sort_keys=True))
    print("%d needs, %d problems" % (len(needs), len(problems)))
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
