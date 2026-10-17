"""`jocal pi`: Pi on the local model against a running oMLX, with nothing from the cloud profile."""

import json
import unittest
from pathlib import Path

from harness import JocalTest


class PiSession(JocalTest):
    def setUp(self):
        super().setUp()
        self.write_conf()
        self.start_runtime()

    def test_starts_pi_on_the_default_model_with_the_local_flags(self):
        r = self.jocal("pi")
        self.assertEqual(r.returncode, 0, r.stderr)
        pi = self.pi_run()
        self.assertEqual(pi["argv"], ["--model", "local/Qwen3.5-4B-MLX-4bit", "--no-skills", "--no-prompt-templates",
                                      "--tools", "read,edit,write,bash", "--no-mcp",
                                      "--extension", str(self.state / "pi" / "read.ts"),
                                      "--append-system-prompt", str(self.state / "pi" / "APPEND_SYSTEM.md")])

    def test_pi_runs_offline_with_its_own_agent_dir(self):
        self.jocal("pi")
        env = self.pi_run()["env"]
        self.assertEqual(env["PI_CODING_AGENT_DIR"], str(self.state / "pi"))
        self.assertEqual(env["PI_OFFLINE"], "1")
        self.assertEqual(env["PI_TELEMETRY"], "0")
        self.assertEqual(env["PI_SKIP_VERSION_CHECK"], "1")

    def test_models_json_points_at_the_local_runtime_with_every_model(self):
        self.write_conf("CTX=16384 MAX_OUT=2048")
        self.jocal("pi")
        models = json.loads(self.pi_run()["files"]["models.json"])
        local = models["providers"]["local"]
        self.assertEqual(local["baseUrl"], f"http://127.0.0.1:{self.port}/v1")
        self.assertEqual([m["id"] for m in local["models"]], ["Qwen3.5-4B-MLX-4bit", "Qwen3.5-9B-MLX-4bit"])
        self.assertEqual({m["contextWindow"] for m in local["models"]}, {16384})
        self.assertEqual({m["maxTokens"] for m in local["models"]}, {2048})

    def test_settings_json_turns_telemetry_off_and_sizes_compaction(self):
        self.write_conf("MAX_OUT=2048")
        self.jocal("pi")
        settings = json.loads(self.pi_run()["files"]["settings.json"])
        self.assertIs(settings["enableInstallTelemetry"], False)
        self.assertEqual(settings["compaction"], {"reserveTokens": 2048, "keepRecentTokens": 8000})

    def test_pi_loads_the_read_extension_with_the_cap_sized_to_the_window(self):
        self.jocal("pi")
        pi = self.pi_run()
        extension = self.state / "pi" / "read.ts"
        self.assertIn("--extension", pi["argv"])
        self.assertEqual(pi["argv"][pi["argv"].index("--extension") + 1], str(extension))
        self.assertEqual(pi["files"]["read.ts"], (Path(__file__).parents[1] / "read.ts").read_text())
        self.assertEqual(pi["env"]["JOCAL_READ_CAP_TOKENS"], "20480")   # ~20K at CTX=32768, MAX_OUT=4096

    def test_the_read_cap_follows_ctx_and_max_out(self):
        self.write_conf("CTX=16384 MAX_OUT=2048")
        self.jocal("pi")
        self.assertEqual(self.pi_run()["env"]["JOCAL_READ_CAP_TOKENS"], "6144")

    def test_9b_flag_selects_the_opt_in_model(self):
        self.jocal("pi", "--9b")
        self.assertEqual(self.pi_run()["argv"][:2], ["--model", "local/Qwen3.5-9B-MLX-4bit"])

    def test_a_key_added_to_models_gets_its_own_flag(self):
        self.write_conf('MODELS="4b=Qwen3.5-4B-MLX-4bit 9b=Qwen3.5-9B-MLX-4bit gemma12b=gemma-4-12b-it-4bit"')
        self.jocal("pi", "--gemma12b")
        pi = self.pi_run()
        self.assertEqual(pi["argv"][:2], ["--model", "local/gemma-4-12b-it-4bit"])
        local = json.loads(pi["files"]["models.json"])["providers"]["local"]
        self.assertIn("gemma-4-12b-it-4bit", [m["id"] for m in local["models"]])

    def test_the_first_key_in_models_is_the_default(self):
        self.write_conf('MODELS="9b=Qwen3.5-9B-MLX-4bit 4b=Qwen3.5-4B-MLX-4bit"')
        self.jocal("pi")
        self.assertEqual(self.pi_run()["argv"][:2], ["--model", "local/Qwen3.5-9B-MLX-4bit"])

    def test_an_unknown_key_fails_listing_the_known_keys_and_starts_nothing(self):
        r = self.jocal("pi", "--27b")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn("27b", r.stderr)
        self.assertIn("4b", r.stderr)
        self.assertIn("9b", r.stderr)
        self.assertIsNone(self.pi_run())
        self.assertEqual(self.omlx_calls(), [])

    def test_arguments_after_the_jocal_ones_reach_pi_unchanged(self):
        self.jocal("pi", "--9b", "-p", "say --4b and hi", "--continue", "--9b", "")
        self.assertEqual(self.pi_run()["argv"][-5:], ["-p", "say --4b and hi", "--continue", "--9b", ""])

    def test_harness_flags_without_a_digit_are_not_taken_for_model_keys(self):
        r = self.jocal("pi", "--continue")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.pi_run()["argv"][-1], "--continue")
        self.assertIn("local/Qwen3.5-4B-MLX-4bit", self.pi_run()["argv"])

    def test_a_reverse_video_banner_marks_the_session_as_local(self):
        r = self.jocal("pi", "--9b")
        banner = f"\x1b[7m JOCAL · pi · 9b (Qwen3.5-9B-MLX-4bit) · oMLX http://127.0.0.1:{self.port} · prompts stay on this Mac \x1b[0m"
        self.assertIn(banner, r.stderr)

    def test_the_terminal_title_names_the_harness_and_model(self):
        r = self.jocal("pi", "--9b")
        self.assertIn("\x1b]0;JOCAL · pi · 9b\x07", r.stderr)
        self.assertEqual(r.stdout, "")

    def test_the_title_is_cleared_when_pi_exits_even_on_failure(self):
        r = self.jocal("pi", FAKE_PI_EXIT="1")
        self.assertTrue(r.stderr.endswith("\x1b]0;\x07"), repr(r.stderr[-20:]))

    def test_pi_exit_status_is_jocal_exit_status(self):
        r = self.jocal("pi", FAKE_PI_EXIT="3")
        self.assertEqual(r.returncode, 3)

    def test_the_profile_is_regenerated_each_session_and_pi_sessions_survive(self):
        self.jocal("pi")
        (self.state / "pi" / "settings.json").write_text("{}")
        (self.state / "pi" / "sessions").mkdir()
        (self.state / "pi" / "sessions" / "s1.jsonl").write_text("history\n")
        self.jocal("pi")
        self.jocal("pi", "--explain")
        self.assertIn("compaction", json.loads(self.pi_run()["files"]["settings.json"]))
        self.assertEqual((self.state / "pi" / "sessions" / "s1.jsonl").read_text(), "history\n")

    def test_an_env_pi_bin_beats_the_one_in_the_config(self):
        self.write_conf("PI_BIN=/nonexistent/pi")
        r = self.jocal("pi", PI_BIN=str(Path(__file__).parent / "fakes" / "pi"))
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIsNotNone(self.pi_run())


class Explain(JocalTest):
    def setUp(self):
        super().setUp()
        self.write_conf()

    def test_lists_env_flags_and_generated_files_and_starts_nothing(self):
        r = self.jocal("pi", "--explain", "--9b", "-p", "hi")
        self.assertEqual(r.returncode, 0, r.stderr)
        for line in ["PI_CODING_AGENT_DIR=" + str(self.state / "pi"), "PI_OFFLINE=1", "PI_TELEMETRY=0",
                     "PI_SKIP_VERSION_CHECK=1"]:
            self.assertIn(line, r.stdout)
        self.assertIn("pi --model local/Qwen3.5-9B-MLX-4bit --no-skills --no-prompt-templates "
                      f"--tools read,edit,write,bash --no-mcp --extension {self.state}/pi/read.ts --append-system-prompt {self.state}/pi/APPEND_SYSTEM.md -p hi",
                      r.stdout)
        for name in ["models.json", "settings.json"]:
            path = self.state / "pi" / name
            self.assertIn(str(path), r.stdout)
            self.assertIn(path.read_text(), r.stdout)
        self.assertIsNone(self.pi_run())
        self.assertEqual(self.omlx_calls(), [])

    def test_shows_the_read_cap(self):
        r = self.jocal("pi", "--explain")
        self.assertIn("read cap: ~20480 tokens (81920 chars)", r.stdout)
        self.assertIn("JOCAL_READ_CAP_TOKENS=20480", r.stdout)

    def test_works_with_the_model_key_first(self):
        r = self.jocal("pi", "--9b", "--explain")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("local/Qwen3.5-9B-MLX-4bit", r.stdout)
        self.assertIsNone(self.pi_run())


if __name__ == "__main__":
    unittest.main()
