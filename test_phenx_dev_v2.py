"""Offline tests for phenx_dev_v2.py (no network). Apache-2.0."""
import os
import tempfile
import unittest
import urllib.error

import phenx_dev as v1
import phenx_dev_v2 as v2

LIST_HTML = ('<li><a href="/protocols/view/590603?origin=browse">12-Step Group Participation</a></li>'
             '<li><a href="/protocols/view/41001?origin=browse">Abdominal &amp; Aortic\n Aneurysm</a></li>'
             '<li><a href="/protocols/view/41001?origin=browse">duplicate later link</a></li>'
             '<li><a href="/protocols/view/30301">no origin, not a list link</a></li>')


class ParseTests(unittest.TestCase):
    def test_read_qrels(self):
        text = "PX030301 0 phs000007 1\nPX030301 0 phs000209 1\nPX180801 0 phs000796 1\n\nnoise line\n"
        self.assertEqual(v2.read_qrels(text), {"PX030301": {"phs000007", "phs000209"},
                                               "PX180801": {"phs000796"}})

    def test_list_names_pads_ids_and_unescapes(self):
        names = v2.list_names(LIST_HTML)
        self.assertEqual(names, {"PX590603": "12-Step Group Participation",
                                 "PX041001": "Abdominal & Aortic Aneurysm"})

    def test_page_protocols_prefers_xlsx_name(self):
        xlsx = {"PX180801": {"name": "Perceived Stress", "studies": {"phs000007"}, "phv": set()}}
        names = {"PX180801": "Perceived Stress - Adult", "PX041001": "Abdominal Aortic Aneurysm"}
        p = v2.page_protocols({"PX180801": {"phs000007", "phs000209"}, "PX041001": {"phs1"},
                               "PX999999": {"phs2"}}, xlsx, names)
        self.assertEqual(p["PX180801"]["name"], "Perceived Stress")
        self.assertEqual(p["PX180801"]["studies"], {"phs000007", "phs000209"})
        self.assertEqual(p["PX041001"]["name"], "Abdominal Aortic Aneurysm")
        self.assertEqual(p["PX999999"]["name"], "")

    def test_union_queries_first_name_wins_and_skips_unnamed(self):
        a = {"PX2": {"name": "B", "studies": set()}}
        b = {"PX2": {"name": "B2", "studies": set()}, "PX1": {"name": "A", "studies": set()},
             "PX3": {"name": "", "studies": set()}}
        self.assertEqual(v2.union_queries(a, b), [{"id": "PX1", "query": "A"}, {"id": "PX2", "query": "B"}])


class UnionTests(unittest.TestCase):
    def test_union_protocols_merges_studies_and_keeps_names(self):
        xlsx = {"PX1": {"name": "A", "studies": {"s1"}, "phv": {"v"}},
                "PX9": {"name": "Old", "studies": {"s9"}, "phv": set()}}
        pages = {"PX1": {"name": "A2", "studies": {"s3"}, "phv": set()},
                 "PX2": {"name": "", "studies": {"s2"}, "phv": set()}}
        u = v2.union_protocols(xlsx, pages)
        self.assertEqual(u["PX1"], {"name": "A", "studies": {"s1", "s3"}, "phv": set()})
        self.assertEqual(u["PX9"]["studies"], {"s9"})
        self.assertEqual(u["PX2"]["name"], "")
        self.assertEqual(xlsx["PX1"]["studies"], {"s1"})  # inputs untouched

    def test_unlisted_facts(self):
        xlsx = {"PX1": {"name": "A", "studies": {"s1"}, "phv": set()},
                "PX8": {"name": "Old", "studies": {"s1", "s8"}, "phv": set()}}
        pages = {"PX1": {"name": "A", "studies": {"s1"}, "phv": set()}}
        f = v2.unlisted_facts(xlsx, pages, {"PX1": "A"})
        self.assertEqual(f, {"xlsx_protocols_unlisted": 1, "xlsx_unlisted_ids": ["PX8"],
                             "xlsx_unlisted_studies": 2, "xlsx_unlisted_studies_not_on_any_page": 1})


class FetchTests(unittest.TestCase):
    def test_longer_retries_patches_v1_once(self):
        saved = v1.NEW_FETCH
        try:
            self.assertTrue(v2.longer_retries())
            self.assertIn(v2.NEW_TRIES, v1.NEW_FETCH)
            self.assertNotIn(v2.OLD_TRIES, v1.NEW_FETCH)
            self.assertFalse(v2.longer_retries())
            text, done = v1.patch_finder("x\n" + v1.OLD_FETCH)
            self.assertTrue(done)
            self.assertIn("tries=6, wait=30", text)
        finally:
            v1.NEW_FETCH = saved

    def test_fetch_published_waits_out_404_only(self):
        calls, sleeps = [], []

        def flaky(url):
            calls.append(url)
            if len(calls) < 3:
                raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)
            return b"ok"

        self.assertEqual(v2.fetch_published("u", fetch=flaky, sleep=sleeps.append, wait=7), b"ok")
        self.assertEqual(sleeps, [7, 7])

        def broken(url):
            raise urllib.error.HTTPError(url, 500, "err", {}, None)

        with self.assertRaises(urllib.error.HTTPError):
            v2.fetch_published("u", fetch=broken, sleep=sleeps.append)

        def missing(url):
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)

        with self.assertRaises(urllib.error.HTTPError):
            v2.fetch_published("u", fetch=missing, sleep=lambda s: None, tries=2)


class ScoreTests(unittest.TestCase):
    def setUp(self):
        self.corpus = {"s1", "s2", "s3", "s4"}
        self.xlsx = {"PX1": {"name": "A", "studies": {"s1"}, "phv": set()},
                     "PX2": {"name": "B", "studies": {"s2"}, "phv": set()}}
        self.pages = {"PX1": {"name": "A", "studies": {"s1", "s3"}, "phv": set()},
                      "PX2": {"name": "B", "studies": {"s2"}, "phv": set()},
                      "PX3": {"name": "C", "studies": {"s4"}, "phv": set()}}
        self.run = {"PX1": ["s3", "s1"], "PX2": ["s2"], "PX3": ["s4"]}

    def test_fuller_labels_credit_a_found_study(self):
        x, _, _ = v2.score_label_set(self.xlsx, self.run, self.corpus)
        p, _, _ = v2.score_label_set(self.pages, self.run, self.corpus)
        self.assertEqual(x["questions"], 2)
        self.assertEqual(p["questions"], 3)
        self.assertLess(x["systems"]["finder"]["ndcg10"], p["systems"]["finder"]["ndcg10"])
        self.assertIn("prior_loo", p["systems"])

    def test_only_restricts_questions(self):
        block, per, qrels = v2.score_label_set(self.pages, self.run, self.corpus, only={"PX1", "PX2"})
        self.assertEqual(block["questions"], 2)
        self.assertEqual(set(qrels), {"PX1", "PX2"})
        self.assertEqual(set(per["finder"]), {"PX1", "PX2"})

    def test_studies_outside_corpus_are_dropped(self):
        pages = {"PX1": {"name": "A", "studies": {"gone"}, "phv": set()}}
        block, _, qrels = v2.score_label_set(pages, {}, self.corpus)
        self.assertEqual(block["questions"], 0)
        self.assertEqual(qrels, {})

    def test_write_qrels(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "q.txt")
            v2.write_qrels(path, {"PX2": {"s2": 1}, "PX1": {"s3": 1, "s1": 1}})
            with open(path, encoding="utf-8") as f:
                self.assertEqual(f.read(), "PX1 0 s1 1\nPX1 0 s3 1\nPX2 0 s2 1\n")


if __name__ == "__main__":
    unittest.main()
