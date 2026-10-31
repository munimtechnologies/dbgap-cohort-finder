"""Tests for wording_check (standard library only; no snapshot data needed)."""

import unittest

import wording_check as wc

SILVER = ["Studies of asthma in adults and with whole genome sequencing",
          "Studies of sickle cell disease consented for general research use",
          "Studies of breast cancer including at least 100 African American participants and with RNA-seq",
          "Studies of type 2 diabetes and obesity in children",
          "Studies of lung adenocarcinoma with DNA methylation data and with exome sequencing"]


class DecomposeTest(unittest.TestCase):
    def test_keys(self):
        self.assertEqual(wc.decompose(SILVER[0]), ("asthma", ["adults", "wgs"]))
        self.assertEqual(wc.decompose(SILVER[1]), ("sickle cell disease", ["gru"]))
        self.assertEqual(wc.decompose(SILVER[2]), ("breast cancer", [("race", "African American"), "rnaseq"]))

    def test_disease_with_and(self):
        self.assertEqual(wc.decompose(SILVER[3]), ("type 2 diabetes and obesity", ["children"]))

    def test_not_silver(self):
        self.assertIsNone(wc.decompose("Find dbGaP studies of asthma"))
        self.assertIsNone(wc.decompose("Studies of asthma"))

    def test_short_round_trip(self):
        for text in SILVER:
            disease, keys = wc.decompose(text)
            self.assertEqual(wc.render("v0_short", disease, keys), text)


class RenderTest(unittest.TestCase):
    def test_official(self):
        self.assertEqual(wc.render("v1_official", "asthma", ["adults", "wgs"]),
                         "Find dbGaP studies involving adult participants with asthma as the primary disease, "
                         "where participant-level data include whole genomic sequences.")
        self.assertEqual(wc.render("v1_official", "breast cancer", [("race", "Latino"), "gru"]),
                         "Find dbGaP studies involving participants with breast cancer as the primary disease, "
                         "consented for general research use, including at least 100 Latino participants.")

    def test_question(self):
        self.assertEqual(wc.render("v2_question", "lung adenocarcinoma", ["methylation", "wes"]),
                         "Which dbGaP studies enrolled participants diagnosed with lung adenocarcinoma and have "
                         "DNA methylation data and exome sequencing data available?")
        self.assertEqual(wc.render("v2_question", "asthma", ["children"]),
                         "Which dbGaP studies enrolled children diagnosed with asthma?")

    def test_chat(self):
        self.assertEqual(wc.render("v3_chat", "asthma", ["adults", "wgs", "gru"]),
                         "I'm looking for asthma cohorts in adults that have WGS data and with GRU consent.")
        self.assertEqual(wc.render("v3_chat", "asthma", ["children"]), "I'm looking for asthma cohorts in kids.")

    def test_synonyms(self):
        self.assertEqual(wc.render("v4_synonyms", "asthma", ["adults", ("race", "Asian")]),
                         "Studies of asthma in participants aged 18 or older and with 100 or more Asian participants")

    def test_disease_copied_unchanged(self):
        for text in SILVER:
            disease, keys = wc.decompose(text)
            for v in wc.VARIANTS:
                self.assertIn(disease, wc.render(v, disease, keys))

    def test_unknown_variant(self):
        with self.assertRaises(ValueError):
            wc.render("v9", "asthma", ["adults"])

    def test_join_and(self):
        self.assertEqual(wc.join_and(["a"]), "a")
        self.assertEqual(wc.join_and(["a", "b"]), "a and b")
        self.assertEqual(wc.join_and(["a", "b", "c"]), "a, b and c")


class VariantsTest(unittest.TestCase):
    def test_rows(self):
        rows, unparsed = wc.variants([{"id": "dev001", "query": SILVER[0]}, {"id": "dev002", "query": "odd"}])
        self.assertEqual(unparsed, ["dev002"])
        self.assertEqual([r["variant"] for r in rows], list(wc.VARIANTS))
        self.assertEqual(rows[0]["info_need_id"], "dev001-v0_short")
        self.assertEqual(rows[0]["constraints"], ["adults", "wgs"])
        rows, _ = wc.variants([{"id": "dev003", "query": SILVER[2]}])
        self.assertEqual(rows[0]["constraints"], ["race", "rnaseq"])


class MeasureTest(unittest.TestCase):
    def test_constraint_parse(self):
        q = {"data_types": {"wgs", "wes"}, "age": (18, None), "topic": ["asthma"], "tokens": ["x"]}
        self.assertEqual(wc.constraint_parse(q), {"age": [18, None], "data_types": ["wes", "wgs"]})
        self.assertEqual(wc.differing({"age": [18, None]}, {"age": None, "groups": []}), ["age", "groups"])

    def test_summarize(self):
        def need(i, scores, diff, keys=("adults",)):
            return {"id": i, "constraints": list(keys), "ndcg": dict(zip(wc.VARIANTS, scores)),
                    "seconds": {v: 1.0 for v in wc.VARIANTS},
                    "parse_diff": {v: (["age"] if v in diff else []) for v in wc.VARIANTS},
                    "topic_diff": {v: ([] if v == "v3_chat" else None) for v in wc.VARIANTS}}
        per = [need("a", [1.0, 1.0, 0.5, 1.0, 0.0], {"v4_synonyms"}),
               need("b", [0.5, 0.5, 0.5, 1.0, 0.5], set(), ("wgs",))]
        s = wc.summarize(per)
        self.assertEqual(s["v0_short"]["ndcg@10"], 0.75)
        self.assertEqual(s["v2_question"]["lower_than_v0"], 1)
        self.assertEqual(s["v2_question"]["loss"], 0.5)
        self.assertEqual(s["v2_question"]["loss_from_parse_differs"], 0.0)
        self.assertEqual(s["v3_chat"]["higher_than_v0"], 1)
        self.assertEqual(s["v3_chat"]["topic_differs"], 2)  # an emptied topic still counts
        self.assertEqual(s["v4_synonyms"]["loss_from_parse_differs"], 1.0)
        self.assertEqual(s["v4_synonyms"]["by_constraint"]["adults"], {"needs": 1, "ndcg@10": 0.0})
        self.assertEqual(s["v1_official"]["mean_seconds"], 1.0)


if __name__ == "__main__":
    unittest.main()
