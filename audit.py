#!/usr/bin/env python3
"""audit: a random sample of snapshot_survey's participant-age and race/ethnicity picks, for checking by hand.

Reads <out>/studies.jsonl and <out>/age_candidates.jsonl (and, if present,
<data>/var_values.jsonl.gz for the coded labels of each picked race variable)
and writes <out>/audit.md.

Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
"""

import argparse
import gzip
import json
import os
import random
import sys
from collections import Counter, defaultdict


def read_jsonl(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def cell(text, width=70):
    text = " ".join(str(text if text is not None else "").split()).replace("|", "/")
    return text if len(text) <= width else text[:width - 3] + "..."


def coded_labels(path, wanted):
    """{(study, dataset, name): [labels]} for the wanted race/ethnicity variables."""
    out = {}
    if not wanted or not os.path.exists(path):
        return out
    with gzip.open(path, "rt", encoding="utf-8") as f:
        for line in f:
            row = json.loads(line)
            key = (row.get("study"), row.get("dataset"), row.get("name"))
            if key in wanted:
                out[key] = row.get("values") or []
    return out


def var_key(study, var):
    dataset, _, name = (var or "").partition(" ")
    return (study, dataset, name)


def audit(studies, cands, labels_path, n=30, seed=11):
    rng = random.Random(seed)
    by_study = defaultdict(list)
    for c in cands:
        by_study[c["study"]].append(c)
    aged = [s for s in studies if s.get("age_var")]
    raced = [s for s in studies if s.get("race_var") or s.get("ethnicity_var")]
    age_sample = sorted(rng.sample(aged, min(n, len(aged))), key=lambda s: s["accession"])
    race_sample = sorted(rng.sample(raced, min(n, len(raced))), key=lambda s: s["accession"])
    wanted = set()
    for s in race_sample:
        for slot in ("race_var", "ethnicity_var"):
            if s.get(slot):
                wanted.add(var_key(s["accession"], s[slot]))
    labels = coded_labels(labels_path, wanted)

    picked = [c for c in cands if c.get("picked")]
    age_names = Counter("%s: %s" % (c["name"], cell(c.get("desc"), 50)) for c in picked)
    race_names = Counter(s["race_var"].partition(" ")[2] for s in studies if s.get("race_var"))
    eth_names = Counter(s["ethnicity_var"].partition(" ")[2] for s in studies if s.get("ethnicity_var"))

    out = ["# Audit of snapshot_survey picks", "",
           "- Studies: %d" % len(studies),
           "- With a participant-age pick: %d" % len(aged),
           "- With a race pick: %d; with an ethnicity pick: %d"
           % (sum(1 for s in studies if s.get("race_var")), sum(1 for s in studies if s.get("ethnicity_var"))),
           "- Age candidates considered: %d" % len(cands), ""]
    out += ["## Most common picked age variables", "", "| Variable: description | Studies |", "|---|---:|"]
    out += ["| %s | %d |" % (cell(k, 80), v) for k, v in age_names.most_common(25)]
    out += ["", "## Most common picked race / ethnicity variable names", "", "| Race variable | Studies |", "|---|---:|"]
    out += ["| %s | %d |" % (cell(k), v) for k, v in race_names.most_common(15)]
    out += ["", "| Ethnicity variable | Studies |", "|---|---:|"]
    out += ["| %s | %d |" % (cell(k), v) for k, v in eth_names.most_common(15)]

    out += ["", "## Random sample: participant age (seed %d)" % seed, "",
            "| Study | Title | Picked variable | Description | Range (median) | n | Other candidates |",
            "|---|---|---|---|---|---:|---|"]
    for s in age_sample:
        mine = by_study.get(s["accession"], [])
        pick = next((c for c in mine if c.get("picked")), {})
        others = ", ".join(sorted({c["name"] for c in mine if not c.get("picked")}))
        out.append("| %s | %s | %s | %s | %s-%s (%s) | %s | %s |" % (
            s["accession"], cell(s.get("name"), 45), cell(s.get("age_var"), 40), cell(pick.get("desc"), 50),
            s.get("age_min"), s.get("age_max"), s.get("age_median"), pick.get("n", ""), cell(others, 60)))

    out += ["", "## Random sample: reported race / ethnicity (seed %d)" % seed, "",
            "| Study | Title | Variable | Groups | Coded labels |", "|---|---|---|---|---|"]
    for s in race_sample:
        for slot, counts in (("race_var", "race_counts"), ("ethnicity_var", "ethnicity_counts")):
            if not s.get(slot):
                continue
            groups = ", ".join("%s %s" % (g, c) for g, c in sorted((s.get(counts) or {}).items(),
                                                                    key=lambda kv: -kv[1]))
            coded = "; ".join(labels.get(var_key(s["accession"], s[slot]), []))
            out.append("| %s | %s | %s | %s | %s |" % (s["accession"], cell(s.get("name"), 40),
                                                       cell(s[slot], 40), cell(groups, 70), cell(coded, 90)))
    out += [""]
    return "\n".join(out)


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--out", default="/out")
    ap.add_argument("--data", default="/data")
    ap.add_argument("-n", type=int, default=30)
    ap.add_argument("--seed", type=int, default=11)
    args = ap.parse_args(argv)
    studies = read_jsonl(os.path.join(args.out, "studies.jsonl"))
    cands = read_jsonl(os.path.join(args.out, "age_candidates.jsonl"))
    text = audit(studies, cands, os.path.join(args.data, "var_values.jsonl.gz"), args.n, args.seed)
    with open(os.path.join(args.out, "audit.md"), "w", encoding="utf-8") as f:
        f.write(text)
    print(text[:3000])
    return 0


if __name__ == "__main__":
    sys.exit(main())
