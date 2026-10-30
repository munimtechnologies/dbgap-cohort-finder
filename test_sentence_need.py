# Tests for sentence_need.py (needs cohort_finder.py, snapshot.py and test_snapshot.py next to it).
# Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
import json
import os
import tempfile
import unittest

import cohort_finder as cf
import sentence_need as sen
import snapshot as sn
from test_snapshot import LUNG_NEED, Corpus

OFFICIAL = ("Find dbGaP studies involving adult participants with lung adenocarcinoma as the primary disease, "
            "where participant-level data include a history of smoking or smoking exposure and whole genomic "
            "sequences.")
OFFICIAL_P5 = OFFICIAL.replace("whole genomic sequences", "whole-genome sequencing data")
SHORT = [LUNG_NEED, "adults with asthma", "Children with asthma with exome sequencing and Hispanic participants",
         "Adults with asthma and smoking history", "COPD patients with BMI measured",
         "Studies of asthma including at least 100 African American participants",
         "At least 1,000 participants with coronary artery disease, LDL cholesterol measured, and genotype data"]
# Short needs and their sentence rewrites that differ only by template words (sentence_needs.jsonl s4, s7).
PAIRS = [("Women aged 40-70 with breast cancer and RNA-seq data",
          "Find dbGaP studies involving women aged 40-70 with breast cancer as the primary disease, where "
          "participant-level data include RNA-seq data."),
         ("Autism spectrum disorder in children with whole genome sequencing of families",
          "Find dbGaP studies involving children with autism spectrum disorder as the primary disease, where "
          "participant-level data include whole genome sequencing of families.")]


class ParseTest(unittest.TestCase):
    def test_official_wording(self):
        for text in (OFFICIAL, OFFICIAL_P5):
            q = sen.parse_need(text)
            self.assertEqual(q["topic"], ["lung", "adenocarcinoma"])
            self.assertIn("wgs", q["data_types"])
            self.assertEqual(q["var_alts"], [[["smoking"], ["smoking", "exposure"]]])
            self.assertEqual(q["var_terms"], [])
            self.assertEqual(q["age"], (18, None))

    def test_short_needs_unchanged(self):
        for text in SHORT:
            self.assertEqual(sen.summary(sen.parse_need(text)), sen.summary(sn.parse_need(text)), text)

    def test_primary_disease(self):
        self.assertEqual(sen.primary_disease(OFFICIAL), "lung adenocarcinoma")
        self.assertEqual(sen.parse_need("Studies whose primary disease is asthma, in adults with genotype data")
                         ["topic"], ["asthma"])
        need = "Participants with a primary diagnosis of sickle cell disease and exome sequencing"
        self.assertEqual(sen.primary_disease(need), "sickle cell disease")
        # snapshot.topic_tokens drops "cell" as a constraint word ("single cell"), as it does for short needs.
        self.assertEqual(sen.parse_need(need)["topic"], ["sickle"])
        self.assertIsNone(sen.primary_disease("adults with asthma"))

    def test_list_items(self):
        types, needs = sen.sentence_var_needs(
            "where participant-level data include HbA1c measurements, LDL cholesterol or total cholesterol, "
            "RNA-seq data and consent allows general research use.")
        self.assertEqual(types, {"rnaseq"})
        self.assertEqual(needs, [[["hba1c"]], [["ldl", "cholesterol"], ["total", "cholesterol"]]])

    def test_data_types(self):
        self.assertIn("wgs", sen.parse_need("adults with whole genomic sequences")["data_types"])
        self.assertIn("wes", sen.parse_need("adults with exomic data")["data_types"])
        self.assertNotIn("wgs", sen.parse_need("adults with genomic data")["data_types"])

    def test_fallback_topic(self):
        q = sen.parse_need("Find dbGaP studies involving adults with asthma, where participant-level data include "
                           "smoking history and genotype data.")
        self.assertEqual(q["topic"], ["asthma"])
        self.assertEqual(q["var_terms"], [["smoking"]])
        self.assertEqual(q["var_alts"], [])

    def test_overlap(self):
        self.assertEqual(sen.overlap(["a", "b"], ["b", "c"]), 0.5)
        self.assertEqual(sen.overlap([], []), 0.0)


class TokenTest(unittest.TestCase):
    def test_template_words_left_out(self):
        template = set(cf.tokens("involving primary disease participant-level"))
        for text in (OFFICIAL, OFFICIAL_P5):
            tokens = set(sen.parse_need(text)["tokens"])
            self.assertTrue(tokens.isdisjoint(template), sorted(tokens & template))
            self.assertTrue({"lung", "adenocarcinoma"} <= tokens)
            self.assertEqual(sen.parse_need(text, strip=False)["tokens"], sn.parse_need(text)["tokens"])

    def test_disease_in_topic_kept(self):
        q = sen.parse_need("Find dbGaP studies involving at least 1,000 participants with coronary artery disease "
                           "as the primary disease, where participant-level data include LDL cholesterol "
                           "measurements and genotype data.")
        self.assertIn(cf.tokens("disease")[0], q["tokens"])
        self.assertNotIn(cf.tokens("primary")[0], q["tokens"])

    def test_short_tokens_unchanged(self):
        # LUNG_NEED says "as the primary disease", so it is the one short need whose tokens change.
        for text in SHORT[1:]:
            self.assertEqual(sen.parse_need(text)["tokens"], sn.parse_need(text)["tokens"], text)
        self.assertNotIn(cf.tokens("primary")[0], sen.parse_need(LUNG_NEED)["tokens"])

    def test_pairs_same_tokens(self):
        for short, sentence in PAIRS:
            self.assertEqual(sen.token_set(sen.parse_need(short)), sen.token_set(sen.parse_need(sentence)))
            self.assertNotEqual(sen.token_set(sen.parse_need(short)),
                                sen.token_set(sen.parse_need(sentence, strip=False)))


class RequirementTest(Corpus):
    def test_patch_is_noop_without_alternatives(self):
        self.assertIs(sn.requirements, sen.requirements)
        for text in SHORT:
            q = sn.parse_need(text)
            for i in range(len(self.index.studies)):
                self.assertEqual(sn.requirements(self.index, i, q), sen.requirements.base(self.index, i, q))

    def test_alternatives(self):
        q = sen.parse_need(OFFICIAL)
        reqs = {s["accession"]: sn.requirements(self.index, i, q) for i, s in enumerate(self.index.studies)}
        self.assertIn((1.0, "data dictionary has smoking"), reqs["phs000100.v1.p1"])
        self.assertIn((0.0, "data dictionary has no smoking variables"), reqs["phs000200.v1.p1"])
        self.assertIn((cf.UNKNOWN, "no data dictionary in the snapshot (smoking)"), reqs["phs000300.v1.p1"])


class RankTest(Corpus):
    def test_official_top(self):
        for tier in (None, sen.TIER):
            for strip in (True, False):
                ranked = [r["accession"] for r in sen.rank(self.index, sen.parse_need(OFFICIAL, strip), tier=tier)]
                self.assertEqual(ranked[0], "phs000100.v1.p1")

    def test_old_parse_matches_gated(self):
        q = sn.parse_need(LUNG_NEED)
        self.assertEqual([r["accession"] for r in sen.rank(self.index, q)],
                         [r["accession"] for r in sn.rank(self.index, q, sn.K, True, True, True)])

    def test_cli(self):
        queries, qrels = sn.make_devset(self.studies, n=5, seed=1)
        with tempfile.TemporaryDirectory() as d:
            dev, needs, out = (os.path.join(d, n) for n in ("dev.json", "needs.jsonl", "report.json"))
            with open(dev, "w", encoding="utf-8") as f:
                json.dump({"queries": queries, "qrels": qrels}, f)
            with open(needs, "w", encoding="utf-8") as f:
                f.write(json.dumps({"info_need_id": "ex1", "info_need": LUNG_NEED}) + "\n")
                f.write(json.dumps({"info_need_id": "s1", "info_need": OFFICIAL, "pair": "ex1"}) + "\n")
            sen.main(["--studies", self.paths[0], "--variables", self.paths[1], "--values", self.paths[2],
                      "--devset", dev, "--needs", needs, "--out", out])
            with open(out, encoding="utf-8") as f:
                report = json.load(f)
        self.assertEqual(report["silver"]["questions"], len(queries))
        self.assertEqual(report["silver"]["tokens_changed"], [])
        self.assertEqual([n["id"] for n in report["needs"]], ["ex1", "s1"])
        self.assertFalse(report["needs"][0]["parse_changed"])
        self.assertTrue(report["needs"][1]["parse_changed"])
        self.assertTrue(report["needs"][1]["tokens_changed"])
        self.assertEqual(report["pairs"][0]["short"], "ex1")
        self.assertIn("new_gated", report["pairs"][0]["overlap@10"])
        self.assertIn("same_tokens", report["pairs"][0])


if __name__ == "__main__":
    unittest.main()
