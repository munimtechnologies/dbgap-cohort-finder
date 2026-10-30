#!/usr/bin/env python3
"""sentence_need: read SPARK dbGaP Task 2 needs written as full sentences.

The Task 2 description writes its example need as one sentence: "Find dbGaP
studies involving adult participants with lung adenocarcinoma as the primary
disease, where participant-level data include a history of smoking or smoking
exposure and whole genomic sequences." snapshot.parse_need 0.2.1 was built for
short needs. Read against its code, it gets three things wrong here: "whole
genomic sequences" is not read as whole genome sequencing, "a history of smoking
or smoking exposure" is not read as a variable need, and the disease topic takes
in "involving", "smoking", "exposure" and "genomic", so no study's primary
disease matches it.

parse_need() starts from snapshot.parse_need and, only where the sentence says
so, takes the topic from "X as the primary disease", reads "data include ..."
lists as variable needs (an item's "or" alternatives count as one need, met by
the best of them), and reads "whole genomic sequences" as WGS. Since 0.2.0 the
same sentences also keep their template words ("involving", "as the primary
disease", "participant-level") out of the text-scoring tokens. Needs without
those cues parse as before. rank() is snapshot.rank with those needs scored,
optionally with tier_bench's primary-disease tiering. main() compares the old
and new parsers on a silver dev set and on files of needs. CPU only, standard
library only.

Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
"""

import argparse
import json
import re
import sys

import cohort_finder as cf
import snapshot as sn

__version__ = "0.2.0"

EXAMPLE_STUDY = "phs001954.v2.p1"  # the expected answer in the Task 2 description
TIER = 0.6  # tier_bench 0.1.0's pre-registered threshold: below it the disease is only mentioned

DISEASE_NOUN = r"(?:disease|diagnosis|condition|disorder)"
# "with lung adenocarcinoma as the primary disease" (the phrase never crosses another "with")
PRIMARY_AS_RE = re.compile(
    r"\bwith\s+((?:(?!\bwith\b)[^,;.])+?)\s+as\s+(?:the|their|its)\s+(?:primary|main)\s+%s\b" % DISEASE_NOUN,
    re.I)
# "whose primary disease is asthma", "a primary diagnosis of sickle cell disease and ..."
PRIMARY_IS_RE = re.compile(
    r"\b(?:primary|main)\s+%s\s+(?:is|of)\s+((?:(?!\b(?:and|where|with|whose|in)\b)[^,;.])+)" % DISEASE_NOUN,
    re.I)
# "participant-level data include a history of smoking or smoking exposure and whole genomic sequences"
DATA_LIST_RE = re.compile(
    r"\b(?:data|information|records|measurements|variables)\s+(?:that\s+)?(?:include|includes|including"
    r"|covering|such as)\s+(.+?)(?=[.;]|$)", re.I)
ITEM_SPLIT_RE = re.compile(r"\s*,\s*(?:and\s+|or\s+)?|\s+and\s+", re.I)
ALT_SPLIT_RE = re.compile(r"\s+or\s+", re.I)
LEAD_RE = re.compile(
    r"^(?:(?:a|an|the|any|some)\s+)?(?:(?:history|histories|measures?|measurements?|levels?|status|information"
    r"|data|records?)\s+(?:of|on|about)\s+)?", re.I)
TRAIL_RE = re.compile(
    r"\s+(?:variables?|measurements?|measured|measures|data|information|records|assessments?|levels?|scores?"
    r"|status|history)$", re.I)
# Sentence spellings the short-need rules miss.
SENTENCE_DATA_TYPE_RULES = [(r"whole[- ]genom\w*\s+sequenc", "wgs"), (r"\bexomic\b", "wes")]
# Words of a sentence-style need that never name a disease.
FILLER = {"involving", "involve", "involved", "enrolled", "enrolling", "recruited", "whose", "having",
          "focused", "focusing"}
# Template words of a sentence-style need, left out of its text-scoring tokens. "primary" and "disease"
# go only where they frame the topic: "coronary artery disease as the primary disease" keeps the first.
SCAFFOLD_RES = [
    re.compile(r"\bas\s+(?:the|their|its)\s+(?:primary|main)\s+%s\b" % DISEASE_NOUN, re.I),
    re.compile(r"\b(?:primary|main)\s+%s\s+(?:is|of)\b" % DISEASE_NOUN, re.I),
    re.compile(r"\bparticipant[- ]level\b", re.I),
    re.compile(r"\b(?:%s)\b" % "|".join(sorted(FILLER)), re.I)]


# ---------------------------------------------------------------- parsing

def primary_disease(text):
    """The disease phrase of 'with X as the primary disease' or 'primary disease is X', or None."""
    for regex in (PRIMARY_AS_RE, PRIMARY_IS_RE):
        m = regex.search(text or "")
        if m and m.group(1).strip():
            return m.group(1).strip()
    return None


def data_items(text):
    """Items of every 'data include ...' list, each a list of its 'or' alternatives, as written."""
    out = []
    for m in DATA_LIST_RE.finditer(text or ""):
        for item in ITEM_SPLIT_RE.split(m.group(1)):
            alts = [a.strip() for a in ALT_SPLIT_RE.split(item) if a.strip()]
            if alts:
                out.append(alts)
    return out


def search_text(text):
    """The need without its sentence template words, for text scoring."""
    for regex in SCAFFOLD_RES:
        text = regex.sub(" ", text or "")
    return text


def type_tags(phrase):
    return cf._tags(phrase, cf.DATA_TYPE_RULES) | cf._tags(phrase, SENTENCE_DATA_TYPE_RULES)


def var_words(phrase):
    """'a history of smoking' -> ['smoking']; 'HbA1c measurements' -> ['hba1c']."""
    core = TRAIL_RE.sub("", LEAD_RE.sub("", phrase.strip()))
    return [t for t in cf.tokens(core) if t not in sn.GENERIC_VAR]


def sentence_var_needs(text):
    """(data types named in 'data include' lists, [[word list per alternative] per variable need])."""
    types, needs = set(), []
    for alts in data_items(text):
        typed = [a for a in alts if type_tags(a)]
        if typed:
            for a in typed:
                types |= type_tags(a)
            continue
        if any(cf._tags(a, cf.CONSENT_RULES) or cf._tags(a, cf.QUERY_DESIGN_RULES) for a in alts):
            continue
        words = []
        for a in alts:
            w = var_words(a)
            if w and w not in words:
                words.append(w)
        if words and words not in needs:
            needs.append(words)
    return types, needs


def parse_need(text, strip=True):
    """strip: leave template words out of the text-scoring tokens of sentence-style needs (0.2.0)."""
    q = sn.parse_need(text)
    types, needs = sentence_var_needs(text)
    q["data_types"] = set(q["data_types"]) | cf._tags(text, SENTENCE_DATA_TYPE_RULES) | types
    q["var_alts"] = []
    for alts in needs:
        if len(alts) == 1:
            if alts[0] not in q["var_terms"]:
                q["var_terms"].append(alts[0])
        elif not any(a in q["var_terms"] for a in alts):
            q["var_alts"].append(alts)
    phrase = primary_disease(text)
    topic = sn.topic_tokens(phrase, cf.parse_query(phrase)) if phrase else []
    if not topic:
        listed = set()
        for alts in data_items(text):
            for a in alts:
                listed.update(cf.tokens(a))
        topic = [t for t in q["topic"] if t not in FILLER and t not in listed] or q["topic"]
    q["topic"] = topic
    q["primary_phrase"] = phrase
    if strip and (phrase or data_items(text)):
        q["tokens"] = cf.parse_query(search_text(text))["tokens"]
    return q


def summary(q):
    """The parsed fields that steer ranking, JSON-ready."""
    return {"topic": q.get("topic"), "var_terms": q.get("var_terms"), "var_alts": q.get("var_alts") or [],
            "data_types": sorted(q.get("data_types") or []), "age": list(q["age"]) if q.get("age") else None,
            "groups": q.get("groups")}


# ---------------------------------------------------------------- ranking

def alt_requirement(alts, var_doc, has_dictionary):
    """The best of the 'or' alternatives of one variable need."""
    return max((sn.var_requirement(words, var_doc, has_dictionary) for words in alts), key=lambda r: r[0])


_base_requirements = getattr(sn.requirements, "base", sn.requirements)


def requirements(index, i, query, disease=True):
    """snapshot.requirements plus one requirement per 'or' variable need (none for older parses)."""
    out = _base_requirements(index, i, query, disease)
    has_dictionary = bool(index.studies[i].get("dictionary"))
    for alts in query.get("var_alts") or []:
        out.append(alt_requirement(alts, index.var_docs[i], has_dictionary))
    return out


requirements.base = _base_requirements
sn.requirements = requirements  # snapshot.rank looks it up when called


def by_accession(index):
    lookup = getattr(index, "_by_acc", None)
    if lookup is None:
        lookup = index._by_acc = {s["accession"]: s for s in index.studies}
    return lookup


def rank(index, query, k=sn.K, tier=None):
    """snapshot.rank (conjunctive, dictionary scored only for needs that name variables).

    tier: also sort studies whose disease fit is below it after the rest, as tier_bench 0.1.0 does."""
    gate = not (query.get("var_alts") and not query.get("var_terms"))
    results = sn.rank(index, query, len(index.studies) if tier else k, True, True, gate)
    if tier:
        topic = query.get("topic")
        lookup = by_accession(index)
        for r in results:
            r["weak_disease"] = int(bool(topic) and sn.disease_requirement(lookup[r["accession"]], topic)[0] < tier)
        results.sort(key=lambda r: (r["fails"], r["weak_disease"], -r["score"], r["accession"]))
    return results[:k]


# ---------------------------------------------------------------- comparison

SYSTEMS = (("old_gated", sn.parse_need, None), ("new_gated", parse_need, None),
           ("old_tier06", sn.parse_need, TIER), ("new_tier06", parse_need, TIER))
PARSERS = {"old": sn.parse_need, "new": parse_need}  # looked up when called, so a later module can swap them


def position(ranked, accession):
    """1-based rank of accession, or None if it is not returned."""
    return ranked.index(accession) + 1 if accession in ranked else None


def overlap(a, b, k=10):
    """Share of the top k that two rankings have in common."""
    a, b = a[:k], b[:k]
    return round(len(set(a) & set(b)) / float(max(len(a), len(b)) or 1), 4)


def token_set(q):
    return sorted(set(q.get("tokens") or []))


def bench(index, queries, qrels, k=10):
    out = {}
    for name, parse, tier in SYSTEMS:
        scores = {}
        for q in queries:
            ranked = [r["accession"] for r in rank(index, parse(q["query"]), tier=tier)]
            scores[q["id"]] = cf.ndcg(ranked, qrels.get(q["id"], {}), k)
        out[name] = {"ndcg@%d" % k: round(sum(scores.values()) / len(scores), 4) if scores else 0.0,
                     "per_query": scores}
    for name in ("new_gated", "new_tier06"):
        base = out[name.replace("new", "old")]["per_query"]
        per = out[name]["per_query"]
        out[name]["vs_old"] = {"higher": sorted(q for q in per if per[q] > base[q] + 1e-9),
                               "lower": sorted(q for q in per if per[q] < base[q] - 1e-9),
                               "same": sum(1 for q in per if abs(per[q] - base[q]) <= 1e-9)}
    old, new = PARSERS["old"], PARSERS["new"]
    out["parse_changed"] = sorted(q["id"] for q in queries
                                  if summary(old(q["query"])) != summary(new(q["query"])))
    out["tokens_changed"] = sorted(q["id"] for q in queries
                                   if token_set(old(q["query"])) != token_set(new(q["query"])))
    out["questions"] = len(queries)
    return out


def compare_needs(index, needs, k=10):
    """Both parses, the top k under each system, and where the example answer lands."""
    out = []
    for need_id, text in needs:
        parses = {p: parse(text) for p, parse in PARSERS.items()}
        item = {"id": need_id, "need": text, "parse": {p: summary(q) for p, q in parses.items()},
                "parse_changed": summary(parses["old"]) != summary(parses["new"]),
                "tokens": {p: token_set(q) for p, q in parses.items()},
                "example_rank": {}, "top": {}}
        item["tokens_changed"] = item["tokens"]["old"] != item["tokens"]["new"]
        for name, _, tier in SYSTEMS:
            results = rank(index, parses[name.split("_")[0]], tier=tier)
            ranked = [r["accession"] for r in results]
            item["example_rank"][name] = position(ranked, EXAMPLE_STUDY)
            item["top"][name] = ranked[:k]
            if not tier:
                item["top3_why_" + name] = [{"accession": r["accession"], "fails": r["fails"], "why": r["why"]}
                                            for r in results[:3]]
        out.append(item)
    return out


def read_pairs(paths):
    """(short id, sentence id) for every need with a 'pair' field."""
    out = []
    for path in paths:
        with open(path, encoding="utf-8") as f:
            for line in f:
                if line.strip():
                    item = json.loads(line)
                    if item.get("pair"):
                        out.append((str(item["pair"]), str(item["info_need_id"])))
    return out


def pair_overlaps(items, pairs, k=10):
    """Top-k overlap between each short need and its sentence rewrite, per system, and the means."""
    by_id = {n["id"]: n for n in items}
    key = "overlap@%d" % k
    out = []
    for short, sentence in pairs:
        if short in by_id and sentence in by_id:
            out.append({"short": short, "sentence": sentence,
                        key: {name: overlap(by_id[short]["top"][name], by_id[sentence]["top"][name], k)
                              for name, _, _ in SYSTEMS},
                        "same_tokens": {p: by_id[short]["tokens"][p] == by_id[sentence]["tokens"][p]
                                        for p in PARSERS}})
    mean = {name: round(sum(p[key][name] for p in out) / len(out), 4) if out else None for name, _, _ in SYSTEMS}
    return out, mean


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--studies", required=True)
    ap.add_argument("--variables")
    ap.add_argument("--values")
    ap.add_argument("--devset", required=True)
    ap.add_argument("--needs", nargs="*", default=[])
    ap.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    index = cf.Index(sn.load(args.studies, args.variables, args.values))
    with open(args.devset, encoding="utf-8") as f:
        dev = json.load(f)
    report = {"version": __version__, "tier": TIER, "silver": bench(index, dev["queries"], dev["qrels"]),
              "needs": []}
    for path in args.needs:
        report["needs"].extend(compare_needs(index, sn.read_needs(path)))
    report["pairs"], report["pair_mean"] = pair_overlaps(report["needs"], read_pairs(args.needs))
    with open(args.out, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    silver = report["silver"]
    for name, _, _ in SYSTEMS:
        line = "%s ndcg@10 %s" % (name, silver[name]["ndcg@10"])
        if "vs_old" in silver[name]:
            v = silver[name]["vs_old"]
            line += " (higher %d, lower %d, same %d)" % (len(v["higher"]), len(v["lower"]), v["same"])
        print(line)
    print("silver parse changed: %d of %d; tokens changed: %d" % (
        len(silver["parse_changed"]), silver["questions"], len(silver["tokens_changed"])))
    for n in report["needs"]:
        print("%s: parse changed %s; tokens changed %s; example rank %s" % (
            n["id"], n["parse_changed"], n["tokens_changed"],
            " ".join("%s=%s" % kv for kv in sorted(n["example_rank"].items()))))
    for p in report["pairs"]:
        print("pair %s/%s overlap@10 %s" % (p["short"], p["sentence"], json.dumps(p["overlap@10"], sort_keys=True)))
    print("pair mean overlap@10: %s" % json.dumps(report["pair_mean"], sort_keys=True))
    return 0


if __name__ == "__main__":
    sys.exit(main())
