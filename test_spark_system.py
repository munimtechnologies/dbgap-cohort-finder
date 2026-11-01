# Tests for spark_system.py (needs cohort_finder.py, snapshot.py, sentence_need.py, wording_fix.py,
# spark_submit.py, spark_manifest.py and test_snapshot.py next to it).
# Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

import spark_system as sy
from test_snapshot import Corpus
from test_spark_submit import OFFICIAL


class SystemTest(Corpus):
    def setUp(self):
        self.dir = tempfile.mkdtemp()
        self.index = os.path.join(self.dir, "index")
        self.app = os.path.join(self.dir, "app")
        os.makedirs(self.app)
        for name in sy.CODE_FILES:
            with open(os.path.join(self.app, name), "w", encoding="utf-8") as f:
                f.write("# %s\n" % name)

    def tearDown(self):
        shutil.rmtree(self.dir)

    def fake_survey(self, tar, index):
        # Stands in for snapshot_survey.py: puts the test corpus where the survey writes it.
        self.assertEqual(tar, "dbgap.tar.gz")
        for src, rel in zip(self.paths, sy.INDEX_FILES):
            os.makedirs(os.path.dirname(os.path.join(index, rel)), exist_ok=True)
            shutil.copyfile(src, os.path.join(index, rel))

    def test_build_writes_manifest(self):
        m = sy.build("dbgap.tar.gz", self.index, app=self.app, run_survey=self.fake_survey)
        self.assertEqual([e["path"] for e in m["index"]["files"]], sorted(sy.INDEX_FILES))
        self.assertEqual(len(m["code"]["files"]), len(sy.CODE_FILES))
        self.assertTrue(all("content_sha256" in e for e in m["index"]["files"] if e["path"].endswith(".gz")))
        with open(os.path.join(self.index, sy.MANIFEST), encoding="utf-8") as f:
            self.assertEqual(json.load(f), m)
        self.assertEqual({s for _, _, s in sy.verify(self.index, app=self.app)}, {"same"})

    def test_verify_finds_changes(self):
        sy.build("dbgap.tar.gz", self.index, app=self.app, run_survey=self.fake_survey)
        with open(os.path.join(self.app, "snapshot.py"), "a", encoding="utf-8") as f:
            f.write("# edited\n")
        os.remove(os.path.join(self.index, "out", "studies.jsonl"))
        status = {(part, path): s for part, path, s in sy.verify(self.index, app=self.app)}
        self.assertEqual(status[("code", "snapshot.py")], "differs")
        self.assertEqual(status[("index", "out/studies.jsonl")], "missing")
        self.assertEqual(status[("index", "data/variables.jsonl.gz")], "same")

    def test_run_and_check_use_the_index(self):
        sy.build("dbgap.tar.gz", self.index, app=self.app, run_survey=self.fake_survey)
        needs, out = os.path.join(self.dir, "needs.jsonl"), os.path.join(self.dir, "sub.jsonl")
        with open(needs, "w", encoding="utf-8") as f:
            f.write(json.dumps({"info_need_id": "dbT2_1", "info_need": OFFICIAL}) + "\n")
        old = os.environ.get("SPARK_INDEX")
        os.environ["SPARK_INDEX"] = self.index
        try:
            with redirect_stdout(io.StringIO()) as buf:
                self.assertEqual(sy.main(["run", "--needs", needs, "--out", out, "-k", "3"]), 0)
                self.assertEqual(sy.main(["check", "--needs", needs, "--submission", out, "-k", "3"]), 0)
        finally:
            if old is None:
                del os.environ["SPARK_INDEX"]
            else:
                os.environ["SPARK_INDEX"] = old
        self.assertIn("1 needs, 0 problems", buf.getvalue())
        with open(out, encoding="utf-8") as f:
            row = json.loads(f.readline())
        self.assertEqual(row["results"][0], "phs000100.v1.p1")

    def test_index_args(self):
        args = sy.index_args("/index")
        self.assertEqual(args[0::2], ["--studies", "--variables", "--values"])
        self.assertEqual(args[1], os.path.join("/index", "out", "studies.jsonl"))

    def test_code_files_cover_the_ranker(self):
        # Every local module the default ranker imports must be hashed into the manifest.
        for name in ("cohort_finder.py", "snapshot.py", "sentence_need.py", "wording_fix.py", "spark_submit.py"):
            self.assertIn(name, sy.CODE_FILES)
        self.assertEqual(len(sy.CODE_FILES), len(set(sy.CODE_FILES)))


if __name__ == "__main__":
    unittest.main()
