#!/usr/bin/env python3
"""abbrev_oos: does the SPARK default's abbreviation handling hold on abbreviations nobody picked?

abbrev_fix 0.1.0 was written after reading which of 39 hand-picked disease
abbreviations failed (disease_check.ABBREV), so its measured gain is in-sample.
This harness picks abbreviations automatically instead: for every silver need
whose disease is NOT one of those 39, it looks for a short form that the
snapshot's own text defines with that disease as its long form ("... colon
cancer (CC) ..."), using abbrev_fix's own mined definitions. The disease as
stored, or turned around ("hepatocellular carcinoma"), must equal a mined long
form. The most often defined short form wins; short forms in abbrev_fix.STOP,
in disease_check.ABBREV, or equal to the disease itself are skipped.

Each picked need is written with the disease (d0) and with the short form
(auto), in the short silver frame and the official sentence frame, and ranked
by the 0.2.0 default (base = spark_submit.padded_answer) and the 0.3.0 default
(fix = spark_submit.abbrev_answer). It reports NDCG@10 on the silver labels, how
often the short form's most frequent mined long form is the disease
(top_matches), and which rows abbrev_fix acted on.

Silver labels are circular, and every short form here is defined somewhere in
the snapshot, so this measures abbreviations the snapshot defines, not ones it
never spells out (such as "HES"). Pre-registered in
20261102T051313Z-civic-tech/findings/prereg-abbrev-oos.md.

    python abbrev_oos.py --studies out/studies.jsonl --variables data/variables.jsonl.gz \
        --values data/var_values.jsonl.gz --devset devset.json --out /out

Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
"""

import argparse
import collections
import json
import os
import sys
import time

__version__ = "0.1.0"

FRAMES = ("v0_short", "v1_official")


def reverse_definitions(defs, normalize):
    """{normalized long form: [(short form, count), ...]} from {short: Counter(long: count)}."""
    rev = collections.defaultdict(list)
    for short, counts in (defs or {}).items():
        for long, n in counts.items():
            rev[normalize(long)].append((short, n))
    return dict(rev)


def disease_names(disease, normalize, uninvert):
    """The normalized names a long form may match: the disease as stored, and turned around."""
    names = [normalize(disease)]
    turned = uninvert(disease)
    if turned:
        t = normalize(turned)
        if t not in names:
            names.append(t)
    return names


def pick(disease, rev, defs, normalize, uninvert, long_form, skip_upper):
    """The automatic abbreviation for one disease, or None.

    Returns {"abbrev", "matched", "count", "top", "top_count", "top_matches"}."""
    names = disease_names(disease, normalize, uninvert)
    cands = []
    for name in names:
        for short, n in rev.get(name, []):
            if short.upper() in skip_upper or short.lower() == disease.lower() or short.lower() in name.split():
                continue
            cands.append((n, short, name))
    if not cands:
        return None
    n, short, name = sorted(cands, key=lambda c: (-c[0], c[1], c[2]))[0]
    top, top_n = long_form(defs, short)
    return {"abbrev": short, "matched": name, "count": n, "top": top, "top_count": top_n,
            "top_matches": bool(top) and normalize(top) in names}


def mean(values):
    values = list(values)
    return round(sum(values) / len(values), 4) if values else None


def summarize(items, picks, frames=FRAMES, key="ndcg@10"):
    """Per frame and group: needs, d0 and auto means for base and fix, gains, rows lower/higher, seconds."""
    d0 = {(i["source"], i["frame"]): i for i in items if i["variant"] == "d0_as_is"}
    out = {}
    for frame in frames:
        auto = [i for i in items if i["variant"] == "auto" and i["frame"] == frame and (i["source"], frame) in d0]
        groups = {"all": auto,
                  "top_matches": [i for i in auto if picks[i["source"]]["top_matches"]],
                  "top_differs": [i for i in auto if not picks[i["source"]]["top_matches"]],
                  "in_table": [i for i in auto if i.get("in_table")],
                  "not_in_table": [i for i in auto if not i.get("in_table")],
                  "triggered": [i for i in auto if i.get("triggered")],
                  "not_triggered": [i for i in auto if not i.get("triggered")]}
        res = {}
        for name, members in groups.items():
            if not members:
                res[name] = {"needs": 0}
                continue
            d0_base = mean(d0[(m["source"], frame)]["base"][key] for m in members)
            d0_fix = mean(d0[(m["source"], frame)]["fix"][key] for m in members)
            base = mean(m["base"][key] for m in members)
            fix = mean(m["fix"][key] for m in members)
            drop = round(d0_base - base, 4)
            res[name] = {
                "needs": len(members), "d0_base": d0_base, "d0_fix": d0_fix, "base": base, "fix": fix,
                "fix_minus_base": round(fix - base, 4), "base_drop": drop,
                "recovered": round((fix - base) / drop, 4) if drop > 1e-9 else None,
                "fix_lower": sum(1 for m in members if m["fix"][key] < m["base"][key] - 1e-4),
                "fix_higher": sum(1 for m in members if m["fix"][key] > m["base"][key] + 1e-4),
                "base_seconds": mean(m["base"]["seconds"] for m in members),
                "fix_seconds": mean(m["fix"]["seconds"] for m in members)}
        d0_rows = [i for i in d0.values() if i["frame"] == frame]
        res["d0_rows"] = len(d0_rows)
        res["d0_fix_differs"] = sum(1 for i in d0_rows if abs(i["fix"][key] - i["base"][key]) > 1e-4)
        out[frame] = res
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--studies", required=True)
    ap.add_argument("--variables")
    ap.add_argument("--values")
    ap.add_argument("--devset", required=True)
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
    start = time.perf_counter()
    index = cf.Index(sn.load(args.studies, args.variables, args.values))
    load_seconds = round(time.perf_counter() - start, 2)
    defs = af.index_definitions(index)
    rev = reverse_definitions(defs, af.normalize)
    in_sample = {d.lower() for d in dc.ABBREV}
    skip_upper = {s.upper() for s in af.STOP} | {a.upper() for a in dc.ABBREV.values()}

    picks, rows, unparsed, excluded, no_pick = {}, [], [], [], []
    for q in dev["queries"]:
        parts = wc.decompose(q["query"])
        if parts is None:
            unparsed.append(q["id"])
            continue
        disease, keys = parts
        if disease.lower() in in_sample:
            excluded.append(q["id"])
            continue
        p = pick(disease, rev, defs, af.normalize, dc.uninvert, af.long_form, skip_upper)
        if p is None:
            no_pick.append(q["id"])
            continue
        p["disease"] = disease
        picks[q["id"]] = p
        for variant, named in (("d0_as_is", disease), ("auto", p["abbrev"])):
            for frame in FRAMES:
                rows.append({"source": q["id"], "disease": disease, "variant": variant, "frame": frame,
                             "named": named, "info_need": wc.render(frame, named, keys)})

    items = dc.measure(index, rows, dev["qrels"], (("base", ss.padded_answer), ("fix", ss.abbrev_answer)),
                       sen.parse_need, sen.TIER)
    for i in items:
        if i["variant"] == "auto":
            row_text = wc.render(i["frame"], i["named"], wc.decompose(
                next(q["query"] for q in dev["queries"] if q["id"] == i["source"]))[1])
            found = af.disease_abbreviations(row_text, defs)
            i["triggered"] = any(f["abbrev"] == i["named"] for f in found)
            i["found"] = [f["abbrev"] for f in found]
            i["in_table"] = bool(cf.expand_abbreviations(i["named"]))
    summary = summarize(items, picks)
    official = []
    for need_id, text in sn.read_needs("official_needs.jsonl") if os.path.exists("official_needs.jsonl") else []:
        official.append({"id": need_id, "base": sen.position(ss.padded_answer(index, text), sen.EXAMPLE_STUDY),
                         "fix": sen.position(ss.abbrev_answer(index, text), sen.EXAMPLE_STUDY)})

    report = {"abbrev_oos": __version__, "abbrev_fix": af.__version__, "spark_submit": ss.__version__,
              "disease_check": dc.__version__, "sentence_need": sen.__version__, "tier": sen.TIER,
              "systems": {"base": "spark_submit.padded_answer (0.2.0 default)",
                          "fix": "spark_submit.abbrev_answer (0.3.0 default)"},
              "questions": len(dev["queries"]), "unparsed": unparsed, "excluded_in_sample": excluded,
              "no_pick": no_pick, "picked": len(picks), "load_seconds": load_seconds,
              "mined_short_forms": len(defs), "picks": picks,
              "top_matches": sum(1 for p in picks.values() if p["top_matches"]),
              "summary": summary, "official": official, "items": items,
              "note": "Silver labels are circular; the short forms are ones the snapshot defines; this measures "
                      "abbreviation handling out of the hand-picked sample, not the official score."}
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "oos_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)

    print("%d silver needs: %d did not decompose, %d in-sample excluded, %d no pick, %d picked; "
          "top long form is the disease for %d; load %ss, %d short forms mined" % (
              len(dev["queries"]), len(unparsed), len(excluded), len(no_pick), len(picks),
              report["top_matches"], load_seconds, len(defs)))
    for source, p in sorted(picks.items()):
        print("  %s: %s -> %s (%d); top %s (%d)%s" % (source, p["abbrev"], p["matched"], p["count"], p["top"],
                                                     p["top_count"], "" if p["top_matches"] else " DIFFERS"))
    for frame, groups in summary.items():
        print("%s: d0 rows %d, d0 rows where fix differs %d" % (frame, groups["d0_rows"], groups["d0_fix_differs"]))
        for name, e in groups.items():
            if not isinstance(e, dict):
                continue
            if not e["needs"]:
                print("  %s: 0 needs" % name)
                continue
            print("  %s: %d needs; d0 %s; base %s fix %s (fix-base %s, base drop %s, recovered %s); "
                  "fix lower %d higher %d; s/need base %s fix %s" % (
                      name, e["needs"], e["d0_base"], e["base"], e["fix"], e["fix_minus_base"], e["base_drop"],
                      e["recovered"], e["fix_lower"], e["fix_higher"], e["base_seconds"], e["fix_seconds"]))
    for item in official:
        print("%s example rank base=%s fix=%s" % (item["id"], item["base"], item["fix"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
