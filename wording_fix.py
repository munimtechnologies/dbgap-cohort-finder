#!/usr/bin/env python3
"""wording_fix: keep the words the parse already read as constraints out of the text search.

wording_check 0.1.0 (2026-10-31) reworded 150 silver needs four ways with the
disease unchanged. The structured parse barely moved (at most 3 of 150 needs per
variant), yet NDCG@10 fell from 0.8943 to 0.8656 (official sentence template),
0.8754 (question), 0.7782 (chat) and 0.8846 (synonyms). Almost none of the loss
came from needs whose parse changed (0.07 of 5.08 for the template). What does
change is the BM25 word list: "whole genome sequencing", "whole genomic
sequences", "WGS data" and "transcriptome sequencing" put different words into
the text search, although the data type is already scored as a constraint. The
chat wording also leaves a stray "m" from "I'm" in the disease topic of every need.

parse_need() is sentence_need.parse_need with two changes:
- contractions such as "I'm" and "we're" are taken out before parsing
- words of a constraint group (data type, age, consent, study design) leave the
  text-search tokens, but only when the parse read that kind of constraint, and
  never when they are topic or variable words. A few request words ("cohorts",
  "enrolled", "diagnosed") always leave. If nothing would be left, the tokens stay.

main() measures the current system and this one on the same five wordings and
on the official example needs. Pre-registered in
20261031T103556Z-civic-tech/findings/prereg-wording-fix.md.

    python wording_fix.py --studies out/studies.jsonl --variables data/variables.jsonl.gz \
        --values data/var_values.jsonl.gz --devset devset.json --needs official_needs.jsonl --out /out

Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
"""

import argparse
import json
import os
import re
import sys
import time

import cohort_finder as cf
import sentence_need as sen
import snapshot as sn

__version__ = "0.1.0"

CONTRACTION_RE = re.compile(r"\b(?:i|we|you|they|let)['’](?:m|re|ve|d|ll|s)\b", re.I)
# Each group leaves the text search only when the parse read that kind of constraint.
GROUP_WORDS = {
    "data_types": """whole genome genomes genomic sequencing sequenced sequence sequences wgs exome exomes exomic
        wes wxs rna seq rnaseq transcriptome transcriptomic methylation epigenome epigenomic wide genotype
        genotypes genotyped genotyping gwas snp snps array arrays imputed imputation chip atac proteomic
        proteomics metabolomic metabolomics mirna profile profiles""",
    "age": """adult adults child children pediatric paediatric kid kids infant infants newborn newborns neonatal
        adolescent adolescents teen teens teenager youth aged age ages year years old older elderly senior
        seniors geriatric young younger under""",
    "consent": "general research gru hmb health medical biomedical profit commercial industry irb approval",
    "designs": """case control controls longitudinal prospective retrospective cross sectional trio trios twin
        twins trial trials randomized""",
}
GROUPS = {field: frozenset(cf.tokens(words)) for field, words in GROUP_WORDS.items()}
# Request words that never name what is studied.
REQUEST = frozenset(cf.tokens("cohort cohorts enrolled enrolling recruited diagnosed involving"))


# ---------------------------------------------------------------- parsing

def constraint_words(q):
    """Words to leave out of q's text search: REQUEST, plus each group the parse read."""
    out = set(REQUEST)
    for field, words in GROUPS.items():
        if q.get(field):
            out |= words
    return out


def kept_words(q):
    """Topic and variable words, which always stay."""
    keep = set(q.get("topic") or [])
    items = list(q.get("var_terms") or [])
    for alts in q.get("var_alts") or []:
        items.extend(alts)
    for item in items:
        keep.update([item] if isinstance(item, str) else item)
    return keep


def parse_need(text):
    q = sen.parse_need(CONTRACTION_RE.sub(" ", text or ""))
    drop = constraint_words(q) - kept_words(q)
    tokens = q.get("tokens") or []
    q["tokens"] = [t for t in tokens if t not in drop] or tokens
    return q


def answer(index, text, k=sn.K, tier=sen.TIER):
    """Ranked accessions for one need, as spark_submit.answer but with this parse."""
    return [r["accession"] for r in sen.rank(index, parse_need(text), k=k, tier=tier)]


# ---------------------------------------------------------------- measuring

def compare(per_need, variants):
    """Means over the variants, their spread, and how often each variant keeps v0's top 3."""
    import wording_check as wc
    s = wc.summarize(per_need)
    means = [s[v]["ndcg@10"] for v in variants]
    return {"variants": s, "mean_over_variants": round(sum(means) / len(means), 4),
            "spread": round(max(means) - min(means), 4),
            "top3_same_as_v0": {v: sum(1 for n in per_need if n["top3"][v] == n["top3"][variants[0]])
                                for v in variants}}


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--studies", required=True)
    ap.add_argument("--variables")
    ap.add_argument("--values")
    ap.add_argument("--devset", required=True)
    ap.add_argument("--needs", nargs="*", default=[])
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    import spark_submit as ss
    import wording_check as wc

    with open(args.devset, encoding="utf-8") as f:
        dev = json.load(f)
    rows, unparsed = wc.variants(dev["queries"])
    start = time.perf_counter()
    index = cf.Index(sn.load(args.studies, args.variables, args.values))
    report = {"wording_fix": __version__, "wording_check": wc.__version__, "sentence_need": sen.__version__,
              "tier": sen.TIER, "questions": len(dev["queries"]), "unparsed": unparsed,
              "load_seconds": round(time.perf_counter() - start, 2), "systems": {}}
    systems = (("base", ss.answer, sen.parse_need), ("fix", answer, parse_need))
    per = {}
    for name, ans, parse in systems:
        lengths = []

        def counted(index, text, ans=ans, lengths=lengths):
            ranked = ans(index, text)
            lengths.append(len(ranked))
            return ranked

        start = time.perf_counter()
        per[name] = wc.measure(index, rows, dev["qrels"], counted, parse)
        report["systems"][name] = compare(per[name], wc.VARIANTS)
        report["systems"][name]["short_lists"] = sum(1 for n in lengths if n < sn.K)
        report["systems"][name]["seconds"] = round(time.perf_counter() - start, 1)
    changed = dict.fromkeys(wc.VARIANTS, 0)
    for row in rows:
        if set(sen.parse_need(row["info_need"])["tokens"]) != set(parse_need(row["info_need"])["tokens"]):
            changed[row["variant"]] += 1
    report["tokens_changed_by_fix"] = changed
    report["official"] = []
    for path in args.needs:
        for need_id, text in sn.read_needs(path):
            item = {"id": need_id}
            for name, ans, _ in systems:
                item[name] = sen.position(ans(index, text), sen.EXAMPLE_STUDY)
            report["official"].append(item)
    report["per_need"] = [{"id": n["id"], "constraints": n["constraints"],
                           "ndcg": {name: per[name][i]["ndcg"] for name in per},
                           "topic_fix": per["fix"][i]["topic_diff"]}
                          for i, n in enumerate(per["base"])]
    report["note"] = "Silver labels are circular; this measures wording sensitivity, not the official score."
    os.makedirs(args.out, exist_ok=True)
    with open(os.path.join(args.out, "wording_fix_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    for name, _, _ in systems:
        s = report["systems"][name]
        print("%s: mean over variants %s, spread %s, short lists %d, %ss" % (
            name, s["mean_over_variants"], s["spread"], s["short_lists"], s["seconds"]))
        for v in wc.VARIANTS:
            x = s["variants"][v]
            print("  %s ndcg@10 %s lower %d higher %d parse_differs %d topic_differs %d top3_same %d %ss/need" % (
                v, x["ndcg@10"], x["lower_than_v0"], x["higher_than_v0"], x["parse_differs"], x["topic_differs"],
                s["top3_same_as_v0"][v], x["mean_seconds"]))
    print("tokens changed by fix: %s" % json.dumps(changed, sort_keys=True))
    for item in report["official"]:
        print("%s example rank base=%s fix=%s" % (item["id"], item["base"], item["fix"]))
    return 0


if __name__ == "__main__":
    sys.exit(main())
