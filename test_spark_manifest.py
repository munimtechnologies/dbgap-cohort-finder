# Tests for spark_manifest.py (standard library only, no network).
# Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
import gzip
import hashlib
import io
import json
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

import spark_manifest as sm

LINES = b'{"study": "phs000001", "phv": "phv00000001.v1"}\n'


def write_gz(path, data, mtime):
    with open(path, "wb") as raw:
        with gzip.GzipFile(filename="variables.jsonl", mode="wb", fileobj=raw, mtime=mtime) as f:
            f.write(data)


class ManifestTest(unittest.TestCase):
    def setUp(self):
        self.a = tempfile.mkdtemp()
        self.b = tempfile.mkdtemp()
        for root, mtime in ((self.a, 1000), (self.b, 2000)):
            os.makedirs(os.path.join(root, "data"))
            with open(os.path.join(root, "studies.jsonl"), "wb") as f:
                f.write(b'{"accession": "phs000001.v3.p1"}\n')
            write_gz(os.path.join(root, "data", "variables.jsonl.gz"), LINES, mtime)

    def tearDown(self):
        shutil.rmtree(self.a)
        shutil.rmtree(self.b)

    def test_entry_hashes(self):
        e = sm.entry(self.a, "studies.jsonl")
        self.assertEqual(e["sha256"], hashlib.sha256(b'{"accession": "phs000001.v3.p1"}\n').hexdigest())
        self.assertNotIn("content_sha256", e)
        g = sm.entry(self.a, os.path.join("data", "variables.jsonl.gz"))
        self.assertEqual(g["path"], "data/variables.jsonl.gz")
        self.assertEqual(g["content_sha256"], hashlib.sha256(LINES).hexdigest())
        self.assertEqual(g["content_bytes"], len(LINES))

    def test_folder_expands_sorted(self):
        m = sm.make(self.a, ["studies.jsonl", "data"])
        self.assertEqual([e["path"] for e in m["files"]], ["data/variables.jsonl.gz", "studies.jsonl"])

    def test_gzip_time_is_same_content(self):
        m = sm.make(self.a, ["studies.jsonl", "data"])
        self.assertEqual(dict(sm.verify(self.b, m)),
                         {"data/variables.jsonl.gz": "same content", "studies.jsonl": "same"})
        self.assertEqual(dict(sm.verify(self.a, m))["data/variables.jsonl.gz"], "same")

    def test_differs_and_missing(self):
        m = sm.make(self.a, ["studies.jsonl", "data"])
        write_gz(os.path.join(self.b, "data", "variables.jsonl.gz"), LINES + LINES, 1000)
        os.remove(os.path.join(self.b, "studies.jsonl"))
        self.assertEqual(dict(sm.verify(self.b, m)),
                         {"data/variables.jsonl.gz": "differs", "studies.jsonl": "missing"})

    def test_cli(self):
        out = os.path.join(self.a, "manifest.json")
        with redirect_stdout(io.StringIO()):
            self.assertEqual(sm.main(["make", "--root", self.a, "--out", out, "studies.jsonl", "data"]), 0)
        with open(out, encoding="utf-8") as f:
            self.assertEqual(len(json.load(f)["files"]), 2)
        buf = io.StringIO()
        with redirect_stdout(buf):
            self.assertEqual(sm.main(["verify", "--root", self.b, "--manifest", out]), 0)
            self.assertEqual(sm.main(["verify", "--root", self.b, "--manifest", out, "--strict"]), 1)
        self.assertIn("data/variables.jsonl.gz: same content", buf.getvalue())


if __name__ == "__main__":
    unittest.main()
