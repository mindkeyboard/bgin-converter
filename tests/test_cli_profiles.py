"""Public CLI conversions preserve source bytes and require an explicit target."""
import json
import os
from pathlib import Path
import subprocess
import sys
import tempfile
import unittest

from bgin_json import encode, parse


class ProfileCliTests(unittest.TestCase):
    def test_four_targets_in_separate_processes(self):
        with tempfile.TemporaryDirectory() as folder:
            root = Path(folder)
            source = root / "source.bgin"
            original = encode({"name": "cli", "screens": [{"type": "StackContainer", "name": "main"}]})
            source.write_bytes(original)
            project = Path(__file__).resolve().parents[1]
            env = dict(os.environ, PYTHONPATH=os.pathsep.join((str(project / "src"), str(project / "vendor"))))
            for mode in ("a8-0.0.2", "a8-1.6.0", "a8-3.7.0", "a8-5.8.0"):
                target = root / (mode + ".bgin")
                result = subprocess.run([sys.executable, "-m", "bgin_json", str(source),
                                         "--to", "bgin", "--target-format", mode, "-o", str(target)],
                                        env=env, capture_output=True, text=True)
                self.assertEqual(result.returncode, 0, result.stderr)
                self.assertEqual(parse(target.read_bytes())["format"], mode)
            self.assertEqual(source.read_bytes(), original)
            rejected = subprocess.run([sys.executable, "-m", "bgin_json", str(source),
                                       "--to", "bgin", "-o", str(root / "missing.bgin")],
                                      env=env, capture_output=True, text=True)
            self.assertEqual(rejected.returncode, 1)
            self.assertIn("explicit target", json.loads(rejected.stderr)["error"])
            self.assertFalse((root / "missing.bgin").exists())
