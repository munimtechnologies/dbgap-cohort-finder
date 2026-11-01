"""Tests for wording_pad (standard library only; no snapshot data needed)."""

import unittest

import cohort_finder as cf
import wording_pad as wp


class PadTest(unittest.TestCase):
    def test_fills_in_order_without_repeats(self):
        self.assertEqual(wp.pad(["a", "b"], ["b", "c", "a", "d"], k=10), ["a", "b", "c", "d"])

    def test_caps_at_k(self):
        self.assertEqual(wp.pad(["a", "b"], ["c", "d", "e"], k=3), ["a", "b", "c"])
        self.assertEqual(wp.pad(["a", "b", "c", "d"], ["e"], k=3), ["a", "b", "c"])

    def test_full_first_list_unchanged(self):
        first = ["s%d" % i for i in range(100)]
        self.assertEqual(wp.pad(first, ["x", "y"]), first)

    def test_empty_lists(self):
        self.assertEqual(wp.pad([], ["a"], k=5), ["a"])
        self.assertEqual(wp.pad(["a"], [], k=5), ["a"])

    def test_never_lowers_ndcg(self):
        relevance = {"a": 2, "b": 1, "c": 1, "d": 2, "e": 1}
        cases = [(["x", "a"], ["d", "b", "c"]), (["b"], ["x", "y", "a"]), ([], ["e", "a"]),
                 (["a", "d", "b", "c", "e"], ["x"])]
        for first, second in cases:
            padded = wp.pad(first, second, k=100)
            for depth in (1, 3, 10, 100):
                self.assertGreaterEqual(cf.ndcg(padded, relevance, depth) + 1e-12,
                                        cf.ndcg(first, relevance, depth), (first, second, depth))


class SummaryTest(unittest.TestCase):
    def item(self, need, variant, base, fix, pad, lengths=(100, 40, 100)):
        out = {"id": need, "variant": variant, "added": lengths[2] - lengths[1]}
        for name, value, length in zip(wp.SYSTEMS, (base, fix, pad), lengths):
            out[name] = {"ndcg@10": value, "ndcg@100": value, "length": length, "seconds": 1.0}
        return out

    def test_summarize(self):
        per = [self.item("q1", "v0", 0.5, 1.0, 1.0), self.item("q2", "v0", 1.0, 0.5, 0.5),
               self.item("q1", "v1", 0.0, 1.0, 1.0, (90, 100, 100)), self.item("q2", "v1", 1.0, 1.0, 1.0)]
        s = wp.summarize(per, ("v0", "v1"), k=100)
        self.assertEqual(s["base"]["variants"]["v0"]["ndcg@10"], 0.75)
        self.assertEqual(s["base"]["variants"]["v1"]["ndcg@10"], 0.5)
        self.assertEqual(s["base"]["mean_ndcg@10"], 0.625)
        self.assertEqual(s["base"]["spread_ndcg@10"], 0.25)
        self.assertEqual(s["base"]["short_lists"], 1)
        self.assertEqual(s["fix"]["short_lists"], 3)
        self.assertEqual(s["pad"]["short_lists"], 0)
        self.assertEqual(s["pad"]["mean_seconds"], 1.0)


if __name__ == "__main__":
    unittest.main()
