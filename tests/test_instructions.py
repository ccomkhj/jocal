"""Local instructions (`LOCAL.md`) appended to Pi's system prompt, and the instruction-size warnings."""

import unittest

from harness import JocalTest


class LocalInstructions(JocalTest):
    def setUp(self):
        super().setUp()
        self.write_conf()
        self.start_runtime()
        self.local_md = self.home / ".config" / "jocal" / "LOCAL.md"

    def test_a_first_run_writes_a_short_starter_local_md(self):
        r = self.jocal("pi")
        self.assertEqual(r.returncode, 0, r.stderr)
        starter = self.local_md.read_text()
        self.assertTrue(200 <= len(starter) <= 480, len(starter))   # ~80 tokens at chars/4

    def test_an_edited_local_md_is_never_overwritten(self):
        self.jocal("pi")
        self.local_md.write_text("Answer in French.\n")
        self.jocal("pi")
        self.assertEqual(self.local_md.read_text(), "Answer in French.\n")

    def test_pi_gets_local_md_as_its_append_system_prompt_file(self):
        self.jocal("pi")
        self.local_md.write_text("Answer in French.\n")
        self.jocal("pi")
        pi = self.pi_run()
        self.assertEqual(pi["files"]["APPEND_SYSTEM.md"], "Answer in French.\n")
        # The flag beats a trusted repo's .pi/APPEND_SYSTEM.md, which would otherwise replace it.
        flag = pi["argv"].index("--append-system-prompt")
        self.assertEqual(pi["argv"][flag + 1], str(self.state / "pi" / "APPEND_SYSTEM.md"))

    def test_an_empty_local_instructions_turns_them_off_even_after_a_session_with_them(self):
        self.jocal("pi")
        self.write_conf("LOCAL_INSTRUCTIONS=")
        r = self.jocal("pi")
        self.assertEqual(r.returncode, 0, r.stderr)
        pi = self.pi_run()
        self.assertNotIn("APPEND_SYSTEM.md", pi["files"])
        self.assertNotIn("--append-system-prompt", pi["argv"])

    def test_with_local_instructions_off_no_starter_is_written(self):
        self.write_conf("LOCAL_INSTRUCTIONS=")
        self.jocal("pi")
        self.assertFalse(self.local_md.exists())

    def test_local_md_past_the_token_budget_warns_but_pi_still_starts(self):
        self.write_conf("LOCAL_INSTRUCTIONS_MAX_TOKENS=100")
        self.local_md.parent.mkdir(parents=True, exist_ok=True)
        self.local_md.write_text("x" * 404 + "\n")   # 405 chars, ~101 tokens
        r = self.jocal("pi")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"{self.local_md} is ~101 tokens, over LOCAL_INSTRUCTIONS_MAX_TOKENS=100", r.stderr)
        self.assertIsNotNone(self.pi_run())

    def test_local_md_within_the_budget_does_not_warn(self):
        self.write_conf("LOCAL_INSTRUCTIONS_MAX_TOKENS=100")
        self.local_md.parent.mkdir(parents=True, exist_ok=True)
        self.local_md.write_text("x" * 399 + "\n")   # 400 chars, 100 tokens
        r = self.jocal("pi")
        self.assertNotIn("LOCAL_INSTRUCTIONS_MAX_TOKENS", r.stderr)


class ProjectInstructions(JocalTest):
    """The project's AGENTS.md/CLAUDE.md loads as Pi loads it; jocal only warns when it makes a cold reply slow."""

    def setUp(self):
        super().setUp()
        self.write_conf()
        self.start_runtime()

    def banner(self, r):
        return next(line for line in r.stderr.splitlines() if "\x1b[7m JOCAL" in line)

    def test_an_agents_md_over_1k_tokens_warns_in_the_banner(self):
        (self.project / "AGENTS.md").write_text("x" * 4400)
        r = self.jocal("pi")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("AGENTS.md is ~1100 tokens; each 1K adds 3-5 s to a cold first reply", self.banner(r))

    def test_a_small_agents_md_does_not_warn(self):
        (self.project / "AGENTS.md").write_text("x" * 3600)
        r = self.jocal("pi")
        self.assertNotIn("tokens", self.banner(r))

    def test_a_claude_md_in_a_parent_directory_counts_too(self):
        (self.project / "CLAUDE.md").write_text("x" * 2400)
        (self.project / "sub").mkdir()
        (self.project / "sub" / "AGENTS.md").write_text("x" * 2400)
        r = self.jocal("pi", cwd=self.project / "sub")
        self.assertIn("CLAUDE.md + AGENTS.md is ~1200 tokens", self.banner(r))

    def test_pi_is_not_told_to_skip_or_replace_the_project_file(self):
        (self.project / "AGENTS.md").write_text("x" * 4400)
        self.jocal("pi")
        argv = self.pi_run()["argv"]
        for flag in ["--no-context-files", "-nc", "--system-prompt"]:
            self.assertNotIn(flag, argv)


class Explain(JocalTest):
    def setUp(self):
        super().setUp()
        self.write_conf()

    def test_shows_the_local_instructions_file_in_use_and_what_pi_is_given(self):
        local_md = self.home / ".config" / "jocal" / "LOCAL.md"
        local_md.parent.mkdir(parents=True)
        local_md.write_text("Answer in French.\n")
        r = self.jocal("pi", "--explain")
        self.assertIn(f"local instructions: {local_md} (~4 tokens)", r.stdout)
        self.assertIn(f"--- {self.state}/pi/APPEND_SYSTEM.md\nAnswer in French.\n", r.stdout)
        self.assertIsNone(self.pi_run())

    def test_says_when_local_instructions_are_off(self):
        self.write_conf("LOCAL_INSTRUCTIONS=")
        r = self.jocal("pi", "--explain")
        self.assertIn("local instructions: off (LOCAL_INSTRUCTIONS is empty)", r.stdout)
        self.assertNotIn("APPEND_SYSTEM.md", r.stdout)

    def test_names_the_project_instruction_files_pi_will_load(self):
        (self.project / "AGENTS.md").write_text("x" * 400)
        r = self.jocal("pi", "--explain")
        self.assertIn(f"project instructions: {self.project}/AGENTS.md (~100 tokens)", r.stdout)

    def test_says_when_there_are_no_project_instructions(self):
        r = self.jocal("pi", "--explain")
        self.assertIn("project instructions: none", r.stdout)


if __name__ == "__main__":
    unittest.main()
