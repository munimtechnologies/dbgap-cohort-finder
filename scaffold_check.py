#!/usr/bin/env python3
"""scaffold_check: sentence_need 0.2.0 (template words left out of text scoring) against 0.1.0.

Runs sentence_need.main with "old" = parse_need(strip=False), which is 0.1.0's
parse, and "new" = 0.2.0's parse, so the report shows what leaving "involving",
"as the primary disease" and "participant-level" out of the BM25 tokens changes.
Pre-registered in 20261030T131635Z-civic-tech/findings/prereg-scaffold-check.md.

Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
"""

import sys

import sentence_need as sen


def parse_v010(text):
    return sen.parse_need(text, strip=False)


sen.PARSERS = {"old": parse_v010, "new": sen.parse_need}
sen.SYSTEMS = (("old_gated", parse_v010, None), ("new_gated", sen.parse_need, None),
               ("old_tier06", parse_v010, sen.TIER), ("new_tier06", sen.parse_need, sen.TIER))

if __name__ == "__main__":
    sys.exit(sen.main())
