"""Offline tests for phenx_dev.py (no network). Apache-2.0."""
import io
import os
import tempfile
import unittest
import zipfile

import phenx_dev as pd

HEADER = ["VARIABLE_ID", "VARIABLE_NAME", "PROTOCOL_NAME", "VARIABLE_DESCRIPTION",
          "dbGaP VARIABLE_DESCRIPTION", "dbGaP VARIABLE_ID", "dbGaP STUDY_ID"]


def rows(*body):
    return [HEADER] + [list(r) for r in body]


class LabelTests(unittest.TestCase):
    def test_protocol_studies_unversioned(self):
        p, facts = pd.build_labels(rows(
            ["PX010101010100", "x", "Current Age", "d", "dd", "phv00079232.v4.p3", "phs000200.v9.p3"],
            ["PX010101010200", "x", "Current Age", "d", "dd", "phv00174652.v1.p3", "phs000209.v13.p3"],
            ["PX010201010000", "x", "Birthplace", "d", "dd", "phv00000001.v1.p1", "phs000200.v10.p3"]))
        self.assertEqual(p["PX010101"]["studies"], {"phs000200", "phs000209"})
        self.assertEqual(p["PX010201"]["studies"], {"phs000200"})
        self.assertEqual(p["PX010101"]["name"], "Current Age")
        self.assertEqual(facts["distinct_studies"], 2)
        self.assertEqual(facts["distinct_variables"], 3)
        self.assertEqual(facts["rows_with_swapped_ids"], 0)

    def test_swapped_columns_still_read(self):
        p, facts = pd.build_labels(rows(
            ["PX030301010000", "x", "Alcohol", "d", "dd", "phs000219.v1.p1", "phv00081806.v1.p1"]))
        self.assertEqual(p["PX030301"]["studies"], {"phs000219"})
        self.assertEqual(p["PX030301"]["phv"], {"phv00081806"})
        self.assertEqual(facts["rows_with_swapped_ids"], 1)

    def test_short_rows_and_non_px_rows(self):
        p, facts = pd.build_labels(rows(["PX040101010000", "x", "Weight", "d"], ["note", "", ""]))
        self.assertEqual(p["PX040101"]["studies"], set())
        self.assertEqual(facts["rows_without_study"], 1)
        self.assertEqual(facts["protocols"], 1)

    def test_devset_keeps_only_corpus_studies(self):
        p = {"PX1": {"name": "A", "studies": {"phs1", "phs2"}, "phv": set()},
             "PX2": {"name": "B", "studies": {"phs9"}, "phv": set()}}
        q, qrels = pd.make_devset(p, {"phs1", "phs3"})
        self.assertEqual(q, [{"id": "PX1", "query": "A"}])
        self.assertEqual(qrels, {"PX1": {"phs1": 1}})


class MetricTests(unittest.TestCase):
    def test_ndcg_perfect_and_zero(self):
        self.assertAlmostEqual(pd.ndcg(["a", "b"], {"a", "b"}), 1.0)
        self.assertEqual(pd.ndcg(["c"], {"a"}), 0.0)
        self.assertEqual(pd.ndcg([], set()), 0.0)

    def test_ndcg_second_place(self):
        self.assertAlmostEqual(pd.ndcg(["x", "a"], {"a"}), 1 / pd.math.log2(3))

    def test_condensed_drops_unjudged(self):
        ranked = ["u1", "a", "u2", "b"]
        self.assertEqual(pd.condensed(ranked, {"a", "b", "c"}), ["a", "b"])
        self.assertAlmostEqual(pd.ndcg(pd.condensed(ranked, {"a", "b"}), {"a", "b"}), 1.0)

    def test_recall_and_rr(self):
        self.assertEqual(pd.recall(["a", "x", "b"], {"a", "b", "c", "d"}, 2), 0.25)
        self.assertEqual(pd.rr(["x", "y", "a"], {"a"}, 10), 1 / 3.0)
        self.assertEqual(pd.rr(["x"], {"a"}, 10), 0.0)

    def test_score_system_missing_question_is_zero(self):
        mean, per = pd.score_system({}, {"q1": {"a": 1}}, {"a"})
        self.assertEqual(mean["ndcg10"], 0.0)
        self.assertEqual(mean["questions_with_no_results"], 1)


class PriorTests(unittest.TestCase):
    def test_leave_one_out(self):
        p = {"PX1": {"studies": {"big", "q_only"}}, "PX2": {"studies": {"big", "mid"}},
             "PX3": {"studies": {"big", "mid"}}, "PX4": {"studies": {"gone"}}}
        self.assertEqual(pd.prior_ranking(p, "PX1", {"big", "mid", "q_only"}), ["big", "mid"])
        self.assertEqual(pd.prior_ranking(p, "PX2", {"big", "mid", "q_only"}), ["big", "mid", "q_only"])


class PatchTests(unittest.TestCase):
    def test_patch_applies_once_or_not_at_all(self):
        text, done = pd.patch_finder("import x\n" + pd.OLD_FETCH + "\nrest\n")
        self.assertTrue(done)
        self.assertIn("def decode_body(raw):", text)
        self.assertNotIn(pd.OLD_FETCH, text)
        same, done = pd.patch_finder("def fetch_json(url, timeout=60, tries=3):\n    pass\n")
        self.assertFalse(done)
        self.assertEqual(same, "def fetch_json(url, timeout=60, tries=3):\n    pass\n")


class IoTests(unittest.TestCase):
    def test_read_run_strips_versions_and_orders_by_rank(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "run.txt")
            with open(path, "w", encoding="utf-8") as f:
                f.write("q1 Q0 phs2 2 0.5 t\nq1 Q0 phs1.v3.p1 1 0.9 t\n")
            self.assertEqual(pd.read_run(path), {"q1": ["phs1", "phs2"]})

    def test_read_xlsx_shared_and_inline_strings(self):
        buf = io.BytesIO()
        with zipfile.ZipFile(buf, "w") as z:
            z.writestr("xl/workbook.xml",
                       '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" '
                       'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">'
                       '<sheets><sheet name="With mappings" sheetId="1" r:id="rId1"/></sheets></workbook>')
            z.writestr("xl/_rels/workbook.xml.rels",
                       '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                       '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/></Relationships>')
            z.writestr("xl/sharedStrings.xml",
                       '<sst xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
                       '<si><t>VARIABLE_ID</t></si><si><t>PX010101010100</t></si></sst>')
            z.writestr("xl/worksheets/sheet1.xml",
                       '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"><sheetData>'
                       '<row r="1"><c r="A1" t="s"><v>0</v></c></row>'
                       '<row r="2"><c r="A2" t="s"><v>1</v></c><c r="C2" t="inlineStr"><is><t>Age</t></is></c></row>'
                       '</sheetData></worksheet>')
        sheets = pd.read_xlsx(buf.getvalue())
        self.assertEqual(sheets["With mappings"], [["VARIABLE_ID"], ["PX010101010100", "", "Age"]])


if __name__ == "__main__":
    unittest.main()
