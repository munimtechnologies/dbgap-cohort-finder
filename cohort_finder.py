#!/usr/bin/env python3
"""dbgap-cohort-finder: rank public dbGaP studies for cohort-feasibility questions.

A researcher asks "which dbGaP studies have whole genome sequencing on at least
1,000 African American adults with type 2 diabetes, consented for general
research use?" and wants a short ranked list of studies before filing a Data
Access Request. This tool answers from public study metadata only: titles,
descriptions, conditions, study design, consent groups, subject counts,
molecular data types and dbGaP's computed ancestry counts, all read from the
public dbGaP FHIR API (https://dbgap-api.ncbi.nlm.nih.gov/fhir/x1), plus the
public data dictionaries and aggregate variable reports that dbGaP publishes
for each study (https://ftp.ncbi.nlm.nih.gov/dbgap/studies/). No
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
import random
import re
import sys
import time
import urllib.error
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter

__version__ = "0.2.0"

FHIR_BASE = "https://dbgap-api.ncbi.nlm.nih.gov/fhir/x1"
FTP_BASE = "https://ftp.ncbi.nlm.nih.gov/dbgap/studies"
REPO_URL = "https://github.com/munimtechnologies/dbgap-cohort-finder"
USER_AGENT = "dbgap-cohort-finder/%s (+%s)" % (__version__, REPO_URL)
PAGE_SIZE = 100
PAGE_DELAY = 0.5  # seconds between FHIR pages; NCBI asks for gentle use
FILE_DELAY = 0.34  # seconds between data dictionary files (about 3 requests a second)
MAX_PAGES = 500
MAX_TABLES = 200  # data dictionary files read per study
MESH_SYSTEM = "urn:oid:2.16.840.1.113883.6.177"
RUN_TAG = "cohortfinder"

# Ranking weights. Text relevance and constraint satisfaction are both in
# [0, 1]; a question with no structured constraints is ranked by text alone.
# Matches in a study's data dictionary add a smaller bonus on top.
W_TEXT = 0.6
W_CONSTRAINTS = 0.4
W_VARS = 0.2
VAR_B = 0.3  # weak length normalization: big studies simply measure more
ANCESTRY_MIN = 100  # computed-ancestry subjects that count as "has this group"
UNKNOWN = 0.3       # satisfaction when the study does not report the field
SMALL_CELL = 11     # counts below this are shown as "fewer than 11"

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

FEMALE_RE = re.compile(r"\b(?:women|woman|females?|girls?|mothers?|maternal|pregnan\w*)\b")
MALE_RE = re.compile(r"\b(?:men|man|males?|boys?|fathers?|paternal)\b")
SEX_LABELS = {"female": "women", "male": "men"}

CONSTRAINT_KEYS = ("min_subjects", "data_types", "designs", "ancestry", "consent", "sex")

# Common abbreviations in feasibility questions. Their spelled-out words are
# added to the search, because study titles and MeSH terms use the long form.
# Abbreviations of three letters or fewer must be written in capitals
# ("AD", not "ad"), so ordinary words are never expanded.
ABBREVIATIONS = {
    "T2D": "type 2 diabetes mellitus", "T2DM": "type 2 diabetes mellitus",
    "T1D": "type 1 diabetes mellitus", "T1DM": "type 1 diabetes mellitus",
    "CAD": "coronary artery disease", "CHD": "coronary heart disease",
    "MI": "myocardial infarction", "AF": "atrial fibrillation", "AFib": "atrial fibrillation",
    "HF": "heart failure", "CVD": "cardiovascular disease",
    "COPD": "chronic obstructive pulmonary disease", "CKD": "chronic kidney disease",
    "ESRD": "end stage renal disease kidney failure", "AD": "alzheimer disease",
    "PD": "parkinson disease", "ALS": "amyotrophic lateral sclerosis",
    "ASD": "autism spectrum disorder", "ADHD": "attention deficit hyperactivity disorder",
    "MDD": "major depressive disorder depression", "SCZ": "schizophrenia",
    "PTSD": "post traumatic stress disorder", "IBD": "inflammatory bowel disease",
    "UC": "ulcerative colitis", "RA": "rheumatoid arthritis", "SLE": "systemic lupus erythematosus",
    "NAFLD": "nonalcoholic fatty liver disease", "NASH": "nonalcoholic steatohepatitis",
    "MASLD": "metabolic dysfunction associated steatotic liver disease fatty liver",
    "HIV": "human immunodeficiency virus", "HCV": "hepatitis c virus",
    "OSA": "obstructive sleep apnea", "SCD": "sickle cell disease",
    "AML": "acute myeloid leukemia", "CLL": "chronic lymphocytic leukemia",
    "NSCLC": "non small cell lung carcinoma cancer", "BMI": "body mass index",
    "HbA1c": "glycated hemoglobin a1c", "A1c": "glycated hemoglobin a1c", "A1C": "glycated hemoglobin a1c",
    "LDL": "low density lipoprotein cholesterol", "HDL": "high density lipoprotein cholesterol",
    "BP": "blood pressure", "SBP": "systolic blood pressure", "DBP": "diastolic blood pressure",
    "eGFR": "estimated glomerular filtration rate", "ECG": "electrocardiogram", "EKG": "electrocardiogram",
    "MRI": "magnetic resonance imaging", "EHR": "electronic health records",
    "AUD": "alcohol use disorder", "SUD": "substance use disorder", "OUD": "opioid use disorder",
}
_SHORT_ABBREV = sorted((k for k in ABBREVIATIONS if len(k) <= 3), key=len, reverse=True)
_LONG_ABBREV = sorted((k for k in ABBREVIATIONS if len(k) > 3), key=len, reverse=True)
ABBREV_CS_RE = re.compile(r"\b(%s)\b" % "|".join(map(re.escape, _SHORT_ABBREV)))
ABBREV_CI_RE = re.compile(r"\b(%s)\b" % "|".join(map(re.escape, _LONG_ABBREV)), re.I)
_ABBREV_LOWER = {k.lower(): v for k, v in ABBREVIATIONS.items() if len(k) > 3}

# Follow-up turns in a conversation ("only those with WGS", "what about asthma?").
FOLLOW_UP_RE = re.compile(
    r"^\s*(?:and|also|only|just|now|but|plus|then|what about|how about|instead"
    r"|of (?:those|these|them)|among (?:those|these|them)|which of (?:those|these|them)"
    r"|narrow|filter|restrict|limit|same)\b", re.I)
SWITCH_RE = re.compile(r"^\s*(?:what about|how about)\b|\binstead\b", re.I)
FOLLOW_WORDS = {"only", "just", "about", "now", "also", "instead", "same", "among", "ones",
                "narrow", "filter", "restrict", "limit", "plus", "then", "but"}

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

# Words ending in "s" that are not plurals ("diabetes", "species"). Words
# ending in -ss, -us or -is ("mass", "mellitus", "fibrosis") are kept too.
KEEP_S = {"diabetes", "herpes", "measles", "mumps", "rabies", "rickets", "scabies",
          "series", "species", "aids", "sars", "news"}

TAG_RE = re.compile(r"<[^>]+>")
TOKEN_RE = re.compile(r"[a-z0-9]+")
HREF_RE = re.compile(r"""href\s*=\s*["']?([^"'\s>]+)""", re.I)
SUBJECT_REPORT_RE = re.compile(r"[._]subject(?:[_-]?consent)?\.var_report\.xml$", re.I)
CONSENT_SUFFIX_RE = re.compile(r"\.c(\d+)$")


def clean_text(text):
    """Plain text from dbGaP's HTML-flavoured strings."""
    text = html.unescape(TAG_RE.sub(" ", text or ""))
    return " ".join(text.split())


def _stem(token):
    if token in KEEP_S:
        return token
    if len(token) > 4 and token.endswith("ies"):
        return token[:-3] + "y"
    if len(token) > 3 and token.endswith("s") and not token.endswith(("ss", "us", "is")):
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


def fmt_count(n):
    """A count for display; small cells are not shown exactly."""
    if 0 < n < SMALL_CELL:
        return "fewer than %d" % SMALL_CELL
    return format(n, ",")


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


def _mesh_terms(concepts):
    """{MeSH id: [preferred term, entry terms...]} from MeSH and MeSH entry-term codings."""
    terms = {}
    for concept in concepts:
        for coding in concept.get("coding") or []:
            system = coding.get("system") or ""
            code = (coding.get("code") or "").strip()
            if system == MESH_SYSTEM and code:
                key = code
            elif system.endswith("MeshEntryTerm") and " entry term" in code:
                key = code.split(" ", 1)[0]
            else:
                continue
            term = clean_text(coding.get("display") or concept.get("text"))
            bucket = terms.setdefault(key, [])
            if term and term not in bucket:
                bucket.append(term)
    return {key: names for key, names in terms.items() if names}


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
        "mesh_terms": {},
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
    study["mesh_terms"] = _mesh_terms(list(resource.get("condition") or []) + list(resource.get("focus") or [])
                                      + list(resource.get("keyword") or []))

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


def fetch_bytes(url, timeout=60):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return resp.read()


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


# ------------------------------------------- data dictionaries (aggregate)

def _as_bytes(data):
    return data.encode("utf-8") if isinstance(data, str) else data


def _int(text):
    try:
        return int(float((text or "").strip()))
    except ValueError:
        return None


def listing_files(page, suffix):
    """File names ending in suffix, in order, from an HTML directory listing."""
    out = []
    for href in HREF_RE.findall(page or ""):
        name = href.rsplit("/", 1)[-1]
        if name.endswith(suffix) and name not in out:
            out.append(name)
    return out


def parse_data_dict(data):
    """A dbGaP data_dict.xml -> [(name, description, unit), ...]."""
    root = ET.fromstring(_as_bytes(data))
    out = []
    for var in root.iter("variable"):
        name = (var.findtext("name") or "").strip()
        description = clean_text(var.findtext("description"))
        unit = (var.findtext("unit") or "").strip()
        if name or description:
            out.append((name, description, unit))
    return out


def parse_sex_counts(data):
    """Male/female counts from a subject-table var_report.xml.

    Variables with a '.cN' suffix describe one consent group; summing the first
    variable of each group counts only subjects in shareable consent groups.
    Without consent-group variables the table-wide total is used.
    """
    root = ET.fromstring(_as_bytes(data))
    first = {}
    for var in root.iter("variable"):
        m = CONSENT_SUFFIX_RE.search(var.get("id") or "")
        group = m.group(1) if m else ""
        if group in first:
            continue
        sex = var.find("total/subject_profile/sex")
        if sex is None:
            continue
        first[group] = (_int(sex.findtext("male")), _int(sex.findtext("female")))
    groups = [v for g, v in sorted(first.items()) if g]
    if not groups and "" in first:
        groups = [first[""]]
    if not groups:
        return None
    return {"male": sum(m or 0 for m, _ in groups), "female": sum(f or 0 for _, f in groups)}


def _empty_dictionary():
    return {"tables": 0, "variables": [], "sex": None}


def study_dictionary(version, fetcher=fetch_bytes, delay=FILE_DELAY, max_tables=MAX_TABLES):
    """Public variable names, descriptions and units plus sex counts for one study version.

    Returns None when the listing could not be read (try again later), and an
    empty record when the study has no phenotype tables.
    """
    phs = version.split(".")[0]
    base = "%s/%s/%s/pheno_variable_summaries/" % (FTP_BASE, phs, version)
    try:
        page = fetcher(base).decode("utf-8", "replace")
    except urllib.error.HTTPError as err:
        return _empty_dictionary() if err.code == 404 else None
    except (urllib.error.URLError, OSError, ValueError):
        return None
    tables = listing_files(page, ".data_dict.xml")[:max_tables]
    reports = [n for n in listing_files(page, ".var_report.xml") if SUBJECT_REPORT_RE.search(n)]
    record = _empty_dictionary()
    record["tables"] = len(tables)
    seen = set()
    for name in tables:
        if delay:
            time.sleep(delay)
        try:
            parsed = parse_data_dict(fetcher(base + name))
        except (urllib.error.URLError, OSError, ValueError, ET.ParseError):
            continue
        for name_, description, unit in parsed:
            key = (name_.lower(), description.lower())
            if key not in seen:
                seen.add(key)
                record["variables"].append([name_, description, unit])
    if reports:
        if delay:
            time.sleep(delay)
        try:
            record["sex"] = parse_sex_counts(fetcher(base + reports[0]))
        except (urllib.error.URLError, OSError, ValueError, ET.ParseError):
            record["sex"] = None
    return record


def add_dictionaries(studies, fetcher=fetch_bytes, delay=FILE_DELAY, cache_dir=None,
                     max_tables=MAX_TABLES, log=None, deadline=None):
    """Attach 'dictionary', 'dictionary_tables' and 'sex' to each study; returns how many got one.

    With cache_dir, each study's record is saved as <version>.json and reused,
    so an interrupted run resumes where it stopped. After deadline (a
    time.time() value) only cached records are read, so a time-limited run
    still finishes and writes its output.
    """
    done = 0
    for n, study in enumerate(studies, 1):
        version = study.get("version")
        if not version:
            continue
        path = os.path.join(cache_dir, version + ".json") if cache_dir else None
        if path and os.path.exists(path):
            with open(path, encoding="utf-8") as f:
                record = json.load(f)
        elif deadline is not None and time.time() > deadline:
            continue
        else:
            record = study_dictionary(version, fetcher, delay, max_tables)
            if path and record is not None:
                with open(path, "w", encoding="utf-8", newline="\n") as f:
                    json.dump(record, f, ensure_ascii=False)
        if record is None:
            if log:
                log("%d/%d %s: listing not readable, skipped" % (n, len(studies), version))
            continue
        study["dictionary"] = record["variables"]
        study["dictionary_tables"] = record["tables"]
        study["sex"] = record["sex"]
        done += 1
        if log:
            log("%d/%d %s: %d tables, %d variables" % (n, len(studies), version,
                                                     record["tables"], len(record["variables"])))
    return done


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


def expand_abbreviations(text):
    """Spelled-out forms of the abbreviations in a question, in order of appearance."""
    hits = [(m.start(), ABBREVIATIONS[m.group(1)]) for m in ABBREV_CS_RE.finditer(text or "")]
    hits += [(m.start(), _ABBREV_LOWER[m.group(1).lower()]) for m in ABBREV_CI_RE.finditer(text or "")]
    return _unique(expansion for _, expansion in sorted(hits))


def query_sex(low):
    female, male = bool(FEMALE_RE.search(low)), bool(MALE_RE.search(low))
    if female and not male:
        return "female"
    if male and not female:
        return "male"
    return None


def parse_query(text):
    """A free-text feasibility question -> search tokens plus structured constraints."""
    low = (text or "").lower()
    ancestry = []
    for pattern, codes in ANCESTRY_RULES:
        if re.search(pattern, low) and set(codes) not in ancestry:
            ancestry.append(set(codes))
    words = tokens(text)
    for extra in tokens(" ".join(expand_abbreviations(text))):
        if extra not in words:
            words.append(extra)
    return {
        "text": text,
        "tokens": words,
        "min_subjects": min_subjects(text),
        "data_types": _tags(low, DATA_TYPE_RULES),
        "designs": _tags(low, QUERY_DESIGN_RULES),
        "ancestry": ancestry,
        "consent": _tags(low, CONSENT_RULES),
        "sex": query_sex(low),
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
        elif n >= SMALL_CELL:
            out.append((0.5, "only %d %s subjects by computed ancestry" % (n, label)))
        elif n > 0:
            out.append((0.5, "fewer than %d %s subjects by computed ancestry" % (SMALL_CELL, label)))
        else:
            out.append((0.0, "no %s subjects by computed ancestry" % label))
    want_sex = query.get("sex")
    if want_sex:
        label = SEX_LABELS[want_sex]
        need = query.get("min_subjects") or ANCESTRY_MIN
        n = (study.get("sex") or {}).get(want_sex)
        if n is None:
            out.append((UNKNOWN, "sex counts not available (%s)" % label))
        elif n >= need:
            out.append((1.0, "%s %s in shareable consent groups" % (format(n, ","), label)))
        elif n > 0:
            out.append((0.5, "only %s %s in shareable consent groups" % (fmt_count(n), label)))
        else:
            out.append((0.0, "no %s in shareable consent groups" % label))
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


def variable_tokens(study):
    """The set of words in a study's data dictionary (variable names and descriptions)."""
    words = set()
    for item in study.get("dictionary") or []:
        words.update(tokens(" ".join(item[:2])))
    return words


class Index:
    """BM25 over study metadata, plus a second BM25 over data dictionaries."""

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

        self.var_docs = [variable_tokens(s) for s in self.studies]
        self.var_lengths = [len(d) for d in self.var_docs]
        filled = [x for x in self.var_lengths if x]
        self.var_avgdl = (sum(filled) / float(len(filled))) if filled else 1.0
        vdf = Counter()
        for doc in self.var_docs:
            vdf.update(doc)
        self.var_idf = {t: math.log(1 + (n - d + 0.5) / (d + 0.5)) for t, d in vdf.items()}

    def bm25(self, i, query_tokens):
        doc, score = self.docs[i], 0.0
        norm = self.k1 * (1 - self.b + self.b * self.lengths[i] / self.avgdl)
        for term in set(query_tokens):
            f = doc.get(term)
            if f:
                score += self.idf[term] * f * (self.k1 + 1) / (f + norm)
        return score

    def var_score(self, i, query_tokens):
        doc = self.var_docs[i]
        if not doc:
            return 0.0
        norm = self.k1 * (1 - VAR_B + VAR_B * self.var_lengths[i] / self.var_avgdl)
        return sum(self.var_idf[t] * (self.k1 + 1) / (1 + norm) for t in set(query_tokens) if t in doc)

    def var_matches(self, i, query_tokens):
        return [t for t in _unique(query_tokens) if t in self.var_docs[i]]


def search(index, text, k=10):
    """The k best studies for a question, each with a score and the reasons behind it."""
    return search_query(index, parse_query(text), k)


def search_query(index, query, k=10):
    """search() for an already parsed (or merged) question."""
    has_constraints = any(query.get(key) for key in CONSTRAINT_KEYS)
    if not query.get("tokens") and not has_constraints:
        return []
    n = len(index.studies)
    raw = [index.bm25(i, query["tokens"]) for i in range(n)]
    top = max(raw) if raw and max(raw) > 0 else 1.0
    var_raw = [index.var_score(i, query["tokens"]) for i in range(n)]
    var_top = max(var_raw) if var_raw and max(var_raw) > 0 else 1.0
    results = []
    for i, study in enumerate(index.studies):
        text_score = raw[i] / top
        var_score = var_raw[i] / var_top
        reqs = requirements(study, query)
        cons = sum(s for s, _ in reqs) / len(reqs) if reqs else None
        if text_score <= 0 and var_score <= 0 and (cons is None or cons < 1.0):
            continue
        score = text_score if cons is None else W_TEXT * text_score + W_CONSTRAINTS * cons
        score += W_VARS * var_score
        score += math.log10((study.get("subjects") or 0) + 1) / 1000.0  # tie-break: bigger studies first
        why = [why for _, why in reqs]
        if var_score > 0:
            why.append("data dictionary mentions: " + ", ".join(index.var_matches(i, query["tokens"])[:6]))
        results.append({
            "accession": study.get("accession"),
            "version": study.get("version"),
            "title": study.get("title"),
            "subjects": study.get("subjects"),
            "url": study.get("url"),
            "score": round(score, 6),
            "why": why,
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


# ------------------------------------------------------------ conversation

def is_follow_up(text):
    return bool(FOLLOW_UP_RE.match(text or ""))


def merge_queries(prev, new, switch=False):
    """Fold a follow-up turn into the running question.

    Plain follow-ups ("only those with WGS") add constraints. "What about ..." or
    "... instead" replaces constraints of the same kind; when such a turn has no
    constraints at all ("what about asthma?") it changes the topic and keeps the
    constraints.
    """
    merged = dict(prev)
    merged["text"] = "%s; %s" % (prev.get("text") or "", new.get("text") or "")
    old_tokens = list(prev.get("tokens") or [])
    fresh = [t for t in new.get("tokens") or [] if t not in FOLLOW_WORDS]
    has_new = any(new.get(key) for key in CONSTRAINT_KEYS)
    if switch and not has_new:
        merged["tokens"] = fresh or old_tokens
        return merged
    merged["tokens"] = old_tokens + [t for t in _unique(fresh) if t not in old_tokens]
    for key in ("min_subjects", "sex"):
        if new.get(key):
            merged[key] = new[key]
    for key in ("data_types", "designs", "consent"):
        if new.get(key):
            merged[key] = set(new[key]) if switch else set(prev.get(key) or ()) | set(new[key])
    if new.get("ancestry"):
        old = [] if switch else list(prev.get("ancestry") or [])
        merged["ancestry"] = old + [c for c in new["ancestry"] if c not in old]
    return merged


class Conversation:
    """A multi-turn feasibility chat: follow-ups refine the previous question."""

    def __init__(self, index, k=10):
        self.index, self.k, self.query = index, k, None

    def reset(self):
        self.query = None

    def ask(self, text):
        new = parse_query(text)
        if self.query is not None and is_follow_up(text):
            self.query = merge_queries(self.query, new, switch=bool(SWITCH_RE.search(text)))
        else:
            self.query = new
        return search_query(self.index, self.query, self.k)


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


# Settings compared by `bench`. Keys are module weights, or k1/b for BM25.
BENCH_CONFIGS = [
    ("baseline", {}),
    ("text only", {"W_TEXT": 1.0, "W_CONSTRAINTS": 0.0}),
    ("no dictionary", {"W_VARS": 0.0}),
    ("dictionary 0.4", {"W_VARS": 0.4}),
    ("text 0.8", {"W_TEXT": 0.8, "W_CONSTRAINTS": 0.2}),
    ("text 0.4", {"W_TEXT": 0.4, "W_CONSTRAINTS": 0.6}),
    ("unknown 0", {"UNKNOWN": 0.0}),
    ("unknown 0.5", {"UNKNOWN": 0.5}),
    ("bm25 k1 0.9 b 0.4", {"k1": 0.9, "b": 0.4}),
    ("bm25 k1 1.5 b 0.9", {"k1": 1.5, "b": 0.9}),
]


def _mrr_recall(ranked, relevance, k):
    relevant = {acc for acc, rel in relevance.items() if rel > 0}
    first = next((rank for rank, acc in enumerate(ranked[:k], 1) if acc in relevant), None)
    found = len(relevant & set(ranked[:k]))
    return (1.0 / first if first else 0.0), (found / float(len(relevant)) if relevant else 0.0)


def bench(studies, queries, qrels, configs=BENCH_CONFIGS, k=10):
    """Mean NDCG@k, MRR and recall@k of each ranking configuration on the same questions."""
    index = Index(studies)
    k1, b = index.k1, index.b
    module = globals()
    out = []
    for name, settings in configs:
        weights = {key: v for key, v in settings.items() if key not in ("k1", "b")}
        saved = {key: module[key] for key in weights}
        index.k1, index.b = settings.get("k1", k1), settings.get("b", b)
        module.update(weights)
        try:
            started = time.perf_counter()
            run = {qid: [r["accession"] for r in search(index, text, k)] for qid, text in queries}
            seconds = time.perf_counter() - started
        finally:
            module.update(saved)
            index.k1, index.b = k1, b
        mean, _ = evaluate(run, qrels, k)
        pairs = [_mrr_recall(run.get(qid, []), rel, k) for qid, rel in qrels.items()]
        out.append({
            "config": name,
            "settings": settings,
            "ndcg": round(mean, 4),
            "mrr": round(sum(p[0] for p in pairs) / len(pairs), 4) if pairs else 0.0,
            "recall": round(sum(p[1] for p in pairs) / len(pairs), 4) if pairs else 0.0,
            "questions": len(qrels),
            "seconds": round(seconds, 2),
        })
    return out


# ------------------------------------------------- census of public dbGaP

# Primary consent codes from most to least open use. NRES: no restrictions.
CONSENT_ORDER = ("NRES", "GRU", "HMB", "DS", "other")


def consent_base(code):
    """'DS-CVD-IRB-NPU' -> 'DS'; 'GRU-COL' -> 'GRU'; anything unrecognised -> 'other'."""
    base = (code or "").upper().split("-")[0].strip()
    return base if base in CONSENT_ORDER[:-1] else "other"


def most_open(consents):
    """The most open primary consent code among a study's consent groups, or None."""
    bases = [consent_base(c) for c in consents or []]
    return min(bases, key=CONSENT_ORDER.index) if bases else None


def _pct(part, whole):
    return "%.1f%%" % (100.0 * part / whole) if whole else "-"


def census(studies):
    """Aggregate counts over harvested studies: consent use, computed ancestry, data types, sex.

    Subjects can be enrolled in more than one study (for example a cohort and
    a TOPMed study built on it), so sums count study enrolments, not people.
    """
    c = {
        "studies": len(studies), "with_subjects": 0, "subjects_total": 0,
        "with_consents": 0, "consent_groups": Counter(), "consent_modifiers": Counter(),
        "studies_by_most_open": Counter(), "studies_for_profit_ok": 0,
        "with_ancestry": 0, "ancestry_total": Counter(), "ancestry_top_level": Counter(),
        "ancestry_by_most_open": {}, "ancestry_for_profit": Counter(),
        "data_types": Counter(), "ancestry_with_wgs": Counter(),
        "with_sex": 0, "sex_total": Counter(),
    }
    for study in studies:
        if study.get("subjects") is not None:
            c["with_subjects"] += 1
            c["subjects_total"] += study["subjects"]
        consents = study.get("consents") or []
        best = most_open(consents)
        profit = any(consent_ok(code, {"NO_NPU"}) and consent_base(code) != "other" for code in consents)
        if consents:
            c["with_consents"] += 1
            c["studies_by_most_open"][best] += 1
            c["studies_for_profit_ok"] += profit
            for code in consents:
                base = consent_base(code)
                parts = (code or "").upper().split("-")[2 if base == "DS" else 1:]  # DS-<disease>-...
                c["consent_groups"][base] += 1
                c["consent_modifiers"].update(set(parts))
        types = set(study.get("data_types") or []) or data_type_tags(study.get("data_types_raw") or [])
        c["data_types"].update(types)
        ancestry = study.get("ancestry") or {}
        if ancestry:
            c["with_ancestry"] += 1
        for code, n in ancestry.items():
            c["ancestry_total"][code] += n
            if not study.get("substudies"):
                c["ancestry_top_level"][code] += n
            bucket = c["ancestry_by_most_open"].setdefault(code, Counter())
            bucket[best or "not reported"] += n
            if profit:
                c["ancestry_for_profit"][code] += n
            if "wgs" in types:
                c["ancestry_with_wgs"][code] += n
        sex = study.get("sex")
        if sex:
            c["with_sex"] += 1
            c["sex_total"].update({key: sex.get(key) or 0 for key in ("male", "female")})
    return json.loads(json.dumps(c))


def census_markdown(c):
    """census() as a short Markdown report."""
    total = sum(c["ancestry_total"].values())
    lines = [
        "# Census of public dbGaP studies",
        "",
        "%s studies; %s report a subject count (%s study enrolments in all), %s report consent groups, "
        "%s report computed ancestry." % (format(c["studies"], ","), format(c["with_subjects"], ","),
                                          format(c["subjects_total"], ","), format(c["with_consents"], ","),
                                          format(c["with_ancestry"], ",")),
        "",
        "## Consent groups by primary code",
        "",
        "| Code | Consent groups | Studies whose most open group is this |",
        "|---|---|---|",
    ]
    for code in CONSENT_ORDER:
        lines.append("| %s | %s | %s |" % (code, format(c["consent_groups"].get(code, 0), ","),
                                          format(c["studies_by_most_open"].get(code, 0), ",")))
    lines += [
        "",
        "%s of %s studies with consent groups (%s) have at least one group without `NPU`, "
        "so for-profit use is possible." % (format(c["studies_for_profit_ok"], ","), format(c["with_consents"], ","),
                                            _pct(c["studies_for_profit_ok"], c["with_consents"])),
        "",
        "## Computed ancestry by how openly the study can be used",
        "",
        "Shares of each group's study enrolments that sit in studies with a GRU (or NRES) consent group, "
        "with at least an HMB group, and with a group that allows for-profit use.",
        "",
        "| Ancestry | Enrolments | Share of all | GRU or NRES | HMB or more open | For-profit allowed |",
        "|---|---|---|---|---|---|",
    ]
    for code, n in sorted(c["ancestry_total"].items(), key=lambda kv: -kv[1]):
        by = c["ancestry_by_most_open"].get(code, {})
        gru = by.get("NRES", 0) + by.get("GRU", 0)
        hmb = gru + by.get("HMB", 0)
        lines.append("| %s | %s | %s | %s | %s | %s |" % (
            code, format(n, ","), _pct(n, total), _pct(gru, n), _pct(hmb, n),
            _pct(c["ancestry_for_profit"].get(code, 0), n)))
    lines += ["", "## Studies by molecular data type", "", "| Type | Studies |", "|---|---|"]
    for tag, n in sorted(c["data_types"].items(), key=lambda kv: -kv[1]):
        lines.append("| %s | %s |" % (tag, format(n, ",")))
    if c["with_sex"]:
        sex = c["sex_total"]
        both = sex.get("male", 0) + sex.get("female", 0)
        lines += ["", "Sex counts from %s subject tables: %s women, %s men (%s women)." % (
            format(c["with_sex"], ","), format(sex.get("female", 0), ","), format(sex.get("male", 0), ","),
            _pct(sex.get("female", 0), both))]
    lines += ["", "Subjects can be enrolled in more than one study, so sums count study enrolments, not people. "
              "Ancestry is dbGaP's computed (GRAF-pop) ancestry for the whole study, not per consent group."]
    return "\n".join(lines) + "\n"


# ---------------------------------------------------- silver development set

NICE_SIZES = (100, 200, 500, 1000, 2000, 5000, 10000, 20000, 50000)
DEV_DATA_TYPES = [("wgs", "whole genome sequencing"), ("wes", "exome sequencing"),
                  ("rnaseq", "RNA-seq"), ("methylation", "DNA methylation"),
                  ("genotypes", "genotyping array")]
DEV_ANCESTRY = [(("AFA",), "African American"), (("EUR",), "European ancestry"),
                (("LAC", "LEN"), "Hispanic or Latino"), (("EAS",), "East Asian")]


def _nice_size(n):
    best = None
    for size in NICE_SIZES:
        if size <= (n or 0):
            best = size
    return best


def _dev_question(term, dtype=None, size=None, ancestry=None):
    if not (dtype or size or ancestry):
        return "Which dbGaP studies cover %s?" % term
    who = "participants"
    if ancestry:
        who = "%s %s" % (ancestry, who)
    if size:
        who = "at least %s %s" % (format(size, ","), who)
    if dtype:
        return "Which dbGaP studies have %s data on %s with %s?" % (dtype, who, term)
    return "Which dbGaP studies have %s with %s?" % (who, term)


def _meets(study, intended):
    """Does a study meet every structured constraint a dev question was built with?"""
    tag = intended.get("data_type")
    if tag and tag not in (study.get("data_types") or []):
        return False
    size = intended.get("min_subjects")
    if size and (study.get("subjects") or 0) < size:
        return False
    codes = intended.get("ancestry")
    if codes and sum((study.get("ancestry") or {}).get(c, 0) for c in codes) < ANCESTRY_MIN:
        return False
    return True


def make_devset(studies, n=100, seed=7, max_group=25):
    """Silver questions and graded judgments built from harvested metadata.

    Each question names one MeSH condition (by its preferred or entry term) and
    may add a data type, a size and an ancestry taken from one study that has
    that condition, so at least one study fully meets it. Every study coded with
    the condition is judged: 2 if it meets all the constraints, else 1. Studies
    without the code count as not relevant, which misses related conditions, so
    use these labels to compare versions of the ranker, not to predict the
    official score.
    """
    rng = random.Random(seed)
    by_code, terms = {}, {}
    for study in studies:
        for code in study.get("mesh") or []:
            by_code.setdefault(code, []).append(study)
        for code, names in (study.get("mesh_terms") or {}).items():
            bucket = terms.setdefault(code, [])
            for name in names:
                if name not in bucket:
                    bucket.append(name)
    codes = sorted(c for c, group in by_code.items() if len(group) <= max_group and terms.get(c))
    rng.shuffle(codes)
    queries, qrels = [], []
    for code in codes:
        if len(queries) >= n:
            break
        group = sorted(by_code[code], key=lambda s: s.get("accession") or "")
        anchor = rng.choice(group)
        names = [t for t in terms[code] if "," not in t] or terms[code]
        term = rng.choice(names)
        if not tokens(term):
            continue
        intended, dtype, size, anc = {}, None, None, None
        types = [(tag, phrase) for tag, phrase in DEV_DATA_TYPES if tag in (anchor.get("data_types") or [])]
        if types and rng.random() < 0.5:
            intended["data_type"], dtype = rng.choice(types)
        nice = _nice_size(anchor.get("subjects"))
        if nice and rng.random() < 0.5:
            intended["min_subjects"] = size = nice
        groups = [(c, p) for c, p in DEV_ANCESTRY
                  if sum((anchor.get("ancestry") or {}).get(x, 0) for x in c) >= ANCESTRY_MIN]
        if groups and rng.random() < 0.35:
            intended["ancestry"], anc = rng.choice(groups)
        qid = "dev%03d" % (len(queries) + 1)
        queries.append({"id": qid, "query": _dev_question(term, dtype, size, anc), "mesh": code, "silver": True})
        for study in group:
            qrels.append((qid, study.get("accession"), 2 if _meets(study, intended) else 1))
    return queries, qrels


# --------------------------------------------------------------------- CLI

def main(argv=None):
    ap = argparse.ArgumentParser(description="Rank public dbGaP studies for cohort-feasibility questions.")
    ap.add_argument("--version", action="version", version=__version__)
    sub = ap.add_subparsers(dest="cmd")

    h = sub.add_parser("harvest", help="download public study metadata from the dbGaP FHIR API")
    h.add_argument("--out", default="studies.jsonl")
    h.add_argument("--delay", type=float, default=PAGE_DELAY)

    d = sub.add_parser("dictionaries", help="add public data dictionaries and sex counts to harvested studies")
    d.add_argument("--studies", default="studies.jsonl")
    d.add_argument("--out", default=None, help="defaults to overwriting --studies")
    d.add_argument("--cache", default="dictionary_cache", help="folder of per-study records, for resuming")
    d.add_argument("--delay", type=float, default=FILE_DELAY)
    d.add_argument("--max-tables", type=int, default=MAX_TABLES)
    d.add_argument("--budget-minutes", type=float, default=0,
                   help="stop downloading after this many minutes and write what is cached (0: no limit)")

    s = sub.add_parser("search", help="answer one question")
    s.add_argument("query")
    s.add_argument("--studies", default="studies.jsonl")
    s.add_argument("-k", type=int, default=10)
    s.add_argument("--json", action="store_true", help="print JSON instead of text")

    c = sub.add_parser("chat", help="answer questions from standard input; follow-ups refine the last one")
    c.add_argument("--studies", default="studies.jsonl")
    c.add_argument("-k", type=int, default=10)

    r = sub.add_parser("run", help="answer a file of questions and write a TREC run")
    r.add_argument("--queries", required=True, help="JSON lines with id and query")
    r.add_argument("--studies", default="studies.jsonl")
    r.add_argument("--out", default="run.txt")
    r.add_argument("-k", type=int, default=10)

    e = sub.add_parser("evaluate", help="mean NDCG@k of a TREC run against TREC qrels")
    e.add_argument("--run", required=True)
    e.add_argument("--qrels", required=True)
    e.add_argument("-k", type=int, default=10)

    v = sub.add_parser("devset", help="build silver questions and qrels from harvested studies")
    v.add_argument("--studies", default="studies.jsonl")
    v.add_argument("-n", type=int, default=100)
    v.add_argument("--seed", type=int, default=7)
    v.add_argument("--max-group", type=int, default=25)
    v.add_argument("--queries-out", default="silver_queries.jsonl")
    v.add_argument("--qrels-out", default="silver_qrels.txt")

    bn = sub.add_parser("bench", help="compare ranking settings on judged questions")
    bn.add_argument("--studies", default="studies.jsonl")
    bn.add_argument("--queries", required=True)
    bn.add_argument("--qrels", required=True)
    bn.add_argument("-k", type=int, default=10)
    bn.add_argument("--out", default=None, help="also write the results as JSON")

    cs = sub.add_parser("census", help="aggregate consent, ancestry and data type counts over all studies")
    cs.add_argument("--studies", default="studies.jsonl")
    cs.add_argument("--out", default="census", help="writes <out>.json and <out>.md")

    args = ap.parse_args(argv)
    log = lambda msg: print(msg, file=sys.stderr)  # noqa: E731
    if args.cmd == "harvest":
        studies = harvest(delay=args.delay, log=log)
        write_studies(studies, args.out)
        print("%d studies -> %s" % (len(studies), args.out))
        return 0
    if args.cmd in ("search", "run", "chat", "dictionaries", "devset", "bench", "census"):
        if not os.path.exists(args.studies):
            log("no %s yet; run 'python cohort_finder.py harvest' first" % args.studies)
            return 1
        studies = read_studies(args.studies)
        if args.cmd == "dictionaries":
            if args.cache:
                os.makedirs(args.cache, exist_ok=True)
            deadline = time.time() + 60 * args.budget_minutes if args.budget_minutes else None
            done = add_dictionaries(studies, delay=args.delay, cache_dir=args.cache,
                                    max_tables=args.max_tables, log=log, deadline=deadline)
            out = args.out or args.studies
            write_studies(studies, out)
            print("%d of %d studies have dictionary records -> %s" % (done, len(studies), out))
            return 0
        if args.cmd == "devset":
            queries, qrels = make_devset(studies, args.n, args.seed, args.max_group)
            with open(args.queries_out, "w", encoding="utf-8", newline="\n") as f:
                for item in queries:
                    f.write(json.dumps(item, ensure_ascii=False) + "\n")
            with open(args.qrels_out, "w", encoding="utf-8", newline="\n") as f:
                for qid, acc, grade in qrels:
                    f.write("%s 0 %s %d\n" % (qid, acc, grade))
            print("%d questions -> %s, %d judgments -> %s" % (len(queries), args.queries_out,
                                                            len(qrels), args.qrels_out))
            return 0
        if args.cmd == "census":
            result = census(studies)
            with open(args.out + ".json", "w", encoding="utf-8", newline="\n") as f:
                json.dump(result, f, indent=1, sort_keys=True)
            text = census_markdown(result)
            with open(args.out + ".md", "w", encoding="utf-8", newline="\n") as f:
                f.write(text)
            print(text)
            return 0
        if args.cmd == "bench":
            rows = bench(studies, read_queries(args.queries), read_qrels(args.qrels), k=args.k)
            print("config\tNDCG@%d\tMRR\trecall@%d\tseconds" % (args.k, args.k))
            for row in rows:
                print("%s\t%.4f\t%.4f\t%.4f\t%.2f" % (row["config"], row["ndcg"], row["mrr"],
                                                     row["recall"], row["seconds"]))
            if args.out:
                with open(args.out, "w", encoding="utf-8", newline="\n") as f:
                    json.dump({"studies": len(studies), "with_dictionary": sum(1 for s in studies if s.get("dictionary")),
                               "k": args.k, "results": rows}, f, indent=1)
            return 0
        index = Index(studies)
        if args.cmd == "search":
            results = search(index, args.query, args.k)
            print(json.dumps(results, indent=2, ensure_ascii=False) if args.json else answer(results, args.query))
            return 0
        if args.cmd == "chat":
            conv = Conversation(index, args.k)
            for line in sys.stdin:
                text = line.strip()
                if not text:
                    continue
                if text.lower() in ("reset", "new", "new question"):
                    conv.reset()
                    print("(new question)\n")
                    continue
                results = conv.ask(text)
                print(answer(results, conv.query["text"]) + "\n")
            return 0
        started = time.perf_counter()
        lines, asked = [], 0
        for qid, text in read_queries(args.queries):
            lines += run_lines(qid, search(index, text, args.k))
            asked += 1
        elapsed = time.perf_counter() - started
        with open(args.out, "w", encoding="utf-8", newline="\n") as f:
            f.write("\n".join(lines) + ("\n" if lines else ""))
        print("%d lines -> %s (%d questions in %.2f s)" % (len(lines), args.out, asked, elapsed))
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
