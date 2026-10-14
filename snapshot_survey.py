#!/usr/bin/env python3
"""snapshot_survey: one streaming pass over the NLM SPARK dbGaP challenge snapshot.

The SPARK dbGaP tasks (NIH/NLM, 2026-27) are judged only on a fixed public
snapshot, https://ftp.ncbi.nlm.nih.gov/dbgap/NLM_Challenge/dbgap.tar.gz
(about 1.5 GB packed, 6.3 GB unpacked). This script reads the archive as a
stream, without unpacking it, and writes:

  /out/README.txt            the snapshot's own README
  /out/field_coverage.json   per object type: how many objects fill each field
  /out/samples/              the first two JSON objects of each type, verbatim
  /out/studies.jsonl         one compact record per study (the retrieval units), with the
                             participants' age range and race/ethnicity counts read from
                             the aggregate variable summaries (var_summary.xml)
  /out/census.json, .md      studies and subjects by consent class, population, data type,
                             age band and reported race/ethnicity
  /out/age_candidates.jsonl  every variable considered as "participant age", with the pick
  <data>/variables.jsonl.gz  every variable: study, dataset, name, description, type, units
  <data>/var_values.jsonl.gz coded values of every enumerated variable (data_dict.xml)

Standard library only. Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
"""

import argparse
import gzip
import json
import os
import re
import sys
import tarfile
import time
import urllib.request
import xml.etree.ElementTree as ET
from collections import Counter, defaultdict

__version__ = "0.2.0"

SNAPSHOT_URL = "https://ftp.ncbi.nlm.nih.gov/dbgap/NLM_Challenge/dbgap.tar.gz"
USER_AGENT = "dbgap-cohort-finder-survey/%s (+https://github.com/munimtechnologies/dbgap-cohort-finder)" % __version__
EMPTY = {"", "not applicable", "not provided", "none", "null", "n/a"}
KINDS = {"pheno_datasets": "dataset", "variables": "variable", "genotype_datasets": "genotype",
         "documents": "document", "analyses": "analysis"}
SAMPLES_PER_KIND = 2
TOP = 25
MAX_VALUES = 40   # coded values kept per variable
MIN_AGE_N = 10    # an age variable needs at least this many non-null values

# Study fields copied into studies.jsonl (whichever exist).
STUDY_KEEP = ("accession", "name", "description", "main_disease", "study_disease_mesh_name", "disease_mesh_name",
              "all_population", "consent_abbrev", "consent_label", "has_gru_consent", "irb_required",
              "study_subject_count", "study_sample_count", "study_sequenced_sample_count", "sample_use",
              "study_type", "study_design", "study_structure_type", "study_is_root_study", "parent_study_accession",
              "genotype_platform", "study_has_sra", "study_variable_count", "study_dataset_count", "primary_ic",
              "study_gsr_mode", "study_release_date", "is_member_of_collection")
NAME_KEYS = ("name", "variable_name", "var_name")
DESC_KEYS = ("description", "variable_description", "desc")

# "Participant age" variables. Ages of other events or other people are skipped.
AGE_RE = re.compile(r"\bages?\b", re.I)
AGE_NAME_RE = re.compile(r"^age|_age$|_age_", re.I)  # not "...age$": STAGE, DOSAGE
AGE_SKIP_RE = re.compile(
    r"onset|diagnos|\bdx\b|said|told|menarche|menopaus|death|died|deceased|smok|cigar|quit|stopp|start|began|begin"
    r"|mother|father|parent|sibling|brother|sister|spouse|partner|offspring|child(?:ren)?'?s age|gestation"
    r"|\blast\b|surgery|group|categor|range|interval|first (?:use|time|drink|diagnos|symptom|period|pregnan)|when",
    re.I)
AGE_PREFER_RE = re.compile(
    r"enrol|baseline|visit|exam|consent|interview|collect|recruit|entry|randomi|draw|blood|sample|participant"
    r"|current|at (?:the )?time|in years", re.I)

# Race and ethnicity variables, and the coarse groups their coded labels map to.
RACE_RE = re.compile(r"\brace\b|racial|ethnic|ancestr", re.I)
RACE_SKIP_RE = re.compile(r"mother|father|parent|spouse|partner|grand|interviewer|child'?s|baby|infant'?s", re.I)
NOT_HISPANIC_RE = re.compile(r"\bnon[- ]?hispanic|not hispanic|not latin", re.I)
POP_GROUPS = [
    ("nhpi", re.compile(r"hawaiian|pacific island", re.I)),
    ("aian", re.compile(r"american indian|alaska|native american|first nation", re.I)),
    ("hispanic", re.compile(r"hispanic|latin[oax]|mexican|puerto ric|cuban|dominican|central american", re.I)),
    ("black", re.compile(r"black|african", re.I)),
    ("white", re.compile(r"white|caucasian|european", re.I)),
    ("asian", re.compile(r"asian|chinese|japanese|korean|filipino|vietnamese|\bindian\b|pakistan|bangladesh", re.I)),
    ("multiple", re.compile(r"more than one|multi|two or more|mixed|biracial", re.I)),
]
GROUP_ORDER = ("white", "black", "hispanic", "asian", "aian", "nhpi", "multiple", "other")


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
    return [str(value).strip()]


def as_int(value):
    for v in as_list(value):
        m = re.match(r"^\d+$", v.replace(",", ""))
        if m:
            return int(m.group(0))
    return None


def as_num(value):
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def first(fields, keys):
    for k in keys:
        if not is_empty(fields.get(k)):
            v = fields[k]
            return " | ".join(as_list(v)) if isinstance(v, list) else str(v).strip()
    return None


def consent_class(abbrev):
    """'GRU-NPU' -> 'GRU'; 'DS-CVD-IRB' -> 'DS'; 'HMB-IRB-PUB' -> 'HMB'."""
    a = abbrev.upper().strip()
    for cls in ("GRU", "HMB", "DS", "NRUP", "COL"):
        if a == cls or a.startswith(cls + "-") or a.startswith(cls + " "):
            return cls
    return "other"


def classify(name):
    """Member path -> (kind, study accession) or (None, None)."""
    parts = name.split("/")
    if "studies" not in parts:
        return None, None
    i = parts.index("studies")
    rest = parts[i + 1:]
    if len(rest) == 2 and rest[1] == rest[0] + ".json":
        return "study", rest[0]
    if len(rest) == 3 and rest[1] == "pheno_datasets" and rest[2].endswith(".data_dict.xml"):
        return "data_dict", rest[0]
    if len(rest) == 3 and rest[1] == "pheno_datasets" and rest[2].endswith(".var_summary.xml"):
        return "var_summary", rest[0]
    if len(rest) == 3 and rest[2].endswith(".json") and rest[1] in KINDS:
        return KINDS[rest[1]], rest[0]
    return None, None


def phv_key(var_id):
    """'phv00054122.v1.p1.c2' -> 'phv00054122' (one key per variable across versions and consent groups)."""
    m = re.match(r"(phv\d+)", var_id or "")
    return m.group(1) if m else None


def _text(elem, path):
    return " ".join((elem.findtext(path) or "").split())


# ---------------------------------------------------------------- XML sidecars

def parse_data_dict(data):
    """data_dict.xml -> {phv key: {"id", "name", "desc", "type", "units", "values": {code: label}}}."""
    root = ET.fromstring(data)
    out = {}
    for var in root.iter("variable"):
        key = phv_key(var.get("id"))
        if not key:
            continue
        values = {}
        for v in var.findall("value"):
            if v.get("code") is not None:
                values[v.get("code").strip()] = " ".join((v.text or "").split())
        out[key] = {"id": var.get("id"), "name": _text(var, "name"), "desc": _text(var, "description"),
                    "type": _text(var, "type"), "units": _text(var, "unit") or None, "values": values}
    return out


def _summary(var):
    s = {"id": var.get("id"), "name": var.get("var_name") or "", "desc": _text(var, "description"),
         "type": var.get("calculated_type") or var.get("reported_type") or "", "units": var.get("units"),
         "n": 0, "min": None, "max": None, "median": None, "male": 0, "female": 0, "enums": {}}
    total = var.find("total")
    if total is None:
        return s
    sex = total.find("subject_profile/sex")
    if sex is not None:
        s["male"] = as_int(sex.findtext("male")) or 0
        s["female"] = as_int(sex.findtext("female")) or 0
    stat = total.find("stats/stat")
    if stat is not None:
        s["n"] = as_int(stat.get("n")) or 0
        for k in ("min", "max", "median"):
            s[k] = as_num(stat.get(k))
    for e in total.findall("stats/enum"):
        code = e.get("code")
        code = (code if code is not None else (e.text or "")).strip()
        s["enums"][code] = s["enums"].get(code, 0) + (as_int(e.get("count")) or 0)
    return s


def _merge(parts):
    """Sum per-consent-group summaries when a file has no all-consent total."""
    s = dict(parts[0], n=0, male=0, female=0, median=None, enums={})
    mins = [p["min"] for p in parts if p["min"] is not None]
    maxs = [p["max"] for p in parts if p["max"] is not None]
    s["min"], s["max"] = (min(mins) if mins else None), (max(maxs) if maxs else None)
    for p in parts:
        for k in ("n", "male", "female"):
            s[k] += p[k]
        for code, count in p["enums"].items():
            s["enums"][code] = s["enums"].get(code, 0) + count
    return s


def parse_var_summary(data):
    """var_summary.xml -> {phv key: summary of all consent groups together}.

    Each variable appears once for all subjects (id 'phv...p1') and once per
    consent group ('phv...p1.c1'); the all-subject entry is used when present."""
    root = ET.fromstring(data)
    base, groups = {}, defaultdict(list)
    for var in root.iter("variable"):
        vid = var.get("id") or ""
        key = phv_key(vid)
        if not key:
            continue
        if re.search(r"\.c\d+$", vid):
            groups[key].append(_summary(var))
        else:
            base[key] = _summary(var)
    for key, parts in groups.items():
        if key not in base:
            base[key] = _merge(parts)
    return base


def years_factor(units):
    u = (units or "").strip().lower()
    if not u or "year" in u or u in ("y", "yr", "yrs"):
        return 1.0
    if "month" in u:
        return 1 / 12.0
    if "week" in u:
        return 1 / 52.18
    if "day" in u:
        return 1 / 365.25
    return None


def age_candidate(s):
    """A var_summary entry -> participant-age candidate dict, or None."""
    name, desc = s.get("name") or "", s.get("desc") or ""
    if not (AGE_RE.search(desc) or (not desc and AGE_NAME_RE.search(name))):
        return None
    if AGE_SKIP_RE.search(desc) or AGE_SKIP_RE.search(name):
        return None
    factor = years_factor(s.get("units"))
    if factor is None or s.get("min") is None or s.get("max") is None or (s.get("n") or 0) < MIN_AGE_N:
        return None
    lo, hi = s["min"] * factor, s["max"] * factor
    if lo < 0 or hi > 120 or lo > hi:
        return None
    plain = desc.strip().lower().rstrip(".") in ("age", "age in years", "age (years)", "age, years", "participant age")
    return {"name": name, "desc": desc, "units": s.get("units"), "n": s["n"], "min": round(lo, 2),
            "max": round(hi, 2), "median": (round(s["median"] * factor, 2) if s.get("median") is not None else None),
            "preferred": bool(plain or AGE_PREFER_RE.search(desc))}


def best_age(cands):
    if not cands:
        return None
    return max(cands, key=lambda c: (c["preferred"], c["n"], -len(c["name"])))


def is_race_var(name, desc):
    text = "%s %s" % (name or "", desc or "")
    return bool(RACE_RE.search(text)) and not RACE_SKIP_RE.search(desc or "")


def pop_group(label):
    """A coded race/ethnicity label -> coarse group ('white', 'black', ...), or None for 'not Hispanic'."""
    if NOT_HISPANIC_RE.search(label or ""):
        return None
    for group, regex in POP_GROUPS:
        if regex.search(label or ""):
            return group
    return "other"


def group_counts(enums, labels):
    """Enum counts {code: n} plus code labels -> ({group: n}, {label: n})."""
    groups, raw = Counter(), Counter()
    for code, count in enums.items():
        label = labels.get(code) or code
        raw[label] += count
        g = pop_group(label)
        if g:
            groups[g] += count
    return dict(groups), dict(raw)


# ---------------------------------------------------------------------- survey

class Survey:
    def __init__(self, out_dir, data_dir):
        self.out, self.data = out_dir, data_dir
        self.coverage = defaultdict(Counter)
        self.objects = Counter()
        self.samples = Counter()
        self.studies = {}
        self.var_keys = Counter()
        self.var_by_study = Counter()
        self.dataset_sex = defaultdict(lambda: [0, 0])
        self.age_cands = defaultdict(list)
        self.race_sums = {}     # (study, phv key) -> var_summary entry of a race/ethnicity variable
        self.race_labels = {}   # (study, phv key) -> {code: label} from data_dict.xml
        self.bad = []
        os.makedirs(os.path.join(out_dir, "samples"), exist_ok=True)
        os.makedirs(data_dir, exist_ok=True)
        self.var_out = gzip.open(os.path.join(data_dir, "variables.jsonl.gz"), "wt", encoding="utf-8")
        self.values_out = gzip.open(os.path.join(data_dir, "var_values.jsonl.gz"), "wt", encoding="utf-8")

    def add_xml(self, kind, study, name, raw):
        dataset = os.path.basename(name).split(".data_dict")[0].split(".var_summary")[0]
        try:
            parsed = (parse_data_dict if kind == "data_dict" else parse_var_summary)(raw)
        except ET.ParseError as err:
            self.bad.append("%s (%s)" % (name, err))
            return
        self.objects[kind] += 1
        if self.samples[kind] < 1 and len(raw) < 200000:
            self.samples[kind] += 1
            with open(os.path.join(self.out, "samples", "%s-1.xml" % kind), "wb") as f:
                f.write(raw)
        if kind == "data_dict":
            for key, v in parsed.items():
                if v["values"]:
                    labels = list(v["values"].values())[:MAX_VALUES]
                    self.values_out.write(json.dumps({"study": study, "dataset": dataset, "phv": v["id"],
                                                      "name": v["name"], "values": labels},
                                                     ensure_ascii=False) + "\n")
                    if is_race_var(v["name"], v["desc"]):
                        self.race_labels[(study, key)] = v["values"]
            return
        for key, s in parsed.items():
            cand = age_candidate(s)
            if cand:
                cand["dataset"] = dataset
                self.age_cands[study].append(cand)
            if s["enums"] and is_race_var(s["name"], s["desc"]):
                self.race_sums[(study, key)] = dict(s, dataset=dataset)

    def add(self, kind, study, name, raw):
        if kind in ("data_dict", "var_summary"):
            return self.add_xml(kind, study, name, raw)
        try:
            obj = json.loads(raw.decode("utf-8", errors="replace"))
        except ValueError as err:
            self.bad.append("%s (%s)" % (name, err))
            return
        fields = obj.get("fields") or {}
        self.objects[kind] += 1
        cov = self.coverage[kind]
        for k, v in fields.items():
            if not is_empty(v):
                cov[k] += 1
        if self.samples[kind] < SAMPLES_PER_KIND:
            self.samples[kind] += 1
            with open(os.path.join(self.out, "samples", "%s-%d.json" % (kind, self.samples[kind])), "w",
                      encoding="utf-8") as f:
                json.dump(obj, f, indent=1, ensure_ascii=False)
        if kind == "study":
            rec = {k: fields[k] for k in STUDY_KEEP if k in fields and not is_empty(fields[k])}
            rec["accession"] = fields.get("accession") or study
            if isinstance(rec.get("description"), str):
                rec["description"] = rec["description"][:4000]
            self.studies[rec["accession"]] = rec
        elif kind == "variable":
            for k in NAME_KEYS + DESC_KEYS:
                if k in fields:
                    self.var_keys[k] += 1
            self.var_by_study[study] += 1
            row = {"study": study, "phv": fields.get("accession") or obj.get("_meta", {}).get("accession"),
                   "dataset": fields.get("dataset_accession"), "name": first(fields, NAME_KEYS),
                   "desc": first(fields, DESC_KEYS), "type": first(fields, ("variable_data_type",)),
                   "units": first(fields, ("variable_units",))}
            self.var_out.write(json.dumps(row, ensure_ascii=False) + "\n")
        elif kind == "dataset":
            sex = self.dataset_sex[study]
            sex[0] = max(sex[0], as_int(fields.get("dataset_male_count")) or 0)
            sex[1] = max(sex[1], as_int(fields.get("dataset_female_count")) or 0)

    def race_by_study(self):
        """Per study, the race/ethnicity variable with the most subjects, as coarse group counts."""
        best = {}
        for (study, key), s in self.race_sums.items():
            groups, raw = group_counts(s["enums"], self.race_labels.get((study, key), {}))
            real = {g: n for g, n in groups.items() if g != "other"}
            if not real:
                continue
            total = sum(s["enums"].values())
            ethnicity_only = set(real) == {"hispanic"}
            slot = "ethnicity" if ethnicity_only else "race"
            pick = {"var": "%s %s" % (s["dataset"], s["name"]), "desc": s["desc"][:200], "subjects": total,
                    "groups": groups, "labels": dict(Counter(raw).most_common(12))}
            cur = best.setdefault(study, {}).get(slot)
            if cur is None or total > cur["subjects"]:
                best[study][slot] = pick
        return best

    def finish(self):
        self.var_out.close()
        self.values_out.close()
        coverage = {kind: {"objects": self.objects[kind],
                           "fields": dict(sorted(c.items(), key=lambda kv: (-kv[1], kv[0])))}
                    for kind, c in sorted(self.coverage.items())}
        coverage["xml_sidecars"] = {"data_dict": self.objects["data_dict"], "var_summary": self.objects["var_summary"]}
        coverage["variable_name_keys"] = dict(self.var_keys)
        coverage["unreadable"] = self.bad[:50]
        coverage["unreadable_total"] = len(self.bad)
        with open(os.path.join(self.out, "field_coverage.json"), "w", encoding="utf-8") as f:
            json.dump(coverage, f, indent=1, ensure_ascii=False)
        race = self.race_by_study()
        with open(os.path.join(self.out, "age_candidates.jsonl"), "w", encoding="utf-8") as f:
            for acc in sorted(self.age_cands):
                pick = best_age(self.age_cands[acc])
                for c in self.age_cands[acc]:
                    f.write(json.dumps(dict(c, study=acc, picked=c is pick), ensure_ascii=False) + "\n")
        with open(os.path.join(self.out, "studies.jsonl"), "w", encoding="utf-8") as f:
            for acc in sorted(self.studies):
                rec = self.studies[acc]
                rec["variables_in_snapshot"] = self.var_by_study.get(acc, 0)
                male, female = self.dataset_sex.get(acc, (0, 0))
                if male or female:
                    rec["max_dataset_male"], rec["max_dataset_female"] = male, female
                age = best_age(self.age_cands.get(acc))
                if age:
                    rec["age_min"], rec["age_max"], rec["age_median"] = age["min"], age["max"], age["median"]
                    rec["age_var"] = "%s %s" % (age["dataset"], age["name"])
                for slot, pick in race.get(acc, {}).items():
                    rec[slot + "_counts"] = pick["groups"]
                    rec[slot + "_var"] = pick["var"]
                f.write(json.dumps(rec, ensure_ascii=False) + "\n")
        census = build_census(list(self.studies.values()))
        census["objects"] = dict(self.objects)
        with open(os.path.join(self.out, "census.json"), "w", encoding="utf-8") as f:
            json.dump(census, f, indent=1, ensure_ascii=False)
        with open(os.path.join(self.out, "census.md"), "w", encoding="utf-8") as f:
            f.write(census_markdown(census))
        return coverage


def top_level(s):
    return str(s.get("study_structure_type", "")).lower() != "child" and \
        str(s.get("study_is_root_study", "yes")).lower() != "no"


def age_band(s):
    lo, hi = s.get("age_min"), s.get("age_max")
    if lo is None or hi is None:
        return "not reported"
    if hi < 18:
        return "children only (max < 18)"
    if lo >= 65:
        return "65+ only"
    if lo >= 18:
        return "adults only (min >= 18)"
    return "children and adults"


def build_census(studies):
    """Studies and subjects by consent class, population, data type, age band and race/ethnicity.
    Top-level studies only, so parent and child studies are not counted twice."""
    tops = [s for s in studies if top_level(s)]
    consent, population, sample_use = Counter(), Counter(), Counter()
    subjects_by_pop = Counter()
    cross = defaultdict(Counter)
    ages = Counter()
    race_total, race_studies, race_100 = Counter(), Counter(), Counter()
    with_race = 0
    no_pop = 0
    for s in tops:
        classes = sorted({consent_class(a) for a in as_list(s.get("consent_abbrev"))}) or ["not stated"]
        pops = sorted(set(as_list(s.get("all_population")))) or []
        if not pops:
            no_pop += 1
        subjects = as_int(s.get("study_subject_count")) or 0
        for c in classes:
            consent[c] += 1
        for p in pops:
            population[p] += 1
            subjects_by_pop[p] += subjects
            for c in classes:
                cross[p][c] += 1
        for u in set(as_list(s.get("sample_use"))):
            sample_use[u] += 1
        ages[age_band(s)] += 1
        groups = dict(s.get("race_counts") or {})
        eth = s.get("ethnicity_counts") or {}
        if "hispanic" not in groups and eth.get("hispanic"):
            groups["hispanic"] = eth["hispanic"]
        if groups:
            with_race += 1
            for g, n in groups.items():
                race_total[g] += n
                if n > 0:
                    race_studies[g] += 1
                if n >= 100:
                    race_100[g] += 1
    top_pops = [p for p, _ in population.most_common(TOP)]
    return {
        "studies": len(studies),
        "top_level_studies": len(tops),
        "top_level_without_population": no_pop,
        "consent_classes": dict(consent.most_common()),
        "populations": [{"population": p, "studies": population[p], "subjects_summed": subjects_by_pop[p]}
                        for p in top_pops],
        "population_x_consent": {p: dict(cross[p]) for p in top_pops},
        "sample_use": dict(sample_use.most_common(TOP)),
        "age_bands": dict(ages.most_common()),
        "race_ethnicity": {
            "top_level_studies_with_race_variable": with_race,
            "groups": [{"group": g, "subjects_summed": race_total[g], "studies_with_any": race_studies[g],
                        "studies_with_100_plus": race_100[g]} for g in GROUP_ORDER if g in race_total],
        },
        "notes": ["Counts are studies, not people: one person can be enrolled in several studies.",
                  "all_population is a study-level label and many studies leave it empty.",
                  "Race/ethnicity counts come from each study's largest coded race or ethnicity variable in the "
                  "public aggregate summaries (var_summary.xml), mapped to coarse groups from the coded labels; "
                  "they are self-reported or study-assigned categories, not genetic ancestry.",
                  "Age bands use the participant-age variable with the most values (baseline/visit ages preferred).",
                  "A study with several consent groups counts once in each of its classes.",
                  "Subject sums use top-level studies only."],
    }


def census_markdown(c):
    out = ["# Public dbGaP snapshot census (NLM SPARK challenge corpus)", "",
           "- Studies: %d (%d top-level; %d of those name no population)"
           % (c["studies"], c["top_level_studies"], c["top_level_without_population"]), "",
           "## Consent classes (top-level studies)", "", "| Class | Studies |", "|---|---:|"]
    out += ["| %s | %d |" % kv for kv in c["consent_classes"].items()]
    classes = list(c["consent_classes"])
    out += ["", "## Populations x consent class (top-level studies)", "",
            "| Population | Studies | Subjects (summed) | " + " | ".join(classes) + " |",
            "|---|---:|---:|" + "---:|" * len(classes)]
    for p in c["populations"]:
        row = c["population_x_consent"].get(p["population"], {})
        out.append("| %s | %d | %d | %s |" % (p["population"], p["studies"], p["subjects_summed"],
                                              " | ".join(str(row.get(k, 0)) for k in classes)))
    out += ["", "## Molecular data types (sample_use)", "", "| Type | Studies |", "|---|---:|"]
    out += ["| %s | %d |" % kv for kv in c["sample_use"].items()]
    out += ["", "## Participant age (top-level studies)", "", "| Age band | Studies |", "|---|---:|"]
    out += ["| %s | %d |" % kv for kv in c.get("age_bands", {}).items()]
    race = c.get("race_ethnicity") or {}
    out += ["", "## Reported race/ethnicity (top-level studies with a coded race or ethnicity variable: %d)"
            % race.get("top_level_studies_with_race_variable", 0), "",
            "| Group | Subjects (summed) | Studies with any | Studies with 100+ |", "|---|---:|---:|---:|"]
    out += ["| %s | %d | %d | %d |" % (g["group"], g["subjects_summed"], g["studies_with_any"],
                                       g["studies_with_100_plus"]) for g in race.get("groups", [])]
    out += ["", "## Notes", ""] + ["- " + n for n in c["notes"]]
    out += ["", "Made by MV2 of Munim, Inc. with AI agents. CC BY 4.0. Source: NCBI dbGaP public metadata.", ""]
    return "\n".join(out)


def download(url, path, log=print):
    if os.path.exists(path) and os.path.getsize(path) > 0:
        log("using cached %s (%d bytes)" % (path, os.path.getsize(path)))
        return path
    tmp = path + ".part"
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=120) as resp, open(tmp, "wb") as f:
        done, mark = 0, time.time()
        while True:
            chunk = resp.read(1 << 20)
            if not chunk:
                break
            f.write(chunk)
            done += len(chunk)
            if time.time() - mark > 60:
                log("[%s] %d MB" % (time.strftime("%H:%M:%S"), done >> 20))
                mark = time.time()
    os.replace(tmp, path)
    return path


def survey(tar_path, out_dir, data_dir, log=print):
    s = Survey(out_dir, data_dir)
    n = 0
    with tarfile.open(tar_path, mode="r|gz") as tar:
        for member in tar:
            if not member.isfile():
                continue
            name = member.name
            if name.endswith("README.txt") and name.count("/") <= 1:
                with open(os.path.join(out_dir, "README.txt"), "wb") as f:
                    f.write(tar.extractfile(member).read())
                continue
            kind, study = classify(name)
            if kind is None:
                continue
            s.add(kind, study, name, tar.extractfile(member).read())
            n += 1
            if n % 100000 == 0:
                log("[%s] %d objects" % (time.strftime("%H:%M:%S"), n))
    cov = s.finish()
    log("objects: %s; unreadable: %d" % (dict(s.objects), len(s.bad)))
    return cov


def main(argv=None):
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--tar", help="a local dbgap.tar.gz (skips the download)")
    ap.add_argument("--data", default="/data")
    ap.add_argument("--out", default="/out")
    args = ap.parse_args(argv)
    tar_path = args.tar or download(SNAPSHOT_URL, os.path.join(args.data, "dbgap.tar.gz"))
    survey(tar_path, args.out, args.data)
    return 0


if __name__ == "__main__":
    sys.exit(main())
