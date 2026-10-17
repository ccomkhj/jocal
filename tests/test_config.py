"""`jocal.conf`: found through JOCAL_CONFIG or ~/.config/jocal/, and written once on first run."""

import unittest

from harness import JocalTest


class StarterConfig(JocalTest):
    def test_a_first_run_writes_a_starter_config_with_the_spec_defaults(self):
        r = self.jocal("pi", "--explain")
        self.assertEqual(r.returncode, 0, r.stderr)
        conf = self.config.read_text()
        for line in ['MODELS="4b=Qwen3.5-4B-MLX-4bit 9b=Qwen3.5-9B-MLX-4bit"', "CTX=32768", "MAX_OUT=4096",
                     "PORT=8000", "STOP_RUNTIME=last-exit", "PIN_PI=1.3.0", "LOCAL_INSTRUCTIONS_MAX_TOKENS=300"]:
            self.assertIn(line, conf)
        self.assertIn("local/Qwen3.5-4B-MLX-4bit", r.stdout)
        self.assertIn("http://127.0.0.1:8000/v1", r.stdout)

    def test_an_edited_config_is_never_overwritten(self):
        self.jocal("pi", "--explain")
        edited = 'MODELS="9b=Qwen3.5-9B-MLX-4bit"\nCTX=16384\n'
        self.config.write_text(edited)
        r = self.jocal("pi", "--explain")
        self.assertEqual(self.config.read_text(), edited)
        self.assertIn("local/Qwen3.5-9B-MLX-4bit", r.stdout)
        self.assertIn('"contextWindow": 16384', r.stdout)

    def test_without_overrides_config_and_state_live_under_home(self):
        env = dict(self.env)
        del env["JOCAL_CONFIG"], env["JOCAL_STATE"]
        self.env = env
        r = self.jocal("pi", "--explain")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue((self.home / ".config" / "jocal" / "jocal.conf").exists())
        self.assertIn(f"PI_CODING_AGENT_DIR={self.home}/.jocal/pi", r.stdout)

    def test_pi_bin_overrides_the_pi_on_path(self):
        self.write_conf()
        r = self.jocal("pi", "--explain", PI_BIN="/opt/pi/bin/pi")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("  /opt/pi/bin/pi --model", r.stdout)

    def test_an_empty_models_list_is_refused(self):
        self.write_conf('MODELS=""')
        r = self.jocal("pi", "--explain")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("MODELS", r.stderr)

    def test_a_key_that_could_pass_for_a_harness_flag_is_refused(self):
        self.write_conf('MODELS="4b=Qwen3.5-4B-MLX-4bit qwen=Qwen3.5-9B-MLX-4bit"')
        r = self.jocal("pi", "--explain")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("qwen", r.stderr)

    def test_a_window_that_leaves_no_read_budget_is_refused(self):
        self.write_conf("CTX=8192 MAX_OUT=4096")   # 8192 - 4096 - 8192 < 0
        for cmd in ("pi", "claude"):
            r = self.jocal(cmd, "--explain")
            self.assertEqual(r.returncode, 2, r.stderr)
            self.assertIn("CTX=8192", r.stderr)
            self.assertIn("MAX_OUT=4096", r.stderr)


if __name__ == "__main__":
    unittest.main()
