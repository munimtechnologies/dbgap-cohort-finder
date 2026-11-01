#!/usr/bin/env python3
"""disease_check: does MV2's SPARK Task 2 system still find the studies when a need names its disease the way people do?

The silver dev needs copy each study's main_disease as dbGaP stores it, often as an
inverted MeSH-style heading ("carcinoma, hepatocellular", "infant, premature",
"stomach neoplasms"). The one official Task 2 example says "lung adenocarcinoma",
the way a person writes it. wording_check 0.1.0 kept the disease fixed and moved
only the framing; this file keeps the framing fixed and moves only the disease:

    d0_as_is       the disease as the silver need writes it (the baseline)
    d1_uninverted  comma headings turned around mechanically ("hepatocellular carcinoma")
    d2_natural     a hand-written everyday or clinical name ("gastric cancer", "Crohn's disease")
    d3_abbrev      a common abbreviation ("COPD", "PCOS"), split by whether cohort_finder's
                   abbreviation table knows it

Each variant is written in two frames, the short silver form and the official
sentence template, and only needs whose text changes are measured. For each, it
reports NDCG@10 against the silver labels for the current system (spark_submit.answer)
and for wording_fix.answer, the parsed disease topic, and "fit": the share of the
need's relevant studies whose disease still meets the primary-disease tier with that
topic (snapshot.disease_requirement >= sentence_need.TIER). Silver labels are
circular and the names were written by the same agents that read the matcher, so
this measures naming sensitivity, not the official score. Pre-registered in
20261031T173156Z-civic-tech/findings/prereg-disease-check.md.

    python disease_check.py --studies out/studies.jsonl --variables data/variables.jsonl.gz \
        --values data/var_values.jsonl.gz --devset devset.json --out /out

Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
"""

import argparse
import json
import os
import sys
import time

__version__ = "0.1.0"

VARIANTS = ("d0_as_is", "d1_uninverted", "d2_natural", "d3_abbrev")
FRAMES = ("v0_short", "v1_official")
SYSTEMS = ("base", "fix")
POSSESSIVE = ("parkinson disease", "tourette syndrome", "crohn disease", "huntington disease")

# Everyday or clinical names, keyed by the silver need's disease. Written before any run.
NATURAL = {
    "pediatric multisystem inflammatory disease, covid-19 related": "multisystem inflammatory syndrome in children",
    "glomerulosclerosis, focal segmental": "focal segmental glomerulosclerosis",
    "infant, premature": "preterm infants",
    "parkinson disease": "Parkinson's disease",
    "alcoholism": "alcohol use disorder",
    "drug-related side effects and adverse reactions": "adverse drug reactions",
    "myeloproliferative disorders": "myeloproliferative neoplasms",
    "urea cycle disorders, inborn": "urea cycle disorders",
    "andersen syndrome": "Andersen-Tawil syndrome",
    "staphylococcus aureus": "Staphylococcus aureus infections",
    "macular degeneration": "age-related macular degeneration",
    "mucopolysaccharidoses": "mucopolysaccharidosis",
    "intestinal neoplasms": "intestinal cancer",
    "carcinoma, hepatocellular": "hepatocellular carcinoma",
    "hepatitis c": "hepatitis C infection",
    "carcinoma, small cell": "small cell lung cancer",
    "fuchs' endothelial dystrophy": "Fuchs endothelial corneal dystrophy",
    "depressive disorder, major": "major depressive disorder",
    "lung neoplasms": "lung cancer",
    "melanoma, cutaneous malignant": "cutaneous melanoma",
    "tourette syndrome": "Tourette's syndrome",
    "crohn disease": "Crohn's disease",
    "chromosome 9p deletion syndrome": "9p deletion syndrome",
    "congenital abnormalities": "birth defects",
    "peanut hypersensitivity": "peanut allergy",
    "spinocerebellar ataxias": "spinocerebellar ataxia",
    "gastro-enteropancreatic neuroendocrine tumor": "gastroenteropancreatic neuroendocrine tumors",
    "plasmodium falciparum": "falciparum malaria",
    "gallbladder neoplasms": "gallbladder cancer",
    "non-alcoholic fatty liver disease": "nonalcoholic fatty liver disease",
    "dermatitis, atopic": "atopic dermatitis",
    "sequence analysis, rna": "RNA sequence analysis",
    "dna copy number variations": "copy number variants",
    "stomach neoplasms": "gastric cancer",
    "hypertension": "high blood pressure",
    "colonic neoplasms": "colon cancer",
    "leukemia, lymphocytic, chronic, b-cell": "chronic lymphocytic leukemia",
    "lymphoma, t-cell, cutaneous": "cutaneous T-cell lymphoma",
    "pulmonary disease, chronic obstructive": "chronic obstructive pulmonary disease",
    "leukemia, myelomonocytic, juvenile": "juvenile myelomonocytic leukemia",
    "intracranial aneurysm": "brain aneurysms",
    "scleroderma, systemic": "systemic sclerosis",
    "esophageal neoplasms": "esophageal cancer",
    "heroin dependence": "heroin addiction",
    "drug resistance, neoplasm": "cancer drug resistance",
    "alpha 1-antitrypsin deficiency": "alpha-1 antitrypsin deficiency",
    "carcinoma, intraductal, noninfiltrating": "ductal carcinoma in situ",
    "colorectal neoplasms": "colorectal cancer",
    "hypercholesterolemia": "high cholesterol",
    "leukemia, myeloid, acute": "acute myeloid leukemia",
    "acne vulgaris": "acne",
    "anemia, sickle cell": "sickle cell disease",
    "subcutaneous fat, abdominal": "abdominal subcutaneous fat",
    "sarcoma, synovial": "synovial sarcoma",
    "vaginosis, bacterial": "bacterial vaginosis",
    "premature birth": "preterm birth",
    "lymphoma, b-cell": "B-cell lymphoma",
    "coronary disease": "coronary artery disease",
    "peripheral nervous system diseases": "peripheral neuropathy",
    "brain neoplasms": "brain tumors",
    "hiv": "HIV infection",
    "arthritis, rheumatoid": "rheumatoid arthritis",
    "platelet disorder, familial, with associated myeloid malignancy":
        "familial platelet disorder with associated myeloid malignancy",
    "graft vs host disease": "graft-versus-host disease",
    "neurofibromatosis 1": "neurofibromatosis type 1",
    "sezary syndrome": "Sézary syndrome",
    "huntington disease": "Huntington's disease",
    "leukemia, lymphoid": "lymphoid leukemia",
    "cryptorchidism": "undescended testicles",
    "leiomyoma": "uterine fibroids",
    "heterotaxy syndrome": "heterotaxy",
    "cholangiocarcinoma": "bile duct cancer",
    "bone marrow failure disorders": "bone marrow failure syndromes",
}

# Common abbreviations, keyed the same way. Written before any run.
ABBREV = {
    "pediatric multisystem inflammatory disease, covid-19 related": "MIS-C",
    "glomerulosclerosis, focal segmental": "FSGS",
    "parkinson disease": "PD",
    "alcoholism": "AUD",
    "macular degeneration": "AMD",
    "retinopathy of prematurity": "ROP",
    "carcinoma, hepatocellular": "HCC",
    "hepatitis c": "HCV",
    "carcinoma, small cell": "SCLC",
    "polycystic ovary syndrome": "PCOS",
    "osteoarthritis": "OA",
    "depressive disorder, major": "MDD",
    "cystic fibrosis": "CF",
    "hypereosinophilic syndrome": "HES",
    "glioblastoma": "GBM",
    "non-alcoholic fatty liver disease": "NAFLD",
    "leukemia, lymphocytic, chronic, b-cell": "CLL",
    "lymphoma, t-cell, cutaneous": "CTCL",
    "pulmonary disease, chronic obstructive": "COPD",
    "leukemia, myelomonocytic, juvenile": "JMML",
    "obsessive-compulsive disorder": "OCD",
    "lymphangioleiomyomatosis": "LAM",
    "acute lung injury": "ALI",
    "alpha 1-antitrypsin deficiency": "AATD",
    "carcinoma, intraductal, noninfiltrating": "DCIS",
    "colorectal neoplasms": "CRC",
    "leukemia, myeloid, acute": "AML",
    "anemia, sickle cell": "SCD",
    "coronary disease": "CAD",
    "charcot-marie-tooth disease": "CMT",
    "schizophrenia": "SCZ",
    "hiv": "HIV",
    "arthritis, rheumatoid": "RA",
    "neuroendocrine tumors": "NETs",
    "graft vs host disease": "GVHD",
    "congenital disorders of glycosylation": "CDG",
    "neurofibromatosis 1": "NF1",
    "idiopathic pulmonary fibrosis": "IPF",
    "huntington disease": "HD",
}


# ---------------------------------------------------------------- naming

def uninvert(disease):
    """'carcinoma, hepatocellular' -> 'hepatocellular carcinoma'; None if not an inverted heading.

    Lists ("congenital, hereditary, and neonatal ...") and qualifiers that start with
    "with" are left alone."""
    if ", " not in disease or " and " in disease:
        return None
    parts = disease.split(", ")
    if any(p.startswith("with ") for p in parts):
        return None
    return " ".join(reversed(parts))


def name(variant, disease):
    """The disease as one variant names it, or None when the variant has no other name for it."""
    if variant == "d0_as_is":
        return disease
    if variant == "d1_uninverted":
        new = uninvert(disease)
    elif variant == "d2_natural":
        new = NATURAL.get(disease)
    elif variant == "d3_abbrev":
        new = ABBREV.get(disease)
    else:
        raise ValueError("unknown variant %r" % variant)
    return new if new and new != disease else None


def in_table(abbrev):
    """Whether cohort_finder's abbreviation table spells this abbreviation out."""
    import cohort_finder as cf
    return bool(cf.expand_abbreviations(abbrev))


def rows_for(queries):
    """(rows to run, ids that did not decompose). Each row is one need in one variant and frame."""
    import wording_check as wc
    rows, unparsed = [], []
    for q in queries:
        parts = wc.decompose(q["query"])
        if parts is None:
            unparsed.append(q["id"])
            continue
        disease, keys = parts
        for variant in VARIANTS:
            named = name(variant, disease)
            if named is None:
                continue
            for frame in FRAMES:
                rows.append({"source": q["id"], "disease": disease, "variant": variant, "frame": frame,
                             "named": named, "info_need": wc.render(frame, named, keys)})
    return rows, unparsed


# ---------------------------------------------------------------- measuring

def fit(lookup, relevant, topic, tier):
    """Share of the relevant studies whose disease meets the tier for this topic (None without a topic)."""
    import snapshot as sn
    if not topic or not relevant:
        return None
    ok = sum(1 for acc in relevant if acc in lookup and sn.disease_requirement(lookup[acc], topic)[0] >= tier)
    return round(ok / len(relevant), 4)


def measure(index, rows, qrels, answers, parse, tier, k=10):
    """One item per row: NDCG@k and seconds per system, the parsed topic, fit and constraint parse."""
    import cohort_finder as cf
    import sentence_need as sen
    import wording_check as wc
    lookup = sen.by_accession(index)
    out = []
    for row in rows:
        relevance = qrels.get(row["source"], {})
        q = parse(row["info_need"])
        topic = sorted(set(q.get("topic") or []))
        item = {key: row[key] for key in ("source", "disease", "variant", "frame", "named")}
        item.update({"topic": topic, "fit": fit(lookup, [a for a, r in relevance.items() if r > 0], topic, tier),
                     "constraints": wc.constraint_parse(q)})
        for system, answer in answers:
            start = time.perf_counter()
            ranked = answer(index, row["info_need"])
            item[system] = {"ndcg@%d" % k: round(cf.ndcg(ranked, relevance, k), 4),
                            "seconds": round(time.perf_counter() - start, 3)}
        out.append(item)
    return out


def summarize(items, k=10):
    """Per frame, variant (and abbreviation group) and system: needs, means against d0 on the same needs, losses.

    The d0_as_is group is every measured need against itself (its drop is 0)."""
    key = "ndcg@%d" % k
    base = {(i["source"], i["frame"]): i for i in items if i["variant"] == "d0_as_is"}
    groups = {}
    for i in items:
        if (i["source"], i["frame"]) not in base:
            continue
        names = [i["variant"]]
        if i["variant"] == "d3_abbrev":
            names.append("d3_abbrev_" + ("in_table" if i.get("in_table") else "not_in_table"))
        if i["variant"] == "d2_natural" and i["disease"] in POSSESSIVE:
            names.append("d2_possessive")
        for n in names:
            groups.setdefault((i["frame"], n), []).append(i)
    out = {}
    for (frame, group), members in sorted(groups.items()):
        entry = {"needs": len(members)}
        for system in SYSTEMS:
            pairs = [(base[(m["source"], frame)][system][key], m[system][key]) for m in members]
            drops = [b - v for b, v in pairs]
            entry[system] = {
                "d0_" + key: round(sum(b for b, _ in pairs) / len(pairs), 4),
                key: round(sum(v for _, v in pairs) / len(pairs), 4),
                "drop": round(sum(drops) / len(drops), 4),
                "same": sum(1 for d in drops if abs(d) <= 1e-4),
                "lower": sum(1 for d in drops if d > 1e-4),
                "higher": sum(1 for d in drops if d < -1e-4),
                "lost_over_0.2": sum(1 for d in drops if d > 0.2),
                "mean_seconds": round(sum(m[system]["seconds"] for m in members) / len(members), 3)}
        lost_fit, loss_all, loss_fit = 0, 0.0, 0.0
        for m in members:
            b = base[(m["source"], frame)]
            drop = b["base"][key] - m["base"][key]
            fell = b["fit"] is not None and b["fit"] >= 0.5 and (m["fit"] is None or m["fit"] < 0.5)
            lost_fit += fell
            if drop > 1e-4:
                loss_all += drop
                loss_fit += drop if fell else 0.0
        entry["fit_lost"] = lost_fit
        entry["topic_empty"] = sum(1 for m in members if not m["topic"])
        entry["parse_differs"] = sum(1 for m in members if m["constraints"] != base[(m["source"], frame)]["constraints"])
        entry["base_loss"] = round(loss_all, 4)
        entry["base_loss_from_fit_lost"] = round(loss_fit, 4)
        out.setdefault(frame, {})[group] = entry
    return out


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
    import wording_check as wc
    import wording_fix as wf

    with open(args.devset, encoding="utf-8") as f:
        dev = json.load(f)
    rows, unparsed = rows_for(dev["queries"])
    start = time.perf_counter()
    index = cf.Index(sn.load(args.studies, args.variables, args.values))
    load_seconds = round(time.perf_counter() - start, 2)
    items = measure(index, rows, dev["qrels"], (("base", ss.answer), ("fix", wf.answer)), sen.parse_need, sen.TIER)
    for i in items:
        if i["variant"] == "d3_abbrev":
            i["in_table"] = in_table(i["named"])
    report = {"disease_check": __version__, "spark_submit": ss.__version__, "sentence_need": sen.__version__,
              "wording_check": wc.__version__, "wording_fix": wf.__version__, "tier": sen.TIER,
              "questions": len(dev["queries"]), "unparsed": unparsed, "rows": len(rows),
              "load_seconds": load_seconds, "summary": summarize(items), "items": items,
              "note": "Silver labels are circular and the names were written by the agents that read the matcher; "
                      "this measures disease-naming sensitivity, not the official score."}
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "disease_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    print("%d silver needs, %d did not decompose, %d rows" % (len(dev["queries"]), len(unparsed), len(rows)))
    for frame, groups in report["summary"].items():
        for group, e in groups.items():
            print("%s %s: %d needs, fit_lost %d, topic_empty %d, parse_differs %d, base loss %s (from fit lost %s)"
                  % (frame, group, e["needs"], e["fit_lost"], e["topic_empty"], e["parse_differs"],
                     e["base_loss"], e["base_loss_from_fit_lost"]))
            for system in SYSTEMS:
                s = e[system]
                print("  %s: d0 %s -> %s (drop %s) same %d lower %d higher %d lost>0.2 %d %ss/need" % (
                    system, s["d0_ndcg@10"], s["ndcg@10"], s["drop"], s["same"], s["lower"], s["higher"],
                    s["lost_over_0.2"], s["mean_seconds"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
