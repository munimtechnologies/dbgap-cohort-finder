"""Tests for abbrev_oos (no snapshot needed). Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license."""

import collections
import unittest

import abbrev_oos as ao


def norm(s):
    return " ".join(s.lower().split())


def uninvert(d):
    if ", " not in d:
        return None
    return " ".join(reversed(d.split(", ")))


def long_form(defs, short):
    counts = defs.get(short)
    if not counts:
        return None, 0
    return sorted(counts.items(), key=lambda kv: (-kv[1], len(kv[0]), kv[0]))[0]


DEFS = {
    "HCC": collections.Counter({"hepatocellular carcinoma": 12}),
    "HC": collections.Counter({"hepatocellular carcinoma": 1, "healthy control": 30}),
    "CC": collections.Counter({"colon cancer": 3}),
    "WGS": collections.Counter({"whole genome sequencing": 50}),
    "ASTHMA": collections.Counter({"asthma": 2}),
}


class PickTest(unittest.TestCase):
    def setUp(self):
        self.rev = ao.reverse_definitions(DEFS, norm)

    def test_reverse(self):
        self.assertEqual(sorted(self.rev["hepatocellular carcinoma"]), [("HC", 1), ("HCC", 12)])

    def test_uninverted_match_and_most_frequent(self):
        p = ao.pick("carcinoma, hepatocellular", self.rev, DEFS, norm, uninvert, long_form, set())
        self.assertEqual(p["abbrev"], "HCC")
        self.assertEqual(p["matched"], "hepatocellular carcinoma")
        self.assertTrue(p["top_matches"])

    def test_skip_and_top_differs(self):
        p = ao.pick("carcinoma, hepatocellular", self.rev, DEFS, norm, uninvert, long_form, {"HCC"})
        self.assertEqual(p["abbrev"], "HC")
        self.assertEqual(p["top"], "healthy control")
        self.assertFalse(p["top_matches"])

    def test_no_pick(self):
        self.assertIsNone(ao.pick("asthma", self.rev, DEFS, norm, uninvert, long_form, set()))
        self.assertIsNone(ao.pick("lung neoplasms", self.rev, DEFS, norm, uninvert, long_form, set()))

    def test_names(self):
        self.assertEqual(ao.disease_names("carcinoma, small cell", norm, uninvert),
                         ["carcinoma, small cell", "small cell carcinoma"])
        self.assertEqual(ao.disease_names("asthma", norm, uninvert), ["asthma"])


def item(source, variant, frame, base, fix, **extra):
    d = {"source": source, "variant": variant, "frame": frame,
         "base": {"ndcg@10": base, "seconds": 1.0}, "fix": {"ndcg@10": fix, "seconds": 2.0}}
    d.update(extra)
    return d


class SummaryTest(unittest.TestCase):
    def test_summary(self):
        items = [item("a", "d0_as_is", "v0_short", 1.0, 1.0), item("b", "d0_as_is", "v0_short", 0.8, 0.8),
                 item("a", "auto", "v0_short", 0.5, 1.0, triggered=True, in_table=False),
                 item("b", "auto", "v0_short", 0.8, 0.7, triggered=True, in_table=True)]
        picks = {"a": {"top_matches": True}, "b": {"top_matches": False}}
        s = ao.summarize(items, picks, frames=("v0_short",))["v0_short"]
        self.assertEqual(s["all"]["needs"], 2)
        self.assertEqual(s["all"]["base"], 0.65)
        self.assertEqual(s["all"]["fix"], 0.85)
        self.assertEqual(s["all"]["fix_minus_base"], 0.2)
        self.assertEqual(s["all"]["base_drop"], 0.25)
        self.assertEqual(s["all"]["recovered"], 0.8)
        self.assertEqual((s["all"]["fix_lower"], s["all"]["fix_higher"]), (1, 1))
        self.assertEqual(s["top_matches"]["needs"], 1)
        self.assertEqual(s["top_differs"]["fix_minus_base"], -0.1)
        self.assertEqual(s["not_triggered"], {"needs": 0})
        self.assertEqual((s["d0_rows"], s["d0_fix_differs"]), (2, 0))


if __name__ == "__main__":
    unittest.main()
