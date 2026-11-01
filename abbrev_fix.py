#!/usr/bin/env python3
"""abbrev_fix: let a SPARK Task 2 need name its disease by an abbreviation.

disease_check 0.1.0 (2026-11-01) renamed only the disease in 150 silver needs.
Everyday names cost little, but abbreviations cost about 0.16 NDCG@10, in two ways:
- an abbreviation the ranker doesn't know ("SCLC", "CTCL", "AATD", "NETs") leaves a
  topic word no study's disease fields contain, so the disease check fails;
- an abbreviation the ranker does know is replaced by its spelled-out words ("HIV"
  -> human immunodeficiency virus), so studies that store the short form ("HIV" is
  the main disease of many dbGaP studies) fail the disease check.

This module changes only needs that contain a disease abbreviation:
1. Unknown abbreviations are looked up in definitions mined from the snapshot's own
   study titles, descriptions and disease terms ("small cell lung cancer (SCLC)"),
   with the Schwartz-Hearst rule (Pac Symp Biocomput 2003). If one is found, the
   abbreviation in the need is replaced by its long form before parsing.
2. While the need is ranked, a study's disease fit is the best of the parsed topic,
   the abbreviation itself, and the topic of the need as written (and a mined long
   form that differs from the table's), so no reading the current system makes is lost.
Needs without a disease abbreviation get exactly spark_submit.padded_answer.

Pre-registered in 20261101T140844Z-civic-tech/findings/prereg-abbrev-fix.md.

Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
"""

import collections
import contextlib
import re

import cohort_finder as cf
import sentence_need as sen
import snapshot as sn

__version__ = "0.1.0"

CANDIDATE_RE = re.compile(r"(?<![\w-])([A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*)(?![\w-])")
PAREN_RE = re.compile(r"\(\s*([A-Za-z][A-Za-z0-9]*(?:-[A-Za-z0-9]+)*)\s*\)")
CLAUSE_RE = re.compile(r"[.;:!?()\[\]]")
POSSESSIVE_RE = re.compile(r"['’]s\b")
# Capitalised words that are never a disease: places, agencies, data types, consent codes,
# ancestry codes and measurements (these are constraints or variables, not what is studied).
STOP = frozenset(w.upper() for w in """
    US USA UK EU NIH NLM NCBI NHLBI NHGRI NCI dbGaP ID IDs OK FAQ
    DNA RNA SNP SNPs GWAS WGS WES WXS GRU HMB IRB NPU MDS COL PUB NRES DS GSO
    EUR AFA AFO LAC LEN EAS SAS OAS ATAC ChIP TOPMed RNA-seq scRNA-seq
    BMI LDL HDL BP SBP DBP eGFR ECG EKG MRI CT EHR HbA1c A1c
    """.split())


def is_short_form(word):
    """Looks like an abbreviation: 2-10 characters, starts with a letter, at least two capitals,
    and capitals make up at least half of its letters ("HIV", "NETs", "MIS-C"; not "Andersen-Tawil")."""
    letters = [c for c in word if c.isalpha()]
    upper = sum(1 for c in letters if c.isupper())
    return 2 <= len(word) <= 10 and word[0].isalpha() and upper >= 2 and 2 * upper >= len(letters)


def best_long_form(short, long):
    """The shortest end of `long` whose letters spell `short` in order, the first at a word start, or None.

    Schwartz & Hearst's findBestLongForm."""
    s, i = len(short) - 1, len(long) - 1
    while s >= 0:
        c = short[s].lower()
        if not c.isalnum():
            s -= 1
            continue
        while (i >= 0 and long[i].lower() != c) or (s == 0 and i > 0 and long[i - 1].isalnum()):
            i -= 1
        if i < 0:
            return None
        i -= 1
        s -= 1
    return long[long.rfind(" ", 0, i + 1) + 1:]


def normalize(long):
    """Lower case, possessive "'s" dropped, spaces collapsed, edge punctuation removed."""
    text = POSSESSIVE_RE.sub("", long.lower())
    return " ".join(text.split()).strip(" ,-/")


def definitions(text):
    """(short, long) pairs for every 'long form (SHORT)' in text."""
    out = []
    for m in PAREN_RE.finditer(text or ""):
        short = m.group(1)
        if not is_short_form(short):
            continue
        words = CLAUSE_RE.split(text[:m.start()])[-1].split()
        limit = min(len(short) + 5, 2 * len(short))
        long = best_long_form(short, " ".join(words[-limit:]))
        if not long:
            continue
        long = normalize(long)
        if len(long) <= len(short) or len(long.split()) > limit or short.lower() in long.split():
            continue
        out.append((short, long))
    return out


def mine(texts):
    """{short form: Counter of long forms} over an iterable of texts."""
    defs = collections.defaultdict(collections.Counter)
    for text in texts:
        for short, long in definitions(text):
            defs[short][long] += 1
    return dict(defs)


def study_texts(study):
    yield study.get("title") or ""
    yield study.get("description") or ""
    yield ". ".join(study.get("conditions") or [])


def index_definitions(index):
    """Definitions mined from every study in the index, computed once per index."""
    defs = getattr(index, "_abbrev_defs", None)
    if defs is None:
        defs = index._abbrev_defs = mine(t for s in index.studies for t in study_texts(s))
    return defs


def long_form(defs, short):
    """(most frequent long form, its count) for short (exact case first, then any case), or (None, 0)."""
    counts = (defs or {}).get(short)
    if not counts:
        merged = collections.Counter()
        for key, c in (defs or {}).items():
            if key.upper() == short.upper():
                merged.update(c)
        counts = merged
    if not counts:
        return None, 0
    long, n = sorted(counts.items(), key=lambda kv: (-kv[1], len(kv[0]), kv[0]))[0]
    return long, n


def disease_abbreviations(text, defs=None):
    """The need's disease abbreviations, each {"abbrev", "table", "mined", "mined_count"}.

    Words that are constraints (data types, consent, ancestry codes), measurements, or part
    of a 'with X measured' phrase are skipped."""
    var_words = set()
    for phrase in sn.var_phrases(text):
        var_words.update(cf.tokens(phrase))
    out, seen = [], set()
    for m in CANDIDATE_RE.finditer(text or ""):
        word = m.group(1)
        if word in seen or not is_short_form(word) or word.upper() in STOP:
            continue
        toks = cf.tokens(word)
        if not toks or all(t in sn.CONSTRAINT_WORDS for t in toks) or any(t in var_words for t in toks):
            continue
        seen.add(word)
        table = cf.expand_abbreviations(word)
        mined, count = long_form(defs, word)
        out.append({"abbrev": word, "table": table[0] if table else None, "mined": mined, "mined_count": count})
    return out


def rewrite(text, replacements):
    """text with each whole-word abbreviation replaced by its long form."""
    for short, long in replacements.items():
        text = re.sub(r"(?<![\w-])%s(?![\w-])" % re.escape(short), lambda _m, long=long: long, text)
    return text


@contextlib.contextmanager
def topic_alternatives(alternatives):
    """While active, snapshot.disease_requirement is the best over the given topic and each alternative."""
    original = sn.disease_requirement
    alts = [list(a) for a in alternatives if a]

    def best(study, topic):
        result = original(study, topic)
        for alt in alts:
            if alt != list(topic):
                other = original(study, alt)
                if other[0] > result[0]:
                    result = other
        return result

    sn.disease_requirement = best
    try:
        yield
    finally:
        sn.disease_requirement = original


def plan(index, text):
    """(text to rank, topic alternatives, abbreviations found) for one need."""
    found = disease_abbreviations(text, index_definitions(index))
    if not found:
        return text, [], found
    replacements, alts = {}, []
    for f in found:
        alts.append(cf.tokens(f["abbrev"]))
        if f["table"] is None and f["mined"]:
            replacements[f["abbrev"]] = f["mined"]
        elif f["table"] and f["mined"] and normalize(f["mined"]) != normalize(f["table"]):
            alts.append(sn.topic_tokens(f["mined"], cf.parse_query(f["mined"])))
    alts.append(sen.parse_need(text).get("topic") or [])
    return rewrite(text, replacements), alts, found


def answer(index, text, k=sn.K, tier=sen.TIER):
    """Ranked accessions for one need: spark_submit.padded_answer, with abbreviations handled as above."""
    import spark_submit as ss
    new_text, alts, found = plan(index, text)
    if not found:
        return ss.padded_answer(index, text, k, tier)
    with topic_alternatives(alts):
        return ss.padded_answer(index, new_text, k, tier)
