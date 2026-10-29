"""Crawl PhenX Toolkit protocol pages for their "Mapped dbGaP Studies" tables and compare them with PhenX's
public Variable_cross_reference.xlsx ("With mappings" sheet).

Why: run 214 found that the xlsx lacks mappings its own protocol pages show (Perceived Stress: 3 of 13 dbGaP
variables; Medical History: only variables up to "Chlamydia"). The pages are the fuller label source for a
dbGaP study-retrieval dev set (SPARK dbGaP Task 2 practice).

Politeness: robots.txt (checked 2026-10-28) allows /protocols/ and asks for Crawl-delay: 10. Every request
here waits at least 10 s after the previous one, uses plain /protocols/view/<id> paths (no query strings),
and stops by itself when the time budget runs out, recording which protocols were left.

Standard library only. Made with AI agents working in MV2's name (MV2, Munim, Inc.). Apache-2.0.
"""
import html
import io
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
import zipfile
import xml.etree.ElementTree as ET

__version__ = "0.1.0"

BASE = "https://www.phenxtoolkit.org"
LIST_PATH = "/protocols"
XREF_PATH = "/toolkit_content/documents/resources/Variable_cross_reference.xlsx"
SHEET = "With mappings"
USER_AGENT = "MV2-Munim-phenx-crawl/%s (mv2@munimtech.com)" % __version__
DELAY_S = 10
# Counts phenx-probe-v1 saw on 2026-10-28 (any phv / phs id anywhere on the page): parser sanity check.
PROBE = {"PX030301": {"phv": 9, "phs": 6}, "PX180801": {"phv": 13, "phs": 5}, "PX161301": {"phv": 898}}

LIST_LINK = re.compile(r'href="/protocols/view/(\d+)\?origin=browse">(.*?)</a>', re.S)
ANY_VIEW = re.compile(r"/protocols/view/(\d+)")
H1 = re.compile(r"<h1>\s*Protocol\s*-\s*(.*?)\s*</h1>", re.S)
MODAL = re.compile(r'id="modal-(PX\d{6,})"')
MAP_NAME = re.compile(r"Mapping for\s+(PX\w+)\s*</p>")
ROW = re.compile(r'study_id=(phs\d{6})[^>]*>([^<]*)</a>\s*</td>\s*<td>\s*(phv\d{8})\s*</td>\s*<td>(.*?)</tr>', re.S)
PHS = re.compile(r"\bphs(\d{6})", re.I)
PHV = re.compile(r"\bphv(\d{8})", re.I)
PX = re.compile(r"^PX(\d{6})")
NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"


def px_of(view_id):
    return "PX%06d" % int(view_id)


def clean(text):
    return " ".join(html.unescape(re.sub(r"<[^>]+>", " ", text)).split())


def parse_list(text):
    """Protocol browse page -> [(view_id, title)] in page order, each id once."""
    seen, out = set(), []
    for vid, title in LIST_LINK.findall(text):
        if vid not in seen:
            seen.add(vid)
            out.append((vid, clean(title)))
    for vid in ANY_VIEW.findall(text):
        if vid not in seen:
            seen.add(vid)
            out.append((vid, ""))
    return out


def parse_page(text):
    """Protocol page -> {"title", "variables": {name: [{"phs", "study", "phv", "desc"}]}, "unparsed_phv"}.

    unparsed_phv counts phv ids inside mapping blocks that the row pattern did not pick up (should be 0).
    """
    m = H1.search(text)
    starts = [x.start() for x in MODAL.finditer(text)]
    variables, unparsed = {}, 0
    for i, s in enumerate(starts):
        block = text[s:starts[i + 1] if i + 1 < len(starts) else len(text)]
        name_m = MAP_NAME.search(block)
        if not name_m:
            continue
        rows = [{"phs": phs, "study": clean(study), "phv": phv, "desc": clean(desc)}
                for phs, study, phv, desc in ROW.findall(block)]
        variables.setdefault(name_m.group(1), []).extend(rows)
        unparsed += len(set(PHV.findall(block)) - {r["phv"][3:] for r in rows})
    return {"title": clean(m.group(1)) if m else "", "variables": variables, "unparsed_phv": unparsed}


def page_sets(parsed):
    phv = {r["phv"] for rows in parsed["variables"].values() for r in rows}
    phs = {r["phs"] for rows in parsed["variables"].values() for r in rows}
    return phv, phs


def col_index(ref):
    n = 0
    for ch in re.match(r"[A-Z]+", ref).group(0):
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def read_sheet(data, name):
    """Rows of one sheet from xlsx bytes (same reader as phenx_dev.py, one sheet only)."""
    z = zipfile.ZipFile(io.BytesIO(data))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    targets = {r.get("Id"): r.get("Target") for r in rels}
    for s in wb.find("m:sheets", NS):
        if s.get("name") != name:
            continue
        target = targets[s.get(REL_NS)].lstrip("/")
        root = ET.fromstring(z.read(target if target.startswith("xl/") else "xl/" + target))
        rows = []
        for row in root.iter("{%s}row" % NS["m"]):
            cells = {}
            for c in row.findall("m:c", NS):
                t = c.get("t")
                if t == "inlineStr":
                    val = "".join(x.text or "" for x in c.iter("{%s}t" % NS["m"]))
                else:
                    v = c.find("m:v", NS)
                    val = v.text if v is not None and v.text is not None else ""
                    if t == "s" and val != "":
                        val = shared[int(val)]
                cells[col_index(c.get("r"))] = val
            rows.append([cells.get(i, "") for i in range(max(cells) + 1 if cells else 0)])
        return rows
    raise KeyError(name)


def xlsx_sets(rows):
    """Mapping rows (header first) -> {"PX030301": {"phv": set, "phs": set}}; ids read from both id columns."""
    header = [h.strip() for h in rows[0]]
    i_var = header.index("VARIABLE_ID")
    i_phv, i_phs = header.index("dbGaP VARIABLE_ID"), header.index("dbGaP STUDY_ID")
    out = {}
    for row in rows[1:]:
        cell = lambda i: row[i] if i < len(row) else ""  # noqa: E731
        m = PX.match(cell(i_var))
        if not m:
            continue
        ids = cell(i_phv) + " " + cell(i_phs)
        entry = out.setdefault("PX" + m.group(1), {"phv": set(), "phs": set()})
        entry["phv"].update("phv" + v for v in PHV.findall(ids))
        entry["phs"].update("phs" + s for s in PHS.findall(ids))
    return out


def order_ids(listed, xlsx_px):
    """Protocols the xlsx maps come first (so a short budget still covers the comparison), then the rest."""
    first = [v for v, _ in listed if px_of(v) in xlsx_px]
    return first + [v for v, _ in listed if px_of(v) not in xlsx_px]


def compare(pages, xlsx):
    """pages: {px: {"phv": set, "phs": set}} for FETCHED protocols; xlsx: same shape for the whole file.

    Only protocols that were fetched are compared, so a crawl cut short by its budget is not misread as
    missing data.
    """
    per = {}
    for px in sorted(pages):
        pg = pages.get(px, {"phv": set(), "phs": set()})
        xl = xlsx.get(px, {"phv": set(), "phs": set()})
        per[px] = {"page_phv": len(pg["phv"]), "xlsx_phv": len(xl["phv"]),
                   "page_only_phv": len(pg["phv"] - xl["phv"]), "xlsx_only_phv": len(xl["phv"] - pg["phv"]),
                   "page_phs": len(pg["phs"]), "xlsx_phs": len(xl["phs"]),
                   "page_only_phs": len(pg["phs"] - xl["phs"])}
    union = lambda d, k, keys: set().union(*[d[p][k] for p in keys if p in d])  # noqa: E731
    fetched = set(pages)
    xlsx_fetched = [p for p in xlsx if p in fetched]
    page_phv, xl_phv = union(pages, "phv", fetched), union(xlsx, "phv", xlsx_fetched)
    page_phs, xl_phs = union(pages, "phs", fetched), union(xlsx, "phs", xlsx_fetched)
    both = [p for p in xlsx_fetched if pages[p]["phv"] or xlsx[p]["phv"]]
    summary = {
        "protocols_fetched": len(fetched),
        "protocols_with_page_mappings": sum(1 for p in fetched if pages[p]["phv"]),
        "xlsx_protocols": len(xlsx), "xlsx_protocols_fetched": len(xlsx_fetched),
        "page_phv": len(page_phv), "xlsx_phv_fetched": len(xl_phv),
        "page_only_phv": len(page_phv - xl_phv), "xlsx_only_phv": len(xl_phv - page_phv),
        "page_phs": len(page_phs), "xlsx_phs_fetched": len(xl_phs),
        "page_only_phs": len(page_phs - xl_phs), "xlsx_only_phs": len(xl_phs - page_phs),
        "xlsx_protocols_compared": len(both),
        "xlsx_protocols_with_page_only_phv": sum(1 for p in both if per[p]["page_only_phv"]),
        "xlsx_protocols_complete": sum(1 for p in both if not per[p]["page_only_phv"]),
        "page_protocols_absent_from_xlsx": sum(1 for p in fetched if pages[p]["phv"] and p not in xlsx),
    }
    return summary, per


def probe_check(pages):
    out = {}
    for px, want in PROBE.items():
        if px in pages:
            got = {k: len(pages[px][k]) for k in want}
            out[px] = {"want": want, "got": got, "match": got == want}
    return out


def fetch(path, timeout=90, tries=3):
    for attempt in range(tries):
        req = urllib.request.Request(BASE + path, headers={"User-Agent": USER_AGENT})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as r:
                return r.status, r.read()
        except urllib.error.HTTPError as err:
            if err.code < 500 and err.code != 429:
                return err.code, b""
            if attempt == tries - 1:
                return err.code, b""
        except (urllib.error.URLError, OSError):
            if attempt == tries - 1:
                raise
        time.sleep(60 * (attempt + 1))


class Polite:
    """Waits DELAY_S between requests; refuses query strings and paths robots.txt disallows."""

    def __init__(self, fetch_fn=fetch, sleep=time.sleep, clock=time.monotonic, delay=DELAY_S):
        self.fetch_fn, self.sleep, self.clock, self.delay, self.last = fetch_fn, sleep, clock, delay, None

    def get(self, path):
        if "?" in path or path.startswith(("/search/", "/users/")) or path.endswith(".html"):
            raise ValueError("path not allowed: %s" % path)
        if self.last is not None:
            wait = self.delay - (self.clock() - self.last)
            if wait > 0:
                self.sleep(wait)
        try:
            return self.fetch_fn(path)
        finally:
            self.last = self.clock()


def crawl(ids, polite, out_path, budget_s, clock=time.monotonic):
    """Fetch each protocol page once, appending one JSON line per protocol; stop when the budget is spent."""
    start, done, left, errors = clock(), {}, [], 0
    with open(out_path, "a", encoding="utf-8", newline="\n") as f:
        for i, vid in enumerate(ids):
            if clock() - start > budget_s:
                left = list(ids[i:])
                break
            px = px_of(vid)
            rec = {"view_id": vid, "px": px}
            try:
                status, body = polite.get("/protocols/view/%s" % vid)
                rec["status"] = status
                if status == 200:
                    parsed = parse_page(body.decode("utf-8", "replace"))
                    rec.update(parsed)
                    phv, phs = page_sets(parsed)
                    done[px] = {"phv": phv, "phs": phs}
                else:
                    errors += 1
            except Exception as e:  # record and go on
                rec["error"], errors = repr(e), errors + 1
            f.write(json.dumps(rec, ensure_ascii=False) + "\n")
            f.flush()
    return done, left, errors


def main(out_dir, budget_min=215.0):
    os.makedirs(out_dir, exist_ok=True)
    polite = Polite()
    t0 = time.monotonic()
    status, body = polite.get(LIST_PATH)
    listed = parse_list(body.decode("utf-8", "replace")) if status == 200 else []
    status_x, data = polite.get(XREF_PATH)
    xlsx = xlsx_sets(read_sheet(data, SHEET)) if status_x == 200 else {}
    ids = order_ids(listed, set(xlsx))
    budget = budget_min * 60 - (time.monotonic() - t0)
    pages, left, errors = crawl(ids, polite, os.path.join(out_dir, "pages.jsonl"), budget)
    summary, per = compare(pages, xlsx)
    report = {"version": __version__, "listed_protocols": len(listed), "list_status": status,
              "xlsx_status": status_x, "xlsx_bytes": len(data), "fetch_errors": errors,
              "left_unfetched": len(left), "minutes": round((time.monotonic() - t0) / 60, 1),
              "summary": summary, "probe_check": probe_check(pages)}
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    with open(os.path.join(out_dir, "per_protocol.json"), "w", encoding="utf-8") as f:
        json.dump(per, f, indent=1, sort_keys=True)
    with open(os.path.join(out_dir, "left_unfetched.txt"), "w", encoding="utf-8", newline="\n") as f:
        f.write("".join(v + "\n" for v in left))
    with open(os.path.join(out_dir, "qrels_pages.txt"), "w", encoding="utf-8", newline="\n") as f:
        for px in sorted(pages):
            for s in sorted(pages[px]["phs"]):
                f.write("%s 0 %s 1\n" % (px, s))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out", float(sys.argv[2]) if len(sys.argv) > 2 else 215.0)
