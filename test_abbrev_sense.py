"""Tests for abbrev_sense (no snapshot needed). Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license."""

import collections
import json
import os
import tempfile
import unittest

import abbrev_fix as af
import abbrev_sense as asn


def uninvert(d):
    if ", " not in d:
        return None
    return " ".join(reversed(d.split(", ")))


DEFS = {
    "HCC": collections.Counter({"hepatocellular carcinoma": 12}),
    "HC": collections.Counter({"hepatocellular carcinoma": 1, "healthy control": 30}),
    "OS": collections.Counter({"overall survival": 13, "osteosarcoma": 2}),
    "ASTHMA": collections.Counter({"asthma": 2}),
}


class PickTest(unittest.TestCase):
    def setUp(self):
        self.rev = asn.reverse_definitions(DEFS, af.normalize)

    def test_pick_uninverted_and_skip(self):
        self.assertEqual(asn.pick("carcinoma, hepatocellular", self.rev, af.normalize, uninvert, set()),
                         ("HCC", "hepatocellular carcinoma", 12))
        self.assertEqual(asn.pick("carcinoma, hepatocellular", self.rev, af.normalize, uninvert, {"HCC"}),
                         ("HC", "hepatocellular carcinoma", 1))
        self.assertIsNone(asn.pick("asthma", self.rev, af.normalize, uninvert, set()))

    def test_senses(self):
        s = asn.senses("OS", ["osteosarcoma"], DEFS, {"osteosarcoma"}, af)
        self.assertEqual((s["a_sense"], s["b_sense"]), ("overall survival", "osteosarcoma"))
        self.assertEqual((s["a_matches"], s["b_matches"], s["sense_changed"], s["senses"]), (False, True, True, 2))
        s = asn.senses("HCC", ["carcinoma, hepatocellular", "hepatocellular carcinoma"], DEFS,
                       {"hepatocellular carcinoma"}, af)
        self.assertEqual((s["a_matches"], s["b_matches"], s["sense_changed"]), (True, True, False))


def item(source, variant, frame, base, a, b, **extra):
    d = {"source": source, "variant": variant, "frame": frame,
         "base": {"ndcg@10": base, "seconds": 1.0}, "a": {"ndcg@10": a, "seconds": 2.0},
         "b": {"ndcg@10": b, "seconds": 3.0}}
    d.update(extra)
    return d


class SummaryTest(unittest.TestCase):
    def test_summary(self):
        items = [item("x", "d0_as_is", "v0_short", 1.0, 1.0, 1.0), item("y", "d0_as_is", "v0_short", 1.0, 1.0, 0.5),
                 item("x", "auto", "v0_short", 0.5, 0.0, 1.0, in_table=False),
                 item("y", "auto", "v0_short", 0.8, 0.9, 0.9, in_table=True)]
        picks = {"x": {"sense_changed": True, "a_matches": False}, "y": {"sense_changed": False, "a_matches": True}}
        s = asn.summarize(items, picks, frames=("v0_short",))["v0_short"]
        self.assertEqual(s["all"]["needs"], 2)
        self.assertEqual((s["all"]["base"], s["all"]["a"], s["all"]["b"]), (0.65, 0.45, 0.95))
        self.assertEqual((s["all"]["b_minus_a"], s["all"]["b_minus_base"]), (0.5, 0.3))
        self.assertEqual((s["all"]["b_lower_than_a"], s["all"]["b_higher_than_a"]), (0, 1))
        self.assertEqual(s["sense_changed"]["b_minus_a"], 1.0)
        self.assertEqual(s["sense_same"]["needs"], 1)
        self.assertEqual((s["d0_rows"], s["d0_b_differs_from_base"], s["sense_same_b_differs_from_a"]), (2, 1, 0))
        self.assertEqual(s["all"]["b_seconds"], 3.0)


class DevsetTest(unittest.TestCase):
    def test_devset_diseases(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = os.path.join(tmp, "dev.json")
            with open(path, "w", encoding="utf-8") as f:
                json.dump({"queries": [{"id": "dev001", "query": "q1"}, {"id": "dev002", "query": "q2"}]}, f)

            def decompose(text):
                return ("Lyme Disease", ["k"]) if text == "q1" else None

            self.assertEqual(asn.devset_diseases(path, decompose), {"lyme disease"})


if __name__ == "__main__":
    unittest.main()
