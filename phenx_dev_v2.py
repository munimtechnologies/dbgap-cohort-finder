"""phenx-dev v2: the v1 evaluation scored against three label sets on the same runs.

Label sets: (1) PhenX's public Variable_cross_reference.xlsx, as in v1; (2) the "Mapped dbGaP Studies" tables on
PhenX's own protocol pages, as crawled by phenx-crawl-v1 (qrels_pages.txt, published with attribution and fetched
here from GitHub); (3) their union. phenx-crawl-v1 found the two sources only partly overlap: the pages show
mappings the xlsx lacks, and 62 of the xlsx's 182 protocol ids are no longer on PhenX's protocol list. One
question per protocol; the query is the protocol name (the xlsx name where the xlsx has one, else the name on
PhenX's protocol list). The xlsx and page label sets are also scored on the protocols they share, which isolates
the effect of the labels from the effect of the question set.

Needs phenx_dev.py (v1, unchanged) next to it. Standard library only. Made with AI agents working in MV2's name
(MV2, Munim, Inc.). Apache-2.0.
"""
import hashlib
import html
import json
import os
import re
import sys
import time
import urllib.error

import phenx_dev as v1

__version__ = "0.3.0"

LIST_URL = "https://www.phenxtoolkit.org/protocols"
LIST_LINK = re.compile(r'href="/protocols/view/(\d+)\?origin=browse">(.*?)</a>', re.S)
QREL = re.compile(r"^(PX\d{6})\s+\S+\s+(phs\d{6})\b")
PHENX_DELAY_S = 10  # robots.txt Crawl-delay

# phenx-dev-v1 died on a dbGaP 502 that outlasted 3 tries 5-10 s apart; wait longer between tries here.
OLD_TRIES = "def fetch_json(url, timeout=60, tries=3, wait=5):"
NEW_TRIES = "def fetch_json(url, timeout=60, tries=6, wait=30):"


def longer_retries():
    """Raise v1's in-job finder patch to 6 tries, 30-150 s apart. True if applied."""
    if v1.NEW_FETCH.count(OLD_TRIES) != 1:
        return False
    v1.NEW_FETCH = v1.NEW_FETCH.replace(OLD_TRIES, NEW_TRIES)
    return True


def fetch_published(url, fetch=v1.fetch, sleep=time.sleep, tries=13, wait=300):
    """The label file is committed right after the filing run; a 404 means not yet, so wait up to an hour."""
    for attempt in range(tries):
        try:
            return fetch(url)
        except urllib.error.HTTPError as err:
            if err.code != 404 or attempt == tries - 1:
                raise
            sleep(wait)


def read_qrels(text):
    """qrels lines 'PX030301 0 phs000007 1' -> {"PX030301": {"phs000007", ...}}."""
    out = {}
    for line in text.splitlines():
        m = QREL.match(line.strip())
        if m:
            out.setdefault(m.group(1), set()).add(m.group(2))
    return out


def list_names(text):
    """PhenX /protocols browse page -> {"PX030301": "Alcohol - 30-Day Quantity and Frequency", ...}."""
    names = {}
    for vid, title in LIST_LINK.findall(text):
        name = " ".join(html.unescape(re.sub(r"<[^>]+>", " ", title)).split())
        names.setdefault("PX%06d" % int(vid), name)
    return names


def page_protocols(qrels, xlsx_protocols, names):
    """Page labels in v1's protocol shape; name from the xlsx where it has one, else from the browse list."""
    out = {}
    for px, studies in qrels.items():
        name = xlsx_protocols.get(px, {}).get("name") or names.get(px, "")
        out[px] = {"name": name, "studies": set(studies), "phv": set()}
    return out


def union_protocols(xlsx_protocols, page_protocols_):
    """Per protocol id, the studies either source maps; the xlsx name wins, as in page_protocols."""
    out = {}
    for source in (xlsx_protocols, page_protocols_):
        for px, p in source.items():
            entry = out.setdefault(px, {"name": p["name"], "studies": set(), "phv": set()})
            entry["name"] = entry["name"] or p["name"]
            entry["studies"] |= p["studies"]
    return out


def unlisted_facts(xlsx_protocols, page_protocols_, names):
    """How much of the xlsx sits on protocol ids that PhenX's current protocol list no longer shows."""
    unlisted = sorted(px for px in xlsx_protocols if px not in names)
    page_studies = set().union(*[p["studies"] for p in page_protocols_.values()]) if page_protocols_ else set()
    studies = set().union(*[xlsx_protocols[px]["studies"] for px in unlisted]) if unlisted else set()
    return {"xlsx_protocols_unlisted": len(unlisted), "xlsx_unlisted_ids": unlisted,
            "xlsx_unlisted_studies": len(studies),
            "xlsx_unlisted_studies_not_on_any_page": len(studies - page_studies)}


def union_queries(*label_sets):
    """One question per protocol across all label sets (first non-empty name wins), sorted by id."""
    names = {}
    for protocols in label_sets:
        for px, p in protocols.items():
            if p["name"] and px not in names:
                names[px] = p["name"]
    return [{"id": px, "query": names[px]} for px in sorted(names)]


def score_label_set(protocols, finder_run, corpus, only=None):
    """Score the finder and the leave-one-out prior against one label set; only = protocol ids to keep."""
    _, qrels = v1.make_devset(protocols, corpus)
    if only is not None:
        qrels = {q: r for q, r in qrels.items() if q in only}
    judged = set().union(*[p["studies"] for p in protocols.values()]) & corpus if protocols else set()
    sizes = sorted(len(r) for r in qrels.values())
    block = {"questions": len(qrels), "judged_studies": len(judged),
             "relevant_per_question_median": sizes[len(sizes) // 2] if sizes else 0,
             "relevant_per_question_max": sizes[-1] if sizes else 0, "systems": {}}
    runs = {"finder": finder_run, "prior_loo": {q: v1.prior_ranking(protocols, q, corpus) for q in qrels}}
    per_question = {}
    for name, run in runs.items():
        mean, per = v1.score_system(run, qrels, judged)
        block["systems"][name] = mean
        per_question[name] = per
    return block, per_question, qrels


def write_qrels(path, qrels):
    with open(path, "w", encoding="utf-8", newline="\n") as f:
        for qid in sorted(qrels):
            for s in sorted(qrels[qid]):
                f.write("%s 0 %s 1\n" % (qid, s))


def main(out_dir, page_qrels_url):
    os.makedirs(out_dir, exist_ok=True)
    work = os.path.join(out_dir, "work")
    os.makedirs(work, exist_ok=True)
    retries_raised = longer_retries()
    data = v1.fetch(v1.XREF_URL)
    x_protocols, x_facts = v1.build_labels(v1.read_xlsx(data)[v1.SHEET])
    time.sleep(PHENX_DELAY_S)
    names = list_names(v1.fetch(LIST_URL).decode("utf-8", "replace"))
    page_raw = fetch_published(page_qrels_url)
    p_protocols = page_protocols(read_qrels(page_raw.decode("utf-8")), x_protocols, names)
    u_protocols = union_protocols(x_protocols, p_protocols)
    facts = {"xlsx": x_facts, "xlsx_bytes": len(data), "page_qrels_url": page_qrels_url,
             "page_qrels_sha256": hashlib.sha256(page_raw).hexdigest(),
             "page_qrels_lines": len(page_raw.decode("utf-8").splitlines()), "page_protocols": len(p_protocols),
             "page_protocols_without_name": sum(1 for p in p_protocols.values() if not p["name"]),
             "listed_protocols": len(names), "union_protocols": len(u_protocols),
             "finder_retries_raised": retries_raised}
    facts.update(unlisted_facts(x_protocols, p_protocols, names))

    source, facts["finder_fetch_patched"] = v1.patch_finder(v1.fetch(v1.FINDER_URL).decode("utf-8"))
    with open(os.path.join(work, "cohort_finder.py"), "w", encoding="utf-8", newline="\n") as f:
        f.write(source)
    studies_path = os.path.join(work, "studies.jsonl")
    v1.finder(["harvest", "--out", studies_path], work)
    corpus = set()
    with open(studies_path, encoding="utf-8") as f:
        for line in f:
            if line.strip():
                corpus.add(json.loads(line)["accession"].split(".")[0])
    facts["corpus_studies"] = len(corpus)

    queries = union_queries(x_protocols, p_protocols)
    q_path = os.path.join(out_dir, "phenx_queries.jsonl")
    with open(q_path, "w", encoding="utf-8", newline="\n") as f:
        for q in queries:
            f.write(json.dumps(q, ensure_ascii=False) + "\n")
    run_path = os.path.join(out_dir, "run_finder.txt")
    v1.finder(["run", "--queries", q_path, "--studies", studies_path, "--out", run_path, "-k", str(v1.DEPTH)],
              work)
    finder_run = v1.read_run(run_path)

    report = {"version": __version__, "v1_version": v1.__version__, "finder_sha": v1.FINDER_SHA, "facts": facts,
              "label_sets": {}}
    per_question = {}
    shared = set(v1.make_devset(x_protocols, corpus)[1]) & set(v1.make_devset(p_protocols, corpus)[1])
    for key, protocols, only in (("xlsx", x_protocols, None), ("pages", p_protocols, None),
                                 ("union", u_protocols, None),
                                 ("shared_xlsx", x_protocols, shared), ("shared_pages", p_protocols, shared)):
        block, per, qrels = score_label_set(protocols, finder_run, corpus, only)
        report["label_sets"][key] = block
        per_question[key] = per
        if only is None:
            write_qrels(os.path.join(out_dir, "qrels_%s_used.txt" % key), qrels)
    report["facts"]["shared_questions"] = len(shared)
    with open(os.path.join(out_dir, "report.json"), "w", encoding="utf-8") as f:
        json.dump(report, f, indent=1)
    with open(os.path.join(out_dir, "per_question.json"), "w", encoding="utf-8") as f:
        json.dump(per_question, f, indent=1, sort_keys=True)
    os.remove(os.path.join(work, "cohort_finder.py"))
    print(json.dumps(report, indent=1))


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
