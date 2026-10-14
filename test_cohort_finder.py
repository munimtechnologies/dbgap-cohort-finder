import contextlib
import io
import json
import math
import os
import sys
import tempfile
import unittest
import urllib.error
from unittest import mock

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

# Shaped like the public dbGaP files for phs001218.v3.p1, read 2026-10-14 from
# https://ftp.ncbi.nlm.nih.gov/dbgap/studies/phs001218/phs001218.v3.p1/pheno_variable_summaries/
# (abridged; the sex counts are the real ones).
DD_BASE = cf.FTP_BASE + "/phs001218/phs001218.v3.p1/pheno_variable_summaries/"
SUBJECT_DD = "phs001218.v3.pht005957.v1.TOPMed_WGS_GeneSTAR_Subject.data_dict.xml"
PHENO_DD = "phs001218.v3.pht007766.v1.TOPMed_WGS_GeneSTAR_Subject_Phenotypes.data_dict.xml"
SUBJECT_VR = "phs001218.v3.pht005957.v1.p1.TOPMed_WGS_GeneSTAR_Subject.var_report.xml"
PHENO_VR = "phs001218.v3.pht007766.v1.p1.TOPMed_WGS_GeneSTAR_Subject_Phenotypes.var_report.xml"

LISTING = """<html><body><h1>Index of /dbgap/studies/phs001218/phs001218.v3.p1/pheno_variable_summaries</h1><pre>
<a href="/dbgap/studies/phs001218/phs001218.v3.p1/">Parent Directory</a>
<a href="datadict_v2.xsl">datadict_v2.xsl</a>       2026-09-14 09:40  4.9K
<a href="%s">%s</a>  2021-06-16 22:54  1.2K
<a href="%s">%s</a>  2021-06-16 22:54  3.8K
<a href="%s">%s</a>  2021-06-16 22:54   39K
<a href="%s">%s</a>  2021-06-16 22:54  185K
<a href="varreports_v3.xsl">varreports_v3.xsl</a>     2026-09-14 09:40  8.5K
</pre></body></html>""" % (SUBJECT_DD, SUBJECT_DD, SUBJECT_VR, SUBJECT_VR, PHENO_DD, PHENO_DD, PHENO_VR, PHENO_VR)

SUBJECT_DICT = """<?xml version="1.0" encoding="UTF-8"?>
<?xml-stylesheet type="text/xsl" href="./datadict_v2.xsl"?>
<data_table id="pht005957.v1" study_id="phs001218.v3" participant_set="1" date_created="Tue Jun  8 16:15:05 2021">
<description>The subject consent data table contains subject IDs, consent group information, and subject aliases.</description>
<variable id="phv00273446.v1"><name>SUBJECT_ID</name><description>De-identified Subject ID</description><type>string</type></variable>
<variable id="phv00273447.v1"><name>CONSENT</name><description>Consent group as determined by DAC</description><type>encoded value</type><value code="0">Subject did not participate in the study</value><value code="2">Disease-Specific (Cardiovascular Disease, IRB, NPU, MDS) (DS-CVD-IRB-NPU-MDS)</value></variable>
</data_table>
"""

PHENO_DICT = """<?xml version="1.0" encoding="UTF-8"?>
<?xml-stylesheet type="text/xsl" href="./datadict_v2.xsl"?>
<data_table id="pht007766.v1" study_id="phs001218.v3" participant_set="1" date_created="Tue Jun  8 16:15:02 2021">
<description>Subject phenotypes.</description>
<unique_key phv="00369266" version="1">SUBJECT_ID</unique_key>
<variable id="phv00369266.v1"><name>SUBJECT_ID</name><description>De-identified Subject ID</description><type>string</type></variable>
<variable id="phv00369272.v1"><name>BMI</name><description>Body mass index (calculated as weight (kg) / height (m) ^2 )</description><type>decimal</type><unit>kg/m^2</unit></variable>
<variable id="phv00369289.v1"><name>LDL</name><description>LDL cholesterol (calculated using Friedewald formula)</description><type>decimal</type><unit>mg/dl</unit></variable>
<variable id="phv00369280.v1"><name>HBPORRX</name><description>Hypertension (measured blood pressure &gt;= 140/90mmHg and/or current antihypertensive medication)</description><type>encoded value</type><comment>derived</comment><coll_interval>all visits</coll_interval><value code="0">no</value><value code="1">yes</value></variable>
<has_coll>1</has_coll>
</data_table>
"""


def var_report_variable(vid, name, male, female):
    return ('<variable id="%s" var_name="%s" calculated_type="string" reported_type="string">'
            '<description>x</description><total><subject_profile><sex><male>%d</male><female>%d</female></sex>'
            '</subject_profile><stats><stat n="%d" nulls="0"/></stats></total></variable>'
            % (vid, name, male, female, male + female))


SUBJECT_REPORT = ('<?xml version="1.0" encoding="UTF-8"?>\n'
                  '<?xml-stylesheet type="text/xsl" href="varreports_v3.xsl"?>\n'
                  '<data_table name="TOPMed_WGS_GeneSTAR_Subject" dataset_id="pht005957.v1" study_id="phs001218.v3"'
                  ' participant_set="1" date_created="2021/06/08"><description>x</description>'
                  + var_report_variable("phv00273446.v1.p1", "SUBJECT_ID", 1582, 1628)
                  + var_report_variable("phv00273447.v1.p1", "CONSENT", 1582, 1628)
                  + var_report_variable("phv00273446.v1.p1.c2", "SUBJECT_ID", 737, 1050)
                  + var_report_variable("phv00273447.v1.p1.c2", "CONSENT", 737, 1050)
                  + "</data_table>\n")


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
        self.assertEqual(s["mesh_terms"], {})

    def test_ext_name(self):
        self.assertEqual(cf._ext_name(SD + "Content-NumSubjects"), "Content-NumSubjects")
        self.assertEqual(cf._ext_name("StudyOverviewUrl"), "StudyOverviewUrl")

    def test_mesh_terms(self):
        self.assertEqual(self.s["mesh_terms"], {"D010974": ["Platelet Aggregation", "Aggregation, Platelet"]})


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

    def test_words_that_are_not_plurals(self):
        self.assertEqual(cf.tokens("Diabetes mellitus, cystic fibrosis, species series, body mass, cohorts"),
                         ["diabetes", "mellitus", "cystic", "fibrosis", "species", "series", "body", "mass",
                          "cohort"])

    def test_small_cells(self):
        self.assertEqual(cf.fmt_count(5), "fewer than 11")
        self.assertEqual(cf.fmt_count(11), "11")
        self.assertEqual(cf.fmt_count(1234), "1,234")
        self.assertEqual(cf.fmt_count(0), "0")


class ParseQueryTest(unittest.TestCase):
    def test_full_question(self):
        q = cf.parse_query("Which studies have whole genome sequencing on at least 1,000 African American "
                           "participants with general research use consent?")
        self.assertEqual(q["min_subjects"], 1000)
        self.assertEqual(q["data_types"], {"wgs"})
        self.assertEqual(q["designs"], set())
        self.assertEqual(q["ancestry"], [{"AFA"}])
        self.assertEqual(q["consent"], {"GRU"})
        self.assertIsNone(q["sex"])
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

    def test_sex(self):
        q = cf.parse_query("at least 1,000 women with breast cancer")
        self.assertEqual(q["sex"], "female")
        self.assertEqual(q["min_subjects"], 1000)
        self.assertEqual(cf.parse_query("female participants")["sex"], "female")
        self.assertEqual(cf.parse_query("older males with prostate cancer")["sex"], "male")
        self.assertIsNone(cf.parse_query("men and women")["sex"])
        self.assertIsNone(cf.parse_query("human samples")["sex"])

    def test_abbreviations(self):
        self.assertEqual(cf.expand_abbreviations("T2D and HbA1c, LDL"),
                         ["type 2 diabetes mellitus", "glycated hemoglobin a1c",
                          "low density lipoprotein cholesterol"])
        self.assertEqual(cf.expand_abbreviations("copd or COPD"), ["chronic obstructive pulmonary disease"])
        self.assertEqual(cf.expand_abbreviations("ad hoc pd ra"), [])
        self.assertEqual(cf.expand_abbreviations("T2DM"), ["type 2 diabetes mellitus"])
        words = cf.parse_query("AD cohorts with MRI")["tokens"]
        self.assertEqual(words[:3], ["ad", "cohort", "mri"])
        for word in ("alzheimer", "disease", "magnetic", "resonance", "imaging"):
            self.assertIn(word, words)
        self.assertEqual(len(words), len(set(words)))


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

    def test_small_ancestry_counts_are_suppressed(self):
        study = dict(STUDY_B, ancestry={"EUR": 4000, "AFA": 5})
        reqs = cf.requirements(study, cf.parse_query("African American participants"))
        self.assertEqual(reqs, [(0.5, "fewer than 11 AFA subjects by computed ancestry")])
        reqs = cf.requirements(dict(STUDY_B, ancestry={"AFA": 40}), cf.parse_query("African American participants"))
        self.assertEqual(reqs, [(0.5, "only 40 AFA subjects by computed ancestry")])

    def test_sex_requirement(self):
        study = dict(STUDY_B, sex={"male": 737, "female": 1050})
        q = cf.parse_query("at least 1,000 women")
        self.assertIn((1.0, "1,050 women in shareable consent groups"), cf.requirements(study, q))
        q = cf.parse_query("at least 1,000 men")
        self.assertIn((0.5, "only 737 men in shareable consent groups"), cf.requirements(study, q))
        self.assertIn((cf.UNKNOWN, "sex counts not available (women)"),
                      cf.requirements(STUDY_B, cf.parse_query("women")))


# Two synthetic studies: the text favours the second, its data dictionary the first.
DICT_X = {"accession": "phs900010", "version": "phs900010.v1.p1", "title": "Heart Study Alpha",
          "conditions": ["Cardiovascular Diseases"], "subjects": 2000,
          "dictionary": [["LDL", "LDL cholesterol", "mg/dl"], ["BMI", "Body mass index", "kg/m^2"]]}
DICT_Y = {"accession": "phs900011", "version": "phs900011.v1.p1", "title": "Heart Study",
          "conditions": ["Cardiovascular Diseases"], "subjects": 2000,
          "dictionary": [["AGE", "Age", "years"]]}


class DictionaryTest(unittest.TestCase):
    def fetcher(self, files):
        def fetch(url):
            if url not in files:
                raise urllib.error.HTTPError(url, 404, "Not Found", None, None)
            return files[url].encode("utf-8")
        return fetch

    def files(self):
        return {DD_BASE: LISTING, DD_BASE + SUBJECT_DD: SUBJECT_DICT, DD_BASE + PHENO_DD: PHENO_DICT,
                DD_BASE + SUBJECT_VR: SUBJECT_REPORT}

    def test_listing(self):
        self.assertEqual(cf.listing_files(LISTING, ".data_dict.xml"), [SUBJECT_DD, PHENO_DD])
        self.assertEqual(cf.listing_files(LISTING, ".var_report.xml"), [SUBJECT_VR, PHENO_VR])
        self.assertTrue(cf.SUBJECT_REPORT_RE.search(SUBJECT_VR))
        self.assertIsNone(cf.SUBJECT_REPORT_RE.search(PHENO_VR))

    def test_parse_data_dict(self):
        variables = cf.parse_data_dict(PHENO_DICT)
        self.assertEqual([v[0] for v in variables], ["SUBJECT_ID", "BMI", "LDL", "HBPORRX"])
        self.assertEqual(variables[1][2], "kg/m^2")
        self.assertTrue(variables[3][1].startswith("Hypertension (measured blood pressure >= 140/90mmHg"))
        self.assertEqual(variables[0], ("SUBJECT_ID", "De-identified Subject ID", ""))

    def test_parse_sex_counts(self):
        self.assertEqual(cf.parse_sex_counts(SUBJECT_REPORT), {"male": 737, "female": 1050})
        no_groups = SUBJECT_REPORT.replace(".c2\"", ".x\"")
        self.assertEqual(cf.parse_sex_counts(no_groups), {"male": 1582, "female": 1628})
        self.assertIsNone(cf.parse_sex_counts("<data_table><variable id=\"v\"/></data_table>"))

    def test_study_dictionary(self):
        record = cf.study_dictionary("phs001218.v3.p1", fetcher=self.fetcher(self.files()), delay=0)
        self.assertEqual(record["tables"], 2)
        self.assertEqual([v[0] for v in record["variables"]], ["SUBJECT_ID", "CONSENT", "BMI", "LDL", "HBPORRX"])
        self.assertEqual(record["sex"], {"male": 737, "female": 1050})
        missing = cf.study_dictionary("phs000001.v1.p1", fetcher=self.fetcher({}), delay=0)
        self.assertEqual(missing, {"tables": 0, "variables": [], "sex": None})

        def offline(url):
            raise urllib.error.URLError("offline")
        self.assertIsNone(cf.study_dictionary("phs001218.v3.p1", fetcher=offline, delay=0))

    def test_add_dictionaries_with_cache(self):
        studies = [cf.normalize_study(FHIR_STUDY), {"accession": "phs000002"}]
        with tempfile.TemporaryDirectory() as tmp:
            done = cf.add_dictionaries(studies, fetcher=self.fetcher(self.files()), delay=0, cache_dir=tmp)
            self.assertEqual(done, 1)
            self.assertTrue(os.path.exists(os.path.join(tmp, "phs001218.v3.p1.json")))

            def offline(url):
                raise AssertionError("should read the cache, not the network")
            again = [cf.normalize_study(FHIR_STUDY)]
            self.assertEqual(cf.add_dictionaries(again, fetcher=offline, delay=0, cache_dir=tmp), 1)
            # Past the deadline the cache is still read.
            late = [cf.normalize_study(FHIR_STUDY)]
            self.assertEqual(cf.add_dictionaries(late, fetcher=offline, delay=0, cache_dir=tmp, deadline=0), 1)
        self.assertEqual(studies[0]["sex"], {"male": 737, "female": 1050})
        self.assertEqual(studies[0]["dictionary_tables"], 2)
        self.assertEqual(again[0]["dictionary"], studies[0]["dictionary"])
        self.assertEqual(late[0]["dictionary"], studies[0]["dictionary"])
        self.assertNotIn("dictionary", studies[1])

    def test_deadline_stops_downloads(self):
        def offline(url):
            raise AssertionError("no downloads after the deadline")
        studies = [cf.normalize_study(FHIR_STUDY)]
        with tempfile.TemporaryDirectory() as tmp:
            self.assertEqual(cf.add_dictionaries(studies, fetcher=offline, delay=0, cache_dir=tmp, deadline=0), 0)
            self.assertEqual(os.listdir(tmp), [])
        self.assertNotIn("dictionary", studies[0])

    def test_dictionary_reorders_results(self):
        q = "heart studies with LDL cholesterol"
        with_dict = cf.search(cf.Index([DICT_X, DICT_Y]), q)
        self.assertEqual([r["accession"] for r in with_dict], ["phs900010", "phs900011"])
        self.assertEqual(with_dict[0]["why"], ["data dictionary mentions: ldl, cholesterol"])
        self.assertEqual(with_dict[1]["why"], [])
        plain = [{k: v for k, v in s.items() if k != "dictionary"} for s in (DICT_X, DICT_Y)]
        without = cf.search(cf.Index(plain), q)
        self.assertEqual([r["accession"] for r in without], ["phs900011", "phs900010"])

    def test_dictionary_round_trips_through_jsonl(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "studies.jsonl")
            cf.write_studies([DICT_X, DICT_Y], path)
            index = cf.Index(cf.read_studies(path))
        self.assertEqual(index.var_docs[0], {"ldl", "cholesterol", "bmi", "body", "mass", "index"})


class ConversationTest(unittest.TestCase):
    def setUp(self):
        index = cf.Index([cf.normalize_study(FHIR_STUDY), STUDY_B, STUDY_C, STUDY_D])
        self.conv = cf.Conversation(index)

    def test_follow_up_adds_constraints(self):
        first = self.conv.ask("type 2 diabetes studies")
        self.assertEqual([r["accession"] for r in first][:2], ["phs900001", "phs900002"])
        results = self.conv.ask("only those with whole genome sequencing")
        self.assertEqual(self.conv.query["data_types"], {"wgs"})
        self.assertEqual(self.conv.query["tokens"], ["type", "diabetes", "whole", "genome", "sequencing"])
        self.assertEqual([r["accession"] for r in results], ["phs900002", "phs900001", "phs900003", "phs001218"])
        self.assertIn("has wgs data", results[0]["why"])

    def test_what_about_changes_topic_and_keeps_constraints(self):
        self.conv.ask("type 2 diabetes with whole genome sequencing")
        results = self.conv.ask("what about breast cancer?")
        self.assertEqual(self.conv.query["tokens"], ["breast", "cancer"])
        self.assertEqual(self.conv.query["data_types"], {"wgs"})
        self.assertEqual(results[0]["accession"], "phs900003")

    def test_what_about_replaces_constraints_of_the_same_kind(self):
        self.conv.ask("type 2 diabetes in African Americans")
        self.conv.ask("what about East Asian participants?")
        self.assertEqual(self.conv.query["ancestry"], [{"EAS"}])
        self.conv.ask("and also European")
        self.assertEqual(self.conv.query["ancestry"], [{"EAS"}, {"EUR"}])

    def test_new_question_and_reset(self):
        self.conv.ask("type 2 diabetes with whole genome sequencing")
        self.conv.ask("breast cancer exome")
        self.assertEqual(self.conv.query["data_types"], {"wes"})
        self.assertNotIn("wgs", self.conv.query["data_types"])
        self.conv.reset()
        self.assertIsNone(self.conv.query)
        self.assertFalse(cf.is_follow_up("breast cancer"))
        self.assertTrue(cf.is_follow_up("Only those with WGS"))


DEV_STUDIES = [
    {"accession": "phs1", "mesh": ["D003924"],
     "mesh_terms": {"D003924": ["Diabetes Mellitus, Type 2", "Type 2 Diabetes"]},
     "data_types": ["genotypes", "wgs"], "subjects": 2500, "ancestry": {"AFA": 900}},
    {"accession": "phs2", "mesh": ["D003924"],
     "mesh_terms": {"D003924": ["Diabetes Mellitus, Type 2", "Type 2 Diabetes"]},
     "data_types": ["genotypes"], "subjects": 300, "ancestry": {}},
    {"accession": "phs3", "mesh": ["D001943"], "mesh_terms": {"D001943": ["Breast Neoplasms", "Breast Cancer"]},
     "data_types": ["rnaseq"], "subjects": 150},
    {"accession": "phs4", "mesh": [], "mesh_terms": {}},
]


class DevsetTest(unittest.TestCase):
    def test_question_text_parses_back(self):
        text = cf._dev_question("Type 2 Diabetes", "whole genome sequencing", 1000, "African American")
        self.assertEqual(text, "Which dbGaP studies have whole genome sequencing data on at least 1,000 "
                               "African American participants with Type 2 Diabetes?")
        q = cf.parse_query(text)
        self.assertEqual((q["min_subjects"], q["data_types"], q["ancestry"]), (1000, {"wgs"}, [{"AFA"}]))
        self.assertEqual(cf._dev_question("Asthma"), "Which dbGaP studies cover Asthma?")
        self.assertEqual(cf._dev_question("Asthma", size=500),
                         "Which dbGaP studies have at least 500 participants with Asthma?")

    def test_meets_and_sizes(self):
        intended = {"data_type": "wgs", "min_subjects": 1000, "ancestry": ("AFA",)}
        self.assertTrue(cf._meets(DEV_STUDIES[0], intended))
        self.assertFalse(cf._meets(DEV_STUDIES[1], intended))
        self.assertTrue(cf._meets(DEV_STUDIES[1], {}))
        self.assertEqual(cf._nice_size(2500), 2000)
        self.assertEqual(cf._nice_size(1787), 1000)
        self.assertIsNone(cf._nice_size(50))
        self.assertIsNone(cf._nice_size(None))

    def test_make_devset(self):
        queries, qrels = cf.make_devset(DEV_STUDIES, n=10, seed=1)
        self.assertEqual(len(queries), 2)
        self.assertEqual(cf.make_devset(DEV_STUDIES, n=10, seed=1), (queries, qrels))
        by_q = {}
        for qid, acc, grade in qrels:
            by_q.setdefault(qid, {})[acc] = grade
        for item in queries:
            judged = by_q[item["id"]]
            self.assertIn(2, judged.values())
            self.assertTrue(set(judged.values()) <= {1, 2})
            self.assertTrue(cf.parse_query(item["query"])["tokens"])
            if item["mesh"] == "D003924":
                self.assertEqual(set(judged), {"phs1", "phs2"})
                self.assertIn("Type 2 Diabetes", item["query"])
                self.assertNotIn("Diabetes Mellitus, Type 2", item["query"])
            else:
                self.assertEqual(judged, {"phs3": 2})
        self.assertEqual(len(cf.make_devset(DEV_STUDIES, n=1, seed=1)[0]), 1)
        self.assertEqual(cf.make_devset(DEV_STUDIES, n=10, max_group=1)[0][0]["mesh"], "D001943")


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


BENCH_QUERIES = [("q1", Q_DIABETES), ("q2", Q_BREAST)]
BENCH_QRELS = {"q1": {"phs900002": 2, "phs900001": 1}, "q2": {"phs900003": 1}}


class BenchTest(unittest.TestCase):
    def test_bench_compares_settings_and_restores_them(self):
        studies = [cf.normalize_study(FHIR_STUDY), STUDY_B, STUDY_C, STUDY_D]
        rows = cf.bench(studies, BENCH_QUERIES, BENCH_QRELS)
        by_name = {row["config"]: row for row in rows}
        self.assertEqual([row["config"] for row in rows], [name for name, _ in cf.BENCH_CONFIGS])
        base = by_name["baseline"]
        self.assertEqual((base["ndcg"], base["mrr"], base["recall"], base["questions"]), (1.0, 1.0, 1.0, 2))
        # Text alone puts the GWAS ahead of the WGS study the question asks for.
        expected = ((1 + 3 / math.log2(3)) / (3 + 1 / math.log2(3)) + 1) / 2
        self.assertAlmostEqual(by_name["text only"]["ndcg"], round(expected, 4))
        self.assertEqual((cf.W_TEXT, cf.W_CONSTRAINTS, cf.W_VARS, cf.UNKNOWN), (0.6, 0.4, 0.2, 0.3))

    def test_mrr_recall(self):
        self.assertEqual(cf._mrr_recall(["x", "a", "b"], {"a": 1, "b": 2, "c": 1}, 10), (0.5, 2 / 3.0))
        self.assertEqual(cf._mrr_recall([], {"a": 1}, 10), (0.0, 0.0))


class CensusTest(unittest.TestCase):
    def setUp(self):
        self.c = cf.census([cf.normalize_study(FHIR_STUDY), STUDY_B, STUDY_C, STUDY_D])

    def test_consent_codes(self):
        self.assertEqual(cf.consent_base("DS-CVD-IRB-NPU-MDS"), "DS")
        self.assertEqual(cf.consent_base("GRU-COL"), "GRU")
        self.assertEqual(cf.consent_base("NRES"), "NRES")
        self.assertEqual(cf.consent_base("EA-IRB-NPU-MDS"), "other")
        self.assertEqual(cf.most_open(["DS-CVD-IRB-NPU-MDS", "EA-IRB-NPU-MDS"]), "DS")
        self.assertEqual(cf.most_open(["HMB-IRB", "GRU"]), "GRU")
        self.assertIsNone(cf.most_open([]))

    def test_counts(self):
        c = self.c
        self.assertEqual((c["studies"], c["with_subjects"], c["subjects_total"]), (4, 4, 7887))
        self.assertEqual((c["with_consents"], c["with_ancestry"], c["studies_for_profit_ok"]), (4, 3, 2))
        self.assertEqual(c["consent_groups"], {"DS": 1, "other": 1, "GRU": 2, "HMB": 1})
        self.assertEqual(c["studies_by_most_open"], {"DS": 1, "GRU": 2, "HMB": 1})
        self.assertEqual(c["consent_modifiers"], {"IRB": 3, "NPU": 3, "MDS": 2, "COL": 1})
        self.assertEqual(c["ancestry_total"], {"EUR": 5076, "AFA": 2368, "AFO": 9, "LAC": 12, "OAS": 5, "OTR": 7})
        self.assertEqual(c["ancestry_by_most_open"]["AFA"], {"DS": 768, "GRU": 900, "HMB": 700})
        self.assertEqual(c["ancestry_for_profit"], {"EUR": 4000, "AFA": 900})
        self.assertEqual(c["ancestry_with_wgs"]["AFA"], 1468)
        self.assertEqual(c["data_types"], {"genotypes": 4, "wgs": 2, "wes": 1, "rnaseq": 1})
        self.assertEqual((c["with_sex"], c["sex_total"]), (0, {}))

    def test_markdown(self):
        text = cf.census_markdown(self.c)
        self.assertIn("| AFA | 2,368 | 31.7% | 38.0% | 67.6% | 38.0% |", text)
        self.assertIn("| GRU | 2 | 2 |", text)
        self.assertIn("2 of 4 studies with consent groups (50.0%)", text)
        self.assertLess(text.index("| EUR |"), text.index("| AFA |"))
        with_sex = cf.census([dict(STUDY_B, sex={"male": 737, "female": 1050})])
        self.assertIn("1,050 women, 737 men (58.8% women)", cf.census_markdown(with_sex))


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
            self.assertIn("(2 questions in ", printed.getvalue())
            with contextlib.redirect_stderr(io.StringIO()):
                self.assertEqual(cf.main(["search", "x", "--studies", os.path.join(tmp, "missing.jsonl")]), 1)

    def test_chat_and_devset(self):
        with tempfile.TemporaryDirectory() as tmp:
            studies = os.path.join(tmp, "studies.jsonl")
            cf.write_studies([cf.normalize_study(FHIR_STUDY), STUDY_B, STUDY_C, STUDY_D], studies)
            turns = io.StringIO("type 2 diabetes studies\nonly those with whole genome sequencing\nreset\n")
            with mock.patch("sys.stdin", turns), contextlib.redirect_stdout(io.StringIO()) as printed:
                self.assertEqual(cf.main(["chat", "--studies", studies]), 0)
            text = printed.getvalue()
            self.assertIn("Studies that may fit: type 2 diabetes studies; only those with whole genome sequencing", text)
            self.assertIn("1. phs900002.v1.p1 Diabetes Heart Study WGS (800 subjects)", text)
            self.assertIn("(new question)", text)

            q_out = os.path.join(tmp, "silver_queries.jsonl")
            r_out = os.path.join(tmp, "silver_qrels.txt")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(cf.main(["devset", "--studies", studies, "--queries-out", q_out,
                                          "--qrels-out", r_out]), 0)
            with open(r_out, encoding="utf-8") as f:
                self.assertEqual(f.read(), "dev001 0 phs001218 2\n")
            self.assertEqual(cf.read_queries(q_out)[0][0], "dev001")

    def test_census_and_bench_commands(self):
        with tempfile.TemporaryDirectory() as tmp:
            studies = os.path.join(tmp, "studies.jsonl")
            queries = os.path.join(tmp, "queries.jsonl")
            qrels = os.path.join(tmp, "qrels.txt")
            cf.write_studies([cf.normalize_study(FHIR_STUDY), STUDY_B, STUDY_C, STUDY_D], studies)
            with open(queries, "w", encoding="utf-8") as f:
                f.write(json.dumps({"id": "q2", "query": Q_BREAST}) + "\n")
            with open(qrels, "w", encoding="utf-8") as f:
                f.write("q2 0 phs900003 1\n")
            prefix = os.path.join(tmp, "census")
            bench_out = os.path.join(tmp, "bench.json")
            with contextlib.redirect_stdout(io.StringIO()) as printed:
                self.assertEqual(cf.main(["census", "--studies", studies, "--out", prefix]), 0)
                self.assertEqual(cf.main(["bench", "--studies", studies, "--queries", queries,
                                          "--qrels", qrels, "--out", bench_out]), 0)
            with open(prefix + ".json", encoding="utf-8") as f:
                self.assertEqual(json.load(f)["studies"], 4)
            self.assertTrue(os.path.exists(prefix + ".md"))
            with open(bench_out, encoding="utf-8") as f:
                saved = json.load(f)
            self.assertEqual((saved["studies"], saved["with_dictionary"]), (4, 0))
            self.assertEqual(saved["results"][0]["ndcg"], 1.0)
            self.assertIn("# Census of public dbGaP studies", printed.getvalue())
            self.assertIn("baseline\t1.0000\t1.0000\t1.0000\t", printed.getvalue())


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
