#!/usr/bin/env python3
"""mesh_terms: MeSH disease synonyms for dbgap-cohort-finder's snapshot mode.

A SPARK need may say "heart attack" while the study says "Myocardial
Infarction". This builds a small table of MeSH descriptors from NLM's public
descriptor file (desc<year>.xml, gzipped) with every entry term, and finds the
descriptors named in a piece of text, so the ranker can match a need's topic
against a study's disease fields by concept instead of by spelling.

Only the disease branches are kept by default (tree C, and F03 mental
disorders). Matching is by token set, so inverted headings ("Diabetes
Mellitus, Type 2") match ordinary phrasing ("type 2 diabetes mellitus").
Permuted terms are skipped. The table is built once (for example at Docker
image build time) and needs no network afterwards. Standard library only.

Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
"""

import argparse
import gzip
import json
import os
import re
import sys
import urllib.request
import xml.etree.ElementTree as ET

__version__ = "0.1.0"

MESH_URL = "https://nlmpubs.nlm.nih.gov/projects/mesh/MESH_FILES/xmlmesh/desc%d.gz"
MESH_YEAR = 2026
USER_AGENT = "dbgap-cohort-finder-mesh/%s (+https://github.com/munimtechnologies/dbgap-cohort-finder)" % __version__
DISEASE_TREES = ("C", "F03")
MAX_WORDS = 8  # longest phrase looked up, in words

STOPWORDS = frozenset("a an and as at by for from in into nos of on or the to with without".split())
TOKEN_RE = re.compile(r"[a-z0-9]+")
# Terms this short or this common would match too much text on their own.
MIN_TERM_CHARS = 3
SKIP_TERMS = frozenset(["disease", "diseases", "syndrome", "disorder", "disorders", "condition", "pain",
                        "lesion", "lesions", "injury", "injuries", "abnormalities", "infection", "infections"])


def fold(word):
    """A crude plural fold, applied the same way to terms and text."""
    if len(word) > 4 and word.endswith("ies"):
        return word[:-3] + "y"
    if len(word) > 3 and word.endswith("s") and not word.endswith(("ss", "us", "is")):
        return word[:-1]
    return word


def tokens(text):
    return [fold(t) for t in TOKEN_RE.findall((text or "").lower()) if t not in STOPWORDS]


def key_of(words):
    return " ".join(sorted(words))


# ---------------------------------------------------------------- build

def _strings(record, path):
    return [e.text.strip() for e in record.findall(path) if e.text and e.text.strip()]


def read_descriptors(stream, prefixes=DISEASE_TREES):
    """Yield {"ui", "name", "trees", "terms"} for each descriptor under the given
    tree prefixes (all descriptors if prefixes is empty). stream is the XML file."""
    for event, elem in ET.iterparse(stream, events=("end",)):
        if elem.tag != "DescriptorRecord":
            continue
        trees = _strings(elem, "TreeNumberList/TreeNumber")
        if not prefixes or any(t.startswith(p) for t in trees for p in prefixes):
            name = (_strings(elem, "DescriptorName/String") or [""])[0]
            terms = []
            for term in elem.findall("ConceptList/Concept/TermList/Term"):
                if term.get("IsPermutedTermYN") == "Y":
                    continue
                text = (term.findtext("String") or "").strip()
                if text and text not in terms:
                    terms.append(text)
            if name and name not in terms:
                terms.insert(0, name)
            yield {"ui": (elem.findtext("DescriptorUI") or "").strip(), "name": name,
                   "trees": sorted(trees), "terms": terms}
        elem.clear()


def open_xml(path):
    """The descriptor file as a binary stream, gzipped or not."""
    with open(path, "rb") as f:
        head = f.read(2)
    return gzip.open(path, "rb") if head == b"\x1f\x8b" else open(path, "rb")


def download(year, cache_dir, getter=None):
    path = os.path.join(cache_dir, "desc%d.gz" % year)
    if not os.path.exists(path):
        os.makedirs(cache_dir, exist_ok=True)
        req = urllib.request.Request(MESH_URL % year, headers={"User-Agent": USER_AGENT})
        body = getter(MESH_URL % year) if getter else urllib.request.urlopen(req, timeout=300).read()
        with open(path + ".part", "wb") as f:
            f.write(body)
        os.replace(path + ".part", path)
    return path


def build(src_path, out_path, prefixes=DISEASE_TREES, year=MESH_YEAR):
    with open_xml(src_path) as stream:
        descriptors = list(read_descriptors(stream, prefixes))
    data = {"version": __version__, "source": MESH_URL % year, "year": year, "trees": list(prefixes),
            "descriptors": descriptors}
    opener = gzip.open if out_path.endswith(".gz") else open
    with opener(out_path, "wt", encoding="utf-8") as f:
        json.dump(data, f, ensure_ascii=False, separators=(",", ":"))
    return data


# ---------------------------------------------------------------- lookup

class MeshIndex:
    def __init__(self, descriptors):
        self.descriptors = descriptors
        self.by_key = {}
        for i, d in enumerate(descriptors):
            for term in d["terms"]:
                words = tokens(term)
                if not words or len(words) > MAX_WORDS:
                    continue
                if len(words) == 1 and (len(words[0]) < MIN_TERM_CHARS or words[0] in SKIP_TERMS
                                        or term.lower() in SKIP_TERMS):
                    continue
                self.by_key.setdefault(key_of(words), [])
                if i not in self.by_key[key_of(words)]:
                    self.by_key[key_of(words)].append(i)

    @classmethod
    def load(cls, path):
        opener = gzip.open if path.endswith(".gz") else open
        with opener(path, "rt", encoding="utf-8") as f:
            return cls(json.load(f)["descriptors"])

    def find(self, text):
        """Descriptors named in text, longest phrase first, without overlaps:
        [{"phrase", "ui", "name", "terms"}]."""
        words = tokens(text)
        used = [False] * len(words)
        found = []
        for n in range(min(MAX_WORDS, len(words)), 0, -1):
            for start in range(len(words) - n + 1):
                if any(used[start:start + n]):
                    continue
                hits = self.by_key.get(key_of(words[start:start + n]))
                if not hits:
                    continue
                for j in range(start, start + n):
                    used[j] = True
                for i in hits:
                    d = self.descriptors[i]
                    found.append({"phrase": " ".join(words[start:start + n]), "ui": d["ui"],
                                  "name": d["name"], "terms": d["terms"]})
        return found

    def synonyms(self, text):
        """Every entry term of every descriptor named in text, lowercased and de-duplicated."""
        out = []
        for hit in self.find(text):
            for term in hit["terms"]:
                if term.lower() not in out:
                    out.append(term.lower())
        return out


def lookup_report(index, lines):
    out = ["# MeSH lookups", "", "| Text | Descriptors found |", "|---|---|"]
    for line in lines:
        hits = index.find(line)
        cell = "; ".join("%s (%s, via \"%s\")" % (h["name"], h["ui"], h["phrase"]) for h in hits) or "none"
        out.append("| %s | %s |" % (line.replace("|", "/"), cell))
    return "\n".join(out) + "\n"


def main(argv=None):
    ap = argparse.ArgumentParser(description="MeSH disease synonyms for dbgap-cohort-finder.")
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build", help="download desc<year>.gz once and write the synonym table")
    b.add_argument("--src", help="a local desc<year>.xml or .gz instead of downloading")
    b.add_argument("--cache", default="mesh_cache")
    b.add_argument("--year", type=int, default=MESH_YEAR)
    b.add_argument("--all", action="store_true", help="keep every descriptor, not only diseases")
    b.add_argument("--out", default="mesh_terms.json.gz")
    lk = sub.add_parser("lookup", help="show the descriptors named in each line of text")
    lk.add_argument("--index", default="mesh_terms.json.gz")
    lk.add_argument("--file", help="one text per line; otherwise the text arguments")
    lk.add_argument("--out", help="write a Markdown table here")
    lk.add_argument("text", nargs="*")
    args = ap.parse_args(argv)
    if args.cmd == "build":
        src = args.src or download(args.year, args.cache)
        data = build(src, args.out, () if args.all else DISEASE_TREES, args.year)
        terms = sum(len(d["terms"]) for d in data["descriptors"])
        print("%d descriptors, %d entry terms -> %s" % (len(data["descriptors"]), terms, args.out))
        return 0
    index = MeshIndex.load(args.index)
    lines = list(args.text)
    if args.file:
        with open(args.file, encoding="utf-8") as f:
            lines += [l.strip() for l in f if l.strip() and not l.startswith("#")]
    report = lookup_report(index, lines)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as f:
            f.write(report)
    sys.stdout.write(report)
    return 0


if __name__ == "__main__":
    sys.exit(main())
