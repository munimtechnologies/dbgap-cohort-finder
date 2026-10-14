#!/usr/bin/env python3
"""snapshot: rank studies of the official NLM SPARK dbGaP snapshot for cohort-feasibility needs.

SPARK dbGaP Task 2 judges systems only on a fixed public snapshot
(https://ftp.ncbi.nlm.nih.gov/dbgap/NLM_Challenge/dbgap.tar.gz), and a study
counts as relevant only if it meets every stated need ("adults + lung
adenocarcinoma + smoking variables + WGS"). This module reads the files that
snapshot_survey.py writes from that archive (studies.jsonl, variables.jsonl.gz,
var_values.jsonl.gz), reuses cohort_finder's question parser and BM25 index,
and adds what the snapshot makes possible:

- participant age from the aggregate variable summaries ("adults", "children",
  "aged 40-60", "65 and older");
- reported race/ethnicity counts from coded race and ethnicity variables;
- "with X variables/measurements" needs checked against the data dictionary;
- conjunctive ranking: a study that clearly fails a need ranks below every
  study that does not, whatever its text score.

It writes submissions in the SPARK Task 2 JSONL format. CPU only, standard
library only, no network at run time.

Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
"""

import argparse
import gzip
import json
import math
import random
import re
import sys
from collections import Counter, defaultdict

import cohort_finder as cf

__version__ = "0.1.0"

STUDY_URL = "https://www.ncbi.nlm.nih.gov/projects/gap/cgi-bin/study.cgi?study_id="
EMPTY = {"", "not applicable", "not provided", "none", "null", "n/a"}
K = 100  # studies returned per need

# Ranking: text relevance (study fields, then data dictionary) scaled by how
# well the constraints are met; hard failures sort last.
W_TEXT = 0.6
W_VARS = 0.3
FLOOR = 0.3      # share of the score kept when every constraint is unmet but none clearly fails
PARTIAL_AGE = 0.7

GROUP_LABELS = {"white": "White/European", "black": "Black/African American", "hispanic": "Hispanic/Latino",
                "asian": "Asian", "aian": "American Indian/Alaska Native", "nhpi": "Native Hawaiian/Pacific Islander"}
PEOPLE = r"(?:adults|participants|subjects|individuals|people|women|men|patients|americans|children|youth|cases)"
QUERY_GROUP_RULES = [
    (r"african[- ]american|\bblacks?\b(?= " + PEOPLE + r")|\bafrican\b|\bblacks\b", "black"),
    (r"\beuropean|caucasian|\bwhites?\b(?= " + PEOPLE + r")|\bwhites\b", "white"),
    (r"hispanic|latin[oax]\b|latin american|mexican|puerto ric", "hispanic"),
    (r"\basians?\b|chinese|japanese|korean|south asian|filipino", "asian"),
    (r"american indian|alaska native|native american|indigenous", "aian"),
    (r"pacific islander|native hawaiian", "nhpi"),
]
# Text evidence in a study's own title, description or population labels.
TEXT_GROUP_RULES = dict((g, re.compile(p, re.I)) for g, p in [
    ("black", r"african[- ]american|\bblack\b|\bafrican\b"),
    ("white", r"\beuropean|caucasian|\bwhite\b"),
    ("hispanic", r"hispanic|latin[oax]|mexican|puerto ric"),
    ("asian", r"\basian|chinese|japanese|korean|filipino"),
    ("aian", r"american indian|alaska native|native american"),
    ("nhpi", r"pacific islander|native hawaiian"),
])

CHILD_WORDS = r"children|child|pediatric|paediatric|kids|infants?|newborns?|neonat\w*|adolescents?|teens?|teenagers?|youth|minors"
CHILD_RE = re.compile(r"\b(?:%s)\b" % CHILD_WORDS, re.I)
ADULT_TEXT_RE = re.compile(r"\badults?\b|\baged? (?:1[89]|[2-9]\d)\b|\bolder\b|\belderly\b|\bmen\b|\bwomen\b", re.I)
OLDER_RE = re.compile(r"older adults|elderly|seniors|geriatric", re.I)
AGE_RANGE_RE = re.compile(r"\b(?:aged?|ages)\s*(\d{1,3})\s*(?:-|–|to|and)\s*(\d{1,3})\b", re.I)
AGE_MIN_RE = re.compile(  # (?<![\d,.]): "1,000+ adults" is a size, not "000+"
    r"\b(?:aged?\s*)?(?<![\d,.])(\d{1,3})\s*(?:\+|years?(?: of age)? (?:and|or) (?:older|over|above)|and (?:older|over|above)"
    r"|or (?:older|over|above))|\b(?:over|older than|at least|above)\s*(?:age\s*)?(\d{1,3})\s*(?:years|yrs|y/o)", re.I)
AGE_MAX_RE = re.compile(r"\b(?:under|younger than|below|less than)\s*(?:age\s*)?(\d{1,3})\s*(?:years|yrs|y/o)?", re.I)
ADULT_RE = re.compile(r"\badults?\b", re.I)
MAX_AGE = 110  # larger numbers in an age phrase are cohort sizes ("500+ participants")
NOT_AN_AGE = re.compile(r"\s*(?:%|percent|participants|subjects|individuals|people|patients|samples|cases|controls)",
                        re.I)

VAR_PHRASE_RE = re.compile(
    r"(?:\bwith|\bhaving|\bhas|\bhave|\bincluding|\bincludes?|,|\band)\s+((?:[a-z0-9-]+\s+){0,2}?[a-z0-9-]+)\s+"
    r"(?:variables?|measurements?|measured|measures|data|information|records|assessments?|levels?|scores?"
    r"|status|history)\b", re.I)
GENERIC_VAR = {"genetic", "genomic", "phenotype", "phenotypic", "clinical", "demographic", "sequencing",
               "genotype", "genotyping", "molecular", "omic", "omics", "individual", "level", "imaging",
               "available", "outcome", "health", "medical", "family"}


def is_empty(value):
    if value is None:
        return True
    if isinstance(value, list):
        return all(is_empty(v) for v in value)
    return str(value).strip().lower() in EMPTY


def as_list(value):
    if is_empty(value):
        return []
    if isinstance(value, list):
        return [str(v).strip() for v in value if not is_empty(v)]
    return [s.strip() for s in str(value).split(" | ") if s.strip()]


def as_int(value):
    for v in as_list(value):
        v = v.replace(",", "")
        if v.isdigit():
            return int(v)
    return None


def phv_key(var_id):
    m = re.match(r"(phv\d+)", var_id or "")
    return m.group(1) if m else None


def spaced(name):
    """'Seq_DNA_WholeGenome' -> 'Seq DNA Whole Genome', so dbGaP sample-use codes match the data type rules."""
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", name or "").replace("_", " ")


# ----------------------------------------------------------------- loading

def normalize(rec, dictionary=None):
    """A studies.jsonl record from snapshot_survey -> the study dict cohort_finder ranks."""
    acc = rec["accession"]
    focus = as_list(rec.get("main_disease"))
    conditions = cf._unique(focus + as_list(rec.get("disease_mesh_name")) + as_list(rec.get("study_disease_mesh_name")))
    uses = [spaced(u) for u in as_list(rec.get("sample_use"))]
    platforms = as_list(rec.get("genotype_platform"))
    types = cf.data_type_tags(uses)
    if platforms:
        types.add("genotypes")  # platform names ("HumanExome-12") are arrays, never sequencing
    male, female = rec.get("max_dataset_male"), rec.get("max_dataset_female")
    race = dict(rec.get("race_counts") or {})
    eth = rec.get("ethnicity_counts") or {}
    if "hispanic" not in race and eth.get("hispanic"):
        race["hispanic"] = eth["hispanic"]
    age = None
    if rec.get("age_min") is not None and rec.get("age_max") is not None:
        age = (float(rec["age_min"]), float(rec["age_max"]))
    return {
        "accession": acc,
        "version": acc,
        "title": cf.clean_text(rec.get("name")),
        "description": cf.clean_text(rec.get("description")),
        "conditions": conditions,
        "focus": focus,
        "design": as_list(rec.get("study_design")) + as_list(rec.get("study_type")),
        "data_types_raw": uses + platforms,
        "data_types": sorted(types),
        "subjects": as_int(rec.get("study_subject_count")),
        "consents": as_list(rec.get("consent_abbrev")),
        "sex": {"male": male or 0, "female": female or 0} if (male or female) else None,
        "ancestry": {},
        "populations": as_list(rec.get("all_population")),
        "race_counts": race,
        "has_hispanic_count": "hispanic" in race or bool(eth),
        "age": age,
        "dictionary": dictionary or [],
        "url": STUDY_URL + acc,
        "top_level": str(rec.get("study_structure_type", "")).lower() != "child",
    }


def _open(path):
    return gzip.open(path, "rt", encoding="utf-8") if path.endswith(".gz") else open(path, encoding="utf-8")


def read_dictionaries(variables_path=None, values_path=None):
    """{study: [[name, description + coded value labels], ...]} from the survey's variable files."""
    values = {}
    if values_path:
        with _open(values_path) as f:
            for line in f:
                row = json.loads(line)
                values[(row.get("study"), phv_key(row.get("phv")))] = " ".join(row.get("values") or [])
    out = defaultdict(list)
    if variables_path:
        with _open(variables_path) as f:
            for line in f:
                row = json.loads(line)
                extra = values.get((row.get("study"), phv_key(row.get("phv"))), "")
                out[row.get("study")].append([row.get("name") or "", ((row.get("desc") or "") + " " + extra).strip()])
    return out


def load(studies_path, variables_path=None, values_path=None):
    dictionaries = read_dictionaries(variables_path, values_path)
    with _open(studies_path) as f:
        recs = [json.loads(line) for line in f if line.strip()]
    return [normalize(r, dictionaries.get(r["accession"])) for r in recs]


# ---------------------------------------------------------------- questions

def _ages(regex, text):
    """Plausible ages matched by regex, in order (cohort sizes and percentages are skipped)."""
    out = []
    for m in regex.finditer(text):
        value = int(next(g for g in m.groups() if g))
        if value <= MAX_AGE and not NOT_AN_AGE.match(text, m.end()):
            out.append(value)
    return out


def query_age(text):
    """(min_age, max_age) asked for (max may be None), or None when the need says nothing about age."""
    low = text or ""
    for m in AGE_RANGE_RE.finditer(low):
        a, b = sorted((int(m.group(1)), int(m.group(2))))
        if b <= MAX_AGE:
            return (a, b)
    lo = hi = None
    found = _ages(AGE_MIN_RE, low)
    if found:
        lo = found[0]
    found = _ages(AGE_MAX_RE, low)
    if found:
        hi = found[0] - 1
    if lo is None and OLDER_RE.search(low):
        lo = 65
    if lo is None and hi is None:
        if CHILD_RE.search(low):
            hi = 17
        elif ADULT_RE.search(low):
            lo = 18
    if lo is None and hi is None:
        return None
    return (lo if lo is not None else 0, hi)


def query_groups(text):
    low = (text or "").lower()
    out = []
    for pattern, group in QUERY_GROUP_RULES:
        if re.search(pattern, low) and group not in out:
            out.append(group)
    return out


def query_var_terms(text):
    """Token lists for 'with X variables / X measured / X data' needs (data types are left to their own rule)."""
    out = []
    for m in VAR_PHRASE_RE.finditer(text or ""):
        phrase = m.group(1)
        if cf._tags(phrase, cf.DATA_TYPE_RULES):
            continue
        words = [t for t in cf.tokens(phrase) if t not in GENERIC_VAR]
        if words and words not in out:
            out.append(words)
    return out


def parse_need(text):
    q = cf.parse_query(text)
    q["ancestry"] = []  # replaced by reported race/ethnicity below
    q["age"] = query_age(text)
    if q["age"] and q.get("min_subjects") in q["age"]:
        q["min_subjects"] = None  # "aged 65 and older adults" names an age, not a cohort size
    q["groups"] = query_groups(text)
    q["var_terms"] = query_var_terms(text)
    return q


def age_label(want):
    lo, hi = want
    if hi is None:
        return "aged %d+" % lo
    if lo <= 0:
        return "under %d" % (hi + 1)
    return "aged %d-%d" % (lo, hi)


def age_requirement(study, want):
    lo_w, hi_w = want
    label = age_label(want)
    if study.get("age"):
        lo, hi = study["age"]
        shown = "participants aged %g-%g" % (lo, hi)
        # An upper bound of 17 means "under 18", so 17.5 still fits.
        if hi < lo_w or (hi_w is not None and lo >= hi_w + 1):
            return (0.0, "%s (wanted %s)" % (shown, label))
        if lo >= lo_w and (hi_w is None or hi < hi_w + 1):
            return (1.0, "%s (wanted %s)" % (shown, label))
        return (PARTIAL_AGE, "%s, partly %s" % (shown, label))
    text = "%s %s" % (study.get("title") or "", study.get("description") or "")
    kids, adults = bool(CHILD_RE.search(text)), bool(ADULT_TEXT_RE.search(text))
    if hi_w is not None and hi_w < 18:
        if kids:
            return (0.8, "description mentions children (wanted %s)" % label)
        return (cf.UNKNOWN, "participant ages not reported (wanted %s)" % label)
    if kids and not adults:
        return (0.2, "description suggests a pediatric study (wanted %s)" % label)
    return (cf.UNKNOWN, "participant ages not reported (wanted %s)" % label)


def group_requirement(study, group, need):
    label = GROUP_LABELS[group]
    counts = study.get("race_counts") or {}
    informative = counts and (group != "hispanic" or study.get("has_hispanic_count"))
    if informative:
        n = counts.get(group, 0)
        if n >= need:
            return (1.0, "%s %s participants by reported race/ethnicity" % (format(n, ","), label))
        if n > 0:
            return (0.5, "only %s %s participants by reported race/ethnicity" % (cf.fmt_count(n), label))
        return (0.0, "no %s participants by reported race/ethnicity" % label)
    regex = TEXT_GROUP_RULES[group]
    pops = [p for p in study.get("populations") or [] if regex.search(p)]
    if pops:
        return (1.0, "dbGaP lists population: %s" % ", ".join(pops))
    if regex.search("%s %s" % (study.get("title") or "", study.get("description") or "")):
        return (0.7, "description mentions %s participants" % label)
    return (cf.UNKNOWN, "race/ethnicity not reported (%s)" % label)


def var_requirement(words, var_doc, has_dictionary):
    hits = [w for w in words if w in var_doc]
    phrase = " ".join(words)
    if len(hits) == len(words):
        return (1.0, "data dictionary has %s" % phrase)
    if hits:
        return (0.5 * len(hits) / len(words), "data dictionary has only %s of '%s'" % (", ".join(hits), phrase))
    if not has_dictionary:
        return (cf.UNKNOWN, "no data dictionary in the snapshot (%s)" % phrase)
    return (0.0, "data dictionary has no %s variables" % phrase)


def requirements(index, i, query):
    study = index.studies[i]
    out = cf.requirements(study, query)
    if query.get("age"):
        out.append(age_requirement(study, query["age"]))
    need = query.get("min_subjects") or cf.ANCESTRY_MIN
    for group in query.get("groups") or []:
        out.append(group_requirement(study, group, need))
    for words in query.get("var_terms") or []:
        out.append(var_requirement(words, index.var_docs[i], bool(study.get("dictionary"))))
    return out


# ------------------------------------------------------------------ ranking

def rank(index, query, k=K, constraints=True):
    """Studies for a parsed need: clear failures last, then text relevance scaled by constraint fit."""
    n = len(index.studies)
    raw = [index.bm25(i, query["tokens"]) for i in range(n)]
    var_raw = [index.var_score(i, query["tokens"]) for i in range(n)]
    top = max(raw) if raw and max(raw) > 0 else 0.0
    var_top = max(var_raw) if var_raw and max(var_raw) > 0 else 0.0
    any_text = top > 0 or var_top > 0
    results = []
    for i, study in enumerate(index.studies):
        text = raw[i] / top if top else 0.0
        var = var_raw[i] / var_top if var_top else 0.0
        if any_text and text <= 0 and var <= 0:
            continue
        reqs = requirements(index, i, query) if constraints else []
        sats = [s for s, _ in reqs]
        fails = sum(1 for s in sats if s <= 0)
        fit = sum(sats) / len(sats) if sats else 1.0
        score = (W_TEXT * text + W_VARS * var + 0.05) * (FLOOR + (1 - FLOOR) * fit)
        score += math.log10((study.get("subjects") or 0) + 1) / 1000.0
        results.append({"accession": study["accession"], "title": study.get("title"),
                        "subjects": study.get("subjects"), "url": study.get("url"), "fails": fails,
                        "score": round(score, 6), "why": [w for _, w in reqs]})
    results.sort(key=lambda r: (r["fails"], -r["score"], r["accession"]))
    return results[:k]


def search(index, text, k=K):
    return rank(index, parse_need(text), k)


def submission_line(team_id, submission_id, need_id, need, results):
    """One line of the SPARK Task 2 submission format."""
    return json.dumps({"metadata": {"team_id": team_id, "submission_id": submission_id,
                                    "info_need_id": need_id, "info_need": need},
                       "results": [r["accession"] for r in results]}, ensure_ascii=False)


def read_needs(path):
    """JSON lines with an id ('info_need_id' or 'id') and text ('info_need', 'query' or 'text')."""
    out = []
    with _open(path) as f:
        for n, line in enumerate(f, 1):
            if line.strip():
                item = json.loads(line)
                meta = item.get("metadata") or item
                need_id = meta.get("info_need_id", meta.get("id", n))
                text = meta.get("info_need") or meta.get("query") or meta.get("text") or ""
                out.append((str(need_id), text))
    return out


# --------------------------------------------------------------- dev set

DEV_TYPES = [("wgs", "with whole genome sequencing"), ("wes", "with exome sequencing"),
             ("rnaseq", "with RNA-seq"), ("methylation", "with DNA methylation data")]
GENERIC_DISEASES = {"", "control", "controls", "healthy", "healthy volunteers", "not provided", "multiple"}


def _dev_options(pool):
    """Constraints that some (not necessarily all) studies of one disease meet: (phrase, test)."""
    opts = []
    for tag, phrase in DEV_TYPES:
        if any(tag in s["data_types"] for s in pool):
            opts.append((phrase, lambda s, tag=tag: tag in s["data_types"]))
    if any(any(cf.consent_ok(c, {"GRU"}) for c in s["consents"]) for s in pool):
        opts.append(("consented for general research use",
                     lambda s: any(cf.consent_ok(c, {"GRU"}) for c in s["consents"])))
    if any(s["age"] and s["age"][0] >= 18 for s in pool):
        opts.append(("in adults", lambda s: bool(s["age"]) and s["age"][0] >= 18))
    if any(s["age"] and s["age"][1] < 18 for s in pool):
        opts.append(("in children", lambda s: bool(s["age"]) and s["age"][1] < 18))
    for group in ("black", "hispanic", "asian"):
        if any(s["race_counts"].get(group, 0) >= 100 for s in pool):
            opts.append(("including at least 100 %s participants" % GROUP_LABELS[group].split("/")[-1],
                         lambda s, g=group: s["race_counts"].get(g, 0) >= 100))
    return opts


def make_devset(studies, n=100, seed=7, max_pool=60):
    """Conjunctive silver needs from snapshot fields: one main disease plus one or two constraints.

    A study is labelled relevant only if its main_disease is that disease and it meets every
    constraint by the same fields the ranker reads, so the score is a sanity check, not an
    estimate of the official one."""
    rng = random.Random(seed)
    by_disease = defaultdict(list)
    for s in studies:
        for d in s["focus"]:
            if d.lower() not in GENERIC_DISEASES:
                by_disease[d].append(s)
    diseases = sorted(d for d, pool in by_disease.items() if 2 <= len(pool) <= max_pool)
    rng.shuffle(diseases)
    queries, qrels = [], {}
    for d in diseases:
        if len(queries) >= n:
            break
        pool = by_disease[d]
        opts = _dev_options(pool)
        if not opts:
            continue
        picked = rng.sample(opts, min(len(opts), rng.choice((1, 2))))
        relevant = [s["accession"] for s in pool if all(test(s) for _, test in picked)]
        if not relevant:  # no study meets both; one option always has a match
            picked = picked[:1]
            relevant = [s["accession"] for s in pool if picked[0][1](s)]
        qid = "dev%03d" % (len(queries) + 1)
        text = "Studies of %s %s" % (d.lower(), " and ".join(p for p, _ in picked))
        queries.append({"id": qid, "query": text, "relevant": len(relevant)})
        qrels[qid] = {acc: 1 for acc in relevant}
    return queries, qrels


def bench(studies, queries, qrels, k=10):
    """Mean NDCG@k for text-only BM25 and for the conjunctive ranker on the same needs."""
    index = cf.Index(studies)
    out = {}
    for name, constraints in (("bm25_text_only", False), ("conjunctive", True)):
        scores = {}
        for q in queries:
            ranked = [r["accession"] for r in rank(index, parse_need(q["query"]), K, constraints)]
            scores[q["id"]] = cf.ndcg(ranked, qrels.get(q["id"], {}), k)
        out[name] = {"ndcg@%d" % k: round(sum(scores.values()) / len(scores), 4) if scores else 0.0,
                     "per_query": scores}
    out["questions"] = len(queries)
    out["note"] = ("Silver labels come from the same snapshot fields the ranker reads (circular); "
                   "use this to catch regressions, not to predict the official score.")
    return out


# --------------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--studies", required=True, help="studies.jsonl from snapshot_survey.py")
    ap.add_argument("--variables", help="variables.jsonl.gz from snapshot_survey.py")
    ap.add_argument("--values", help="var_values.jsonl.gz from snapshot_survey.py")
    sub = ap.add_subparsers(dest="cmd", required=True)
    p = sub.add_parser("ask", help="answer one question")
    p.add_argument("question")
    p.add_argument("-k", type=int, default=10)
    p = sub.add_parser("run", help="write a SPARK Task 2 submission for a file of information needs")
    p.add_argument("--needs", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--team-id", default="munim")
    p.add_argument("--submission-id", default="run1")
    p.add_argument("-k", type=int, default=K)
    p = sub.add_parser("devset", help="build conjunctive silver needs")
    p.add_argument("-n", type=int, default=100)
    p.add_argument("--seed", type=int, default=7)
    p.add_argument("--out", required=True)
    p = sub.add_parser("bench", help="NDCG@10 on a dev set")
    p.add_argument("--devset", required=True)
    p.add_argument("--out", required=True)
    args = ap.parse_args(argv)

    studies = load(args.studies, args.variables, args.values)
    if args.cmd == "ask":
        results = search(cf.Index(studies), args.question, args.k)
        print(cf.answer([dict(r, version=r["accession"]) for r in results], args.question))
    elif args.cmd == "run":
        index = cf.Index(studies)
        with open(args.out, "w", encoding="utf-8") as f:
            for need_id, text in read_needs(args.needs):
                f.write(submission_line(args.team_id, args.submission_id, need_id, text,
                                        rank(index, parse_need(text), args.k)) + "\n")
    elif args.cmd == "devset":
        queries, qrels = make_devset(studies, args.n, args.seed)
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump({"queries": queries, "qrels": qrels}, f, indent=1)
        print("%d silver needs, %d relevant labels" % (len(queries), sum(len(v) for v in qrels.values())))
    elif args.cmd == "bench":
        with open(args.devset, encoding="utf-8") as f:
            dev = json.load(f)
        result = bench(studies, dev["queries"], dev["qrels"])
        with open(args.out, "w", encoding="utf-8") as f:
            json.dump(result, f, indent=1)
        print(json.dumps({k: v for k, v in result.items() if k not in ("bm25_text_only", "conjunctive")}))
        for name in ("bm25_text_only", "conjunctive"):
            print(name, result[name]["ndcg@10"])
    return 0


if __name__ == "__main__":
    sys.exit(main())
