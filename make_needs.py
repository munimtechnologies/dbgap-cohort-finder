#!/usr/bin/env python3
"""make_needs: one needs file from need files and a silver dev set, for a SPARK-sized test run.

    python make_needs.py --needs official_needs.jsonl ... --devset devset.json --out needs.jsonl

Each line is {"info_need_id", "info_need"}; silver ids get a "silver-" prefix. Prints the counts.

Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
"""

import argparse
import json
import sys

import snapshot as sn


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--needs", nargs="*", default=[])
    ap.add_argument("--devset")
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    rows, seen = [], set()
    for path in args.needs:
        for need_id, text in sn.read_needs(path):
            rows.append((need_id, text))
    if args.devset:
        with open(args.devset, encoding="utf-8") as f:
            for q in json.load(f)["queries"]:
                rows.append(("silver-%s" % q["id"], q["query"]))
    with open(args.out, "w", encoding="utf-8") as f:
        for need_id, text in rows:
            if need_id in seen:
                print("repeated id %s" % need_id)
                return 1
            seen.add(need_id)
            f.write(json.dumps({"info_need_id": need_id, "info_need": text}, ensure_ascii=False) + "\n")
    print("%d needs (%d silver)" % (len(rows), sum(1 for i, _ in rows if i.startswith("silver-"))))
    return 0


if __name__ == "__main__":
    sys.exit(main())
