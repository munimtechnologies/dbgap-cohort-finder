#!/usr/bin/env python3
"""explain: the top studies snapshot.py ranks for each need, with its reasons, as Markdown for checking by hand.

Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
"""

import argparse
import sys

import cohort_finder as cf
import snapshot as sn


def report(studies, needs, k=5):
    index = cf.Index(studies)
    out = ["# Top studies per need", ""]
    for need_id, text in needs:
        q = sn.parse_need(text)
        out += ["## %s: %s" % (need_id, text), "",
                "Parsed: topic %s; age %s; groups %s; variables %s" % (q.get("topic"), q.get("age"), q.get("groups"),
                                                                    q.get("var_terms")), ""]
        for r in sn.rank(index, q, k):
            out.append("- %s (%s subjects, %d fails): %s -- %s" % (r["accession"], r["subjects"], r["fails"],
                                                                 r["title"], "; ".join(r["why"])))
        out.append("")
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--studies", required=True)
    ap.add_argument("--variables")
    ap.add_argument("--values")
    ap.add_argument("--needs", required=True)
    ap.add_argument("--out", required=True)
    ap.add_argument("-k", type=int, default=5)
    args = ap.parse_args(argv)
    text = report(sn.load(args.studies, args.variables, args.values), sn.read_needs(args.needs), args.k)
    with open(args.out, "w", encoding="utf-8") as f:
        f.write(text)
    print(text[:4000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
