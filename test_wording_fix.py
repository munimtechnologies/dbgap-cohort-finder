"""Tests for wording_fix (standard library only; no snapshot data needed)."""

import unittest

import sentence_need as sen
import wording_fix as wf

OFFICIAL = ("Find dbGaP studies involving adult participants with lung adenocarcinoma as the primary disease, "
            "where participant-level data include a history of smoking or smoking exposure and whole genomic "
            "sequences.")


class ContractionTest(unittest.TestCase):
    def test_removed(self):
        self.assertEqual(wf.CONTRACTION_RE.sub(" ", "I'm looking").split(), ["looking"])
        self.assertEqual(wf.CONTRACTION_RE.sub(" ", "I’m looking, we're done").split(), ["looking,", "done"])
        self.assertEqual(wf.CONTRACTION_RE.sub(" ", "Crohn's disease").split(), ["Crohn's", "disease"])

    def test_chat_topic(self):
        text = "I'm looking for asthma cohorts in adults that have WGS data."
        self.assertIn("m", sen.parse_need(text)["topic"])  # the stray letter wording_check found
        q = wf.parse_need(text)
        self.assertNotIn("m", q["topic"])
        self.assertIn("asthma", q["topic"])


class TokensTest(unittest.TestCase):
    def test_constraint_words(self):
        self.assertEqual(wf.constraint_words({}), set(wf.REQUEST))
        self.assertNotIn("genome", wf.constraint_words({"data_types": set()}))
        self.assertIn("genome", wf.constraint_words({"data_types": {"wgs"}}))
        self.assertIn("adult", wf.constraint_words({"age": (18, None)}))

    def test_kept_words(self):
        q = {"topic": ["cell"], "var_terms": [["family", "history"], "bmi"],
             "var_alts": [[["smoking"], ["smoking", "exposure"]]]}
        self.assertEqual(wf.kept_words(q), {"cell", "family", "history", "bmi", "smoking", "exposure"})

    def test_silver_need(self):
        base = sen.parse_need("Studies of asthma in adults and with whole genome sequencing")
        self.assertIn("genome", base["tokens"])
        q = wf.parse_need("Studies of asthma in adults and with whole genome sequencing")
        self.assertIn("asthma", q["tokens"])
        self.assertNotIn("genome", q["tokens"])
        self.assertNotIn("sequencing", q["tokens"])

    def test_official_need(self):
        q = wf.parse_need(OFFICIAL)
        for word in ("lung", "adenocarcinoma", "smoking"):
            self.assertIn(word, q["tokens"])
        for word in ("whole", "genomic"):
            self.assertNotIn(word, q["tokens"])

    def test_nothing_left_keeps_tokens(self):
        text = "Studies in adults with whole genome sequencing"
        self.assertTrue(wf.parse_need(text)["tokens"])

    def test_parse_unchanged(self):
        for text in (OFFICIAL, "Studies of asthma in adults and with whole genome sequencing"):
            a, b = sen.parse_need(text), wf.parse_need(text)
            for key in ("data_types", "age", "topic", "var_terms", "var_alts"):
                self.assertEqual(a.get(key), b.get(key), key)


if __name__ == "__main__":
    unittest.main()
