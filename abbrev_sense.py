#!/usr/bin/env python3
"""abbrev_sense: does abbrev_fix 0.1.1's sense check help on fresh silver needs?

abbrev-oos-v1 (2026-11-02) picked a disease abbreviation automatically for 24
silver needs and found that every loss came from the abbreviation's most
frequent mined long form being the wrong sense ("OS" -> overall survival).
abbrev_fix 0.1.1 prefers the most frequent mined long form that the snapshot
also stores as a disease term. It was written after reading those 24 needs, so
this harness tests it on needs nobody has read: a second silver dev set
(another seed), minus every disease in the 150-need seed-7 set the agents have
seen and minus the 39 hand-picked abbreviations (disease_check.ABBREV).

Each need gets the short form the snapshot defines most often with its disease
(abbrev_oos 0.1.0's rule), written with the disease (d0) and with the short form
(auto), in the short silver frame and the official sentence frame, and is ranked
by three systems: base = spark_submit.padded_answer (0.2.0 default), a =
abbrev_fix.answer(sense=False) (0.1.0, the 0.3.0 default) and b =
abbrev_fix.answer (0.1.1, sense check on).

Silver labels are circular (they come from main_disease, which the sense check
also reads). Pre-registered in 20261102T094543Z-civic-tech/findings/prereg-abbrev-sense.md.

    python abbrev_sense.py --studies out/studies.jsonl --variables data/variables.jsonl.gz \
        --values data/var_values.jsonl.gz --devset dev11.json --exclude-devset dev7.json --out /out

Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
"""

import argparse
import collections
import functools
import json
import os
import sys
import time

__version__ = "0.1.0"

FRAMES = ("v0_short", "v1_official")
SYSTEMS = ("base", "a", "b")


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


def pick(disease, rev, normalize, uninvert, skip_upper):
    """The short form the snapshot defines most often with this disease, as (short, matched name, count), or None."""
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
    return short, name, n


def senses(short, names, defs, terms, af):
    """What 0.1.0 (a) and 0.1.1 (b) would pick for short, and whether each is the disease."""
    a, a_n = af.long_form(defs, short)
    b, b_n = af.sense_long_form(defs, short, terms)
    na, nb = af.normalize(a or ""), af.normalize(b or "")
    return {"a_sense": a, "a_count": a_n, "b_sense": b, "b_count": b_n,
            "a_matches": na in names, "b_matches": nb in names, "sense_changed": na != nb,
            "senses": len(af.long_form_counts(defs, short))}


def mean(values):
    values = list(values)
    return round(sum(values) / len(values), 4) if values else None


def summarize(items, picks, frames=FRAMES, key="ndcg@10"):
    """Per frame and group: needs, mean NDCG for each system, b-a and b-base, rows where b < a or b > a,
    seconds; plus d0 rows where b differs from base and sense_same rows where b differs from a."""
    d0 = {(i["source"], i["frame"]): i for i in items if i["variant"] == "d0_as_is"}
    out = {}
    for frame in frames:
        auto = [i for i in items if i["variant"] == "auto" and i["frame"] == frame and (i["source"], frame) in d0]
        groups = {"all": auto,
                  "sense_changed": [i for i in auto if picks[i["source"]]["sense_changed"]],
                  "sense_same": [i for i in auto if not picks[i["source"]]["sense_changed"]],
                  "a_top_matches": [i for i in auto if picks[i["source"]]["a_matches"]],
                  "a_top_differs": [i for i in auto if not picks[i["source"]]["a_matches"]],
                  "in_table": [i for i in auto if i.get("in_table")],
                  "not_in_table": [i for i in auto if not i.get("in_table")]}
        res = {}
        for name, members in groups.items():
            if not members:
                res[name] = {"needs": 0}
                continue
            e = {"needs": len(members), "d0_base": mean(d0[(m["source"], frame)]["base"][key] for m in members)}
            for s in SYSTEMS:
                e[s] = mean(m[s][key] for m in members)
                e[s + "_seconds"] = mean(m[s]["seconds"] for m in members)
            e["b_minus_a"] = round(e["b"] - e["a"], 4)
            e["b_minus_base"] = round(e["b"] - e["base"], 4)
            e["a_minus_base"] = round(e["a"] - e["base"], 4)
            e["b_lower_than_a"] = sum(1 for m in members if m["b"][key] < m["a"][key] - 1e-4)
            e["b_higher_than_a"] = sum(1 for m in members if m["b"][key] > m["a"][key] + 1e-4)
            res[name] = e
        d0_rows = [i for i in d0.values() if i["frame"] == frame]
        res["d0_rows"] = len(d0_rows)
        res["d0_b_differs_from_base"] = sum(1 for i in d0_rows if abs(i["b"][key] - i["base"][key]) > 1e-4)
        res["sense_same_b_differs_from_a"] = sum(
            1 for i in groups["sense_same"] if abs(i["b"][key] - i["a"][key]) > 1e-4)
        out[frame] = res
    return out


def devset_diseases(path, decompose):
    with open(path, encoding="utf-8") as f:
        dev = json.load(f)
    out = set()
    for q in dev["queries"]:
        parts = decompose(q["query"])
        if parts:
            out.add(parts[0].lower())
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--studies", required=True)
    ap.add_argument("--variables")
    ap.add_argument("--values")
    ap.add_argument("--devset", required=True)
    ap.add_argument("--exclude-devset", required=True)
    ap.add_argument("--max-picks", type=int, default=150)
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
    terms = af.index_disease_terms(index)
    rev = reverse_definitions(defs, af.normalize)
    seen = devset_diseases(args.exclude_devset, wc.decompose)
    hand = {d.lower() for d in dc.ABBREV}
    skip_upper = {s.upper() for s in af.STOP} | {a.upper() for a in dc.ABBREV.values()}

    picks, rows, unparsed, excluded_seen, excluded_hand, no_pick, capped = {}, [], [], [], [], [], []
    for q in dev["queries"]:
        parts = wc.decompose(q["query"])
        if parts is None:
            unparsed.append(q["id"])
            continue
        disease, keys = parts
        if disease.lower() in hand:
            excluded_hand.append(q["id"])
            continue
        if disease.lower() in seen:
            excluded_seen.append(q["id"])
            continue
        p = pick(disease, rev, af.normalize, dc.uninvert, skip_upper)
        if p is None:
            no_pick.append(q["id"])
            continue
        if len(picks) >= args.max_picks:
            capped.append(q["id"])
            continue
        short, matched, n = p
        names = disease_names(disease, af.normalize, dc.uninvert)
        entry = {"abbrev": short, "matched": matched, "count": n, "disease": disease}
        entry.update(senses(short, names, defs, terms, af))
        picks[q["id"]] = entry
        for variant, named in (("d0_as_is", disease), ("auto", short)):
            for frame in FRAMES:
                rows.append({"source": q["id"], "disease": disease, "variant": variant, "frame": frame,
                             "named": named, "info_need": wc.render(frame, named, keys)})

    systems = (("base", ss.padded_answer), ("a", functools.partial(af.answer, sense=False)), ("b", af.answer))
    items = dc.measure(index, rows, dev["qrels"], systems, sen.parse_need, sen.TIER)
    queries = {q["id"]: q["query"] for q in dev["queries"]}
    for i in items:
        if i["variant"] == "auto":
            row_text = wc.render(i["frame"], i["named"], wc.decompose(queries[i["source"]])[1])
            found = af.disease_abbreviations(row_text, defs)
            i["triggered"] = any(f["abbrev"] == i["named"] for f in found)
            i["found"] = [f["abbrev"] for f in found]
            i["in_table"] = bool(cf.expand_abbreviations(i["named"]))
    summary = summarize(items, picks)
    official = []
    if os.path.exists("official_needs.jsonl"):
        for need_id, text in sn.read_needs("official_needs.jsonl"):
            official.append({"id": need_id, **{name: sen.position(fn(index, text), sen.EXAMPLE_STUDY)
                                                for name, fn in systems}})

    report = {"abbrev_sense": __version__, "abbrev_fix": af.__version__, "spark_submit": ss.__version__,
              "disease_check": dc.__version__, "sentence_need": sen.__version__, "tier": sen.TIER,
              "systems": {"base": "spark_submit.padded_answer (0.2.0 default)",
                          "a": "abbrev_fix.answer(sense=False) (0.1.0 behaviour; the 0.3.0 default)",
                          "b": "abbrev_fix.answer (0.1.1, sense check)"},
              "questions": len(dev["queries"]), "unparsed": unparsed, "excluded_seen": excluded_seen,
              "excluded_hand_picked": excluded_hand, "no_pick": no_pick, "capped": capped,
              "picked": len(picks), "load_seconds": load_seconds, "mined_short_forms": len(defs),
              "disease_terms": len(terms), "picks": picks,
              "a_top_matches": sum(1 for p in picks.values() if p["a_matches"]),
              "b_top_matches": sum(1 for p in picks.values() if p["b_matches"]),
              "sense_changed": sum(1 for p in picks.values() if p["sense_changed"]),
              "sense_changed_b_matches": sum(1 for p in picks.values() if p["sense_changed"] and p["b_matches"]),
              "summary": summary, "official": official, "items": items,
              "note": "Silver labels are circular; the short forms are ones the snapshot defines; fresh needs "
                      "exclude every disease of the seed-7 dev set and the 39 hand-picked abbreviations."}
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "sense_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)

    print("%d fresh silver needs: %d did not decompose, %d seen diseases excluded, %d hand-picked excluded, "
          "%d no pick, %d capped, %d picked; load %ss, %d short forms mined, %d disease terms" % (
              len(dev["queries"]), len(unparsed), len(excluded_seen), len(excluded_hand), len(no_pick),
              len(capped), len(picks), load_seconds, len(defs), len(terms)))
    print("a's sense is the disease for %d, b's for %d; sense changed for %d (b is the disease for %d of them)" % (
        report["a_top_matches"], report["b_top_matches"], report["sense_changed"],
        report["sense_changed_b_matches"]))
    for source, p in sorted(picks.items()):
        if p["sense_changed"] or not p["a_matches"]:
            print("  %s: %s (%s); a %s (%d)%s; b %s (%d)%s" % (
                source, p["abbrev"], p["disease"], p["a_sense"], p["a_count"], "" if p["a_matches"] else " WRONG",
                p["b_sense"], p["b_count"], "" if p["b_matches"] else " WRONG"))
    for frame, groups in summary.items():
        print("%s: d0 rows %d, d0 rows where b differs from base %d, sense-same rows where b differs from a %d" % (
            frame, groups["d0_rows"], groups["d0_b_differs_from_base"], groups["sense_same_b_differs_from_a"]))
        for name, e in groups.items():
            if not isinstance(e, dict):
                continue
            if not e["needs"]:
                print("  %s: 0 needs" % name)
                continue
            print("  %s: %d needs; d0 %s; base %s a %s b %s (b-a %s, b-base %s); b<a %d b>a %d; "
                  "s/row base %s a %s b %s" % (
                      name, e["needs"], e["d0_base"], e["base"], e["a"], e["b"], e["b_minus_a"],
                      e["b_minus_base"], e["b_lower_than_a"], e["b_higher_than_a"], e["base_seconds"],
                      e["a_seconds"], e["b_seconds"]))
    for item in official:
        print("%s example rank base=%s a=%s b=%s" % (item["id"], item["base"], item["a"], item["b"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
