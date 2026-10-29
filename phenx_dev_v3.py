"""phenx-dev v3: phenx-dev-v2 unchanged, with a dbGaP outage waited out.

phenx-dev-v2 died on 2026-10-29 between 15:07 and 15:15 UTC: dbGaP's FHIR server answered 502 to the first study
page on all six tries (about 7.5 minutes), and the same page loaded normally at about 19:30 UTC. v3 runs v2 as it
is, but a failed harvest is retried whole, up to 4 times, 15 minutes apart, and the harvested study list is kept
in the job's data volume for later jobs. Scoring and every prediction are v2's.

Needs phenx_dev.py and phenx_dev_v2.py (unchanged) next to it. Standard library only. Made with AI agents working
in MV2's name (MV2, Munim, Inc.). Apache-2.0.
"""
import json
import os
import shutil
import sys
import time

import phenx_dev as v1
import phenx_dev_v2 as v2

__version__ = "0.4.0"

HARVEST_TRIES = 4
HARVEST_WAIT_S = 900


def patient_finder(finder, attempts, sleep=time.sleep, tries=HARVEST_TRIES, wait=HARVEST_WAIT_S, keep_dir=None,
                   today=lambda: time.strftime("%Y%m%d", time.gmtime())):
    """Wrap v1.finder: a failed harvest is retried after a wait (each try logged in attempts); others run once."""
    def run(args, work):
        if not args or args[0] != "harvest":
            return finder(args, work)
        for attempt in range(tries):
            started = time.time()
            try:
                out = finder(args, work)
            except SystemExit as err:
                attempts.append({"try": attempt + 1, "ok": False, "error": str(err),
                                 "seconds": round(time.time() - started)})
                if attempt == tries - 1:
                    raise
                sleep(wait)
                continue
            attempts.append({"try": attempt + 1, "ok": True, "seconds": round(time.time() - started)})
            break
        if keep_dir and os.path.isdir(keep_dir):
            shutil.copyfile(args[args.index("--out") + 1],
                            os.path.join(keep_dir, "dbgap-studies-%s.jsonl" % today()))
        return out
    return run


def main(out_dir, page_qrels_url, keep_dir="/data"):
    os.makedirs(out_dir, exist_ok=True)
    attempts = []
    v1.finder = patient_finder(v1.finder, attempts, keep_dir=keep_dir)
    try:
        v2.main(out_dir, page_qrels_url)
    finally:
        with open(os.path.join(out_dir, "harvest_attempts.json"), "w", encoding="utf-8") as f:
            json.dump({"version": __version__, "attempts": attempts}, f, indent=1)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2])
