# Tests for snapshot.py (needs cohort_finder.py next to it).
# Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
import gzip
import json
import os
import tempfile
import unittest

import cohort_finder as cf
import snapshot as sn

LUNG = "Adenocarcinoma of Lung"
RECORDS = [
    {"accession": "phs000100.v1.p1", "name": "Lung Adenocarcinoma Genomics Study", "main_disease": LUNG,
     "description": "Smokers and never smokers with lung adenocarcinoma.", "sample_use": ["Seq_DNA_WholeGenome"],
     "consent_abbrev": ["GRU"], "study_subject_count": "1500", "age_min": 30, "age_max": 85,
     "race_counts": {"white": 900, "black": 400}, "study_structure_type": "top"},
    {"accession": "phs000200.v1.p1", "name": "Lung Adenocarcinoma Expression Study", "main_disease": LUNG,
     "description": "Tumor expression profiles.", "sample_use": ["Seq_RNA_Expression"],
     "consent_abbrev": ["HMB-IRB"], "study_subject_count": "800", "age_min": 40, "age_max": 80,
     "race_counts": {"white": 800}},
    {"accession": "phs000300.v1.p1", "name": "Pediatric Asthma Cohort", "main_disease": "Asthma",
     "description": "children with asthma", "sample_use": ["Array_SNP"], "consent_abbrev": "DS-ASTHMA",
     "study_subject_count": "500", "age_min": 5, "age_max": 17,
     "race_counts": {"black": 300, "other": 20}, "ethnicity_counts": {"hispanic": 200}},
    {"accession": "phs000400.v1.p1", "name": "Adult Asthma Study", "main_disease": "Asthma",
     "description": "Adults with asthma.", "sample_use": "Not Provided", "genotype_platform": ["HumanExome-12"],
     "consent_abbrev": ["GRU-NPU"], "study_subject_count": "2000", "all_population": ["African American"]},
]
VARIABLES = [
    {"study": "phs000100.v1.p1", "phv": "phv00000001.v1.p1", "name": "SMOKE", "desc": "Cigarette smoking status"},
    {"study": "phs000200.v1.p1", "phv": "phv00000002.v1.p1", "name": "BMI", "desc": "Body mass index"},
]
VALUES = [{"study": "phs000100.v1.p1", "phv": "phv00000001.v1", "name": "SMOKE",
           "values": ["Never", "Former", "Current"]}]


def write_jsonl(path, rows):
    opener = gzip.open if path.endswith(".gz") else open
    with opener(path, "wt", encoding="utf-8") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


class Corpus(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        d = cls.tmp.name
        cls.paths = [os.path.join(d, n) for n in ("studies.jsonl", "variables.jsonl.gz", "var_values.jsonl.gz")]
        for path, rows in zip(cls.paths, (RECORDS, VARIABLES, VALUES)):
            write_jsonl(path, rows)
        cls.studies = sn.load(*cls.paths)
        cls.by_acc = {s["accession"]: s for s in cls.studies}
        cls.index = cf.Index(cls.studies)

    @classmethod
    def tearDownClass(cls):
        cls.tmp.cleanup()


class HelperTest(unittest.TestCase):
    def test_spaced(self):
        self.assertEqual(sn.spaced("Seq_DNA_WholeGenome"), "Seq DNA Whole Genome")

    def test_query_age(self):
        self.assertEqual(sn.query_age("adults with asthma"), (18, None))
        self.assertEqual(sn.query_age("children with asthma"), (0, 17))
        self.assertEqual(sn.query_age("participants aged 40-60"), (40, 60))
        self.assertEqual(sn.query_age("people 65 and older"), (65, None))
        self.assertEqual(sn.query_age("older adults with dementia"), (65, None))
        self.assertEqual(sn.query_age("infants under 5 years"), (0, 4))
        self.assertIsNone(sn.query_age("at least 500+ participants with lupus"))
        self.assertIsNone(sn.query_age("less than 50 participants"))
        self.assertEqual(sn.query_age("WGS on 1,000+ adults"), (18, None))

    def test_age_is_not_a_size(self):
        q = sn.parse_need("Studies of 65 and older adults with heart failure")
        self.assertEqual(q["age"], (65, None))
        self.assertIsNone(q["min_subjects"])
        self.assertEqual(sn.parse_need("1,000 adults with heart failure")["min_subjects"], 1000)

    def test_query_groups(self):
        self.assertEqual(sn.query_groups("African American and Hispanic adults"), ["black", "hispanic"])
        self.assertEqual(sn.query_groups("white matter lesions on MRI"), [])
        self.assertEqual(sn.query_groups("Black women with lupus"), ["black"])

    def test_query_var_terms(self):
        self.assertEqual(sn.query_var_terms("adults with lung adenocarcinoma, smoking variables and WGS"),
                         [["smoking"]])
        self.assertEqual(sn.query_var_terms("asthma with WGS data"), [])

    def test_submission_line(self):
        line = json.loads(sn.submission_line("t", "s1", "q7", "need", [{"accession": "phs1.v1.p1"}]))
        self.assertEqual(line, {"metadata": {"team_id": "t", "submission_id": "s1", "info_need_id": "q7",
                                             "info_need": "need"}, "results": ["phs1.v1.p1"]})

    def test_read_needs(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "needs.jsonl")
            write_jsonl(path, [{"info_need_id": "q1", "info_need": "asthma"},
                               {"metadata": {"info_need_id": 2, "info_need": "lupus"}}, {"query": "copd"}])
            self.assertEqual(sn.read_needs(path), [("q1", "asthma"), ("2", "lupus"), ("3", "copd")])


class NormalizeTest(Corpus):
    def test_data_types(self):
        self.assertEqual(self.by_acc["phs000100.v1.p1"]["data_types"], ["genotypes", "wgs"])
        self.assertIn("rnaseq", self.by_acc["phs000200.v1.p1"]["data_types"])
        self.assertEqual(self.by_acc["phs000400.v1.p1"]["data_types"], ["genotypes"])  # exome chip, not WES

    def test_fields(self):
        s1, s3 = self.by_acc["phs000100.v1.p1"], self.by_acc["phs000300.v1.p1"]
        self.assertEqual(s1["age"], (30.0, 85.0))
        self.assertEqual(s1["subjects"], 1500)
        self.assertEqual(s1["dictionary"], [["SMOKE", "Cigarette smoking status Never Former Current"]])
        self.assertEqual(s3["race_counts"]["hispanic"], 200)
        self.assertTrue(s3["has_hispanic_count"])
        self.assertFalse(s1["has_hispanic_count"])
        self.assertIsNone(self.by_acc["phs000400.v1.p1"]["age"])


class RequirementTest(Corpus):
    def test_age(self):
        s1, s2, s3 = (self.by_acc[a] for a in ("phs000100.v1.p1", "phs000200.v1.p1", "phs000300.v1.p1"))
        self.assertEqual(sn.age_requirement(s1, (18, None))[0], 1.0)
        self.assertEqual(sn.age_requirement(s1, (40, 60))[0], sn.PARTIAL_AGE)
        self.assertEqual(sn.age_requirement(s2, (0, 17))[0], 0.0)
        self.assertEqual(sn.age_requirement(s3, (0, 17))[0], 1.0)
        self.assertEqual(sn.age_requirement(self.by_acc["phs000400.v1.p1"], (0, 17))[0], cf.UNKNOWN)

    def test_groups(self):
        s1, s2 = self.by_acc["phs000100.v1.p1"], self.by_acc["phs000200.v1.p1"]
        self.assertEqual(sn.group_requirement(s1, "black", 100)[0], 1.0)
        self.assertEqual(sn.group_requirement(s1, "black", 1000)[0], 0.5)
        self.assertEqual(sn.group_requirement(s2, "black", 100)[0], 0.0)
        self.assertEqual(sn.group_requirement(s1, "hispanic", 100)[0], cf.UNKNOWN)
        self.assertEqual(sn.group_requirement(self.by_acc["phs000400.v1.p1"], "black", 100)[0], 1.0)


class RankTest(Corpus):
    def test_conjunctive_need(self):
        results = sn.search(self.index, "adults with lung adenocarcinoma, smoking variables and WGS")
        self.assertEqual(results[0]["accession"], "phs000100.v1.p1")
        self.assertEqual(results[0]["fails"], 0)
        s2 = [r for r in results if r["accession"] == "phs000200.v1.p1"][0]
        self.assertGreaterEqual(s2["fails"], 1)

    def test_children_and_group(self):
        results = sn.search(self.index, "children with asthma in Black participants")
        self.assertEqual(results[0]["accession"], "phs000300.v1.p1")

    def test_devset_and_bench(self):
        queries, qrels = sn.make_devset(self.studies, n=10, seed=1)
        self.assertTrue(queries)
        self.assertEqual(queries[0]["id"], "dev001")
        for q in queries:
            self.assertTrue(qrels[q["id"]])
            self.assertTrue(q["query"].startswith("Studies of "))
        result = sn.bench(self.studies, queries, qrels)
        for name in ("bm25_text_only", "conjunctive"):
            self.assertTrue(0.0 <= result[name]["ndcg@10"] <= 1.0)
        self.assertEqual(result["questions"], len(queries))

    def test_cli_run(self):
        with tempfile.TemporaryDirectory() as d:
            needs, out = os.path.join(d, "needs.jsonl"), os.path.join(d, "sub.jsonl")
            write_jsonl(needs, [{"info_need_id": "q1", "info_need": "adults with asthma"}])
            sn.main(["--studies", self.paths[0], "--variables", self.paths[1], "--values", self.paths[2],
                     "run", "--needs", needs, "--out", out, "--team-id", "munim"])
            with open(out, encoding="utf-8") as f:
                line = json.loads(f.readline())
            self.assertEqual(line["metadata"]["info_need_id"], "q1")
            self.assertEqual(line["results"][0], "phs000400.v1.p1")


if __name__ == "__main__":
    unittest.main()
