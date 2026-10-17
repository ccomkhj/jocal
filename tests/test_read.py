"""The Pi read extension (`read.ts`), through Pi's extension interface: its default export registers a `read`
tool, run here by `read_tool.mjs` on fixture files below, at and above the cap.

The cap is JOCAL_READ_CAP_TOKENS, estimated as chars/4; these tests use 100 tokens, so 400 chars.
"""

import json
import shutil
import subprocess
import tempfile
import unittest
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
EXTENSION = REPO / "read.ts"
DRIVER = Path(__file__).resolve().parent / "read_tool.mjs"
NODE = shutil.which("node")


@unittest.skipUnless(NODE, "node is not on PATH")
class ReadExtension(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp(prefix="jocal-read-"))

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def lines(self, name, n, width=10):
        """A file of `n` numbered lines, each `width` chars with its newline."""
        path = self.dir / name
        path.write_text("".join(f"{i:0{width - 2}d}|\n" for i in range(1, n + 1)))
        return path

    def read(self, cap=100, **params):
        """Runs the read tool with JOCAL_READ_CAP_TOKENS=cap (unset when cap is None)."""
        env = {} if cap is None else {"JOCAL_READ_CAP_TOKENS": str(cap)}
        r = subprocess.run([NODE, str(DRIVER), EXTENSION.as_uri(), str(self.dir), json.dumps(params)],
                           env=env, capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["name"], "read")
        return out

    def test_a_file_under_the_cap_comes_back_whole(self):
        path = self.lines("small.txt", 30)   # 300 chars
        self.assertEqual(self.read(path="small.txt")["text"], path.read_text())

    def test_a_file_at_the_cap_comes_back_whole(self):
        path = self.lines("exact.txt", 40)   # 400 chars
        self.assertEqual(self.read(path="exact.txt")["text"], path.read_text())

    def test_a_file_over_the_cap_is_refused_naming_its_size_and_the_summarise_command(self):
        path = self.dir / "big.txt"
        path.write_text("x" * 401)
        out = self.read(path="big.txt")
        self.assertNotIn("text", out)
        self.assertIn("big.txt is 401 chars (~100 tokens)", out["error"])
        self.assertIn("read cap of ~100 tokens", out["error"])
        self.assertIn('jocal summarise big.txt "<question>"', out["error"])

    def test_the_summarise_command_quotes_a_path_the_shell_would_split(self):
        (self.dir / "my notes.txt").write_text("x" * 2000)
        out = self.read(path="my notes.txt")
        self.assertIn("""jocal summarise 'my notes.txt' "<question>\"""", out["error"])
        self.assertIn("my notes.txt is 2,000 chars (~500 tokens)", out["error"])

    def test_offset_and_limit_read_a_slice_of_a_file_over_the_cap(self):
        self.lines("big.txt", 100)   # 1,000 chars
        out = self.read(path="big.txt", offset=51, limit=3)
        self.assertEqual(out["text"], "00000051|\n00000052|\n00000053|\n\n\n[47 more lines in file. Use offset=54 to continue.]")

    def test_an_offset_alone_reads_to_the_end(self):
        self.lines("big.txt", 100)
        self.assertEqual(self.read(path="big.txt", offset=99)["text"], "00000099|\n00000100|\n")

    def test_a_slice_over_the_cap_stops_at_the_last_whole_line_under_it_and_says_where_to_go_on(self):
        self.lines("big.txt", 100)
        out = self.read(path="big.txt", offset=11, limit=60)   # 600 chars asked for
        lines = "".join(f"{i:08d}|\n" for i in range(11, 51))   # 40 lines, 400 chars
        self.assertEqual(out["text"], lines + "\n\n[Showing lines 11-50 of 100 (read cap ~100 tokens). Use offset=51 to continue.]")

    def test_a_slice_whose_first_line_is_over_the_cap_is_refused(self):
        (self.dir / "wide.csv").write_text("a\n" + "x" * 500 + "\nb\n")
        out = self.read(path="wide.csv", offset=2, limit=1)
        self.assertIn("line 2 of wide.csv is 501 chars, over the read cap of ~100 tokens", out["error"])
        self.assertIn('jocal summarise wide.csv "<question>"', out["error"])

    def test_an_offset_past_the_end_is_an_error(self):
        self.lines("small.txt", 3)
        self.assertIn("Offset 9 is beyond end of file (3 lines total)", self.read(path="small.txt", offset=9)["error"])

    def test_without_a_valid_cap_every_read_is_refused(self):
        self.lines("small.txt", 3)
        for cap in (None, "", "abc", "0", "-5"):
            for params in ({}, {"offset": 1}):
                out = self.read(cap=cap, path="small.txt", **params)
                self.assertNotIn("text", out, (cap, params))
                self.assertIn("JOCAL_READ_CAP_TOKENS", out["error"])
                self.assertIn("jocal pi", out["error"])


if __name__ == "__main__":
    unittest.main()
