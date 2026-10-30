# Tests for spark_submit.py (needs cohort_finder.py, snapshot.py, sentence_need.py and test_snapshot.py next to it).
# Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
import json
import os
import tempfile
import unittest

import sentence_need as sen
import spark_submit as ss
from test_snapshot import LUNG_NEED, Corpus

OFFICIAL = ("Find dbGaP studies involving adult participants with lung adenocarcinoma as the primary disease, "
            "where participant-level data include a history of smoking or smoking exposure and whole genomic "
            "sequences.")
NEEDS = [("dbT2_1", OFFICIAL), ("ex1", LUNG_NEED), ("q3", "adults with asthma")]


def record(need_id="dbT2_1", need=OFFICIAL, results=("phs000100.v1.p1",), **meta):
    m = {"team_id": "team-001", "submission_id": "team-001-run-01", "info_need_id": need_id, "info_need": need}
    m.update(meta)
    return json.dumps({"metadata": m, "results": list(results)})


class CheckTest(unittest.TestCase):
    def test_task_example_passes(self):
        # The record in the Task 2 description, page 5, with its "...." filled in.
        self.assertEqual(ss.check([record()], NEEDS[:1]), [])

    def test_problems(self):
        known = {"phs000100.v1.p1"}
        cases = [
            ("not json", "not JSON"),
            (json.dumps({"metadata": {}, "results": [], "extra": 1}), "keys must be"),
            (json.dumps({"metadata": {"team_id": "t"}, "results": []}), "metadata keys"),
            (record(team_id=""), "non-empty strings"),
            (record(need_id="zz"), "not in the needs file"),
            (record(need="Find studies."), "differs from the original"),
            (record(results=("phs000100.v1.p1", "phs000100.v1.p1")), "repeated accessions"),
            (record(results=("phs100",)), "not study accessions"),
            (record(results=("phs000999.v1.p1",)), "not in the snapshot"),
            ("", "empty"),
        ]
        for line, expected in cases:
            problems = ss.check([line], NEEDS[:1], known)
            self.assertTrue(any(expected in p for p in problems), (line, problems))

    def test_missing_and_repeated_needs(self):
        problems = ss.check([record(), record()], NEEDS[:2])
        self.assertTrue(any("repeated" in p for p in problems))
        self.assertIn("need ex1 has no line", problems)

    def test_bytes_and_k(self):
        self.assertEqual(ss.check([record().encode("utf-8")], NEEDS[:1]), [])
        self.assertIn("line 1: not UTF-8", ss.check([b"\xff\xfe"], NEEDS[:1]))
        problems = ss.check([record(results=("phs000100.v1.p1", "phs000200.v1.p1"))], NEEDS[:1], k=1)
        self.assertTrue(any("more than 1" in p for p in problems))


class RunTest(Corpus):
    def test_same_as_sentence_need(self):
        for text in (OFFICIAL, LUNG_NEED):
            expected = [r["accession"] for r in sen.rank(self.index, sen.parse_need(text), tier=sen.TIER)]
            self.assertEqual(ss.answer(self.index, text), expected)
        self.assertEqual(ss.answer(self.index, OFFICIAL)[0], "phs000100.v1.p1")

    def test_run_lines_pass_check(self):
        lines, seconds = ss.run(self.index, NEEDS, "team-001", "team-001-run-01")
        self.assertEqual(len(lines), 3)
        self.assertEqual(len(seconds), 3)
        self.assertEqual(ss.check(lines, NEEDS, set(self.by_acc)), [])
        first = json.loads(lines[0])
        self.assertEqual(first["metadata"]["info_need_id"], "dbT2_1")
        self.assertEqual(first["metadata"]["info_need"], OFFICIAL)

    def test_cli(self):
        with tempfile.TemporaryDirectory() as d:
            needs, out, stats = (os.path.join(d, n) for n in ("needs.jsonl", "sub.jsonl", "stats.json"))
            with open(needs, "w", encoding="utf-8") as f:
                for need_id, text in NEEDS:
                    f.write(json.dumps({"info_need_id": need_id, "info_need": text}) + "\n")
            base = ["--studies", self.paths[0], "--variables", self.paths[1], "--values", self.paths[2]]
            self.assertEqual(ss.main(base + ["run", "--needs", needs, "--out", out, "--stats", stats, "-k", "3"]), 0)
            with open(stats, encoding="utf-8") as f:
                report = json.load(f)
            self.assertEqual(report["needs"], 3)
            self.assertEqual(report["problems"], [])
            self.assertEqual(report["tier"], sen.TIER)
            with open(out, encoding="utf-8") as f:
                rows = [json.loads(line) for line in f]
            self.assertTrue(all(len(r["results"]) <= 3 for r in rows))
            self.assertEqual(ss.main(base + ["check", "--needs", needs, "--submission", out]), 0)
            with open(out, "a", encoding="utf-8") as f:
                f.write(record(need_id="q3", need="adults with asthma") + "\n")
            self.assertEqual(ss.main(base + ["check", "--needs", needs, "--submission", out]), 1)


if __name__ == "__main__":
    unittest.main()
