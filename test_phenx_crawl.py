import io
import os
import tempfile
import unittest
import zipfile

import phenx_crawl as pc

# Shape copied from a saved PhenX protocol page (phenx-probe-v1, /protocols/view/180801); test fixture only.
PAGE = '''<h1>Protocol - Perceived Stress</h1>
		<!-- Modal -->
		<div class="modal fade" id="modal-PX180801070000" tabindex="-1" role="dialog">
			  <div class="modal-body">
				<p>Mapping for PX180801_Able_To_Control_Irritations</p>
				<table class="table table-bordered mt-2">
					<tr>
						<th>dbGaP Study</th><th>dbGaP Variable</th><th>dbGaP Variable Description</th>
					</tr>
											<tr>
							<td><a href="https://www.ncbi.nlm.nih.gov/projects/gap/cgi-bin/study.cgi?study_id=phs000796" target="_blank">Genome Wide Association Study of Chronic TMD: Discovery Phase</a></td>
							<td>phv00260729</td>
							<td>PSS 7. In the last month, how often have you been able to control irritations in your life?						</tr>
											<tr>
							<td><a href="https://www.ncbi.nlm.nih.gov/projects/gap/cgi-bin/study.cgi?study_id=phs000001" target="_blank">No variable here</a></td>
							<td>N/A</td>
							<td>						</tr>
											<tr>
							<td><a href="https://www.ncbi.nlm.nih.gov/projects/gap/cgi-bin/study.cgi?study_id=phs000762" target="_blank">OPPERA baseline case-control study of chronic TMJD</a></td>
							<td>phv00223376</td>
							<td>7. Been able to control irritations in your life						</tr>
									</table>
			  </div>
		</div>
		<!-- Modal -->
		<div class="modal fade" id="modal-PX180801030000" tabindex="-1" role="dialog">
			  <div class="modal-body">
				<p>Mapping for PX180801_Felt_Nervous_And_Stressed</p>
				<table class="table table-bordered mt-2">
											<tr>
							<td><a href="https://www.ncbi.nlm.nih.gov/projects/gap/cgi-bin/study.cgi?study_id=phs000796" target="_blank">Genome Wide Association Study of Chronic TMD: Discovery Phase</a></td>
							<td>phv00260725</td>
							<td>PSS 3. In the last month, how often have you felt nervous and &#039;stressed&#039;?						</tr>
									</table>
			  </div>
		</div>
'''

LIST = ('<td><h6><label for="cb-protocol-590603"><a href="/protocols/view/590603?origin=browse">12-Step Group '
        'Participation</a></label><br><td><h6><a href="/protocols/view/30301?origin=browse">Alcohol - 30-Day '
        'Quantity &amp; Frequency</a><a href="/protocols/view/590603?origin=browse">dup</a>'
        '<a href="/protocols/view/41001">Abdominal</a>')


def make_xlsx(rows, sheet="With mappings"):
    """Tiny xlsx with inline strings."""
    def cell(ci, ri, v):
        ref = chr(65 + ci) + str(ri)
        return '<c r="%s" t="inlineStr"><is><t>%s</t></is></c>' % (ref, v)
    body = "".join('<row r="%d">%s</row>' % (ri, "".join(cell(ci, ri, v) for ci, v in enumerate(r)))
                   for ri, r in enumerate(rows, 1))
    ns = 'xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main"'
    rns = 'xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"'
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("xl/workbook.xml", '<workbook %s %s><sheets><sheet name="Other" sheetId="1" r:id="rId1"/>'
                   '<sheet name="%s" sheetId="2" r:id="rId2"/></sheets></workbook>' % (ns, rns, sheet))
        z.writestr("xl/_rels/workbook.xml.rels",
                   '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'
                   '<Relationship Id="rId1" Target="worksheets/sheet1.xml"/>'
                   '<Relationship Id="rId2" Target="worksheets/sheet2.xml"/></Relationships>')
        z.writestr("xl/worksheets/sheet1.xml", "<worksheet %s><sheetData/></worksheet>" % ns)
        z.writestr("xl/worksheets/sheet2.xml", "<worksheet %s><sheetData>%s</sheetData></worksheet>" % (ns, body))
    return buf.getvalue()


HEADER = ["VARIABLE_ID", "VARIABLE_NAME", "PROTOCOL_NAME", "VARIABLE_DESCRIPTION", "dbGaP VARIABLE_DESCRIPTION",
          "dbGaP VARIABLE_ID", "dbGaP STUDY_ID"]


class ParseTest(unittest.TestCase):
    def test_px_of(self):
        self.assertEqual(pc.px_of("30301"), "PX030301")
        self.assertEqual(pc.px_of("180801"), "PX180801")

    def test_parse_list_dedupes_and_keeps_order(self):
        self.assertEqual(pc.parse_list(LIST), [("590603", "12-Step Group Participation"),
                                               ("30301", "Alcohol - 30-Day Quantity & Frequency"),
                                               ("41001", "")])

    def test_parse_page(self):
        p = pc.parse_page(PAGE)
        self.assertEqual(p["title"], "Perceived Stress")
        self.assertEqual(sorted(p["variables"]), ["PX180801_Able_To_Control_Irritations",
                                                  "PX180801_Felt_Nervous_And_Stressed"])
        rows = p["variables"]["PX180801_Able_To_Control_Irritations"]
        # the N/A row is skipped and does not steal the next row's variable
        self.assertEqual([(r["phs"], r["phv"]) for r in rows], [("phs000796", "phv00260729"),
                                                                ("phs000762", "phv00223376")])
        self.assertEqual(rows[1]["study"], "OPPERA baseline case-control study of chronic TMJD")
        nervous = p["variables"]["PX180801_Felt_Nervous_And_Stressed"][0]
        self.assertEqual(nervous["desc"], "PSS 3. In the last month, how often have you felt nervous and 'stressed'?")
        self.assertEqual(p["unparsed_phv"], 0)
        phv, phs = pc.page_sets(p)
        self.assertEqual(phv, {"phv00260729", "phv00223376", "phv00260725"})
        self.assertEqual(phs, {"phs000796", "phs000762"})

    def test_page_without_mappings(self):
        p = pc.parse_page("<h1>Protocol - Nothing</h1><p>no tables</p>")
        self.assertEqual((p["title"], p["variables"], p["unparsed_phv"]), ("Nothing", {}, 0))


class XlsxTest(unittest.TestCase):
    def test_read_sheet_and_sets_with_swapped_columns(self):
        rows = [HEADER,
                ["PX180801030000", "x", "Perceived Stress", "q", "d", "phv00022754.v5.p10", "phs000007.v26.p10"],
                ["PX180801070000", "x", "Perceived Stress", "q", "d", "phs000762.v1.p1", "phv00223376.v1.p1"],
                ["PX030301010000", "x", "Alcohol", "q", "d", "phv00072936.v1.p1", "phs000171.v1.p1"],
                ["", "", "", "", "", "", ""]]
        got = pc.xlsx_sets(pc.read_sheet(make_xlsx(rows), "With mappings"))
        self.assertEqual(got["PX180801"]["phv"], {"phv00022754", "phv00223376"})
        self.assertEqual(got["PX180801"]["phs"], {"phs000007", "phs000762"})
        self.assertEqual(sorted(got), ["PX030301", "PX180801"])
        with self.assertRaises(KeyError):
            pc.read_sheet(make_xlsx(rows), "Missing")


class CompareTest(unittest.TestCase):
    def test_compare_counts_only_fetched(self):
        pages = {"PX180801": {"phv": {"a", "b", "c"}, "phs": {"s1", "s2"}},
                 "PX030301": {"phv": {"d"}, "phs": {"s3"}},
                 "PX999999": {"phv": {"e"}, "phs": {"s4"}},
                 "PX000001": {"phv": set(), "phs": set()}}
        xlsx = {"PX180801": {"phv": {"a"}, "phs": {"s1"}},
                "PX030301": {"phv": {"d", "z"}, "phs": {"s3"}},
                "PX555555": {"phv": {"y"}, "phs": {"s9"}}}  # not fetched: must not count as missing
        s, per = pc.compare(pages, xlsx)
        self.assertEqual(s["protocols_fetched"], 4)
        self.assertEqual(s["protocols_with_page_mappings"], 3)
        self.assertEqual(s["xlsx_protocols"], 3)
        self.assertEqual(s["xlsx_protocols_fetched"], 2)
        self.assertEqual((s["page_phv"], s["xlsx_phv_fetched"]), (5, 3))
        self.assertEqual((s["page_only_phv"], s["xlsx_only_phv"]), (3, 1))
        self.assertEqual((s["page_phs"], s["xlsx_phs_fetched"], s["page_only_phs"], s["xlsx_only_phs"]),
                         (4, 2, 2, 0))
        self.assertEqual(s["xlsx_protocols_compared"], 2)
        self.assertEqual(s["xlsx_protocols_with_page_only_phv"], 1)
        self.assertEqual(s["xlsx_protocols_complete"], 1)
        self.assertEqual(s["page_protocols_absent_from_xlsx"], 1)
        self.assertEqual(per["PX180801"]["page_only_phv"], 2)
        self.assertEqual(per["PX030301"]["xlsx_only_phv"], 1)

    def test_order_ids_puts_xlsx_protocols_first(self):
        listed = [("590603", ""), ("30301", ""), ("41001", ""), ("180801", "")]
        self.assertEqual(pc.order_ids(listed, {"PX030301", "PX180801"}), ["30301", "180801", "590603", "41001"])

    def test_probe_check(self):
        pages = {"PX030301": {"phv": set("abcdefghi"), "phs": set("123456")},
                 "PX180801": {"phv": set("abc"), "phs": set("12")}}
        got = pc.probe_check(pages)
        self.assertTrue(got["PX030301"]["match"])
        self.assertFalse(got["PX180801"]["match"])
        self.assertNotIn("PX161301", got)


class FakeClock:
    def __init__(self):
        self.t = 0.0

    def __call__(self):
        return self.t

    def sleep(self, s):
        self.t += s


class PoliteTest(unittest.TestCase):
    def test_waits_between_requests_and_refuses_bad_paths(self):
        clock, calls = FakeClock(), []

        def fetch(path):
            calls.append((path, clock.t))
            clock.t += 1.5
            return 200, b""
        p = pc.Polite(fetch_fn=fetch, sleep=clock.sleep, clock=clock)
        p.get("/protocols")
        p.get("/protocols/view/1")
        p.get("/protocols/view/2")
        gaps = [b[1] - a[1] for a, b in zip(calls, calls[1:])]
        self.assertTrue(all(g >= pc.DELAY_S for g in gaps), gaps)
        for bad in ("/protocols/view/1?origin=browse", "/search/x", "/users/me", "/a.html"):
            with self.assertRaises(ValueError):
                p.get(bad)
        self.assertGreaterEqual(pc.DELAY_S, 10)


class CrawlTest(unittest.TestCase):
    def test_crawl_writes_lines_and_stops_on_budget(self):
        clock = FakeClock()

        def fetch(path):
            clock.t += 1.0
            if path.endswith("/2"):
                return 404, b""
            return 200, PAGE.encode("utf-8")
        polite = pc.Polite(fetch_fn=fetch, sleep=clock.sleep, clock=clock)
        with tempfile.TemporaryDirectory() as d:
            out = os.path.join(d, "pages.jsonl")
            done, left, errors = pc.crawl(["180801", "2", "3", "4", "5"], polite, out, budget_s=20, clock=clock)
            with open(out, encoding="utf-8") as f:
                lines = f.read().splitlines()
        self.assertEqual(len(lines), 3)  # started at 0 s, 1 s, 12 s; at 23 s the 20 s budget is spent
        self.assertEqual(left, ["4", "5"])
        self.assertEqual(errors, 1)
        self.assertEqual(sorted(done), ["PX000003", "PX180801"])
        self.assertEqual(len(done["PX180801"]["phv"]), 3)


if __name__ == "__main__":
    unittest.main()
