#!/usr/bin/env python3
"""abbrev_check: measure abbrev_fix against the current default on disease_check's 574 rows.

Systems: "base" = spark_submit.padded_answer (the 0.2.0 default, "pad");
"fix" = abbrev_fix.answer (pad, with disease abbreviations handled).
Rows: disease_check 0.1.0's rows (each silver need's disease as is, un-inverted,
everyday names and abbreviations, in the short and official frames). Also counts
how many of wording_check's 750 reworded needs contain a disease abbreviation
(those are the only needs abbrev_fix can change), lists the long form found for
each abbreviation, and ranks the official example's study with both systems.
Silver labels are circular; this measures abbreviation handling, not the official
score. Pre-registered in 20261101T140844Z-civic-tech/findings/prereg-abbrev-fix.md.

    python abbrev_check.py --studies out/studies.jsonl --variables data/variables.jsonl.gz \
        --values data/var_values.jsonl.gz --devset devset.json --needs official_needs.jsonl --out /out

Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
"""

import argparse
import json
import os
import sys
import time

__version__ = "0.1.0"


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--studies", required=True)
    ap.add_argument("--variables")
    ap.add_argument("--values")
    ap.add_argument("--devset", required=True)
    ap.add_argument("--needs", nargs="*", default=[])
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    import abbrev_fix as af
    import cohort_finder as cf
    import disease_check as dc
    import sentence_need as sen
    import snapshot as sn
    import spark_submit as ss
    import wording_check as wc

    with open(args.devset, encoding="utf-8") as f:
        dev = json.load(f)
    rows, unparsed = dc.rows_for(dev["queries"])
    start = time.perf_counter()
    index = cf.Index(sn.load(args.studies, args.variables, args.values))
    load_seconds = round(time.perf_counter() - start, 2)
    start = time.perf_counter()
    defs = af.index_definitions(index)
    mine_seconds = round(time.perf_counter() - start, 2)

    # Which rows the fix can change, and what it reads in each.
    triggered = {}
    for row in rows:
        found = af.disease_abbreviations(row["info_need"], defs)
        if found:
            key = "%s/%s" % (row["frame"], row["variant"])
            triggered.setdefault(key, []).append({"source": row["source"], "named": row["named"], "found": found})
    abbrevs = {}
    for name in sorted(set(dc.ABBREV.values())):
        table = cf.expand_abbreviations(name)
        mined, count = af.long_form(defs, name)
        abbrevs[name] = {"in_table": bool(table), "table": table[0] if table else None,
                         "mined": mined, "mined_count": count}
    wording_rows, _ = wc.variants(dev["queries"])
    wording_hits = [{"id": r.get("id"), "variant": r.get("variant"), "found": [f["abbrev"] for f in found]}
                    for r in wording_rows for found in [af.disease_abbreviations(r["info_need"], defs)] if found]

    items = dc.measure(index, rows, dev["qrels"], (("base", ss.padded_answer), ("fix", af.answer)),
                       sen.parse_need, sen.TIER)
    for i in items:
        if i["variant"] == "d3_abbrev":
            i["in_table"] = dc.in_table(i["named"])
    changed = {}
    for i in items:
        if abs(i["base"]["ndcg@10"] - i["fix"]["ndcg@10"]) > 1e-4:
            key = "%s/%s" % (i["frame"], i["variant"])
            changed.setdefault(key, []).append({"source": i["source"], "named": i["named"],
                                                "base": i["base"]["ndcg@10"], "fix": i["fix"]["ndcg@10"]})
    official = []
    for path in args.needs:
        for need_id, text in sn.read_needs(path):
            official.append({"id": need_id,
                             "base": sen.position(ss.padded_answer(index, text), sen.EXAMPLE_STUDY),
                             "fix": sen.position(af.answer(index, text), sen.EXAMPLE_STUDY),
                             "found": [f["abbrev"] for f in af.disease_abbreviations(text, defs)]})

    report = {"abbrev_check": __version__, "abbrev_fix": af.__version__, "disease_check": dc.__version__,
              "spark_submit": ss.__version__, "sentence_need": sen.__version__, "tier": sen.TIER,
              "systems": {"base": "spark_submit.padded_answer (0.2.0 default)",
                          "fix": "abbrev_fix.answer"},
              "questions": len(dev["queries"]), "unparsed": unparsed, "rows": len(rows),
              "load_seconds": load_seconds, "mine_seconds": mine_seconds,
              "mined_short_forms": len(defs), "abbreviations": abbrevs,
              "triggered_rows": {k: len(v) for k, v in sorted(triggered.items())},
              "wording_rows": len(wording_rows), "wording_rows_triggered": len(wording_hits),
              "wording_hits": wording_hits, "ndcg_changed": changed, "official": official,
              "summary": dc.summarize(items), "triggered": triggered, "items": items,
              "note": "Silver labels are circular and the abbreviations were written by the agents that read the "
                      "matcher; this measures abbreviation handling, not the official score."}
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "abbrev_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)

    print("%d silver needs, %d did not decompose, %d rows; load %ss, mining %ss, %d short forms mined" % (
        len(dev["queries"]), len(unparsed), len(rows), load_seconds, mine_seconds, len(defs)))
    found_any = sum(1 for a in abbrevs.values() if a["mined"])
    not_table = [n for n, a in abbrevs.items() if not a["in_table"]]
    print("abbreviations: %d, mined long form for %d; not in table %d, of which mined %d" % (
        len(abbrevs), found_any, len(not_table), sum(1 for n in not_table if abbrevs[n]["mined"])))
    for name, a in abbrevs.items():
        print("  %s: table=%s mined=%s (%d)" % (name, a["table"], a["mined"], a["mined_count"]))
    print("triggered rows: %s" % json.dumps(report["triggered_rows"], sort_keys=True))
    print("wording rows triggered: %d of %d" % (len(wording_hits), len(wording_rows)))
    print("ndcg changed rows: %s" % json.dumps({k: len(v) for k, v in sorted(changed.items())}, sort_keys=True))
    for frame, groups in report["summary"].items():
        for group, e in groups.items():
            b, x = e["base"], e["fix"]
            print("%s %s: %d needs; base %s -> %s (drop %s); fix %s -> %s (drop %s); fix-base %s; "
                  "s/need base %s fix %s" % (
                      frame, group, e["needs"], b["d0_ndcg@10"], b["ndcg@10"], b["drop"], x["d0_ndcg@10"],
                      x["ndcg@10"], x["drop"], round(x["ndcg@10"] - b["ndcg@10"], 4), b["mean_seconds"],
                      x["mean_seconds"]))
    for item in official:
        print("%s example rank base=%s fix=%s found=%s" % (item["id"], item["base"], item["fix"], item["found"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
