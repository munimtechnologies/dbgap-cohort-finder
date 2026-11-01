"""Tests for disease_check (standard library only; no snapshot data needed)."""

import unittest

import disease_check as dc


class NamingTest(unittest.TestCase):
    def test_uninvert(self):
        self.assertEqual(dc.uninvert("carcinoma, hepatocellular"), "hepatocellular carcinoma")
        self.assertEqual(dc.uninvert("leukemia, lymphocytic, chronic, b-cell"), "b-cell chronic lymphocytic leukemia")
        self.assertIsNone(dc.uninvert("asthma"))
        self.assertIsNone(dc.uninvert("congenital, hereditary, and neonatal diseases and abnormalities"))
        self.assertIsNone(dc.uninvert("platelet disorder, familial, with associated myeloid malignancy"))

    def test_name(self):
        self.assertEqual(dc.name("d0_as_is", "stomach neoplasms"), "stomach neoplasms")
        self.assertIsNone(dc.name("d1_uninverted", "stomach neoplasms"))
        self.assertEqual(dc.name("d2_natural", "stomach neoplasms"), "gastric cancer")
        self.assertEqual(dc.name("d3_abbrev", "pulmonary disease, chronic obstructive"), "COPD")
        self.assertIsNone(dc.name("d3_abbrev", "asthma"))
        with self.assertRaises(ValueError):
            dc.name("d9", "asthma")

    def test_tables_never_name_the_same_thing(self):
        # Exact text, as name() compares it. Case alone can count: dbGaP stores "hiv",
        # and cohort_finder spells out only the capitalised abbreviation "HIV"
        # (three-letter abbreviations are matched case-sensitively), so "HIV" is a
        # real d3 variant of "hiv". (disease-check-v1 compared lower-cased text here
        # and failed on that row before any data was read.)
        for table in (dc.NATURAL, dc.ABBREV):
            for disease, named in table.items():
                self.assertEqual(disease, disease.lower(), disease)
                self.assertNotEqual(disease, named, disease)
        self.assertEqual(dc.name("d3_abbrev", "hiv"), "HIV")
        for disease in dc.POSSESSIVE:
            self.assertIn("'s ", dc.NATURAL[disease])

    def test_in_table(self):
        self.assertTrue(dc.in_table("COPD"))
        self.assertTrue(dc.in_table("RA"))
        self.assertFalse(dc.in_table("PCOS"))
        self.assertFalse(dc.in_table("GVHD"))

    def test_rows_for(self):
        queries = [{"id": "dev1", "query": "Studies of carcinoma, hepatocellular with exome sequencing"},
                   {"id": "dev2", "query": "Studies of asthma in adults"},
                   {"id": "dev3", "query": "not a silver need"}]
        rows, unparsed = dc.rows_for(queries)
        self.assertEqual(unparsed, ["dev3"])
        got = {(r["source"], r["variant"], r["frame"]): r["info_need"] for r in rows}
        # dev1: d0, d1, d2, d3 in two frames; dev2: d0 only.
        self.assertEqual(len(got), 10)
        self.assertEqual(got[("dev1", "d0_as_is", "v0_short")],
                         "Studies of carcinoma, hepatocellular with exome sequencing")
        self.assertEqual(got[("dev1", "d1_uninverted", "v0_short")],
                         "Studies of hepatocellular carcinoma with exome sequencing")
        self.assertEqual(got[("dev1", "d3_abbrev", "v0_short")], "Studies of HCC with exome sequencing")
        self.assertIn("with hepatocellular carcinoma as the primary disease",
                      got[("dev1", "d2_natural", "v1_official")])
        self.assertEqual(got[("dev2", "d0_as_is", "v0_short")], "Studies of asthma in adults")


class SummaryTest(unittest.TestCase):
    def item(self, source, variant, base, fix, fit, topic=("x",), disease="d", in_table=None):
        out = {"source": source, "disease": disease, "variant": variant, "frame": "v0_short", "named": "n",
               "topic": list(topic), "fit": fit, "constraints": {},
               "base": {"ndcg@10": base, "seconds": 1.0}, "fix": {"ndcg@10": fix, "seconds": 0.5}}
        if in_table is not None:
            out["in_table"] = in_table
        return out

    def test_summarize(self):
        items = [self.item("q1", "d0_as_is", 1.0, 1.0, 1.0), self.item("q2", "d0_as_is", 0.5, 0.5, 1.0),
                 self.item("q1", "d2_natural", 0.2, 0.4, 0.0), self.item("q2", "d2_natural", 0.5, 0.6, 1.0),
                 self.item("q1", "d3_abbrev", 1.0, 1.0, None, topic=(), in_table=True),
                 self.item("q2", "d3_abbrev", 0.1, 0.1, 0.0, in_table=False)]
        s = dc.summarize(items)["v0_short"]
        nat = s["d2_natural"]
        self.assertEqual(nat["needs"], 2)
        self.assertEqual(nat["base"]["d0_ndcg@10"], 0.75)
        self.assertEqual(nat["base"]["ndcg@10"], 0.35)
        self.assertEqual(nat["base"]["drop"], 0.4)
        self.assertEqual((nat["base"]["same"], nat["base"]["lower"], nat["base"]["higher"]), (1, 1, 0))
        self.assertEqual(nat["base"]["lost_over_0.2"], 1)
        self.assertEqual(nat["fix"]["higher"], 1)
        self.assertEqual(nat["fit_lost"], 1)
        self.assertEqual(nat["base_loss"], 0.8)
        self.assertEqual(nat["base_loss_from_fit_lost"], 0.8)
        self.assertEqual(s["d3_abbrev"]["needs"], 2)
        self.assertEqual(s["d3_abbrev"]["topic_empty"], 1)
        self.assertEqual(s["d3_abbrev_in_table"]["needs"], 1)
        self.assertEqual(s["d3_abbrev_not_in_table"]["base"]["drop"], 0.4)
        self.assertEqual(s["d3_abbrev"]["fit_lost"], 2)
        self.assertNotIn("d1_uninverted", s)
        self.assertEqual(s["d0_as_is"]["needs"], 2)
        self.assertEqual(s["d0_as_is"]["base"]["ndcg@10"], 0.75)
        self.assertEqual(s["d0_as_is"]["base"]["drop"], 0.0)
        self.assertEqual(s["d0_as_is"]["fit_lost"], 0)


if __name__ == "__main__":
    unittest.main()
