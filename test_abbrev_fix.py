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


if __name__ == "__main__":
    unittest.main()
