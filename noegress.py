#!/usr/bin/env python3
"""noegress: run a Python script with every outbound network call refused, and count the attempts.

SPARK runs submitted systems with all external network calls blocked. Docker's
--network none does that for real; this is the same check inside a sandbox
that has a network: socket connects, sends and name lookups raise OSError and
are recorded.

    NOEGRESS_LOG=noegress.json python noegress.py script.py [args...]

Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
"""

import atexit
import json
import os
import runpy
import socket
import sys

ATTEMPTS = []


def _refuse(name, method):
    def refused(*args, **kwargs):
        shown = args[1:] if method else args
        ATTEMPTS.append({"call": name, "args": repr(shown)[:120]})
        raise OSError("network blocked by noegress: %s" % name)
    return refused


def install():
    for name in ("connect", "connect_ex", "sendto"):
        setattr(socket.socket, name, _refuse("socket." + name, True))
    for name in ("create_connection", "getaddrinfo", "gethostbyname"):
        setattr(socket, name, _refuse(name, False))


def write_log():
    with open(os.environ.get("NOEGRESS_LOG") or "noegress.json", "w", encoding="utf-8") as f:
        json.dump({"attempts": len(ATTEMPTS), "calls": ATTEMPTS[:50]}, f, indent=1)


if __name__ == "__main__":
    install()
    atexit.register(write_log)
    sys.argv = sys.argv[1:]
    runpy.run_path(sys.argv[0], run_name="__main__")
