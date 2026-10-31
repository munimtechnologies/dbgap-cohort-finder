# Tests for rerank_check.py (standard library only; no model, no network).
# Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
import unittest

import rerank_check as rc


def res(acc, score, fails=0, weak=0):
    return {"accession": acc, "score": score, "fails": fails, "weak_disease": weak}


class FakeEncoder:
    """Scores a passage by how often the query's first word appears in it."""

    def score(self, query, passages):
        word = query.split()[0].lower()
        return [float(p.lower().count(word)) for p in passages]


class FuseTest(unittest.TestCase):
    def setUp(self):
        self.results = [res("phs000003.v1.p1", 0.9), res("phs000001.v1.p1", 0.5),
                        res("phs000002.v1.p1", 0.5), res("phs000004.v1.p1", 0.8, weak=1),
                        res("phs000005.v1.p1", 0.7, fails=1)]

    def test_w0_keeps_rule_order(self):
        ce = [0.0, 5.0, 9.0, 9.0, 9.0]
        self.assertEqual(rc.fuse(self.results, ce, 0.0), [r["accession"] for r in self.results])

    def test_w1_reorders_only_within_groups(self):
        ce = [0.0, 1.0, 5.0, 9.0, 9.0]
        self.assertEqual(rc.fuse(self.results, ce, 1.0),
                         ["phs000002.v1.p1", "phs000001.v1.p1", "phs000003.v1.p1",
                          "phs000004.v1.p1", "phs000005.v1.p1"])

    def test_tail_is_untouched(self):
        ce = [0.0, 0.0, 9.0]
        self.assertEqual(rc.fuse(self.results, ce, 1.0, n=3),
                         ["phs000002.v1.p1", "phs000003.v1.p1", "phs000001.v1.p1",
                          "phs000004.v1.p1", "phs000005.v1.p1"])

    def test_constant_scores_fall_back_to_accession(self):
        same = [res("phs000002.v1.p1", 0.5), res("phs000001.v1.p1", 0.5)]
        self.assertEqual(rc.fuse(same, [1.0, 1.0], 0.5), ["phs000001.v1.p1", "phs000002.v1.p1"])
        self.assertEqual(rc.fuse([], [], 0.5), [])

    def test_minmax(self):
        self.assertEqual(rc.minmax([2.0, 4.0, 3.0]), [0.0, 1.0, 0.5])
        self.assertEqual(rc.minmax([1.0, 1.0]), [0.0, 0.0])


class PassageTest(unittest.TestCase):
    def test_passage(self):
        study = {"title": "Lung Study.", "conditions": ["Adenocarcinoma of Lung", ""],
                 "description": "x" * 2000}
        p = rc.passage(study)
        self.assertTrue(p.startswith("Lung Study. Conditions: Adenocarcinoma of Lung. x"))
        self.assertEqual(p.count("x"), rc.DESC_CHARS)
        self.assertEqual(rc.passage({"title": "Only"}), "Only")


class MeasureTest(unittest.TestCase):
    def test_measure_and_summarize(self):
        import types
        import sys
        fake_cf = types.ModuleType("cohort_finder")

        def ndcg(ranked, rels, k):
            return 1.0 if ranked and rels.get(ranked[0]) else 0.0
        fake_cf.ndcg = ndcg
        real_cf = sys.modules.get("cohort_finder")
        sys.modules["cohort_finder"] = fake_cf
        try:
            studies = {"phs000001.v1.p1": {"title": "asthma asthma cohort"},
                       "phs000002.v1.p1": {"title": "heart study"}}

            def rank(index, query):
                return [res("phs000002.v1.p1", 0.9), res("phs000001.v1.p1", 0.8)]

            rows = rc.measure(None, [("q1", "asthma studies")], {"q1": {"phs000001.v1.p1": 2}},
                              FakeEncoder(), rank, lambda t: {}, studies, example="phs000001.v1.p1")
            self.assertTrue(rows[0]["w0_same_as_rule"])
            # At w = 0.5 the two fused scores tie (0.5 each), so the rule order stays.
            self.assertEqual(rows[0]["ndcg"], {"0.0": 0.0, "0.25": 0.0, "0.5": 0.0, "1.0": 1.0})
            self.assertEqual(rows[0]["example_rank"]["0.0"], 2)
            self.assertEqual(rows[0]["example_rank"]["1.0"], 1)
            s = rc.summarize(rows)
            self.assertEqual(s["w0_differs"], 0)
            self.assertEqual(s["weights"]["1.0"]["higher_than_w0"], 1)
            self.assertEqual(s["weights"]["0.25"]["ndcg@10"], 0.0)
        finally:
            if real_cf is None:
                del sys.modules["cohort_finder"]
            else:
                sys.modules["cohort_finder"] = real_cf


if __name__ == "__main__":
    unittest.main()
