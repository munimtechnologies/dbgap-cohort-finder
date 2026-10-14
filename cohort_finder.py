#!/usr/bin/env python3
"""dbgap-cohort-finder: rank public dbGaP studies for cohort-feasibility questions.

A researcher asks "which dbGaP studies have whole genome sequencing on at least
1,000 African American adults with type 2 diabetes, consented for general
research use?" and wants a short ranked list of studies before filing a Data
Access Request. This tool answers from public study metadata only: titles,
descriptions, conditions, study design, consent groups, subject counts,
molecular data types and dbGaP's computed ancestry counts, all read from the
public dbGaP FHIR API (https://dbgap-api.ncbi.nlm.nih.gov/fhir/x1). No
controlled-access data is touched.

It is an open baseline for the National Library of Medicine's SPARK dbGaP
Task 2 (conversational cohort feasibility, scored by NDCG), not an official
NIH product. Standard library only, Python 3.8+.

Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
"""

import argparse
import html
import json
import math
import os
import re
import sys
import time
import urllib.request
from collections import Counter

__version__ = "0.1.0"

FHIR_BASE = "https://dbgap-api.ncbi.nlm.nih.gov/fhir/x1"
REPO_URL = "https://github.com/munimv2/dbgap-cohort-finder"
USER_AGENT = "dbgap-cohort-finder/%s (+%s)" % (__version__, REPO_URL)
PAGE_SIZE = 100
PAGE_DELAY = 0.5  # seconds between FHIR pages; NCBI asks for gentle use
MAX_PAGES = 500
MESH_SYSTEM = "urn:oid:2.16.840.1.113883.6.177"
RUN_TAG = "cohortfinder"

# Ranking weights. Text relevance and constraint satisfaction are both in
# [0, 1]; a question with no structured constraints is ranked by text alone.
W_TEXT = 0.6
W_CONSTRAINTS = 0.4
ANCESTRY_MIN = 100  # computed-ancestry subjects that count as "has this group"
UNKNOWN = 0.3       # satisfaction when the study does not report the field

# Molecular data types, shared by study metadata and questions.
DATA_TYPE_RULES = [
    (r"\bwgs\b|whole[- ]genome", "wgs"),
    (r"\bwxs\b|\bwes\b|exome", "wes"),
    (r"\bsnps?\b|genotyp|\bgwas\b|genome[- ]wide association", "genotypes"),
    (r"imput", "imputed"),
    (r"mirna|microrna|small rna", "mirna"),
    (r"(?<!mi)rna[- ]?seq|\bexpression\b|transcriptom", "rnaseq"),
    (r"methyl|bisulfite|epigenom", "methylation"),
    (r"atac", "atacseq"),
    (r"single[- ]cell|scrna|\b10x\b", "scrna"),
    (r"chip[- ]seq", "chipseq"),
    (r"proteom", "proteomics"),
    (r"metabolom", "metabolomics"),
]
# Having the left-hand type also gives you the right-hand ones.
IMPLIES = {"wgs": {"genotypes"}, "wes": {"genotypes"}, "imputed": {"genotypes"}}

DESIGN_RULES = [
    (r"case[- ]control", "case_control"),
    (r"cohort", "cohort"),
    (r"longitudinal|prospective", "longitudinal"),
    (r"cross[- ]sectional", "cross_sectional"),
    (r"\bfamil|\btwins?\b|\btrios?\b|pedigree", "family"),
    (r"clinical trial|randomi[sz]ed", "trial"),
    (r"matched[- ]normal|tumor[- ]normal|tumor vs", "tumor_normal"),
]
# Questions use "cohort" and "family" loosely ("a cohort with...", "family
# history of"), so only phrases that name a design count there.
QUERY_DESIGN_RULES = [
    (r"cohort stud|cohort design|(?:prospective|longitudinal|population[- ]based|birth|retrospective) cohort",
     "cohort"),
    (r"family[- ]based|\bfamilies\b|pedigree|\btwins?\b|\btrios?\b", "family"),
] + [(p, t) for p, t in DESIGN_RULES if t not in ("cohort", "family")]

# dbGaP computed (GRAF-pop) ancestry codes: EUR European, AFA African
# American, AFO other African, LAC Latin American 1, LEN Latin American 2,
# EAS East Asian, SAS South Asian, OAS other Asian or Pacific Islander.
ANCESTRY_RULES = [
    (r"african[- ]american|\bblack (?:americans?|participants|subjects|individuals|adults|people|women|men|patients)",
     ("AFA",)),
    (r"\bafrican\b(?![- ]american)|\bafrica\b", ("AFA", "AFO")),
    (r"\beuropean|caucasian", ("EUR",)),
    (r"hispanic|latin[oax]\b|latin american|mexican|puerto ric|dominican", ("LAC", "LEN")),
    (r"east asian|chinese|japanese|korean", ("EAS",)),
    (r"south asian|asian indian|pakistani|bangladeshi", ("SAS",)),
    (r"(?<!east )(?<!south )\basians?\b", ("EAS", "SAS", "OAS")),
    (r"pacific islander", ("OAS",)),
]

CONSENT_RULES = [
    (r"general research use|\bgru\b", "GRU"),
    (r"\bhmb\b|health[/, ]+medical|biomedical research", "HMB"),
    (r"for[- ]profit|commercial|\bindustry\b", "NO_NPU"),
    (r"without (?:an )?irb|no irb", "NO_IRB"),
]
CONSENT_LABELS = {
    "GRU": "general research use",
    "HMB": "health/medical/biomedical use",
    "NO_NPU": "for-profit use allowed",
    "NO_IRB": "no IRB approval required",
}

NUMBER = r"\b(\d[\d,]*(?:\.\d+)?)\s*(k\b|thousand)?"
MIN_SIZE = 10  # smaller numbers are disease names ("type 2") or ages, not cohort sizes
MIN_RE = re.compile(
    r"(?:at least|more than|over|greater than|minimum of|no fewer than|>=|≥|>)\s*" + NUMBER, re.I)
SIZE_RE = re.compile(
    NUMBER + r"\s*\+?\s+(?:or more\s+)?(?:\w+\s+){0,3}?"
    r"(?:participants|subjects|individuals|people|samples|patients|cases|controls"
    r"|adults|children|women|men|donors)\b", re.I)
NOT_A_SIZE = ("year", "yr", "y/o", "%", "percent", "month", "week", "day", "mg", "kg", "hour")

STOPWORDS = set("""
a an and any are as at be by can do does for from has have how i in into is it
its me my of on or our than that the their them there these they this those to
was we were what which who whom with within would find show list give need want
looking look all also both each study studies dataset datasets data dbgap
available contain contains containing include includes including least more
over most participant participants subject subjects individual individuals
people sample samples use used using allowed consent consented please where
""".split())

TAG_RE = re.compile(r"<[^>]+>")
TOKEN_RE = re.compile(r"[a-z0-9]+")


def clean_text(text):
    """Plain text from dbGaP's HTML-flavoured strings."""
    text = html.unescape(TAG_RE.sub(" ", text or ""))
    return " ".join(text.split())


def _stem(token):
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith("ss"):
        return token[:-1]
    return token


def tokens(text):
    """Lower-case word stems without stopwords or bare numbers."""
    out = []
    for raw in TOKEN_RE.findall((text or "").lower()):
        if raw.isdigit() or raw in STOPWORDS:
            continue
        stem = _stem(raw)
        if stem in STOPWORDS:
            continue
        out.append(stem)
    return out


def _tags(text, rules):
    low = (text or "").lower()
    return {tag for pattern, tag in rules if re.search(pattern, low)}


def data_type_tags(names):
    """Canonical molecular data type tags for dbGaP data type names."""
    tags = set()
    for name in names:
        tags |= _tags(name, DATA_TYPE_RULES)
    for tag in list(tags):
        tags |= IMPLIES.get(tag, set())
    return tags


def design_tags(names):
    tags = set()
    for name in names:
        tags |= _tags(name, DESIGN_RULES)
    return tags


# ---------------------------------------------------------------- FHIR input

def _ext_name(url):
    """'.../StructureDefinition/ResearchStudy-Content-NumSubjects' -> 'Content-NumSubjects'."""
    name = (url or "").rstrip("/").rsplit("/", 1)[-1]
    return name[len("ResearchStudy-"):] if name.startswith("ResearchStudy-") else name


def _count(ext):
    value = (ext.get("valueCount") or {}).get("value")
    if value is None:
        value = ext.get("valueInteger")
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return None


def _codes(ext):
    concept = ext.get("valueCodeableConcept") or {}
    out = [c.get("code") or c.get("display") for c in concept.get("coding") or []]
    if not out and concept.get("text"):
        out = [concept["text"]]
    return [c for c in out if c]


def _unique(values):
    seen, out = set(), []
    for value in values:
        if value and value not in seen:
            seen.add(value)
            out.append(value)
    return out


def _concept_texts(concepts):
    texts = []
    for concept in concepts or []:
        text = concept.get("text")
        if not text:
            text = next((c.get("display") for c in concept.get("coding") or [] if c.get("display")), None)
        texts.append(clean_text(text))
    return _unique(texts)


def normalize_study(resource):
    """One FHIR ResearchStudy resource -> a flat study record."""
    study = {
        "accession": resource.get("id"),
        "version": None,
        "title": clean_text(resource.get("title")),
        "description": clean_text(resource.get("description")),
        "status": resource.get("status"),
        "design": _concept_texts(resource.get("category")),
        "focus": _concept_texts(resource.get("focus")),
        "conditions": _concept_texts(list(resource.get("condition") or []) + list(resource.get("keyword") or [])),
        "mesh": [],
        "consents": [],
        "subjects": None,
        "samples": None,
        "substudies": None,
        "variables": None,
        "ancestry": {},
        "data_types_raw": [],
        "data_types": [],
        "release_date": None,
        "sponsor": (resource.get("sponsor") or {}).get("display"),
        "url": None,
    }
    for ident in resource.get("identifier") or []:
        if ident.get("value"):
            study["version"] = ident["value"]
            break
    mesh = []
    for concept in list(resource.get("condition") or []) + list(resource.get("focus") or []):
        for coding in concept.get("coding") or []:
            if coding.get("system") == MESH_SYSTEM and coding.get("code"):
                mesh.append(coding["code"])
    study["mesh"] = _unique(mesh)

    content_keys = {
        "Content-NumSubjects": "subjects",
        "Content-NumSamples": "samples",
        "Content-NumSubStudies": "substudies",
        "Content-NumVariables": "variables",
    }
    raw_types = []
    for ext in resource.get("extension") or []:
        name = _ext_name(ext.get("url"))
        inner = ext.get("extension") or []
        if name == "StudyOverviewUrl":
            study["url"] = ext.get("valueUrl") or ext.get("valueUri")
        elif name == "ReleaseDate":
            study["release_date"] = ext.get("valueDate") or ext.get("valueDateTime")
        elif name == "StudyConsents":
            study["consents"] = _unique(
                (sub.get("valueCoding") or {}).get("display") for sub in inner)
        elif name == "Content":
            for sub in inner:
                key = content_keys.get(_ext_name(sub.get("url")))
                if key:
                    study[key] = _count(sub)
        elif name == "ComputedAncestry":
            for group in inner:
                code, count = None, None
                for part in group.get("extension") or []:
                    part_name = _ext_name(part.get("url"))
                    if part_name.endswith("-Ancestry"):
                        found = _codes(part)
                        code = found[0] if found else None
                    elif part_name.endswith("-Count"):
                        count = _count(part)
                if code and count is not None:
                    study["ancestry"][code] = study["ancestry"].get(code, 0) + count
        elif name == "MolecularDataTypes":
            for sub in inner:
                raw_types += _codes(sub)
    if not study["url"] and study["version"]:
        study["url"] = "https://www.ncbi.nlm.nih.gov/projects/gap/cgi-bin/study.cgi?study_id=" + study["version"]
    study["data_types_raw"] = _unique(raw_types)
    study["data_types"] = sorted(data_type_tags(study["data_types_raw"]))
    return study


def fetch_json(url, timeout=60):
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "application/fhir+json, application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))


def harvest(fetcher=fetch_json, delay=PAGE_DELAY, page_size=PAGE_SIZE, max_pages=MAX_PAGES, log=None):
    """Every public ResearchStudy on the dbGaP FHIR server, normalized, following 'next' links."""
    url = "%s/ResearchStudy?_count=%d&_format=json" % (FHIR_BASE, page_size)
    studies, seen = [], set()
    for page in range(max_pages):
        bundle = fetcher(url)
        for entry in bundle.get("entry") or []:
            resource = entry.get("resource") or {}
            if resource.get("resourceType") != "ResearchStudy" or resource.get("id") in seen:
                continue
            seen.add(resource.get("id"))
            studies.append(normalize_study(resource))
        nxt = next((link.get("url") for link in bundle.get("link") or []
                    if link.get("relation") == "next" and link.get("url")), None)
        if log:
            log("page %d: %d studies so far" % (page + 1, len(studies)))
        if not nxt:
            break
        url = nxt
        if delay:
            time.sleep(delay)
    studies.sort(key=lambda s: s.get("accession") or "")
    return studies


def read_studies(path):
    with open(path, encoding="utf-8") as f:
        return [json.loads(line) for line in f if line.strip()]


def write_studies(studies, path):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for study in studies:
            f.write(json.dumps(study, ensure_ascii=False, sort_keys=True) + "\n")


# ------------------------------------------------------------ question side

def _to_number(digits, unit):
    value = float(digits.replace(",", ""))
    if unit:
        value *= 1000
    return int(round(value))


def _is_size(text, end):
    after = text[end:end + 12].lower().lstrip(" -")
    return not after.startswith(NOT_A_SIZE)


def min_subjects(text):
    """The largest participant count a question asks for, or None."""
    found = []
    for regex in (MIN_RE, SIZE_RE):
        for m in regex.finditer(text or ""):
            if not _is_size(text, m.end(1)):
                continue
            found.append(_to_number(m.group(1), m.group(2)))
    found = [n for n in found if n >= MIN_SIZE]
    return max(found) if found else None


def parse_query(text):
    """A free-text feasibility question -> search tokens plus structured constraints."""
    low = (text or "").lower()
    ancestry = []
    for pattern, codes in ANCESTRY_RULES:
        if re.search(pattern, low) and set(codes) not in ancestry:
            ancestry.append(set(codes))
    return {
        "text": text,
        "tokens": tokens(text),
        "min_subjects": min_subjects(text),
        "data_types": _tags(low, DATA_TYPE_RULES),
        "designs": _tags(low, QUERY_DESIGN_RULES),
        "ancestry": ancestry,
        "consent": _tags(low, CONSENT_RULES),
    }


def consent_ok(consent, needs):
    """Does one consent code (e.g. 'HMB-IRB-NPU') meet every need?"""
    parts = (consent or "").upper().split("-")
    base = parts[0]
    for need in needs:
        if need == "GRU" and base != "GRU":
            return False
        if need == "HMB" and base not in ("GRU", "HMB"):
            return False
        if need == "NO_NPU" and "NPU" in parts:
            return False
        if need == "NO_IRB" and "IRB" in parts:
            return False
    return True


def requirements(study, query):
    """(satisfaction in [0, 1], explanation) for each constraint in the question."""
    out = []
    want = query.get("min_subjects")
    if want:
        have = study.get("subjects")
        if have is None:
            out.append((UNKNOWN, "subject count not reported (wanted %s)" % format(want, ",")))
        elif have >= want:
            out.append((1.0, "%s subjects (wanted at least %s)" % (format(have, ","), format(want, ","))))
        else:
            out.append((0.8 * have / want, "only %s subjects (wanted %s)" % (format(have, ","), format(want, ","))))
    wanted_types = sorted(query.get("data_types") or [])
    has_types = set(study.get("data_types") or []) if wanted_types else set()
    if wanted_types and not has_types:
        has_types = data_type_tags(study.get("data_types_raw") or [])
    for tag in wanted_types:
        if tag in has_types:
            out.append((1.0, "has %s data" % tag))
        else:
            out.append((0.0, "no %s data listed" % tag))
    wanted_designs = sorted(query.get("designs") or [])
    designs = design_tags(study.get("design") or []) if wanted_designs else set()
    for tag in wanted_designs:
        if tag in designs:
            out.append((1.0, "design: %s" % ", ".join(study.get("design") or [])))
        else:
            out.append((0.0, "design is not %s" % tag.replace("_", "-")))
    ancestry = study.get("ancestry") or {}
    for codes in query.get("ancestry") or []:
        label = "/".join(sorted(codes))
        n = sum(ancestry.get(code, 0) for code in codes)
        if not ancestry:
            out.append((UNKNOWN, "no computed ancestry reported (%s)" % label))
        elif n >= ANCESTRY_MIN:
            out.append((1.0, "%s %s subjects by computed ancestry" % (format(n, ","), label)))
        elif n > 0:
            out.append((0.5, "only %d %s subjects by computed ancestry" % (n, label)))
        else:
            out.append((0.0, "no %s subjects by computed ancestry" % label))
    needs = query.get("consent") or set()
    if needs:
        consents = study.get("consents") or []
        label = ", ".join(CONSENT_LABELS[n] for n in sorted(needs))
        good = [c for c in consents if consent_ok(c, needs)]
        if not consents:
            out.append((UNKNOWN, "consent groups not reported (%s)" % label))
        elif good:
            out.append((1.0, "consent %s fits (%s)" % (good[0], label)))
        else:
            out.append((0.0, "no consent group fits (%s): %s" % (label, ", ".join(consents))))
    return out


# ------------------------------------------------------------------ ranking

def doc_tokens(study):
    """Field-weighted bag of words: title and conditions count three times, primary focus twice."""
    return (tokens(study.get("title")) * 3
            + tokens(" ".join(study.get("conditions") or [])) * 3
            + tokens(" ".join(study.get("focus") or [])) * 2
            + tokens(" ".join((study.get("design") or []) + (study.get("data_types_raw") or [])))
            + tokens(study.get("description")))


class Index:
    """BM25 over study metadata."""

    def __init__(self, studies, k1=1.2, b=0.75):
        self.studies = list(studies)
        self.k1, self.b = k1, b
        self.docs = [Counter(doc_tokens(s)) for s in self.studies]
        self.lengths = [sum(c.values()) for c in self.docs]
        self.avgdl = (sum(self.lengths) / float(len(self.lengths))) if self.lengths else 0.0
        self.avgdl = self.avgdl or 1.0
        df = Counter()
        for doc in self.docs:
            df.update(doc.keys())
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in df.items()}

    def bm25(self, i, query_tokens):
        doc, score = self.docs[i], 0.0
        norm = self.k1 * (1 - self.b + self.b * self.lengths[i] / self.avgdl)
        for term in set(query_tokens):
            f = doc.get(term)
            if f:
                score += self.idf[term] * f * (self.k1 + 1) / (f + norm)
        return score


def search(index, text, k=10):
    """The k best studies for a question, each with a score and the reasons behind it."""
    query = parse_query(text)
    has_constraints = any(query[key] for key in ("min_subjects", "data_types", "designs", "ancestry", "consent"))
    if not query["tokens"] and not has_constraints:
        return []
    raw = [index.bm25(i, query["tokens"]) for i in range(len(index.studies))]
    top = max(raw) if raw and max(raw) > 0 else 1.0
    results = []
    for i, study in enumerate(index.studies):
        text_score = raw[i] / top
        reqs = requirements(study, query)
        cons = sum(s for s, _ in reqs) / len(reqs) if reqs else None
        if text_score <= 0 and (cons is None or cons < 1.0):
            continue
        score = text_score if cons is None else W_TEXT * text_score + W_CONSTRAINTS * cons
        score += math.log10((study.get("subjects") or 0) + 1) / 1000.0  # tie-break: bigger studies first
        results.append({
            "accession": study.get("accession"),
            "version": study.get("version"),
            "title": study.get("title"),
            "subjects": study.get("subjects"),
            "url": study.get("url"),
            "score": round(score, 6),
            "why": [why for _, why in reqs],
        })
    results.sort(key=lambda r: (-r["score"], r["accession"] or ""))
    return results[:k]


def answer(results, text):
    """A short plain-text reply listing the ranked studies and why each fits."""
    if not results:
        return "No public dbGaP study matched: %s" % text
    lines = ["Studies that may fit: %s" % text]
    for rank, r in enumerate(results, 1):
        size = "%s subjects" % format(r["subjects"], ",") if r.get("subjects") is not None else "size not reported"
        lines.append("%d. %s %s (%s)" % (rank, r.get("version") or r["accession"], r.get("title") or "", size))
        for why in r.get("why") or []:
            lines.append("   - " + why)
    lines.append("From public dbGaP metadata only; check each study's consent groups and data before a Data Access Request.")
    return "\n".join(lines)


# --------------------------------------------------------------- evaluation

def ndcg(ranked, relevance, k=10):
    """NDCG@k with gain 2^rel - 1; relevance maps accession -> graded label."""
    def dcg(labels):
        return sum((2 ** rel - 1) / math.log2(i + 2) for i, rel in enumerate(labels[:k]))
    ideal = dcg(sorted((r for r in relevance.values() if r > 0), reverse=True))
    if ideal <= 0:
        return 0.0
    return dcg([relevance.get(acc, 0) for acc in ranked]) / ideal


def read_qrels(path):
    """TREC qrels ('qid 0 accession label') -> {qid: {accession: label}}."""
    qrels = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 4:
                qrels.setdefault(parts[0], {})[parts[2]] = int(float(parts[3]))
    return qrels


def read_run(path):
    """TREC run ('qid Q0 accession rank score tag') -> {qid: [accession, ...]} in rank order."""
    rows = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 5:
                rows.setdefault(parts[0], []).append((int(parts[3]), parts[2]))
    return {qid: [acc for _, acc in sorted(items)] for qid, items in rows.items()}


def run_lines(qid, results, tag=RUN_TAG):
    return ["%s Q0 %s %d %.6f %s" % (qid, r["accession"], rank, r["score"], tag)
            for rank, r in enumerate(results, 1)]


def evaluate(run, qrels, k=10):
    """Mean NDCG@k over the judged questions; unanswered questions score 0."""
    scores = {qid: ndcg(run.get(qid, []), rel, k) for qid, rel in qrels.items()}
    mean = sum(scores.values()) / len(scores) if scores else 0.0
    return mean, scores


def read_queries(path):
    """JSON lines with 'id' and 'query' (or 'text')."""
    out = []
    with open(path, encoding="utf-8") as f:
        for n, line in enumerate(f, 1):
            if line.strip():
                item = json.loads(line)
                out.append((str(item.get("id", n)), item.get("query") or item.get("text") or ""))
    return out


# --------------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(description="Rank public dbGaP studies for cohort-feasibility questions.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")

    h = sub.add_parser("harvest", help="download public study metadata from the dbGaP FHIR API")
    h.add_argument("--out", default="studies.jsonl")
    h.add_argument("--delay", type=float, default=PAGE_DELAY)

    s = sub.add_parser("search", help="answer one question")
    s.add_argument("query")
    s.add_argument("--studies", default="studies.jsonl")
    s.add_argument("-k", type=int, default=10)
    s.add_argument("--json", action="store_true", help="print JSON instead of text")

    r = sub.add_parser("run", help="answer a file of questions and write a TREC run")
    r.add_argument("--queries", required=True, help="JSON lines with id and query")
    r.add_argument("--studies", default="studies.jsonl")
    r.add_argument("--out", default="run.txt")
    r.add_argument("-k", type=int, default=10)

    e = sub.add_parser("evaluate", help="mean NDCG@k of a TREC run against TREC qrels")
    e.add_argument("--run", required=True)
    e.add_argument("--qrels", required=True)
    e.add_argument("-k", type=int, default=10)

    args = ap.parse_args(argv)
    log = lambda msg: print(msg, file=sys.stderr)  # noqa: E731
    if args.cmd == "harvest":
        studies = harvest(delay=args.delay, log=log)
        write_studies(studies, args.out)
        print("%d studies -> %s" % (len(studies), args.out))
        return 0
    if args.cmd in ("search", "run"):
        if not os.path.exists(args.studies):
            log("no %s yet; run 'python cohort_finder.py harvest' first" % args.studies)
            return 1
        index = Index(read_studies(args.studies))
        if args.cmd == "search":
            results = search(index, args.query, args.k)
            print(json.dumps(results, indent=2, ensure_ascii=False) if args.json else answer(results, args.query))
            return 0
        lines = []
        for qid, text in read_queries(args.queries):
            lines += run_lines(qid, search(index, text, args.k))
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))
        print("%d lines -> %s" % (len(lines), args.out))
        return 0
    if args.cmd == "evaluate":
        mean, scores = evaluate(read_run(args.run), read_qrels(args.qrels), args.k)
        for qid in sorted(scores):
            print("%s\t%.4f" % (qid, scores[qid]))
        print("mean NDCG@%d\t%.4f" % (args.k, mean))
        return 0
    ap.print_help()
    return 1


if __name__ == "__main__":
    sys.exit(main())
