"""Offline tests for phenx_dev_v3.py (no network). Apache-2.0."""
import os
import tempfile
import unittest

import phenx_dev_v3 as v3


class PatientFinderTests(unittest.TestCase):
    def test_harvest_retried_until_it_works_and_kept(self):
        calls, sleeps, attempts = [], [], []
        with tempfile.TemporaryDirectory() as d:
            keep = os.path.join(d, "data")
            os.makedirs(keep)
            out = os.path.join(d, "studies.jsonl")

            def flaky(args, work):
                calls.append(args[0])
                if len(calls) < 3:
                    raise SystemExit("finder failed: harvest")
                with open(out, "w", encoding="utf-8") as f:
                    f.write('{"accession": "phs000001.v3.p1"}\n')
                return "1 studies"

            run = v3.patient_finder(flaky, attempts, sleep=sleeps.append, wait=9, keep_dir=keep,
                                    today=lambda: "20261030")
            self.assertEqual(run(["harvest", "--out", out], d), "1 studies")
            self.assertEqual(sleeps, [9, 9])
            self.assertEqual([a["ok"] for a in attempts], [False, False, True])
            with open(os.path.join(keep, "dbgap-studies-20261030.jsonl"), encoding="utf-8") as f:
                self.assertIn("phs000001", f.read())

    def test_gives_up_after_tries(self):
        attempts, sleeps = [], []

        def broken(args, work):
            raise SystemExit("finder failed: harvest")

        run = v3.patient_finder(broken, attempts, sleep=sleeps.append, tries=3, wait=1)
        with self.assertRaises(SystemExit):
            run(["harvest", "--out", "x"], ".")
        self.assertEqual(len(attempts), 3)
        self.assertEqual(sleeps, [1, 1])

    def test_other_commands_run_once(self):
        attempts, calls = [], []

        def broken(args, work):
            calls.append(args[0])
            raise SystemExit("finder failed: run")

        run = v3.patient_finder(broken, attempts, sleep=lambda s: None)
        with self.assertRaises(SystemExit):
            run(["run", "--queries", "q"], ".")
        self.assertEqual(calls, ["run"])
        self.assertEqual(attempts, [])

    def test_no_keep_dir_is_fine(self):
        attempts = []
        run = v3.patient_finder(lambda args, work: "ok", attempts, keep_dir="/no/such/dir/here")
        self.assertEqual(run(["harvest", "--out", "x"], "."), "ok")
        self.assertEqual(attempts[0]["ok"], True)


if __name__ == "__main__":
    unittest.main()
