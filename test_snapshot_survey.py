# Tests for snapshot_survey.py on a tiny synthetic snapshot.
# Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
import gzip
import io
import json
import os
import tarfile
import tempfile
import unittest

import snapshot_survey as ss


def study(acc, consent, pops, subjects, uses, structure="top"):
    return {"_meta": {"accession": acc, "gapobj_type": "study"},
            "fields": {"accession": acc, "name": "Study " + acc, "description": "About " + acc,
                       "consent_abbrev": consent, "all_population": pops, "study_subject_count": subjects,
                       "sample_use": uses, "study_structure_type": structure,
                       "parent_study_accession": "Not Applicable", "main_disease": "Asthma"}}


# Shaped like the real pht000001.v2.p1.var_summary.xml of phs000001 (AREDS).
VAR_SUMMARY = b"""<?xml version="1.0" encoding="UTF-8"?>
<?xml-stylesheet type="text/xsl" href="varreports_v3.xsl"?>
<data_table name="main" dataset_id="pht000001.v1" study_id="phs000001.v1" participant_set="1">
 <variable id="phv00000010.v1.p1" var_name="AGE" calculated_type="integer" units="years" reported_type="integer">
  <description>Age at enrollment</description>
  <total><subject_profile><sex><male>500</male><female>700</female></sex></subject_profile>
   <stats><stat n="1200" nulls="0" mean="50" sd="9" median="52" min="21" max="85"/></stats></total>
 </variable>
 <variable id="phv00000010.v1.p1.c1" var_name="AGE" calculated_type="integer" units="years">
  <description>Age at enrollment</description>
  <total><stats><stat n="100" nulls="0" median="35" min="30" max="40"/></stats></total>
 </variable>
 <variable id="phv00000011.v1.p1" var_name="DIABAGE" calculated_type="integer" units="years">
  <description>AGE DOCTOR FIRST SAID HAD DIABETES</description>
  <total><stats><stat n="300" nulls="900" median="60" min="9" max="77"/></stats></total>
 </variable>
 <variable id="phv00000014.v1.p1" var_name="STAGE" calculated_type="integer">
  <description>Tumor stage</description>
  <total><stats><stat n="300" nulls="0" median="2" min="1" max="4"/></stats></total>
 </variable>
 <variable id="phv00000012.v1.p1" var_name="RACE" calculated_type="enum_integer">
  <description>Self-reported race</description>
  <total><stats><stat n="1200" nulls="0"/>
   <enum code="1" count="800"/><enum code="2" count="350"/><enum code="3" count="50"/></stats></total>
 </variable>
 <variable id="phv00000013.v1.p1.c1" var_name="HISP" calculated_type="enum_integer">
  <description>Hispanic ethnicity</description>
  <total><stats><stat n="600" nulls="0"/><enum code="1" count="90"/><enum code="0" count="510"/></stats></total>
 </variable>
 <variable id="phv00000013.v1.p1.c2" var_name="HISP" calculated_type="enum_integer">
  <description>Hispanic ethnicity</description>
  <total><stats><stat n="600" nulls="0"/><enum code="1" count="30"/><enum code="0" count="570"/></stats></total>
 </variable>
</data_table>
"""

DATA_DICT = b"""<?xml version="1.0" encoding="UTF-8"?>
<data_table id="pht000001.v1" study_id="phs000001.v1" participant_set="1">
 <variable id="phv00000010.v1"><name>AGE</name><description>Age at enrollment</description><type>integer</type>
  <unit>years</unit></variable>
 <variable id="phv00000012.v1"><name>RACE</name><description>Self-reported race</description>
  <type>enumerated integer</type><value code="1">White</value><value code="2">Black or African American</value>
  <value code="3">American Indian or Alaska Native</value></variable>
 <variable id="phv00000013.v1"><name>HISP</name><description>Hispanic ethnicity</description>
  <type>enumerated integer</type><value code="0">Not Hispanic or Latino</value>
  <value code="1">Hispanic or Latino</value></variable>
</data_table>
"""

FILES = {
    "dbgap/README.txt": b"snapshot readme",
    "dbgap/studies/phs000001.v1.p1/phs000001.v1.p1.json":
        study("phs000001.v1.p1", ["GRU", "DS-ASTHMA-IRB"], ["European", "African American"], "1200", ["WGS"]),
    "dbgap/studies/phs000001.v1.p1/phs000001.v1.p1.html.gz": b"\x1f\x8b junk",
    "dbgap/studies/phs000002.v1.p1/phs000002.v1.p1.json":
        study("phs000002.v1.p1", "HMB-IRB-PUB", "African American", "300", ["WXS", "SNP Array"]),
    "dbgap/studies/phs000003.v1.p1/phs000003.v1.p1.json":
        study("phs000003.v1.p1", "GRU", [], "50", "Not Provided", structure="child"),
    "dbgap/studies/phs000001.v1.p1/variables/phv00000001.v1.p1.json":
        {"fields": {"accession": "phv00000001.v1.p1", "name": "SMOKE", "description": "Ever smoked",
                    "dataset_accession": "pht000001.v1.p1", "variable_data_type": "enum_integer"}},
    "dbgap/studies/phs000001.v1.p1/pheno_datasets/pht000001.v1.p1.json":
        {"fields": {"accession": "pht000001.v1.p1", "dataset_male_count": "500", "dataset_female_count": "700"}},
    "dbgap/studies/phs000001.v1.p1/pheno_datasets/pht000001.v1.p1.data_dict.xml": DATA_DICT,
    "dbgap/studies/phs000001.v1.p1/pheno_datasets/pht000001.v1.p1.var_summary.xml": VAR_SUMMARY,
    "dbgap/studies/phs000002.v1.p1/pheno_datasets/pht000002.v1.p1.data_dict.xml": b"<data_table/>",
    "dbgap/studies/phs000002.v1.p1/pheno_datasets/pht000002.v1.p1.var_summary.xml": b"<data_table><broken",
    "dbgap/studies/phs000002.v1.p1/variables/phv00000002.v1.p1.json": b"{not json",
    "dbgap/collections.json": {"x": 1},
}


def make_tar(path):
    with tarfile.open(path, "w:gz") as tar:
        for name, body in FILES.items():
            data = body if isinstance(body, bytes) else json.dumps(body).encode("utf-8")
            info = tarfile.TarInfo(name)
            info.size = len(data)
            tar.addfile(info, io.BytesIO(data))


def summary(name, desc, lo, hi, n=100, units=None, median=None):
    return {"name": name, "desc": desc, "units": units, "n": n, "min": lo, "max": hi, "median": median}


class HelperTest(unittest.TestCase):
    def test_empty_and_lists(self):
        self.assertTrue(ss.is_empty("Not Applicable"))
        self.assertTrue(ss.is_empty(["", "Not Provided"]))
        self.assertFalse(ss.is_empty("0"))
        self.assertEqual(ss.as_list("GRU"), ["GRU"])
        self.assertEqual(ss.as_list(["GRU", "", "HMB"]), ["GRU", "HMB"])
        self.assertEqual(ss.as_int("1,200"), 1200)
        self.assertIsNone(ss.as_int("many"))

    def test_consent_class(self):
        self.assertEqual(ss.consent_class("GRU-NPU"), "GRU")
        self.assertEqual(ss.consent_class("DS-CVD-IRB"), "DS")
        self.assertEqual(ss.consent_class("HMB"), "HMB")
        self.assertEqual(ss.consent_class("GRUX"), "other")

    def test_classify(self):
        self.assertEqual(ss.classify("dbgap/studies/phs1.v1.p1/phs1.v1.p1.json"), ("study", "phs1.v1.p1"))
        self.assertEqual(ss.classify("dbgap/studies/phs1.v1.p1/variables/phv9.v1.p1.json"),
                         ("variable", "phs1.v1.p1"))
        self.assertEqual(ss.classify("dbgap/studies/phs1.v1.p1/pheno_datasets/pht1.v1.p1.var_summary.xml"),
                         ("var_summary", "phs1.v1.p1"))
        self.assertEqual(ss.classify("dbgap/studies/phs1.v1.p1/pheno_datasets/pht1.v1.p1.data_dict.xml"),
                         ("data_dict", "phs1.v1.p1"))
        self.assertEqual(ss.classify("dbgap/studies/phs1.v1.p1/pheno_datasets/pht1.v1.p1.html.gz"), (None, None))
        self.assertEqual(ss.classify("dbgap/studies/phs1.v1.p1/phs1.v1.p1.html.gz"), (None, None))
        self.assertEqual(ss.classify("dbgap/collections/phs5.json"), (None, None))

    def test_phv_key(self):
        self.assertEqual(ss.phv_key("phv00054122.v1.p1.c2"), "phv00054122")
        self.assertEqual(ss.phv_key("phv00054122.v1"), "phv00054122")
        self.assertIsNone(ss.phv_key("x"))

    def test_years_factor(self):
        self.assertEqual(ss.years_factor("years"), 1.0)
        self.assertEqual(ss.years_factor(None), 1.0)
        self.assertEqual(ss.years_factor("Months"), 1 / 12.0)
        self.assertEqual(ss.years_factor("decades"), 10.0)
        self.assertIsNone(ss.years_factor("mg/dL"))

    def test_pop_group(self):
        self.assertEqual(ss.pop_group("Black or African American"), "black")
        self.assertEqual(ss.pop_group("White, Caucasian"), "white")
        self.assertEqual(ss.pop_group("American Indian or Alaska Native"), "aian")
        self.assertEqual(ss.pop_group("Native Hawaiian or Other Pacific Islander"), "nhpi")
        self.assertEqual(ss.pop_group("Hispanic or Latino"), "hispanic")
        self.assertIsNone(ss.pop_group("Not Hispanic or Latino"))
        self.assertIsNone(ss.pop_group("Non-Hispanic"))
        self.assertEqual(ss.pop_group("Chinese American"), "asian")
        self.assertEqual(ss.pop_group("More than one race"), "multiple")
        self.assertEqual(ss.pop_group("Other"), "other")

    def test_pop_group_combined_codes(self):
        # 0.2.0 dropped these: the "not Hispanic" part hid the race.
        self.assertEqual(ss.pop_group("Non-Hispanic White"), "white")
        self.assertEqual(ss.pop_group("Black, not Hispanic or Latino"), "black")
        self.assertEqual(ss.pop_group("Non-Hispanic Asian"), "asian")
        self.assertEqual(ss.pop_group("White, not of Hispanic origin"), "white")
        self.assertEqual(ss.pop_group("Caucasian non-Hispanic"), "white")
        # 0.2.0 counted the old OMB "Asian or Pacific Islander" category as nhpi.
        self.assertEqual(ss.pop_group("Asian or Pacific Islander"), "asian")
        self.assertEqual(ss.pop_group("Asian/Pacific Islander"), "asian")
        self.assertEqual(ss.pop_group("Pacific Islander/Asian"), "asian")

    def test_pop_group_unknown_not_counted(self):
        # 0.2.1 counted these as "other" (seen in the 2026-10-15 audit sample).
        for label in ("Unknown", "Missing", "data not available", "Refused", "Prefer not to answer",
                      "Choose not to answer", "Not reported", "Don't know", "-9", "99", "N/A"):
            self.assertIsNone(ss.pop_group(label), label)
        self.assertEqual(ss.pop_group("Hispanic, race unknown"), "hispanic")
        self.assertIsNone(ss.pop_group("Non-Hispanic, race unknown"))

    def test_pop_group_negated_race(self):
        # 0.2.1 counted "Not Caucasian" as white (seen in phs000255).
        self.assertEqual(ss.pop_group("Not Caucasian"), "other")
        self.assertEqual(ss.pop_group("Non-white"), "other")
        self.assertEqual(ss.pop_group("Other than White"), "other")
        self.assertEqual(ss.pop_group("Non-white Hispanic"), "hispanic")

    def test_pop_group_abbreviations_and_mena(self):
        # The coded labels of phs000621 (ncirace): Hisp, Orient, Haw, Nat Amer, Filip.
        self.assertEqual(ss.pop_group("Hisp"), "hispanic")
        self.assertEqual(ss.pop_group("Orient"), "asian")
        self.assertEqual(ss.pop_group("Oriental"), "asian")
        self.assertEqual(ss.pop_group("Filip"), "asian")
        self.assertEqual(ss.pop_group("Haw"), "nhpi")
        self.assertEqual(ss.pop_group("Nat Amer"), "aian")
        self.assertEqual(ss.pop_group("Afr Am"), "black")
        self.assertEqual(ss.pop_group("Latin American"), "hispanic")
        self.assertEqual(ss.pop_group("Middle Eastern or North African"), "mena")
        self.assertEqual(ss.pop_group("North African"), "mena")
        self.assertEqual(ss.pop_group("African"), "black")

    def test_pop_group_hispanic_yes_no(self):
        self.assertEqual(ss.pop_group("Yes", hispanic_var=True), "hispanic")
        self.assertIsNone(ss.pop_group("No", hispanic_var=True))
        self.assertIsNone(ss.pop_group("Not Hispanic or Latino", hispanic_var=True))
        self.assertEqual(ss.pop_group("Hispanic or Latino", hispanic_var=True), "hispanic")
        self.assertEqual(ss.pop_group("Native American", hispanic_var=True), "aian")
        self.assertEqual(ss.pop_group("Yes"), "other")
        self.assertTrue(ss.is_hispanic_var("HISPANIC", "Hispanic or Latino origin?"))
        self.assertFalse(ss.is_hispanic_var("RACE", "Self-reported race"))

    def test_parse_var_summary(self):
        parsed = ss.parse_var_summary(VAR_SUMMARY)
        age = parsed["phv00000010"]
        self.assertEqual((age["n"], age["min"], age["max"], age["male"], age["female"]), (1200, 21.0, 85.0, 500, 700))
        self.assertEqual(parsed["phv00000012"]["enums"], {"1": 800, "2": 350, "3": 50})
        hisp = parsed["phv00000013"]  # consent groups only, so summed
        self.assertEqual((hisp["n"], hisp["enums"]), (1200, {"1": 120, "0": 1080}))

    def test_parse_data_dict(self):
        parsed = ss.parse_data_dict(DATA_DICT)
        self.assertEqual(parsed["phv00000012"]["values"]["2"], "Black or African American")
        self.assertEqual(parsed["phv00000010"]["units"], "years")
        self.assertEqual(parsed["phv00000010"]["values"], {})

    def test_age_candidates(self):
        parsed = ss.parse_var_summary(VAR_SUMMARY)
        self.assertIsNotNone(ss.age_candidate(parsed["phv00000010"]))
        self.assertIsNone(ss.age_candidate(parsed["phv00000011"]))  # age at diagnosis
        self.assertIsNone(ss.age_candidate(parsed["phv00000014"]))  # STAGE
        months = {"name": "AGE_MO", "desc": "Age in months at visit", "units": "months", "n": 50,
                  "min": 6.0, "max": 30.0, "median": 12.0}
        c = ss.age_candidate(months)
        self.assertEqual((c["min"], c["max"], c["median"], c["preferred"]), (0.5, 2.5, 1.0, True))
        a = {"name": "A", "desc": "age", "units": "years", "n": 10, "min": 1, "max": 2, "preferred": True}
        b = {"name": "B", "desc": "age 2", "units": "years", "n": 99, "min": 1, "max": 2, "preferred": False}
        self.assertIs(ss.best_age([a, b]), a)

    def test_age_counts_and_scores_skipped(self):
        # Wrong 0.2.1 picks in the 2026-10-15 run (phs000519, phs001591, phs001471, phs000462, phs000219,
        # phs004044, phs001310, phs001466).
        for desc in ("Number of incidences of non-severe sunburn at Age greater than or equal to 20 years",
                     "How many of these people are under age 6?",
                     "Of the persons living in your household how many are under 18 years of age?",
                     "Number of study visits for which we have Age of this participant",
                     "AEMSS (Age and Education corrected MOANS scaled score)",
                     "Calculation estimating liver fibrosis based on age, AST, ALT, and platelets",
                     "Age of 1st infection",
                     "Subject age at initiation of hydroxyurea"):
            self.assertIsNone(ss.age_candidate(summary("X", desc, 0.0, 50.0, n=500)), desc)
        self.assertIsNotNone(ss.age_candidate(summary("AGE", "Age at the time of sample collection", 20.0, 80.0)))

    def test_age_in_decades(self):
        c = ss.age_candidate(summary("aged", "Age in decades (age/10)", 2.0, 8.9, n=200, median=6.0))
        self.assertEqual((c["min"], c["max"], c["median"]), (20.0, 89.0, 60.0))

    def test_group_counts(self):
        groups, raw = ss.group_counts({"1": 10, "2": 5, "9": 1}, {"1": "White", "2": "Not Hispanic"})
        self.assertEqual(groups, {"white": 10})  # the unlabeled code 9 is not counted (0.2.2)
        self.assertEqual(raw, {"White": 10, "Not Hispanic": 5, "9": 1})
        groups, _ = ss.group_counts({"1": 12, "0": 88}, {"1": "Yes", "0": "No"}, hispanic_var=True)
        self.assertEqual(groups, {"hispanic": 12})
        groups, _ = ss.group_counts({"1": 50, "2": 7, "3": 4}, {"1": "Caucasian", "2": "Not Caucasian", "3": "Missing"})
        self.assertEqual(groups, {"white": 50, "other": 7})

    def test_race_by_study_combined(self):
        with tempfile.TemporaryDirectory() as tmp:
            s = ss.Survey(os.path.join(tmp, "out"), os.path.join(tmp, "data"))
            s.race_sums[("phs9", "phv1")] = {"dataset": "pht9.v1.p1", "name": "RACETH", "desc": "Race/ethnicity",
                                             "enums": {"1": 60, "2": 30, "3": 10}}
            s.race_labels[("phs9", "phv1")] = {"1": "Non-Hispanic White", "2": "Non-Hispanic Black", "3": "Hispanic"}
            s.race_sums[("phs9", "phv2")] = {"dataset": "pht9.v1.p1", "name": "HISPANIC",
                                             "desc": "Hispanic or Latino ethnicity", "enums": {"1": 12, "0": 88}}
            s.race_labels[("phs9", "phv2")] = {"1": "Yes", "0": "No"}
            best = s.race_by_study()
            s.var_out.close()
            s.values_out.close()
        self.assertEqual(best["phs9"]["race"]["groups"], {"white": 60, "black": 30, "hispanic": 10})
        self.assertEqual(best["phs9"]["race"]["var"], "pht9.v1.p1 RACETH")
        self.assertEqual(best["phs9"]["ethnicity"]["groups"], {"hispanic": 12})
        rows = ss.label_audit(best)
        self.assertEqual(rows[0], {"label": "No", "group": ss.NOT_COUNTED, "variables": 1, "subjects": 88})
        self.assertIn({"label": "Non-Hispanic White", "group": "white", "variables": 1, "subjects": 60}, rows)


class SurveyTest(unittest.TestCase):
    def test_end_to_end(self):
        with tempfile.TemporaryDirectory() as tmp:
            tar_path, out, data = (os.path.join(tmp, n) for n in ("s.tar.gz", "out", "data"))
            make_tar(tar_path)
            cov = ss.survey(tar_path, out, data, log=lambda *a: None)
            self.assertEqual(cov["study"]["objects"], 3)
            self.assertEqual(cov["variable"]["objects"], 1)
            self.assertEqual(cov["dataset"]["objects"], 1)
            self.assertEqual(cov["xml_sidecars"], {"data_dict": 2, "var_summary": 1})
            self.assertEqual(cov["unreadable_total"], 2)
            self.assertNotIn("parent_study_accession", cov["study"]["fields"])
            with open(os.path.join(out, "README.txt"), "rb") as f:
                self.assertEqual(f.read(), b"snapshot readme")
            with open(os.path.join(out, "studies.jsonl"), encoding="utf-8") as f:
                studies = [json.loads(l) for l in f]
            self.assertEqual([s["accession"] for s in studies],
                             ["phs000001.v1.p1", "phs000002.v1.p1", "phs000003.v1.p1"])
            s1 = studies[0]
            self.assertEqual(s1["variables_in_snapshot"], 1)
            self.assertEqual((s1["max_dataset_male"], s1["max_dataset_female"]), (500, 700))
            self.assertEqual((s1["age_min"], s1["age_max"], s1["age_median"]), (21.0, 85.0, 52.0))
            self.assertEqual(s1["age_var"], "pht000001.v1.p1 AGE")
            self.assertEqual(s1["race_counts"], {"white": 800, "black": 350, "aian": 50})
            self.assertEqual(s1["ethnicity_counts"], {"hispanic": 120})
            self.assertEqual(s1["ethnicity_var"], "pht000001.v1.p1 HISP")
            self.assertNotIn("age_min", studies[1])
            with gzip.open(os.path.join(data, "variables.jsonl.gz"), "rt", encoding="utf-8") as f:
                rows = [json.loads(l) for l in f]
            self.assertEqual(rows, [{"study": "phs000001.v1.p1", "phv": "phv00000001.v1.p1",
                                     "dataset": "pht000001.v1.p1", "name": "SMOKE", "desc": "Ever smoked",
                                     "type": "enum_integer", "units": None}])
            with gzip.open(os.path.join(data, "var_values.jsonl.gz"), "rt", encoding="utf-8") as f:
                values = [json.loads(l) for l in f]
            self.assertEqual([v["name"] for v in values], ["RACE", "HISP"])
            self.assertEqual(values[1]["values"], ["Not Hispanic or Latino", "Hispanic or Latino"])
            with open(os.path.join(out, "age_candidates.jsonl"), encoding="utf-8") as f:
                cands = [json.loads(l) for l in f]
            self.assertEqual([(c["study"], c["name"], c["picked"]) for c in cands],
                             [("phs000001.v1.p1", "AGE", True)])
            with open(os.path.join(out, "race_labels.jsonl"), encoding="utf-8") as f:
                labels = [json.loads(l) for l in f]
            self.assertEqual([(r["label"], r["group"], r["subjects"]) for r in labels],
                             [("Not Hispanic or Latino", ss.NOT_COUNTED, 1080), ("White", "white", 800),
                              ("Black or African American", "black", 350), ("Hispanic or Latino", "hispanic", 120),
                              ("American Indian or Alaska Native", "aian", 50)])
            with open(os.path.join(out, "census.json"), encoding="utf-8") as f:
                c = json.load(f)
            self.assertEqual((c["studies"], c["top_level_studies"]), (3, 2))
            self.assertEqual(c["consent_classes"], {"GRU": 1, "DS": 1, "HMB": 1})
            self.assertEqual(c["populations"][0],
                             {"population": "African American", "studies": 2, "subjects_summed": 1500})
            self.assertEqual(c["population_x_consent"]["African American"], {"DS": 1, "GRU": 1, "HMB": 1})
            self.assertEqual(c["sample_use"]["WGS"], 1)
            self.assertEqual(c["age_bands"], {"adults only (min >= 18)": 1, "not reported": 1})
            race = c["race_ethnicity"]
            self.assertEqual(race["top_level_studies_with_race_variable"], 1)
            self.assertEqual([g["group"] for g in race["groups"]], ["white", "black", "hispanic", "aian"])
            self.assertEqual(race["groups"][2], {"group": "hispanic", "subjects_summed": 120,
                                                 "studies_with_any": 1, "studies_with_100_plus": 1})
            self.assertEqual(race["groups"][3]["studies_with_100_plus"], 0)
            self.assertTrue(os.path.exists(os.path.join(out, "samples", "study-2.json")))
            with open(os.path.join(out, "census.md"), encoding="utf-8") as f:
                md = f.read()
            self.assertIn("| African American | 2 | 1500 |", md)
            self.assertIn("| white | 800 | 1 | 1 |", md)
            self.assertIn("| adults only (min >= 18) | 1 |", md)


if __name__ == "__main__":
    unittest.main()
