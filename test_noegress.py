# Tests for noegress.py (standard library only; nothing leaves the machine because every call is refused).
# Made by MV2 of Munim, Inc. with AI agents. Apache-2.0 license.
import json
import os
import subprocess
import sys
import tempfile
import unittest

HERE = os.path.dirname(os.path.abspath(__file__))

FETCH = """import sys, urllib.request
try:
    urllib.request.urlopen("http://example.invalid/", timeout=5)
except OSError as err:
    print("refused:", err)
sys.exit(0)
"""

QUIET = "import sys\nprint(sys.argv[1:])\nsys.exit(3)\n"


class NoEgressTest(unittest.TestCase):
    def run_guarded(self, source, *args):
        with tempfile.TemporaryDirectory() as d:
            script, log = os.path.join(d, "script.py"), os.path.join(d, "log.json")
            with open(script, "w", encoding="utf-8") as f:
                f.write(source)
            env = dict(os.environ, NOEGRESS_LOG=log)
            proc = subprocess.run([sys.executable, os.path.join(HERE, "noegress.py"), script] + list(args),
                                  env=env, stdout=subprocess.PIPE, stderr=subprocess.STDOUT)
            with open(log, encoding="utf-8") as f:
                return proc.returncode, proc.stdout.decode("utf-8", "replace"), json.load(f)

    def test_network_call_is_refused_and_counted(self):
        code, out, log = self.run_guarded(FETCH)
        self.assertEqual(code, 0)
        self.assertIn("noegress", out)
        self.assertGreaterEqual(log["attempts"], 1)
        self.assertIn(log["calls"][0]["call"], ("getaddrinfo", "create_connection", "socket.connect"))

    def test_quiet_script_keeps_args_and_exit_code(self):
        code, out, log = self.run_guarded(QUIET, "a", "b")
        self.assertEqual(code, 3)
        self.assertIn("['a', 'b']", out)
        self.assertEqual(log, {"attempts": 0, "calls": []})


if __name__ == "__main__":
    unittest.main()
