#!/usr/bin/env python3
"""wording_check: does MV2's SPARK Task 2 system give the same answers when a need is worded differently?

SPARK dbGaP Task 2 will judge about 1,000 natural-language needs that nobody has
seen yet. The system (spark_submit.answer: sentence_need's parse and rank with
primary-disease tiering at 0.6) has been tuned on short silver needs ("Studies of
asthma in adults and with whole genome sequencing") and on one official sentence
template. This file takes each silver need from `snapshot.py devset`, splits it into
its disease and constraints, and writes it four more ways with the same meaning:

    v0_short     the silver need as written (the baseline)
    v1_official  the Task 2 description's sentence template
    v2_question  "Which dbGaP studies enrolled adults diagnosed with ... ?"
    v3_chat      "I'm looking for ... cohorts in adults that have WGS data."
    v4_synonyms  the short form with other names for each constraint (WGS, aged 18 or older, GRU)

The disease is copied unchanged in every variant, so only the framing and the
constraint wording move. It reports NDCG@10 against the silver labels per variant,
which constraint fields the parse loses, and how much of each variant's loss comes
from needs whose constraint parse changed. Silver labels are circular (built from
the fields the ranker reads), so this measures wording sensitivity, not the official
score. Pre-registered in 20261031T002124Z-civic-tech/findings/prereg-wording-check.md.

    python wording_check.py --studies out/studies.jsonl --variables data/variables.jsonl.gz \
        --values data/var_values.jsonl.gz --devset devset.json --out /out

Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
"""

import argparse
import json
import os
import re
import sys
import time

__version__ = "0.1.0"

VARIANTS = ("v0_short", "v1_official", "v2_question", "v3_chat", "v4_synonyms")
# snapshot.DEV_TYPES and _dev_options' phrases, as make_devset writes them.
PHRASE_KEYS = {"with whole genome sequencing": "wgs", "with exome sequencing": "wes",
               "with RNA-seq": "rnaseq", "with DNA methylation data": "methylation",
               "consented for general research use": "gru", "in adults": "adults", "in children": "children"}
RACE = r"including at least 100 [A-Za-z][A-Za-z ]*? participants"
CONSTRAINT = r"(?:%s|%s)" % ("|".join(re.escape(p) for p in PHRASE_KEYS), RACE)
SILVER_RE = re.compile(r"Studies of (.+?) (%s)(?: and (%s))?" % (CONSTRAINT, CONSTRAINT))
RACE_RE = re.compile(r"including at least 100 (.+) participants")
DATA_TYPES = ("wgs", "wes", "rnaseq", "methylation")

# How each variant names the data types.
TYPE_WORDS = {
    "v1_official": {"wgs": "whole genomic sequences", "wes": "whole exome sequences",
                    "rnaseq": "RNA sequencing data", "methylation": "DNA methylation profiles"},
    "v2_question": {"wgs": "whole-genome sequencing data", "wes": "exome sequencing data",
                    "rnaseq": "RNA-seq data", "methylation": "DNA methylation data"},
    "v3_chat": {"wgs": "WGS data", "wes": "whole-exome data", "rnaseq": "transcriptomic (RNA-seq) data",
                "methylation": "methylation array data"},
}
SYNONYMS = {"wgs": "with WGS", "wes": "with WES", "rnaseq": "with transcriptome sequencing",
            "methylation": "with epigenome-wide methylation data", "gru": "with GRU consent",
            "adults": "in participants aged 18 or older", "children": "in participants under 18"}
# Parsed fields that carry a need's constraints (only those the parse has are compared).
CONSTRAINT_FIELDS = ("data_types", "age", "groups", "consents", "consent", "min_subjects", "var_terms", "var_alts")


# ---------------------------------------------------------------- wording

def decompose(text):
    """'Studies of asthma in adults and with RNA-seq' -> ('asthma', ['adults', 'rnaseq']), or None.

    A race constraint becomes ('race', label)."""
    m = SILVER_RE.fullmatch((text or "").strip())
    if not m:
        return None
    keys = []
    for phrase in m.groups()[1:]:
        if phrase is None:
            continue
        race = RACE_RE.fullmatch(phrase)
        keys.append(("race", race.group(1)) if race else PHRASE_KEYS[phrase])
    return m.group(1), keys


def join_and(items):
    items = list(items)
    if len(items) <= 2:
        return " and ".join(items)
    return ", ".join(items[:-1]) + " and " + items[-1]


def _split(keys):
    """(age key or None, data type keys, gru?, race label or None)."""
    age = next((k for k in keys if k in ("adults", "children")), None)
    types = [k for k in keys if k in DATA_TYPES]
    race = next((k[1] for k in keys if isinstance(k, tuple)), None)
    return age, types, "gru" in keys, race


def render(variant, disease, keys):
    """The need written one way; keys come from decompose()."""
    age, types, gru, race = _split(keys)
    if variant == "v0_short":
        return "Studies of %s %s" % (disease, " and ".join(_short(k) for k in keys))
    if variant == "v4_synonyms":
        return "Studies of %s %s" % (disease, " and ".join(
            "with 100 or more %s participants" % k[1] if isinstance(k, tuple) else SYNONYMS[k] for k in keys))
    words = [TYPE_WORDS[variant][k] for k in types]
    if variant == "v1_official":
        who = {"adults": "adult participants", "children": "pediatric participants"}.get(age, "participants")
        text = "Find dbGaP studies involving %s with %s as the primary disease" % (who, disease)
        if gru:
            text += ", consented for general research use"
        if race:
            text += ", including at least 100 %s participants" % race
        if words:
            text += ", where participant-level data include %s" % join_and(words)
        return text + "."
    if variant == "v2_question":
        who = {"adults": "adults", "children": "children"}.get(age, "participants")
        parts = []
        if words:
            parts.append("have %s available" % join_and(words))
        if race:
            parts.append("include at least 100 %s participants" % race)
        if gru:
            parts.append("are consented for general research use")
        text = "Which dbGaP studies enrolled %s diagnosed with %s" % (who, disease)
        return text + "".join(" and " + p for p in parts) + "?"
    if variant == "v3_chat":
        text = "I'm looking for %s cohorts" % disease
        text += {"adults": " in adults", "children": " in kids"}.get(age, "")
        parts = []
        if words:
            parts.append("that have %s" % join_and(words))
        if race:
            parts.append("with at least 100 %s participants" % race)
        if gru:
            parts.append("with GRU consent")
        return text + (" " + " and ".join(parts) if parts else "") + "."
    raise ValueError("unknown variant %r" % variant)


def _short(key):
    if isinstance(key, tuple):
        return "including at least 100 %s participants" % key[1]
    return next(p for p, k in PHRASE_KEYS.items() if k == key)


def key_names(keys):
    return ["race" if isinstance(k, tuple) else k for k in keys]


def variants(queries):
    """(rows for variants.jsonl, ids that did not decompose)."""
    rows, unparsed = [], []
    for q in queries:
        parts = decompose(q["query"])
        if parts is None:
            unparsed.append(q["id"])
            continue
        disease, keys = parts
        for v in VARIANTS:
            rows.append({"info_need_id": "%s-%s" % (q["id"], v), "info_need": render(v, disease, keys),
                         "source": q["id"], "variant": v, "constraints": key_names(keys)})
    return rows, unparsed


# ---------------------------------------------------------------- measuring

def constraint_parse(q):
    """The parsed constraint fields, JSON-comparable."""
    out = {}
    for key in CONSTRAINT_FIELDS:
        if key in q:
            v = q[key]
            if isinstance(v, (set, frozenset)):
                v = sorted(v)
            elif isinstance(v, tuple):
                v = list(v)
            out[key] = v
    return json.loads(json.dumps(out, sort_keys=True, default=str))


def differing(a, b):
    return sorted(k for k in set(a) | set(b) if a.get(k) != b.get(k))


def summarize(per_need, k=10):
    """Per-variant means, changes against v0 and the share of each variant's loss from parse changes."""
    out = {}
    base = {n["id"]: n["ndcg"]["v0_short"] for n in per_need}
    for v in VARIANTS:
        scores = {n["id"]: n["ndcg"][v] for n in per_need}
        drops = {i: base[i] - s for i, s in scores.items()}
        parse_diff = {n["id"] for n in per_need if n["parse_diff"].get(v)}
        loss = sum(d for d in drops.values() if d > 1e-9)
        loss_parse = sum(d for i, d in drops.items() if d > 1e-9 and i in parse_diff)
        by_key = {}
        for n in per_need:
            for key in set(n["constraints"]):
                by_key.setdefault(key, []).append(n["ndcg"][v])
        out[v] = {"ndcg@%d" % k: round(sum(scores.values()) / len(scores), 4) if scores else 0.0,
                  "lower_than_v0": sum(1 for d in drops.values() if d > 1e-9),
                  "higher_than_v0": sum(1 for d in drops.values() if d < -1e-9),
                  "parse_differs": len(parse_diff),
                  "topic_differs": sum(1 for n in per_need if n["topic_diff"].get(v) is not None),
                  "loss": round(loss, 4), "loss_from_parse_differs": round(loss_parse, 4),
                  "by_constraint": {key: {"needs": len(s), "ndcg@%d" % k: round(sum(s) / len(s), 4)}
                                    for key, s in sorted(by_key.items())},
                  "mean_seconds": round(sum(n["seconds"][v] for n in per_need) / len(per_need), 3)
                  if per_need else None}
    return out


def measure(index, rows, qrels, answer, parse, k=10):
    import cohort_finder as cf
    by_source = {}
    for row in rows:
        by_source.setdefault(row["source"], []).append(row)
    per_need = []
    for source, items in by_source.items():
        n = {"id": source, "constraints": items[0]["constraints"], "ndcg": {}, "seconds": {},
             "parse_diff": {}, "topic_diff": {}, "top3": {}}
        parsed = {}
        for row in items:
            v = row["variant"]
            start = time.perf_counter()
            ranked = answer(index, row["info_need"])
            n["seconds"][v] = time.perf_counter() - start
            n["ndcg"][v] = round(cf.ndcg(ranked, qrels.get(source, {}), k), 4)
            n["top3"][v] = ranked[:3]
            q = parse(row["info_need"])
            parsed[v] = (constraint_parse(q), sorted(set(q.get("topic") or [])))
        for v in VARIANTS:
            n["parse_diff"][v] = differing(parsed["v0_short"][0], parsed[v][0])
            n["topic_diff"][v] = parsed[v][1] if parsed[v][1] != parsed["v0_short"][1] else None
        n["topic_v0"] = parsed["v0_short"][1]
        n["seconds"] = {v: round(s, 3) for v, s in n["seconds"].items()}
        per_need.append(n)
    return per_need


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--studies", required=True)
    ap.add_argument("--variables")
    ap.add_argument("--values")
    ap.add_argument("--devset", required=True)
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    import cohort_finder as cf
    import sentence_need as sen
    import snapshot as sn
    import spark_submit as ss

    with open(args.devset, encoding="utf-8") as f:
        dev = json.load(f)
    rows, unparsed = variants(dev["queries"])
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "variants.jsonl"), "w", encoding="utf-8", newline="\n") as f:
        for row in rows:
            f.write(json.dumps(row, sort_keys=True) + "\n")
    start = time.perf_counter()
    index = cf.Index(sn.load(args.studies, args.variables, args.values))
    load_seconds = round(time.perf_counter() - start, 2)
    per_need = measure(index, rows, dev["qrels"], ss.answer, sen.parse_need)
    report = {"wording_check": __version__, "spark_submit": ss.__version__, "sentence_need": sen.__version__,
              "tier": sen.TIER, "questions": len(dev["queries"]), "measured": len(per_need),
              "unparsed": unparsed, "load_seconds": load_seconds, "variants": summarize(per_need),
              "per_need": per_need,
              "note": "Silver labels are circular; this measures wording sensitivity, not the official score."}
    with open(os.path.join(args.out, "wording_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print("%d silver needs, %d measured, %d did not decompose" % (len(dev["queries"]), len(per_need), len(unparsed)))
    for v, s in report["variants"].items():
        print("%s ndcg@10 %s lower %d higher %d parse_differs %d topic_differs %d loss %s (from parse %s) %ss/need"
              % (v, s["ndcg@10"], s["lower_than_v0"], s["higher_than_v0"], s["parse_differs"],
                 s["topic_differs"], s["loss"], s["loss_from_parse_differs"], s["mean_seconds"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
