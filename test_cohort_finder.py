import contextlib
import io
import json
import math
import os
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))
sys.path.insert(0, HERE)

import cohort_finder as cf  # noqa: E402

SD = "https://dbgap-api.ncbi.nlm.nih.gov/fhir/x1/StructureDefinition/ResearchStudy-"
CS = "https://dbgap-api.ncbi.nlm.nih.gov/fhir/x1/CodeSystem/"
UCUM = {"system": "http://unitsofmeasure.org", "code": "1"}


def count(name, value):
    return {"url": SD + name, "valueCount": dict(UCUM, value=value)}


def ancestry(code, value):
    return {"url": SD + "ComputedAncestry-AncestryCount", "extension": [
        {"url": SD + "ComputedAncestry-AncestryCount-Ancestry",
         "valueCodeableConcept": {"coding": [{"system": CS + "ResearchStudy-ComputedAncestry-AncestryCount-Ancestry",
                                              "code": code}]}},
        {"url": SD + "ComputedAncestry-AncestryCount-Count", "valueCount": dict(UCUM, value=value)},
    ]}


def concept(system, code, display):
    return {"coding": [{"system": system, "code": code, "display": display}], "text": display}


CONDITIONS = [
    concept("urn:oid:2.16.840.1.113883.6.177", "D010974", "Platelet Aggregation"),
    concept("https://dbgap-api.ncbi.nlm.nih.gov/fhir/x1/NamingSystem/MeshEntryTerm",
            "D010974 entry term: Aggregation, Platelet", "Aggregation, Platelet"),
    concept("https://dbgap-api.ncbi.nlm.nih.gov/fhir/x1/NamingSystem/MeshEntryTerm",
            "D010974 entry term: Platelet Aggregation", "Platelet Aggregation"),
    concept("https://uts.nlm.nih.gov/metathesaurus.html", "C0032176", "Platelet Aggregation"),
]

# Shaped like the real dbGaP FHIR record for phs001218 (GeneSTAR), fetched 2026-10-14.
FHIR_STUDY = {
    "resourceType": "ResearchStudy",
    "id": "phs001218",
    "extension": [
        {"url": SD + "StudyOverviewUrl",
         "valueUrl": "https://www.ncbi.nlm.nih.gov/projects/gap/cgi-bin/study.cgi?study_id=phs001218.v3.p1"},
        {"url": SD + "ReleaseDate", "valueDate": "2021-06-17"},
        {"url": SD + "StudyConsents", "extension": [
            {"url": SD + "StudyConsents-StudyConsent",
             "valueCoding": {"system": CS + "ResearchStudy-StudyConsents-StudyConsent",
                             "code": "phs001218.v3.p1 - 2", "display": "DS-CVD-IRB-NPU-MDS"}},
            {"url": SD + "StudyConsents-StudyConsent",
             "valueCoding": {"system": CS + "ResearchStudy-StudyConsents-StudyConsent",
                             "code": "phs001218.v3.p1 - 999", "display": "EA-IRB-NPU-MDS"}},
        ]},
        {"url": SD + "Content", "extension": [
            count("Content-NumPhenotypeDatasets", 5),
            count("Content-NumMolecularDatasets", 2),
            count("Content-NumVariables", 157),
            count("Content-NumDocuments", 17),
            count("Content-NumAnalyses", 0),
            count("Content-NumSubjects", 1787),
            count("Content-NumSamples", 1785),
            count("Content-NumSubStudies", 0),
        ]},
        {"url": SD + "ComputedAncestry", "extension": [
            ancestry("EUR", 976), ancestry("AFO", 9), ancestry("AFA", 768),
            ancestry("LAC", 12), ancestry("OAS", 5), ancestry("OTR", 7),
        ]},
        {"url": SD + "StudyMarkersets", "extension": [
            {"url": SD + "StudyMarkersets-StudyMarkerset",
             "valueCodeableConcept": {"coding": [{"code": "WGS_markerset_grc38"}]}}]},
        {"url": SD + "MolecularDataTypes", "extension": [
            {"url": SD + "MolecularDataTypes-MolecularDataType",
             "valueCodeableConcept": {"coding": [{"code": "SNP/CNV Genotypes (NGS)"}]}},
            {"url": SD + "MolecularDataTypes-MolecularDataType",
             "valueCodeableConcept": {"coding": [{"code": "WGS"}]}},
        ]},
    ],
    "identifier": [{"type": {"coding": [{"code": "dbgap_study_id"}]}, "value": "phs001218.v3.p1"}],
    "title": "NHLBI TOPMed: Genetic Study of Atherosclerosis Risk (GeneSTAR)",
    "status": "completed",
    "category": [concept(CS + "ResearchStudy-StudyDesign", "Prospective Longitudinal Cohort",
                         "Prospective Longitudinal Cohort")],
    "focus": [concept("urn:oid:2.16.840.1.113883.6.177", "D010974", "Platelet Aggregation")],
    "condition": CONDITIONS,
    "keyword": CONDITIONS,
    "description": "<p>GeneSTAR began in 1982 as the Johns Hopkins Sibling &amp; Family Heart Study.</p>\n",
    "enrollment": [{"reference": "Group/phs001218.v3.p1-all-subjects"}],
    "sponsor": {"reference": "Organization/NHLBI", "type": "Organization",
                "display": "National Heart, Lung, and Blood Institute"},
}

OTHER = {
    "resourceType": "ResearchStudy",
    "id": "phs000483",
    "identifier": [{"value": "phs000483.v1.p1"}],
    "title": "MGH/Eisai NIMH Alzheimer&#39;s Disease GWAS",
}

# Synthetic records (not real dbGaP studies) for the ranking tests.
STUDY_B = {
    "accession": "phs900001", "version": "phs900001.v1.p1", "title": "Type 2 Diabetes Case-Control GWAS",
    "description": "Synthetic test record.", "design": ["Case-Control"],
    "focus": ["Diabetes Mellitus, Type 2"], "conditions": ["Diabetes Mellitus, Type 2"],
    "consents": ["GRU"], "subjects": 5000, "ancestry": {"EUR": 4000, "AFA": 900},
    "data_types_raw": ["SNP Genotypes (Array)"],
}
STUDY_C = {
    "accession": "phs900002", "version": "phs900002.v1.p1", "title": "Diabetes Heart Study WGS",
    "description": "Synthetic test record.", "design": ["Family"],
    "focus": ["Diabetes Mellitus, Type 2"], "conditions": ["Diabetes Mellitus, Type 2", "Cardiovascular Diseases"],
    "consents": ["HMB-IRB-NPU"], "subjects": 800, "ancestry": {"AFA": 700, "EUR": 100},
    "data_types_raw": ["WGS"],
}
STUDY_D = {
    "accession": "phs900003", "version": "phs900003.v1.p1", "title": "Breast Cancer Tumor Sequencing",
    "description": "Synthetic test record.", "design": ["Tumor vs. Matched-Normal"],
    "focus": ["Breast Neoplasms"], "conditions": ["Breast Neoplasms"],
    "consents": ["GRU-COL"], "subjects": 300, "ancestry": {},
    "data_types_raw": ["WXS", "RNA-Seq"],
}

Q_DIABETES = "type 2 diabetes whole genome sequencing in African Americans"
Q_BREAST = "breast cancer exome data usable for for-profit research under general research use"


class NormalizeTest(unittest.TestCase):
    def setUp(self):
        self.s = cf.normalize_study(FHIR_STUDY)

    def test_fields(self):
        s = self.s
        self.assertEqual(s["accession"], "phs001218")
        self.assertEqual(s["version"], "phs001218.v3.p1")
        self.assertEqual(s["title"], "NHLBI TOPMed: Genetic Study of Atherosclerosis Risk (GeneSTAR)")
        self.assertEqual(s["description"], "GeneSTAR began in 1982 as the Johns Hopkins Sibling & Family Heart Study.")
        self.assertEqual(s["status"], "completed")
        self.assertEqual(s["design"], ["Prospective Longitudinal Cohort"])
        self.assertEqual(s["focus"], ["Platelet Aggregation"])
        self.assertEqual(s["conditions"], ["Platelet Aggregation", "Aggregation, Platelet"])
        self.assertEqual(s["mesh"], ["D010974"])
        self.assertEqual(s["sponsor"], "National Heart, Lung, and Blood Institute")
        self.assertEqual(s["release_date"], "2021-06-17")
        self.assertTrue(s["url"].endswith("study_id=phs001218.v3.p1"))

    def test_extensions(self):
        s = self.s
        self.assertEqual(s["consents"], ["DS-CVD-IRB-NPU-MDS", "EA-IRB-NPU-MDS"])
        self.assertEqual((s["subjects"], s["samples"], s["substudies"], s["variables"]), (1787, 1785, 0, 157))
        self.assertEqual(s["ancestry"], {"EUR": 976, "AFO": 9, "AFA": 768, "LAC": 12, "OAS": 5, "OTR": 7})
        self.assertEqual(s["data_types_raw"], ["SNP/CNV Genotypes (NGS)", "WGS"])
        self.assertEqual(s["data_types"], ["genotypes", "wgs"])

    def test_sparse_record(self):
        s = cf.normalize_study(OTHER)
        self.assertEqual(s["title"], "MGH/Eisai NIMH Alzheimer's Disease GWAS")
        self.assertEqual(s["url"], "https://www.ncbi.nlm.nih.gov/projects/gap/cgi-bin/study.cgi?study_id=phs000483.v1.p1")
        self.assertIsNone(s["subjects"])
        self.assertEqual(s["ancestry"], {})
        self.assertEqual(s["consents"], [])

    def test_ext_name(self):
        self.assertEqual(cf._ext_name(SD + "Content-NumSubjects"), "Content-NumSubjects")
        self.assertEqual(cf._ext_name("StudyOverviewUrl"), "StudyOverviewUrl")


class TagsTest(unittest.TestCase):
    def test_data_types(self):
        self.assertEqual(cf.data_type_tags(["miRNA-Seq"]), {"mirna"})
        self.assertEqual(cf.data_type_tags(["RNA Seq expression levels"]), {"rnaseq"})
        self.assertEqual(cf.data_type_tags(["SNP Genotypes (imputed)"]), {"genotypes", "imputed"})
        self.assertEqual(cf.data_type_tags(["WXS"]), {"wes", "genotypes"})
        self.assertEqual(cf.data_type_tags(["Methylation (CpG)"]), {"methylation"})
        self.assertEqual(cf.data_type_tags([]), set())

    def test_designs(self):
        self.assertEqual(cf.design_tags(["Prospective Longitudinal Cohort"]), {"cohort", "longitudinal"})
        self.assertEqual(cf.design_tags(["Family/Twin/Trios"]), {"family"})
        self.assertEqual(cf.design_tags(["Case-Control"]), {"case_control"})

    def test_tokens(self):
        self.assertEqual(cf.tokens("Studies of Diseases in 2,000 Americans"), ["disease", "american"])
        self.assertEqual(cf.tokens(""), [])


class ParseQueryTest(unittest.TestCase):
    def test_full_question(self):
        q = cf.parse_query("Which studies have whole genome sequencing on at least 1,000 African American "
                           "participants with general research use consent?")
        self.assertEqual(q["min_subjects"], 1000)
        self.assertEqual(q["data_types"], {"wgs"})
        self.assertEqual(q["designs"], set())
        self.assertEqual(q["ancestry"], [{"AFA"}])
        self.assertEqual(q["consent"], {"GRU"})
        self.assertEqual(q["tokens"], ["whole", "genome", "sequencing", "african", "american", "general", "research"])

    def test_ages_and_disease_numbers_are_not_sizes(self):
        self.assertIsNone(cf.min_subjects("over 65 years old, type 2 diabetes"))
        self.assertIsNone(cf.min_subjects("at least 50% women"))
        self.assertIsNone(cf.min_subjects("type 2 diabetes patients"))

    def test_sizes(self):
        self.assertEqual(cf.min_subjects("5k+ participants with RNA-seq"), 5000)
        self.assertEqual(cf.min_subjects("more than 2,500 subjects"), 2500)
        self.assertEqual(cf.min_subjects("500 cases and 1,200 controls"), 1200)
        self.assertEqual(cf.min_subjects("aged 40 to 60 years, 2,000 participants"), 2000)

    def test_designs(self):
        q = cf.parse_query("5k+ participants with RNA-seq from a prospective cohort study in families")
        self.assertEqual(q["designs"], {"cohort", "family", "longitudinal"})
        self.assertEqual(q["data_types"], {"rnaseq"})
        self.assertEqual(cf.parse_query("family history of breast cancer")["designs"], set())
        self.assertEqual(cf.parse_query("is there a cohort with asthma")["designs"], set())

    def test_ancestry(self):
        self.assertEqual(cf.parse_query("East Asian adults")["ancestry"], [{"EAS"}])
        self.assertEqual(cf.parse_query("people of African ancestry")["ancestry"], [{"AFA", "AFO"}])
        self.assertEqual(cf.parse_query("Hispanic/Latino children")["ancestry"], [{"LAC", "LEN"}])
        self.assertEqual(cf.parse_query("white matter lesions")["ancestry"], [])

    def test_consent(self):
        self.assertEqual(cf.parse_query("commercial use, HMB")["consent"], {"NO_NPU", "HMB"})
        self.assertTrue(cf.consent_ok("GRU-COL", {"GRU", "NO_NPU"}))
        self.assertTrue(cf.consent_ok("HMB-IRB-NPU", {"HMB"}))
        self.assertFalse(cf.consent_ok("HMB-IRB-NPU", {"NO_NPU"}))
        self.assertFalse(cf.consent_ok("HMB-IRB-NPU", {"GRU"}))
        self.assertFalse(cf.consent_ok("HMB-IRB-NPU", {"NO_IRB"}))
        self.assertFalse(cf.consent_ok("DS-CVD-IRB-NPU-MDS", {"HMB"}))


class SearchTest(unittest.TestCase):
    def setUp(self):
        self.a = cf.normalize_study(FHIR_STUDY)
        self.index = cf.Index([self.a, STUDY_B, STUDY_C, STUDY_D])

    def test_constraints_reorder_text_matches(self):
        results = cf.search(self.index, Q_DIABETES)
        self.assertEqual([r["accession"] for r in results], ["phs900002", "phs900001", "phs900003", "phs001218"])
        self.assertIn("has wgs data", results[0]["why"])
        self.assertIn("700 AFA subjects by computed ancestry", results[0]["why"])
        self.assertIn("no wgs data listed", results[1]["why"])

    def test_consent_and_data_type_filter(self):
        results = cf.search(self.index, Q_BREAST)
        self.assertEqual([r["accession"] for r in results], ["phs900003"])
        self.assertIn("has wes data", results[0]["why"])
        self.assertTrue(any(w.startswith("consent GRU-COL fits") for w in results[0]["why"]))

    def test_k_and_empty(self):
        self.assertEqual(len(cf.search(self.index, Q_DIABETES, k=2)), 2)
        self.assertEqual(cf.search(self.index, "the studies"), [])
        self.assertEqual(cf.search(cf.Index([]), Q_DIABETES), [])

    def test_answer(self):
        text = cf.answer(cf.search(self.index, Q_DIABETES, k=1), Q_DIABETES)
        self.assertIn("1. phs900002.v1.p1 Diabetes Heart Study WGS (800 subjects)", text)
        self.assertIn("   - has wgs data", text)
        self.assertTrue(cf.answer([], "x").startswith("No public dbGaP study matched"))


class EvaluateTest(unittest.TestCase):
    def test_ndcg(self):
        expected = (3 / math.log2(3) + 1 / 2.0) / (3 + 1 / math.log2(3))
        self.assertAlmostEqual(cf.ndcg(["a", "b", "c"], {"a": 0, "b": 2, "c": 1}, k=3), expected)
        self.assertAlmostEqual(cf.ndcg(["b", "c"], {"b": 2, "c": 1}), 1.0)
        self.assertEqual(cf.ndcg(["a"], {"a": 0}), 0.0)
        self.assertEqual(cf.ndcg([], {"a": 1}), 0.0)

    def test_run_roundtrip(self):
        index = cf.Index([cf.normalize_study(FHIR_STUDY), STUDY_B, STUDY_C, STUDY_D])
        lines = cf.run_lines("q1", cf.search(index, Q_DIABETES))
        self.assertTrue(lines[0].startswith("q1 Q0 phs900002 1 "))
        self.assertTrue(lines[0].endswith(" cohortfinder"))
        with tempfile.TemporaryDirectory() as tmp:
            run_path = os.path.join(tmp, "run.txt")
            qrels_path = os.path.join(tmp, "qrels.txt")
            with open(run_path, "w", encoding="utf-8") as f:
                f.write("\n".join(lines) + "\n")
            with open(qrels_path, "w", encoding="utf-8") as f:
                f.write("q1 0 phs900002 2\nq1 0 phs001218 1\nq2 0 phs900003 1\n")
            run = cf.read_run(run_path)
            self.assertEqual(run["q1"], ["phs900002", "phs900001", "phs900003", "phs001218"])
            mean, scores = cf.evaluate(run, cf.read_qrels(qrels_path))
        expected = (3 + 1 / math.log2(5)) / (3 + 1 / math.log2(3))
        self.assertAlmostEqual(scores["q1"], expected)
        self.assertEqual(scores["q2"], 0.0)
        self.assertAlmostEqual(mean, expected / 2)


class HarvestTest(unittest.TestCase):
    def test_follows_next_links(self):
        first = "%s/ResearchStudy?_count=100&_format=json" % cf.FHIR_BASE
        pages = {
            first: {"resourceType": "Bundle", "entry": [{"resource": FHIR_STUDY}],
                    "link": [{"relation": "self", "url": first},
                             {"relation": "next", "url": "https://example.org/page2"}]},
            "https://example.org/page2": {"entry": [{"resource": OTHER}, {"resource": FHIR_STUDY},
                                                    {"resource": {"resourceType": "Group", "id": "g"}}],
                                          "link": [{"relation": "self", "url": "https://example.org/page2"}]},
        }
        calls = []

        def fetcher(url):
            calls.append(url)
            return pages[url]
        studies = cf.harvest(fetcher=fetcher, delay=0)
        self.assertEqual(calls, [first, "https://example.org/page2"])
        self.assertEqual([s["accession"] for s in studies], ["phs000483", "phs001218"])


class MainTest(unittest.TestCase):
    def test_run_and_evaluate(self):
        with tempfile.TemporaryDirectory() as tmp:
            studies = os.path.join(tmp, "studies.jsonl")
            queries = os.path.join(tmp, "queries.jsonl")
            qrels = os.path.join(tmp, "qrels.txt")
            out = os.path.join(tmp, "run.txt")
            cf.write_studies([cf.normalize_study(FHIR_STUDY), STUDY_B, STUDY_C, STUDY_D], studies)
            self.assertEqual(len(cf.read_studies(studies)), 4)
            with open(queries, "w", encoding="utf-8") as f:
                f.write(json.dumps({"id": "q1", "query": Q_DIABETES}) + "\n")
                f.write(json.dumps({"id": "q2", "query": Q_BREAST}) + "\n")
            with open(qrels, "w", encoding="utf-8") as f:
                f.write("q2 0 phs900003 1\n")
            with contextlib.redirect_stdout(io.StringIO()) as printed:
                self.assertEqual(cf.main(["run", "--queries", queries, "--studies", studies, "--out", out]), 0)
                self.assertEqual(cf.main(["evaluate", "--run", out, "--qrels", qrels]), 0)
                self.assertEqual(cf.main(["search", Q_BREAST, "--studies", studies, "-k", "3"]), 0)
            run = cf.read_run(out)
            self.assertEqual(run["q1"][0], "phs900002")
            self.assertEqual(run["q2"], ["phs900003"])
            self.assertIn("mean NDCG@10\t1.0000", printed.getvalue())
            self.assertIn("phs900003.v1.p1 Breast Cancer Tumor Sequencing", printed.getvalue())
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cf.main(["search", "x", "--studies", os.path.join(tmp, "missing.jsonl")]), 1)


@unittest.skipUnless(os.path.exists(os.path.join(HERE, "dev_queries.jsonl")), "no dev_queries.jsonl")
class DevQueriesTest(unittest.TestCase):
    def test_every_dev_query_parses(self):
        queries = cf.read_queries(os.path.join(HERE, "dev_queries.jsonl"))
        self.assertGreaterEqual(len(queries), 10)
        self.assertEqual(len({qid for qid, _ in queries}), len(queries))
        for qid, text in queries:
            q = cf.parse_query(text)
            self.assertTrue(q["tokens"], qid)


if __name__ == "__main__":
    unittest.main()
