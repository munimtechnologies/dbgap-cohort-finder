"""Tests for abbrev_fix. Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license."""

import unittest

import abbrev_fix as af
import snapshot as sn


class ShortFormTest(unittest.TestCase):
    def test_is_short_form(self):
        for word in ("HIV", "NETs", "MIS-C", "NF1", "SCLC", "COPD"):
            self.assertTrue(af.is_short_form(word), word)
        for word in ("Andersen-Tawil", "dbGaP", "Find", "A", "hiv", "Crohn"):
            self.assertFalse(af.is_short_form(word), word)


class LongFormTest(unittest.TestCase):
    def test_best_long_form(self):
        self.assertEqual(af.best_long_form("SCLC", "patients with small cell lung cancer"), "small cell lung cancer")
        self.assertEqual(af.best_long_form("NETs", "gastroenteropancreatic neuroendocrine tumors"),
                         "neuroendocrine tumors")
        self.assertEqual(af.best_long_form("NF1", "children with neurofibromatosis type 1"),
                         "neurofibromatosis type 1")
        self.assertIsNone(af.best_long_form("XQZ", "lung cancer"))

    def test_normalize(self):
        self.assertEqual(af.normalize("Huntington's  Disease"), "huntington disease")
        self.assertEqual(af.normalize("Crohn’s disease,"), "crohn disease")

    def test_definitions(self):
        text = "Adults with small cell lung cancer (SCLC) were enrolled. Huntington's disease (HD) cases too."
        self.assertEqual(af.definitions(text), [("SCLC", "small cell lung cancer"), ("HD", "huntington disease")])

    def test_definitions_skip_non_abbreviations(self):
        self.assertEqual(af.definitions("A cohort (n) of adults (Boston) and data (2010)."), [])

    def test_mine_and_long_form(self):
        defs = af.mine(["small cell lung cancer (SCLC)", "Small cell lung cancer (SCLC) samples",
                        "small cell lung carcinoma (SCLC)", "hypereosinophilic syndrome (HES)"])
        self.assertEqual(af.long_form(defs, "SCLC"), ("small cell lung cancer", 2))
        self.assertEqual(af.long_form(defs, "Hes"), ("hypereosinophilic syndrome", 1))
        self.assertEqual(af.long_form(defs, "AATD"), (None, 0))
        self.assertEqual(af.long_form(None, "AATD"), (None, 0))


class DetectTest(unittest.TestCase):
    def test_table_abbreviation(self):
        found = af.disease_abbreviations("HIV studies with methylation data")
        self.assertEqual([f["abbrev"] for f in found], ["HIV"])
        self.assertEqual(found[0]["table"], "human immunodeficiency virus")
        self.assertIsNone(found[0]["mined"])

    def test_constraints_and_measurements_skipped(self):
        self.assertEqual(af.disease_abbreviations(
            "Find dbGaP studies of lung cancer with WGS and RNA-seq data, GRU consent, HMB"), [])
        found = af.disease_abbreviations("COPD studies with BMI measured")
        self.assertEqual([f["abbrev"] for f in found], ["COPD"])

    def test_unknown_with_mined(self):
        defs = af.mine(["small cell lung cancer (SCLC)"])
        found = af.disease_abbreviations("SCLC studies with RNA-seq data", defs)
        self.assertEqual(found, [{"abbrev": "SCLC", "table": None, "mined": "small cell lung cancer",
                                  "mined_count": 1}])

    def test_rewrite(self):
        self.assertEqual(af.rewrite("SCLC studies with RNA-seq data (SCLC-1 aside)",
                                    {"SCLC": "small cell lung cancer"}),
                         "small cell lung cancer studies with RNA-seq data (SCLC-1 aside)")


class AlternativesTest(unittest.TestCase):
    STUDY = {"focus": ["hiv"], "conditions": ["hiv"], "title": "An HIV study", "description": ""}

    def test_best_of_topics_and_restore(self):
        original = sn.disease_requirement
        long_topic = ["human", "immunodeficiency", "virus"]
        before = sn.disease_requirement(self.STUDY, long_topic)[0]
        with af.topic_alternatives([["hiv"], []]):
            self.assertIsNot(sn.disease_requirement, original)
            self.assertEqual(sn.disease_requirement(self.STUDY, long_topic)[0], 1.0)
        self.assertIs(sn.disease_requirement, original)
        self.assertLess(before, 0.6)

    def test_restore_after_error(self):
        original = sn.disease_requirement
        with self.assertRaises(RuntimeError):
            with af.topic_alternatives([["hiv"]]):
                raise RuntimeError("boom")
        self.assertIs(sn.disease_requirement, original)


class FakeIndex:
    def __init__(self, studies):
        self.studies = studies


SENSE_STUDIES = [
    {"title": "Overall survival (OS) after surgery", "description":
     "Overall survival (OS) in adults. Overall survival (OS) again.", "conditions": ["Breast Neoplasms"],
     "focus": ["Breast Neoplasms"]},
    {"title": "Osteosarcoma (OS) cohort", "description": "", "conditions": ["Osteosarcoma"],
     "focus": ["Osteosarcoma"]},
]


class SenseTest(unittest.TestCase):
    """0.1.1: prefer a mined long form that the snapshot stores as a disease term."""

    def test_term_names(self):
        self.assertEqual(af.term_names("Anemia, Sickle Cell"), ["anemia, sickle cell", "sickle cell anemia"])
        self.assertEqual(af.term_names("Lyme Disease"), ["lyme disease"])
        self.assertEqual(af.term_names(""), [])

    def test_disease_terms(self):
        terms = af.disease_terms([{"conditions": ["Carcinoma, Small Cell"], "focus": ["Lyme Disease"]}, {}])
        self.assertEqual(terms, {"carcinoma, small cell", "small cell carcinoma", "lyme disease"})

    def test_sense_long_form(self):
        defs = af.mine(["overall survival (OS)", "Overall survival (OS)", "overall survival (OS)",
                        "osteosarcoma (OS)"])
        self.assertEqual(af.long_form(defs, "OS"), ("overall survival", 3))
        self.assertEqual(af.sense_long_form(defs, "OS", {"osteosarcoma"}), ("osteosarcoma", 1))
        self.assertEqual(af.sense_long_form(defs, "OS", set()), ("overall survival", 3))
        self.assertEqual(af.sense_long_form(defs, "XYZ", {"osteosarcoma"}), (None, 0))

    def test_plan_sense_and_old_behaviour(self):
        text = "OS studies with WGS data"
        old_text, _, old_found = af.plan(FakeIndex(SENSE_STUDIES), text, sense=False)
        self.assertEqual(old_text, "overall survival studies with WGS data")
        self.assertEqual(old_found[0]["chosen"], "overall survival")
        new_text, alts, found = af.plan(FakeIndex(SENSE_STUDIES), text)
        self.assertEqual(new_text, "osteosarcoma studies with WGS data")
        self.assertEqual(found[0]["chosen"], "osteosarcoma")
        self.assertEqual(found[0]["mined"], "overall survival")
        self.assertTrue(alts)
        self.assertEqual(af.plan(FakeIndex(SENSE_STUDIES), "Breast cancer studies with WGS data")[1:], ([], []))


if __name__ == "__main__":
    unittest.main()
