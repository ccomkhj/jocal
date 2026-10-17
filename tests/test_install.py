"""`install.sh`: puts `jocal` on PATH as a symlink into the repo, so repo edits take effect without reinstalling."""

import subprocess
import unittest

from harness import JOCAL, REPO, JocalTest

INSTALL = REPO / "install.sh"


class Install(JocalTest):
    def test_links_jocal_into_the_bin_dir_and_it_runs_through_the_link(self):
        bin_dir = self.home / ".local" / "bin"
        r = subprocess.run([str(INSTALL), str(bin_dir)], env=self.env, capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        link = bin_dir / "jocal"
        self.assertTrue(link.is_symlink())
        self.assertEqual(link.resolve(), JOCAL.resolve())

        self.write_conf()
        r = subprocess.run(["jocal", "pi", "--explain"], env=self.env | {"PATH": f"{bin_dir}:{self.env['PATH']}"},
                           capture_output=True, text=True, timeout=20)
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("local/Qwen3.5-4B-MLX-4bit", r.stdout)

    def test_refuses_to_replace_a_jocal_that_is_not_ours(self):
        bin_dir = self.home / "bin"
        bin_dir.mkdir()
        (bin_dir / "jocal").write_text("someone else's\n")
        r = subprocess.run([str(INSTALL), str(bin_dir)], env=self.env, capture_output=True, text=True, timeout=20)
        self.assertNotEqual(r.returncode, 0)
        self.assertEqual((bin_dir / "jocal").read_text(), "someone else's\n")


if __name__ == "__main__":
    unittest.main()
