# Tests for mesh_terms.py. Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
import contextlib
import gzip
import io
import os
import tempfile
import unittest

import mesh_terms as mt

# Shaped like NLM's desc2026.xml, including nested strings that must not be read as terms.
XML = """<?xml version="1.0"?>
<DescriptorRecordSet LanguageCode="eng">
 <DescriptorRecord DescriptorClass="1">
  <DescriptorUI>D009203</DescriptorUI>
  <DescriptorName><String>Myocardial Infarction</String></DescriptorName>
  <AllowableQualifiersList><AllowableQualifier><QualifierReferredTo><QualifierUI>Q000097</QualifierUI>
   <QualifierName><String>blood</String></QualifierName></QualifierReferredTo></AllowableQualifier></AllowableQualifiersList>
  <TreeNumberList><TreeNumber>C14.280.647.500</TreeNumber><TreeNumber>C14.907.585.500</TreeNumber></TreeNumberList>
  <ConceptList>
   <Concept PreferredConceptYN="Y"><ConceptUI>M0014340</ConceptUI>
    <ConceptName><String>Myocardial Infarction</String></ConceptName>
    <TermList>
     <Term ConceptPreferredTermYN="Y" IsPermutedTermYN="N" RecordPreferredTermYN="Y"><TermUI>T1</TermUI><String>Myocardial Infarction</String></Term>
     <Term ConceptPreferredTermYN="N" IsPermutedTermYN="Y" RecordPreferredTermYN="N"><TermUI>T2</TermUI><String>Infarction, Myocardial</String></Term>
     <Term ConceptPreferredTermYN="N" IsPermutedTermYN="N" RecordPreferredTermYN="N"><TermUI>T3</TermUI><String>Heart Attack</String></Term>
    </TermList>
   </Concept>
  </ConceptList>
 </DescriptorRecord>
 <DescriptorRecord DescriptorClass="1">
  <DescriptorUI>D003924</DescriptorUI>
  <DescriptorName><String>Diabetes Mellitus, Type 2</String></DescriptorName>
  <TreeNumberList><TreeNumber>C18.452.394.750.149</TreeNumber></TreeNumberList>
  <ConceptList>
   <Concept PreferredConceptYN="Y"><ConceptUI>M1</ConceptUI>
    <TermList>
     <Term IsPermutedTermYN="N"><TermUI>T4</TermUI><String>Diabetes Mellitus, Type 2</String></Term>
     <Term IsPermutedTermYN="N"><TermUI>T5</TermUI><String>Type 2 Diabetes</String></Term>
     <Term IsPermutedTermYN="N"><TermUI>T6</TermUI><String>NIDDM</String></Term>
    </TermList>
   </Concept>
   <Concept PreferredConceptYN="N"><ConceptUI>M2</ConceptUI>
    <TermList><Term IsPermutedTermYN="N"><TermUI>T7</TermUI><String>Adult-Onset Diabetes Mellitus</String></Term></TermList>
   </Concept>
  </ConceptList>
 </DescriptorRecord>
 <DescriptorRecord DescriptorClass="1">
  <DescriptorUI>D004194</DescriptorUI>
  <DescriptorName><String>Disease</String></DescriptorName>
  <TreeNumberList><TreeNumber>C23.550.288</TreeNumber></TreeNumberList>
  <ConceptList><Concept PreferredConceptYN="Y"><TermList>
   <Term IsPermutedTermYN="N"><String>Disease</String></Term>
   <Term IsPermutedTermYN="N"><String>Diseases</String></Term>
  </TermList></Concept></ConceptList>
 </DescriptorRecord>
 <DescriptorRecord DescriptorClass="1">
  <DescriptorUI>D008687</DescriptorUI>
  <DescriptorName><String>Metformin</String></DescriptorName>
  <PharmacologicalActionList><PharmacologicalAction><DescriptorReferredTo><DescriptorUI>D007004</DescriptorUI>
   <DescriptorName><String>Hypoglycemic Agents</String></DescriptorName></DescriptorReferredTo></PharmacologicalAction></PharmacologicalActionList>
  <TreeNumberList><TreeNumber>D02.078.370.141.450</TreeNumber></TreeNumberList>
  <ConceptList><Concept PreferredConceptYN="Y"><TermList>
   <Term IsPermutedTermYN="N"><String>Metformin</String></Term>
   <Term IsPermutedTermYN="N"><String>Glucophage</String></Term>
  </TermList></Concept></ConceptList>
 </DescriptorRecord>
 <DescriptorRecord DescriptorClass="1">
  <DescriptorUI>D003866</DescriptorUI>
  <DescriptorName><String>Depressive Disorder</String></DescriptorName>
  <TreeNumberList><TreeNumber>F03.600.300</TreeNumber></TreeNumberList>
  <ConceptList><Concept PreferredConceptYN="Y"><TermList>
   <Term IsPermutedTermYN="N"><String>Depressive Disorder</String></Term>
   <Term IsPermutedTermYN="N"><String>Depression</String></Term>
  </TermList></Concept></ConceptList>
 </DescriptorRecord>
</DescriptorRecordSet>
"""


def descriptors(prefixes=mt.DISEASE_TREES):
    return list(mt.read_descriptors(io.BytesIO(XML.encode("utf-8")), prefixes))


class TokenTest(unittest.TestCase):
    def test_tokens_and_fold(self):
        self.assertEqual(mt.tokens("Diabetes Mellitus, Type 2"), ["diabete", "mellitus", "type", "2"])
        self.assertEqual(mt.tokens("Allergies of the Lungs"), ["allergy", "lung"])
        self.assertEqual(mt.tokens("arthritis, stress"), ["arthritis", "stress"])
        self.assertEqual(mt.tokens(None), [])

    def test_inverted_heading_has_the_same_key(self):
        self.assertEqual(mt.key_of(mt.tokens("Diabetes Mellitus, Type 2")),
                         mt.key_of(mt.tokens("type 2 diabetes mellitus")))


class ReadTest(unittest.TestCase):
    def test_disease_branches_only(self):
        ds = descriptors()
        self.assertEqual([d["ui"] for d in ds], ["D009203", "D003924", "D004194", "D003866"])
        self.assertEqual(len(descriptors(())), 5)

    def test_terms_skip_permuted_and_nested_strings(self):
        mi = descriptors()[0]
        self.assertEqual(mi["name"], "Myocardial Infarction")
        self.assertEqual(mi["terms"], ["Myocardial Infarction", "Heart Attack"])
        self.assertEqual(mi["trees"], ["C14.280.647.500", "C14.907.585.500"])
        dm = descriptors()[1]
        self.assertEqual(dm["terms"], ["Diabetes Mellitus, Type 2", "Type 2 Diabetes", "NIDDM",
                                       "Adult-Onset Diabetes Mellitus"])
        everything = " ".join(t for d in descriptors(()) for t in d["terms"])
        self.assertNotIn("blood", everything)
        self.assertNotIn("Hypoglycemic", everything)


class IndexTest(unittest.TestCase):
    def setUp(self):
        self.index = mt.MeshIndex(descriptors())

    def test_find_by_entry_term(self):
        hits = self.index.find("adults who had a heart attack, with WGS")
        self.assertEqual([(h["ui"], h["phrase"]) for h in hits], [("D009203", "heart attack")])

    def test_inverted_and_longest_first(self):
        hits = self.index.find("Type 2 diabetes mellitus and depression in older adults")
        self.assertEqual([h["ui"] for h in hits], ["D003924", "D003866"])
        self.assertEqual(hits[0]["phrase"], "type 2 diabete mellitus")

    def test_generic_words_alone_do_not_match(self):
        self.assertEqual(self.index.find("any disease, diseases of adults"), [])
        self.assertEqual(self.index.find(""), [])

    def test_synonyms(self):
        self.assertEqual(self.index.synonyms("NIDDM cases"),
                         ["diabetes mellitus, type 2", "type 2 diabetes", "niddm", "adult-onset diabetes mellitus"])


class CommandTest(unittest.TestCase):
    def test_build_and_lookup_from_gzip(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "desc2026.gz")
            with gzip.open(src, "wb") as f:
                f.write(XML.encode("utf-8"))
            out = os.path.join(tmp, "mesh_terms.json.gz")
            with contextlib.redirect_stdout(io.StringIO()) as printed:
                self.assertEqual(mt.main(["build", "--src", src, "--out", out]), 0)
            self.assertIn("4 descriptors, 10 entry terms", printed.getvalue())
            texts = os.path.join(tmp, "texts.txt")
            with open(texts, "w", encoding="utf-8") as f:
                f.write("# comment\nheart attack survivors\nasthma\n")
            report = os.path.join(tmp, "lookups.md")
            with contextlib.redirect_stdout(io.StringIO()):
                self.assertEqual(mt.main(["lookup", "--index", out, "--file", texts, "--out", report]), 0)
            with open(report, encoding="utf-8") as f:
                md = f.read()
            self.assertIn('| heart attack survivors | Myocardial Infarction (D009203, via "heart attack") |', md)
            self.assertIn("| asthma | none |", md)

    def test_plain_xml_source_and_download_cache(self):
        with tempfile.TemporaryDirectory() as tmp:
            src = os.path.join(tmp, "desc.xml")
            with open(src, "wb") as f:
                f.write(XML.encode("utf-8"))
            data = mt.build(src, os.path.join(tmp, "t.json"), ())
            self.assertEqual(len(data["descriptors"]), 5)
            calls = []

            def getter(url):
                calls.append(url)
                return b"x"

            p1 = mt.download(2026, tmp, getter)
            p2 = mt.download(2026, tmp, getter)
            self.assertEqual(p1, p2)
            self.assertEqual(calls, [mt.MESH_URL % 2026])


if __name__ == "__main__":
    unittest.main()
