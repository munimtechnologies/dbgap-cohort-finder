#!/usr/bin/env python3
"""spark_system: the entry point of MV2's SPARK dbGaP Task 2 Docker image (Dockerfile.spark).

SPARK Task 2 asks for a Docker-based system that NIH can run with all external
network calls blocked, and says participants may have to show hashes proving
that the code and indexes match the versions of January 15, 2027. This file
builds the index once, inside the image, records a SHA-256 manifest of the
index and the code next to it, checks that manifest on demand, and passes
run/check through to spark_submit.py with the image's index filled in.

    python spark_system.py build --tar dbgap.tar.gz --index /index    (at image build time)
    python spark_system.py verify [--index /index] [--strict]
    python spark_system.py run --needs needs.jsonl --out submission.jsonl --team-id <team> \
        --submission-id <team>-run-01 [--stats stats.json]
    python spark_system.py check --needs needs.jsonl --submission submission.jsonl -k 100

The index folder defaults to $SPARK_INDEX, then /index.

Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
"""

import argparse
import json
import os
import subprocess
import sys

import spark_manifest as sm

__version__ = "0.1.0"

APP = os.path.dirname(os.path.abspath(__file__))
INDEX_FILES = ["out/studies.jsonl", "data/variables.jsonl.gz", "data/var_values.jsonl.gz"]
CODE_FILES = ["cohort_finder.py", "snapshot.py", "snapshot_survey.py", "sentence_need.py",
              "spark_submit.py", "spark_manifest.py", "spark_system.py"]
MANIFEST = "MANIFEST.json"


def default_index():
    return os.environ.get("SPARK_INDEX") or "/index"


def index_args(index):
    """The spark_submit.py arguments that point at an index folder."""
    return ["--studies", os.path.join(index, "out", "studies.jsonl"),
            "--variables", os.path.join(index, "data", "variables.jsonl.gz"),
            "--values", os.path.join(index, "data", "var_values.jsonl.gz")]


def survey(tar, index):
    subprocess.check_call([sys.executable, os.path.join(APP, "snapshot_survey.py"), "--tar", tar,
                           "--data", os.path.join(index, "data"), "--out", os.path.join(index, "out")])


def build(tar, index, app=APP, run_survey=survey):
    """Build the index from NLM's snapshot tarball and write its manifest; returns the manifest."""
    run_survey(tar, index)
    manifest = {"spark_system": __version__, "pythonhashseed": os.environ.get("PYTHONHASHSEED"),
                "python": sys.version.split()[0],
                "index": sm.make(index, INDEX_FILES), "code": sm.make(app, CODE_FILES)}
    with open(os.path.join(index, MANIFEST), "w", encoding="utf-8", newline="\n") as f:
        json.dump(manifest, f, indent=1)
        f.write("\n")
    return manifest


def verify(index, app=APP):
    """(part, path, status) for every file in the index's manifest."""
    with open(os.path.join(index, MANIFEST), encoding="utf-8") as f:
        manifest = json.load(f)
    out = []
    for part, root in (("index", index), ("code", app)):
        out.extend((part, path, status) for path, status in sm.verify(root, manifest[part]))
    return out


def main(argv=None):
    argv = list(sys.argv[1:] if argv is None else argv)
    if argv and argv[0] in ("run", "check"):
        import spark_submit as ss
        return ss.main(index_args(default_index()) + argv)
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0],
                                 epilog="run and check take spark_submit.py's arguments.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("build", help="build the index and its manifest (image build time)")
    p.add_argument("--tar", required=True, help="NLM's dbGaP snapshot, dbgap.tar.gz")
    p.add_argument("--index", default=default_index())
    p = sub.add_parser("verify", help="check the index and code against the manifest")
    p.add_argument("--index", default=default_index())
    p.add_argument("--strict", action="store_true", help="a .gz must match byte for byte")
    sub.add_parser("run", help="write and check a submission (spark_submit.py run)")
    sub.add_parser("check", help="check a submission (spark_submit.py check)")
    args = ap.parse_args(argv)

    if args.cmd == "build":
        manifest = build(args.tar, args.index)
        print("%d index files, %d code files" % (len(manifest["index"]["files"]), len(manifest["code"]["files"])))
        return 0
    results = verify(args.index)
    for part, path, status in results:
        print("%s %s: %s" % (part, path, status))
    bad = [s for _, _, s in results if s in ("differs", "missing") or (args.strict and s == "same content")]
    print("%d files, %d not matching" % (len(results), len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
