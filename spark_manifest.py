#!/usr/bin/env python3
"""spark_manifest: SHA-256 manifest of a SPARK system's files, and a check that a rebuild matches it.

SPARK Task 2 says participants "may be required to provide cryptographic hashes or
other verifiable records" for software, indexes and data artifacts, and that the
artifacts must later match the versions documented at the January 15, 2027
deadline. A plain file hash is not enough for the .gz files snapshot_survey.py
writes: a gzip header carries the time it was written, so the same index rebuilt
a minute later has a different hash. For each .gz file the manifest therefore
also records the hash of the uncompressed content.

    python spark_manifest.py make --root build --out manifest.json studies.jsonl data/variables.jsonl.gz ...
    python spark_manifest.py verify --root rebuild --manifest manifest.json [--strict]

Paths are relative to --root; a folder adds every file under it. verify prints one
line per file: "same", "same content" (a .gz whose bytes differ but whose content
is equal), "differs" or "missing". It exits 1 if any file differs or is missing,
or with --strict if any is only "same content".

Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
"""

import argparse
import gzip
import hashlib
import json
import os
import sys

__version__ = "0.1.0"

CHUNK = 1 << 20


def _sha256(f):
    h = hashlib.sha256()
    n = 0
    while True:
        block = f.read(CHUNK)
        if not block:
            return h.hexdigest(), n
        h.update(block)
        n += len(block)


def entry(root, rel):
    """Manifest entry for one file: path, bytes, sha256, and content_sha256 for .gz files."""
    path = os.path.join(root, rel)
    with open(path, "rb") as f:
        digest, size = _sha256(f)
    e = {"path": rel.replace(os.sep, "/"), "bytes": size, "sha256": digest}
    if rel.endswith(".gz"):
        with gzip.open(path, "rb") as f:
            e["content_sha256"], e["content_bytes"] = _sha256(f)
    return e


def expand(root, paths):
    """Relative file paths under root for a list of files and folders, sorted."""
    out = set()
    for rel in paths:
        full = os.path.join(root, rel)
        if os.path.isdir(full):
            for d, _, files in os.walk(full):
                for name in files:
                    out.add(os.path.relpath(os.path.join(d, name), root))
        else:
            out.add(os.path.normpath(rel))
    return sorted(out, key=lambda p: p.replace(os.sep, "/"))


def make(root, paths):
    return {"manifest": "spark_manifest", "version": __version__,
            "files": [entry(root, rel) for rel in expand(root, paths)]}


def compare(expected, actual):
    """'same', 'same content' or 'differs' for two entries of the same path."""
    if expected["sha256"] == actual["sha256"]:
        return "same"
    if expected.get("content_sha256") and expected.get("content_sha256") == actual.get("content_sha256"):
        return "same content"
    return "differs"


def verify(root, manifest):
    """(path, status) for every file in the manifest, checked against the files under root."""
    out = []
    for e in manifest["files"]:
        rel = e["path"].replace("/", os.sep)
        if not os.path.isfile(os.path.join(root, rel)):
            out.append((e["path"], "missing"))
            continue
        out.append((e["path"], compare(e, entry(root, rel))))
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("make", help="write a manifest")
    p.add_argument("--root", default=".")
    p.add_argument("--out", required=True)
    p.add_argument("paths", nargs="+")
    p = sub.add_parser("verify", help="check files against a manifest")
    p.add_argument("--root", default=".")
    p.add_argument("--manifest", required=True)
    p.add_argument("--strict", action="store_true", help="a .gz must match byte for byte")
    args = ap.parse_args(argv)

    if args.cmd == "make":
        m = make(args.root, args.paths)
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            json.dump(m, f, indent=1)
            f.write("\n")
        print("%d files" % len(m["files"]))
        return 0
    with open(args.manifest, encoding="utf-8") as f:
        m = json.load(f)
    results = verify(args.root, m)
    for path, status in results:
        print("%s: %s" % (path, status))
    bad = [s for _, s in results if s in ("differs", "missing") or (args.strict and s == "same content")]
    print("%d files, %d not matching" % (len(results), len(bad)))
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main())
