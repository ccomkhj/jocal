"""`jocal claude`: Claude Code on the local model, with no token, config, MCP server or settings from the cloud profile."""

import json
import subprocess
import unittest
from pathlib import Path

from harness import JocalTest


class ClaudeSession(JocalTest):
    def setUp(self):
        super().setUp()
        self.write_conf("CTX=16384 MAX_OUT=2048")
        self.start_runtime()

    def test_claude_runs_on_the_local_runtime_with_its_own_config_dir_and_a_dummy_token(self):
        r = self.jocal("claude", "--9b", ANTHROPIC_API_KEY="sk-real", CLAUDE_CONFIG_DIR=str(self.home / ".claude"))
        self.assertEqual(r.returncode, 0, r.stderr)
        env = self.claude_run()["env"]
        self.assertEqual(env["CLAUDE_CONFIG_DIR"], str(self.state / "claude"))
        self.assertEqual(env["ANTHROPIC_BASE_URL"], f"http://127.0.0.1:{self.port}")
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "local")
        self.assertEqual(env["ANTHROPIC_API_KEY"], "")
        for name in ["ANTHROPIC_MODEL", "ANTHROPIC_DEFAULT_OPUS_MODEL", "ANTHROPIC_DEFAULT_SONNET_MODEL",
                     "ANTHROPIC_DEFAULT_HAIKU_MODEL", "ANTHROPIC_DEFAULT_FABLE_MODEL", "CLAUDE_CODE_SUBAGENT_MODEL"]:
            self.assertEqual(env[name], "Qwen3.5-9B-MLX-4bit", name)

    def test_budgets_thinking_and_traffic_are_set_for_the_local_window(self):
        self.jocal("claude")
        env = self.claude_run()["env"]
        self.assertEqual(env["CLAUDE_CODE_MAX_CONTEXT_TOKENS"], "16384")
        self.assertEqual(env["CLAUDE_CODE_MAX_OUTPUT_TOKENS"], "2048")
        self.assertEqual(env["MAX_THINKING_TOKENS"], "0")
        self.assertEqual(env["CLAUDE_CODE_DISABLE_NONESSENTIAL_TRAFFIC"], "1")
        self.assertEqual(env["CLAUDE_CODE_DISABLE_EXPERIMENTAL_BETAS"], "1")

    def test_the_read_budget_is_the_same_cap_as_pis(self):
        self.jocal("claude")
        self.assertEqual(self.claude_run()["env"]["CLAUDE_CODE_FILE_READ_MAX_OUTPUT_TOKENS"], "6144")
        self.jocal("pi")
        self.assertEqual(self.pi_run()["env"]["JOCAL_READ_CAP_TOKENS"], "6144")

    def test_no_real_token_or_user_config_dir_reaches_claude(self):
        secrets = {"ANTHROPIC_API_KEY": "sk-real-key", "CLAUDE_CODE_OAUTH_TOKEN": "sk-real-oauth",
                   "ANTHROPIC_AUTH_TOKEN": "sk-real-auth", "CLAUDE_CODE_USE_BEDROCK": "1"}
        self.jocal("claude", CLAUDE_CONFIG_DIR=str(self.home / ".claude"), **secrets)
        run = self.claude_run()
        seen = json.dumps(run)
        for value in ["sk-real-key", "sk-real-oauth", "sk-real-auth", str(self.home / ".claude")]:
            self.assertNotIn(value, seen)
        for name in ["ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN", "CLAUDE_CODE_USE_BEDROCK"]:
            self.assertEqual(run["env"][name], "", name)

    def test_strict_empty_mcp_config_and_the_four_core_tools(self):
        r = self.jocal("claude", "--continue")
        self.assertEqual(r.returncode, 0, r.stderr)
        run = self.claude_run()
        self.assertEqual(run["argv"], ["--settings", str(self.state / "claude-settings-4b.json"), "--strict-mcp-config",
                                       "--mcp-config", str(self.state / "claude-mcp.json"),
                                       "--tools", "Read,Edit,Write,Bash", "--disallowedTools", "mcp__*", "--continue"])
        self.assertEqual(json.loads(run["files"]["--mcp-config"]), {"mcpServers": {}})

    def test_settings_pin_the_base_url_and_turn_off_auto_mode_updates_git_status_and_title(self):
        self.jocal("claude", "--9b")
        settings = json.loads(self.claude_run()["files"]["--settings"])
        self.assertEqual(settings["env"]["ANTHROPIC_BASE_URL"], f"http://127.0.0.1:{self.port}")
        self.assertEqual(settings["permissions"]["defaultMode"], "default")
        self.assertIs(settings["autoUpdates"], False)
        self.assertEqual(settings["env"]["DISABLE_AUTOUPDATER"], "1")
        self.assertIs(settings["includeGitInstructions"], False)
        self.assertEqual(settings["env"]["CLAUDE_CODE_DISABLE_TERMINAL_TITLE"], "1")

    def test_settings_pin_the_provider_and_tokens_against_a_repos_settings_env(self):
        self.jocal("claude")
        env = json.loads(self.claude_run()["files"]["--settings"])["env"]
        for name in ["CLAUDE_CODE_USE_BEDROCK", "CLAUDE_CODE_USE_VERTEX", "CLAUDE_CODE_USE_FOUNDRY",
                     "ANTHROPIC_API_KEY", "CLAUDE_CODE_OAUTH_TOKEN"]:
            self.assertEqual(env[name], "", name)
        self.assertEqual(env["ANTHROPIC_AUTH_TOKEN"], "local")

    def test_the_status_line_reads_jocal_and_the_model_key(self):
        self.jocal("claude", "--9b")
        status = json.loads(self.claude_run()["files"]["--settings"])["statusLine"]
        self.assertEqual(status["type"], "command")
        out = subprocess.run(["sh", "-c", status["command"]], capture_output=True, text=True).stdout
        self.assertEqual(out, "\x1b[7m JOCAL · 9b \x1b[0m")
        settings = json.loads(self.claude_run()["files"]["--settings"])
        self.assertNotIn("disableAllHooks", settings)   # it turns the custom status line off too

    def test_a_reverse_video_banner_and_title_name_claude_code(self):
        r = self.jocal("claude", "--9b")
        self.assertIn(f"\x1b[7m JOCAL · claude · 9b (Qwen3.5-9B-MLX-4bit) · oMLX http://127.0.0.1:{self.port} · "
                      "prompts stay on this Mac \x1b[0m", r.stderr)
        self.assertIn("\x1b]0;JOCAL · claude · 9b\x07", r.stderr)
        self.assertTrue(r.stderr.endswith("\x1b]0;\x07"), repr(r.stderr[-20:]))

    def test_print_mode_drops_the_unrecognized_model_line_and_keeps_the_rest(self):
        r = self.jocal("claude", "-p", "hi", FAKE_CLAUDE_STDERR="a real error")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("unrecognized_model", r.stderr)
        self.assertIn("a real error\n", r.stderr)
        self.assertEqual(r.stdout, "an answer\n")
        self.assertTrue(r.stderr.endswith("\x1b]0;\x07"), repr(r.stderr[-20:]))

    def test_print_mode_in_combined_short_flags_drops_it_too(self):
        r = self.jocal("claude", "-cp", "hi")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertNotIn("unrecognized_model", r.stderr)
        self.assertEqual(r.stdout, "an answer\n")

    def test_claude_exit_status_is_jocal_exit_status(self):
        self.assertEqual(self.jocal("claude", FAKE_CLAUDE_EXIT="3").returncode, 3)
        self.assertEqual(self.jocal("claude", "-p", "hi", FAKE_CLAUDE_EXIT="4").returncode, 4)


class ClaudeLifecycle(JocalTest):
    def setUp(self):
        super().setUp()
        self.write_conf(f"MODELS_DIR={self.tmp}/models")

    def test_starts_the_runtime_on_demand_holds_a_lease_and_stops_it_on_exit(self):
        proc = self.start_session("--9b", harness="claude")
        self.assertTrue(self.runtime_answers())
        self.assertEqual((self.state / "leases" / str(proc.pid)).read_text().splitlines()[0], "claude 9b")
        pid = self.omlx_pid()
        self.end_session(proc)
        self.assertEqual(proc.returncode, 0)
        self.assertEqual(self.leases(), [])
        self.wait_for(lambda: not self.runtime_answers(), "runtime stop")
        self.assertIsNone(self.omlx_pid())
        self.assertNotEqual(pid, None)


    def test_sessions_on_different_keys_keep_their_own_status_line(self):
        self.start_session(harness="claude")
        first = self.claude_run()["argv"]
        self.start_session("--9b", harness="claude")
        settings = first[first.index("--settings") + 1]
        self.assertIn("JOCAL · 4b", json.loads(Path(settings).read_text())["statusLine"]["command"])


class ClaudeExplain(JocalTest):
    def setUp(self):
        super().setUp()
        self.write_conf()

    def test_lists_env_flags_and_generated_files_and_starts_nothing(self):
        r = self.jocal("claude", "--explain", "--9b", "-p", "hi")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("JOCAL · claude · 9b", r.stdout)
        for line in ["CLAUDE_CONFIG_DIR=" + str(self.state / "claude"), "ANTHROPIC_AUTH_TOKEN=local",
                     f"ANTHROPIC_BASE_URL=http://127.0.0.1:{self.port}", "ANTHROPIC_MODEL=Qwen3.5-9B-MLX-4bit",
                     "CLAUDE_CODE_SUBAGENT_MODEL=Qwen3.5-9B-MLX-4bit", "CLAUDE_CODE_MAX_CONTEXT_TOKENS=32768",
                     "MAX_THINKING_TOKENS=0"]:
            self.assertIn(line, r.stdout)
        self.assertIn(f"claude --settings {self.state}/claude-settings-9b.json --strict-mcp-config --mcp-config "
                      f"{self.state}/claude-mcp.json --tools Read,Edit,Write,Bash --disallowedTools mcp__\\* -p hi",
                      r.stdout)
        for name in ["claude-settings-9b.json", "claude-mcp.json"]:
            path = self.state / name
            self.assertIn(str(path), r.stdout)
            self.assertIn(path.read_text(), r.stdout)
        self.assertIsNone(self.claude_run())
        self.assertEqual(self.omlx_calls(), [])


if __name__ == "__main__":
    unittest.main()
