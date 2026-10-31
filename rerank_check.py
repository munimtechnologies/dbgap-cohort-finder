#!/usr/bin/env python3
"""rerank_check: does a local open-weight cross-encoder improve MV2's SPARK Task 2 ranking?

SPARK dbGaP Task 2 allows only open-weight models with no network at run time.
The current system (sentence_need's parse and rank, primary-disease tiering at 0.6)
is rules plus BM25. This file re-scores each need's top N studies with NCBI's
MedCPT cross-encoder (public domain, trained on PubMed search logs) and fuses the
two scores:

    fused = (1 - w) * minmax(rule score) + w * minmax(cross-encoder score)

Only the top N positions move, and only within the same (fails, weak_disease)
group, so a study that fails a stated need never jumps above one that meets it.
w = 0 must reproduce the current order exactly (a sanity gate). It reports
NDCG@10 against the silver labels of `snapshot.py devset` for each w, the rank of
the expected answer on the task's two official example wordings, and the time
and memory the cross-encoder adds. Silver labels are circular (built from the
metadata the rules read), so a gain here is a hint, not an official-score estimate.
Pre-registered in 20261031T053043Z-civic-tech/findings/prereg-rerank-check.md.

    python rerank_check.py --studies out/studies.jsonl --variables data/variables.jsonl.gz \
        --values data/var_values.jsonl.gz --devset devset.json --needs official_needs.jsonl --out /out

Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
"""

import argparse
import json
import os
import sys
import time

__version__ = "0.1.0"

MODEL = "ncbi/MedCPT-Cross-Encoder"
WEIGHTS = (0.0, 0.25, 0.5, 1.0)
TOP_N = 30
MAX_LENGTH = 384
BATCH = 8
DESC_CHARS = 1500


def passage(study):
    """'title. Conditions: a, b. description' (MedCPT reads 'title. abstract')."""
    parts = [(study.get("title") or "").strip().rstrip(".")]
    conditions = [c for c in (study.get("conditions") or []) if c][:10]
    if conditions:
        parts.append("Conditions: " + ", ".join(conditions))
    desc = (study.get("description") or "").strip()
    if desc:
        parts.append(desc[:DESC_CHARS])
    return ". ".join(p for p in parts if p)


def minmax(values):
    lo, hi = min(values), max(values)
    if hi - lo <= 1e-12:
        return [0.0 for _ in values]
    return [(v - lo) / (hi - lo) for v in values]


def fuse(results, ce_scores, w, n=TOP_N):
    """Accessions in fused order: the first n results re-sorted, the rest unchanged.

    results: ranked dicts with accession, score, fails and (optionally) weak_disease;
    ce_scores: one cross-encoder score per result in results[:n]."""
    head, tail = results[:n], results[n:]
    if not head:
        return [r["accession"] for r in tail]
    rule = minmax([r["score"] for r in head])
    ce = minmax(list(ce_scores[:len(head)]))
    keyed = []
    for r, a, b in zip(head, rule, ce):
        fused = (1 - w) * a + w * b
        # Ties on the fused score keep the rule order.
        key = (r.get("fails", 0), r.get("weak_disease", 0), -round(fused, 9), -a, r["accession"])
        keyed.append((key, r["accession"]))
    keyed.sort()
    return [acc for _, acc in keyed] + [r["accession"] for r in tail]


def position(ranked, accession):
    return ranked.index(accession) + 1 if accession in ranked else None


class CrossEncoder:
    """MedCPT cross-encoder on CPU (torch and transformers are imported only here)."""

    def __init__(self, name=MODEL, threads=2):
        import torch
        from transformers import AutoModelForSequenceClassification, AutoTokenizer
        torch.set_num_threads(threads)
        self.torch = torch
        self.tokenizer = AutoTokenizer.from_pretrained(name)
        self.model = AutoModelForSequenceClassification.from_pretrained(name)
        self.model.eval()

    def score(self, query, passages):
        out = []
        with self.torch.no_grad():
            for i in range(0, len(passages), BATCH):
                pairs = [[query, p] for p in passages[i:i + BATCH]]
                enc = self.tokenizer(pairs, truncation=True, padding=True, return_tensors="pt", max_length=MAX_LENGTH)
                out.extend(float(x) for x in self.model(**enc).logits.squeeze(dim=1).reshape(-1))
        return out


def peak_memory_mb():
    try:
        import resource
    except ImportError:
        return None
    return round(resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024.0, 1)


def measure(index, needs, qrels, encoder, rank, parse, lookup, example=None, k=10):
    """Per-need rows: ndcg@k per w (when labelled), example rank per w, top 3 per w, seconds."""
    import cohort_finder as cf
    rows = []
    for need_id, text in needs:
        start = time.perf_counter()
        results = rank(index, parse(text))
        rule_seconds = time.perf_counter() - start
        head = results[:TOP_N]
        start = time.perf_counter()
        ce = encoder.score(text, [passage(lookup[r["accession"]]) for r in head]) if head else []
        ce_seconds = time.perf_counter() - start
        row = {"id": need_id, "candidates": len(head), "rule_seconds": round(rule_seconds, 3),
               "ce_seconds": round(ce_seconds, 3), "ndcg": {}, "example_rank": {}, "top3": {}}
        base = [r["accession"] for r in results]
        for w in WEIGHTS:
            ranked = fuse(results, ce, w)
            key = str(w)
            if w == 0.0:
                row["w0_same_as_rule"] = ranked == base
            if need_id in qrels:
                row["ndcg"][key] = round(cf.ndcg(ranked, qrels[need_id], k), 4)
            if example:
                row["example_rank"][key] = position(ranked, example)
            row["top3"][key] = ranked[:3]
        rows.append(row)
    return rows


def summarize(rows, k=10):
    labelled = [r for r in rows if r["ndcg"]]
    out = {"needs": len(rows), "labelled": len(labelled),
           "w0_differs": sum(1 for r in rows if not r.get("w0_same_as_rule")),
           "mean_ce_seconds": round(sum(r["ce_seconds"] for r in rows) / len(rows), 3) if rows else None,
           "max_ce_seconds": round(max(r["ce_seconds"] for r in rows), 3) if rows else None,
           "mean_rule_seconds": round(sum(r["rule_seconds"] for r in rows) / len(rows), 3) if rows else None,
           "weights": {}}
    for w in WEIGHTS:
        key = str(w)
        scores = [r["ndcg"][key] for r in labelled]
        base = [r["ndcg"]["0.0"] for r in labelled]
        out["weights"][key] = {
            "ndcg@%d" % k: round(sum(scores) / len(scores), 4) if scores else None,
            "higher_than_w0": sum(1 for s, b in zip(scores, base) if s > b + 1e-9),
            "lower_than_w0": sum(1 for s, b in zip(scores, base) if s < b - 1e-9)}
    return out


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--studies", required=True)
    ap.add_argument("--variables")
    ap.add_argument("--values")
    ap.add_argument("--devset", required=True)
    ap.add_argument("--needs", required=True, help="official_needs.jsonl (example-rank needs)")
    ap.add_argument("--out", required=True)
    ap.add_argument("--model", default=MODEL)
    args = ap.parse_args(argv)

    import cohort_finder as cf
    import sentence_need as sen
    import snapshot as sn

    with open(args.devset, encoding="utf-8") as f:
        dev = json.load(f)
    silver = [(q["id"], q["query"]) for q in dev["queries"]]
    official = sn.read_needs(args.needs)
    os.makedirs(args.out, exist_ok=True)

    start = time.perf_counter()
    index = cf.Index(sn.load(args.studies, args.variables, args.values))
    load_seconds = round(time.perf_counter() - start, 2)
    mem_after_index = peak_memory_mb()
    start = time.perf_counter()
    encoder = CrossEncoder(args.model)
    model_seconds = round(time.perf_counter() - start, 2)
    lookup = sen.by_accession(index)

    def rank(idx, query):
        return sen.rank(idx, query, k=sn.K, tier=sen.TIER)

    silver_rows = measure(index, silver, dev["qrels"], encoder, rank, sen.parse_need, lookup)
    official_rows = measure(index, official, {}, encoder, rank, sen.parse_need, lookup, example=sen.EXAMPLE_STUDY)
    report = {"rerank_check": __version__, "sentence_need": sen.__version__, "tier": sen.TIER, "model": args.model,
              "top_n": TOP_N, "max_length": MAX_LENGTH, "weights": list(WEIGHTS), "load_seconds": load_seconds,
              "model_load_seconds": model_seconds, "peak_memory_mb_after_index": mem_after_index,
              "peak_memory_mb": peak_memory_mb(), "silver": summarize(silver_rows),
              "official": [{"id": r["id"], "example_rank": r["example_rank"], "w0_same_as_rule": r["w0_same_as_rule"],
                            "ce_seconds": r["ce_seconds"]} for r in official_rows],
              "per_need": silver_rows,
              "note": "Silver labels are circular; this is a hint about re-ranking, not the official score."}
    with open(os.path.join(args.out, "rerank_report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    s = report["silver"]
    print("%d silver needs, %d labelled, w0 differs on %d; ce %ss/need mean, %ss max; rule %ss/need"
          % (s["needs"], s["labelled"], s["w0_differs"], s["mean_ce_seconds"], s["max_ce_seconds"],
             s["mean_rule_seconds"]))
    for w, v in s["weights"].items():
        print("w=%s ndcg@10 %s higher %d lower %d" % (w, v["ndcg@10"], v["higher_than_w0"], v["lower_than_w0"]))
    for r in report["official"]:
        print("%s example rank %s w0_same %s" % (r["id"], json.dumps(r["example_rank"], sort_keys=True),
                                                 r["w0_same_as_rule"]))
    print("load %ss, model %ss, peak %s MB (after index %s MB)"
          % (load_seconds, model_seconds, report["peak_memory_mb"], mem_after_index))
    return 0


if __name__ == "__main__":
    sys.exit(main())
