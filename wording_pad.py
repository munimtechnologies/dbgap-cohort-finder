#!/usr/bin/env python3
"""wording_pad: fill wording_fix's short lists with the current system's results.

wording_fix 0.1.0 (2026-10-31) kept parsed constraint words out of the text
search. On 150 silver needs written five ways it raised NDCG@10 from a mean of
0.8596 to 0.9158 and made the five wordings agree (spread 0.1161 -> 0.0053). But
239 of its 750 lists held fewer than 100 studies, against 10 for the current
system, because studies that match none of the remaining words are left out.

pad() takes the fix's list and appends the current system's results that are
not already in it, up to 100. Appending never lowers NDCG at any depth, so the
padded list scores at least as well as the fix's own. What this measures is
whether it beats the current system at depth 100 as well as at 10, and what
running both systems costs in time.

main() runs base (spark_submit.answer) and fix (wording_fix.answer) once per
need, builds pad from the two lists, and reports NDCG@10, NDCG@100, short lists,
padded counts and seconds per need for all three, plus the official example's
rank. Pre-registered in 20261031T122435Z-civic-tech/findings/prereg-wording-pad.md.

    python wording_pad.py --studies out/studies.jsonl --variables data/variables.jsonl.gz \
        --values data/var_values.jsonl.gz --devset devset.json --needs official_needs.jsonl --out /out

Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
"""

import argparse
import json
import os
import sys
import time

__version__ = "0.1.0"

SYSTEMS = ("base", "fix", "pad")
DEPTHS = (10, 100)
K = 100


def pad(first, second, k=K):
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


def answer(index, text, k=K):
    """Ranked accessions for one need: wording_fix's list padded with spark_submit's."""
    import spark_submit as ss
    import wording_fix as wf
    return pad(wf.answer(index, text, k=k), ss.answer(index, text), k)


# ---------------------------------------------------------------- measuring

def score(ranked, relevance):
    import cohort_finder as cf
    return {"ndcg@%d" % d: round(cf.ndcg(ranked, relevance, d), 4) for d in DEPTHS}


def measure(index, rows, qrels, k=K):
    """Per need and wording: each system's scores, list length and seconds."""
    import spark_submit as ss
    import wording_fix as wf
    per = []
    for row in rows:
        relevance = qrels.get(row["source"], {})
        start = time.perf_counter()
        base = ss.answer(index, row["info_need"])
        mid = time.perf_counter()
        fix = wf.answer(index, row["info_need"], k=k)
        end = time.perf_counter()
        lists = {"base": base, "fix": fix, "pad": pad(fix, base, k)}
        seconds = {"base": mid - start, "fix": end - mid, "pad": end - start}
        item = {"id": row["source"], "variant": row["variant"], "added": len(lists["pad"]) - len(fix)}
        for name in SYSTEMS:
            item[name] = dict(score(lists[name], relevance), length=len(lists[name]),
                              seconds=round(seconds[name], 3))
        per.append(item)
    return per


def summarize(per, variants, k=K):
    out = {}
    for name in SYSTEMS:
        by_variant = {}
        for v in variants:
            items = [p[name] for p in per if p["variant"] == v]
            n = len(items) or 1
            s = {"ndcg@%d" % d: round(sum(i["ndcg@%d" % d] for i in items) / n, 4) for d in DEPTHS}
            s["short_lists"] = sum(1 for i in items if i["length"] < k)
            s["mean_seconds"] = round(sum(i["seconds"] for i in items) / n, 3)
            s["max_seconds"] = round(max([i["seconds"] for i in items] or [0.0]), 3)
            by_variant[v] = s
        system = {"variants": by_variant}
        for d in DEPTHS:
            means = [by_variant[v]["ndcg@%d" % d] for v in variants]
            system["mean_ndcg@%d" % d] = round(sum(means) / len(means), 4)
            system["spread_ndcg@%d" % d] = round(max(means) - min(means), 4)
        system["short_lists"] = sum(by_variant[v]["short_lists"] for v in variants)
        system["mean_seconds"] = round(sum(by_variant[v]["mean_seconds"] for v in variants) / len(variants), 3)
        out[name] = system
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--studies", required=True)
    ap.add_argument("--variables")
    ap.add_argument("--values")
    ap.add_argument("--devset", required=True)
    ap.add_argument("--needs", nargs="*", default=[])
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    import cohort_finder as cf
    import sentence_need as sen
    import snapshot as sn
    import spark_submit as ss
    import wording_check as wc
    import wording_fix as wf

    with open(args.devset, encoding="utf-8") as f:
        dev = json.load(f)
    rows, unparsed = wc.variants(dev["queries"])
    start = time.perf_counter()
    index = cf.Index(sn.load(args.studies, args.variables, args.values))
    report = {"wording_pad": __version__, "wording_fix": wf.__version__, "wording_check": wc.__version__,
              "sentence_need": sen.__version__, "tier": sen.TIER, "k": sn.K, "questions": len(dev["queries"]),
              "unparsed": unparsed, "load_seconds": round(time.perf_counter() - start, 2)}
    per = measure(index, rows, dev["qrels"], sn.K)
    report["systems"] = summarize(per, wc.VARIANTS, sn.K)
    added = [p["added"] for p in per]
    report["pad_added"] = {"lists_padded": sum(1 for a in added if a > 0), "studies_added": sum(added),
                           "max_added": max(added or [0])}
    report["pad_below_fix"] = sum(1 for p in per for d in DEPTHS
                                  if p["pad"]["ndcg@%d" % d] < p["fix"]["ndcg@%d" % d] - 1e-9)
    report["official"] = []
    for path in args.needs:
        for need_id, text in sn.read_needs(path):
            base, fix = ss.answer(index, text), wf.answer(index, text, k=sn.K)
            lists = {"base": base, "fix": fix, "pad": pad(fix, base, sn.K)}
            report["official"].append(dict({name: sen.position(lists[name], sen.EXAMPLE_STUDY)
                                            for name in SYSTEMS}, id=need_id,
                                           lengths={name: len(lists[name]) for name in SYSTEMS}))
    report["per_need"] = per
    report["note"] = "Silver labels are circular; this compares systems on wording, not the official score."
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "wording_pad_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    for name in SYSTEMS:
        s = report["systems"][name]
        print("%s: mean ndcg@10 %s (spread %s), mean ndcg@100 %s (spread %s), short lists %d, %ss/need" % (
            name, s["mean_ndcg@10"], s["spread_ndcg@10"], s["mean_ndcg@100"], s["spread_ndcg@100"],
            s["short_lists"], s["mean_seconds"]))
        for v in wc.VARIANTS:
            x = s["variants"][v]
            print("  %s ndcg@10 %s ndcg@100 %s short %d %ss/need (max %s)" % (
                v, x["ndcg@10"], x["ndcg@100"], x["short_lists"], x["mean_seconds"], x["max_seconds"]))
    print("pad added: %s; pad below fix: %d" % (json.dumps(report["pad_added"], sort_keys=True),
                                                report["pad_below_fix"]))
    for item in report["official"]:
        print("%s example rank base=%s fix=%s pad=%s lengths %s" % (
            item["id"], item["base"], item["fix"], item["pad"], json.dumps(item["lengths"], sort_keys=True)))
    return 0


if __name__ == "__main__":
    sys.exit(main())
