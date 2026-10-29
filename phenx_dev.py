"""PhenX-labelled dev set for dbGaP study retrieval (SPARK dbGaP Task 2 practice), and a first evaluation.

Labels: PhenX Toolkit's public Variable_cross_reference.xlsx ("With mappings" sheet), where PhenX curators
linked PhenX variables to dbGaP variables (phv) and studies (phs). One question per PhenX protocol: the
protocol name; relevant = every dbGaP study mapped to that protocol. Studies never mapped to any protocol are
unjudged, so two scores are kept: standard NDCG@10 (unjudged = not relevant) and condensed NDCG@10 (unjudged
studies removed from the ranking before the cut-off).

Systems: dbgap-cohort-finder's search at a pinned commit (public metadata only), and a leave-one-out
popularity prior (studies ranked by how many OTHER protocols are mapped to them).

Standard library only. Made with AI agents working in MV2's name (MV2, Munim, Inc.). Apache-2.0.
"""
import io
import json
import math
import os
import re
import subprocess
import sys
import urllib.request
import zipfile
import xml.etree.ElementTree as ET
from collections import Counter

__version__ = "0.1.0"

XREF_URL = "https://www.phenxtoolkit.org/toolkit_content/documents/resources/Variable_cross_reference.xlsx"
SHEET = "With mappings"
FINDER_SHA = "dfc163881d97cf2bc624f4767c69090950487a91"
FINDER_URL = "https://raw.githubusercontent.com/munimtechnologies/dbgap-cohort-finder/%s/cohort_finder.py" % FINDER_SHA
USER_AGENT = "MV2-Munim-phenx-dev/%s (mv2@munimtech.com)" % __version__
DEPTH = 100

# The same in-job fix dbgap-bench-v2 applied (retries; a stray non-UTF-8 byte becomes U+FFFD).
OLD_FETCH = '''def fetch_json(url, timeout=60):
    req = urllib.request.Request(url, headers={
        "User-Agent": USER_AGENT, "Accept": "application/fhir+json, application/json"})
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        return json.loads(resp.read().decode("utf-8"))
'''
NEW_FETCH = '''def decode_body(raw):
    """UTF-8 text. A few dbGaP pages carry a stray non-UTF-8 byte; it becomes U+FFFD."""
    try:
        return raw.decode("utf-8")
    except UnicodeDecodeError:
        return raw.decode("utf-8", "replace")


def fetch_json(url, timeout=60, tries=3, wait=5):
    for attempt in range(tries):
        req = urllib.request.Request(url, headers={
            "User-Agent": USER_AGENT, "Accept": "application/fhir+json, application/json"})
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                return json.loads(decode_body(resp.read()))
        except (urllib.error.URLError, OSError) as err:
            client_error = isinstance(err, urllib.error.HTTPError) and err.code < 500
            if client_error or attempt == tries - 1:
                raise
            time.sleep(wait * (attempt + 1))
'''


def patch_finder(text):
    """(text, patched?) -- applies NEW_FETCH only if OLD_FETCH matches exactly once."""
    if text.count(OLD_FETCH) == 1:
        return text.replace(OLD_FETCH, NEW_FETCH), True
    return text, False

NS = {"m": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}
REL_NS = "{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id"
PHS = re.compile(r"\bphs(\d{6})", re.I)
PHV = re.compile(r"\bphv(\d{8})", re.I)
PX = re.compile(r"^PX(\d{6})")


def col_index(ref):
    letters = re.match(r"[A-Z]+", ref).group(0)
    n = 0
    for ch in letters:
        n = n * 26 + (ord(ch) - 64)
    return n - 1


def read_xlsx(data):
    """Return {sheet_name: [row lists]} from xlsx bytes."""
    z = zipfile.ZipFile(io.BytesIO(data))
    shared = []
    if "xl/sharedStrings.xml" in z.namelist():
        root = ET.fromstring(z.read("xl/sharedStrings.xml"))
        for si in root.findall("m:si", NS):
            shared.append("".join(t.text or "" for t in si.iter("{%s}t" % NS["m"])))
    wb = ET.fromstring(z.read("xl/workbook.xml"))
    rels = ET.fromstring(z.read("xl/_rels/workbook.xml.rels"))
    targets = {r.get("Id"): r.get("Target") for r in rels}
    sheets = {}
    for s in wb.find("m:sheets", NS):
        target = targets[s.get(REL_NS)].lstrip("/")
        path = target if target.startswith("xl/") else "xl/" + target
        root = ET.fromstring(z.read(path))
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
            width = max(cells) + 1 if cells else 0
            rows.append([cells.get(i, "") for i in range(width)])
        sheets[s.get("name")] = rows
    return sheets


def build_labels(rows):
    """Mapping rows (header first) -> (protocols, facts).

    protocols: {"PX010101": {"name": "Current Age", "studies": {"phs000200", ...}, "phv": {...}}}
    The study and variable ids are read from both id columns, because a few rows have them swapped.
    """
    header = [h.strip() for h in rows[0]]
    i_var, i_proto = header.index("VARIABLE_ID"), header.index("PROTOCOL_NAME")
    i_phv, i_phs = header.index("dbGaP VARIABLE_ID"), header.index("dbGaP STUDY_ID")
    protocols, swapped, no_study, names = {}, 0, 0, {}
    for row in rows[1:]:
        cell = lambda i: row[i] if i < len(row) else ""  # noqa: E731
        m = PX.match(cell(i_var))
        if not m:
            continue
        pid = "PX" + m.group(1)
        ids = cell(i_phv) + " " + cell(i_phs)
        if PHS.search(cell(i_phv)) or PHV.search(cell(i_phs)):
            swapped += 1
        studies = {"phs" + s for s in PHS.findall(ids)}
        if not studies:
            no_study += 1
        entry = protocols.setdefault(pid, {"name": cell(i_proto).strip(), "studies": set(), "phv": set()})
        names.setdefault(pid, Counter())[cell(i_proto).strip()] += 1
        entry["studies"].update(studies)
        entry["phv"].update("phv" + v for v in PHV.findall(ids))
    for pid, counter in names.items():
        protocols[pid]["name"] = counter.most_common(1)[0][0]
    facts = {"data_rows": len(rows) - 1, "protocols": len(protocols), "rows_with_swapped_ids": swapped,
             "rows_without_study": no_study,
             "distinct_studies": len(set().union(*[p["studies"] for p in protocols.values()])) if protocols else 0,
             "distinct_variables": len(set().union(*[p["phv"] for p in protocols.values()])) if protocols else 0}
    return protocols, facts


def make_devset(protocols, corpus):
    """Questions and qrels for protocols with at least one mapped study present in the corpus."""
    queries, qrels = [], {}
    for pid in sorted(protocols):
        rel = sorted(s for s in protocols[pid]["studies"] if s in corpus)
        if rel and protocols[pid]["name"]:
            queries.append({"id": pid, "query": protocols[pid]["name"]})
            qrels[pid] = {s: 1 for s in rel}
    return queries, qrels


def prior_ranking(protocols, qid, corpus, depth=DEPTH):
    """Leave-one-out popularity: studies ranked by how many other protocols map to them."""
    counts = Counter()
    for pid, p in protocols.items():
        if pid != qid:
            counts.update(s for s in p["studies"] if s in corpus)
    return [s for s, _ in sorted(counts.items(), key=lambda x: (-x[1], x[0]))][:depth]


def dcg(labels, k):
    return sum(rel / math.log2(i + 2) for i, rel in enumerate(labels[:k]))


def ndcg(ranked, relevant, k=10):
    ideal = dcg([1] * len(relevant), k)
    return dcg([1 if s in relevant else 0 for s in ranked], k) / ideal if ideal else 0.0


def condensed(ranked, judged):
    """Drop unjudged studies, keeping order (Sakai's condensed list)."""
    return [s for s in ranked if s in judged]


def recall(ranked, relevant, k):
    return len(set(ranked[:k]) & relevant) / float(len(relevant)) if relevant else 0.0


def rr(ranked, relevant, k):
    for rank, s in enumerate(ranked[:k], 1):
        if s in relevant:
            return 1.0 / rank
    return 0.0


def score_system(runs, qrels, judged):
    """Mean and per-question metrics; a question with no run scores 0."""
    per = {}
    for qid, rel in qrels.items():
        relevant = set(rel)
        ranked = runs.get(qid, [])
        per[qid] = {"ndcg10": ndcg(ranked, relevant, 10),
                    "ndcg10_condensed": ndcg(condensed(ranked, judged), relevant, 10),
                    "recall100": recall(ranked, relevant, 100),
                    "rr10": rr(ranked, relevant, 10),
                    "returned": len(ranked)}
    n = float(len(per)) or 1.0
    mean = {m: round(sum(v[m] for v in per.values()) / n, 4)
            for m in ("ndcg10", "ndcg10_condensed", "recall100", "rr10")}
    mean["questions_with_no_results"] = sum(1 for v in per.values() if v["returned"] == 0)
    return mean, per


def read_run(path):
    rows = {}
    with open(path, encoding="utf-8") as f:
        for line in f:
            parts = line.split()
            if len(parts) >= 5:
                rows.setdefault(parts[0], []).append((int(parts[3]), parts[2].split(".")[0]))
    return {qid: [acc for _, acc in sorted(items)] for qid, items in rows.items()}


def fetch(url, timeout=180):
    req = urllib.request.Request(url, headers={"User-Agent": USER_AGENT})
    with urllib.request.urlopen(req, timeout=timeout) as r:
        return r.read()


def finder(args, work):
    cmd = [sys.executable, os.path.join(work, "cohort_finder.py")] + args
    done = subprocess.run(cmd, capture_output=True, text=True)
    sys.stderr.write(done.stderr[-4000:])
    if done.returncode != 0:
        raise SystemExit("finder failed: %s" % " ".join(args))
    return done.stdout


def main(out_dir):
    os.makedirs(out_dir, exist_ok=True)
    work = os.path.join(out_dir, "work")
    os.makedirs(work, exist_ok=True)
    data = fetch(XREF_URL)
    rows = read_xlsx(data)[SHEET]
    protocols, facts = build_labels(rows)
    facts["xlsx_bytes"] = len(data)

    source, facts["finder_fetch_patched"] = patch_finder(fetch(FINDER_URL).decode("utf-8"))
    with open(os.path.join(work, "cohort_finder.py"), "w", encoding="utf-8", newline="\n") as f:
        f.write(source)
    studies_path = os.path.join(work, "studies.jsonl")
    finder(["harvest", "--out", studies_path], work)
    corpus = set()
    with open(studies_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                corpus.add(json.loads(line)["accession"].split(".")[0])
    mapped = set().union(*[p["studies"] for p in protocols.values()])
    facts["corpus_studies"] = len(corpus)
    facts["mapped_studies_in_corpus"] = len(mapped & corpus)

    queries, qrels = make_devset(protocols, corpus)
    judged = mapped & corpus
    sizes = sorted(len(r) for r in qrels.values())
    facts["questions"] = len(queries)
    facts["relevant_per_question_median"] = sizes[len(sizes) // 2] if sizes else 0
    facts["relevant_per_question_max"] = sizes[-1] if sizes else 0
    q_path = os.path.join(out_dir, "phenx_queries.jsonl")
    with open(q_path, "w", encoding="utf-8", newline="\n") as f:
        for q in queries:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")
    with open(os.path.join(out_dir, "phenx_qrels.txt"), "w", encoding="utf-8", newline="\n") as f:
        for qid in sorted(qrels):
            for s in sorted(qrels[qid]):
                f.write("%s 0 %s 1\n" % (qid, s))

    run_path = os.path.join(out_dir, "run_finder.txt")
    finder(["run", "--queries", q_path, "--studies", studies_path, "--out", run_path, "-k", str(DEPTH)], work)
    runs = {"finder": read_run(run_path),
            "prior_loo": {q["id"]: prior_ranking(protocols, q["id"], corpus) for q in queries}}
    report = {"version": __version__, "finder_sha": FINDER_SHA, "facts": facts, "systems": {}}
    per_question = {}
    for name, run in runs.items():
        mean, per = score_system(run, qrels, judged)
        report["systems"][name] = mean
        per_question[name] = per
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    with open(os.path.join(out_dir, "per_question.json"), "w", encoding="utf-8") as f:
        json.dump(per_question, f, indent=1, sort_keys=True)
    os.remove(os.path.join(work, "cohort_finder.py"))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main(sys.argv[1] if len(sys.argv) > 1 else "out")
