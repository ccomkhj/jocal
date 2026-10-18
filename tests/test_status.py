"""`jocal status`: runtime state, loaded models, leases, disk and model-count budgets, pin drift and instruction size."""

import unittest

from harness import JocalTest


class StatusTest(JocalTest):
    def setUp(self):
        super().setUp()
        self.models = self.tmp / "models"
        self.models.mkdir()

    def model(self, folder, gb=1.0, revision=None):
        """An installed model folder holding `gb` GB of (sparse) weights and, if given, the revision fetch-model.sh records."""
        d = self.models / folder
        d.mkdir()
        with open(d / "model.safetensors", "wb") as f:
            f.truncate(int(gb * 10**9))
        if revision:
            (d / "REVISION").write_text(revision + "\n")

    def warnings(self, r):
        return [line for line in r.stdout.splitlines() if line.startswith("warning:")]


class Runtime(StatusTest):
    def setUp(self):
        super().setUp()
        self.write_conf(f"MODELS_DIR={self.tmp}/models")

    def test_a_runtime_that_is_down_is_reported_down(self):
        r = self.jocal("status")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn(f"runtime: down (http://127.0.0.1:{self.port})", r.stdout)

    def test_a_running_runtime_shows_its_loaded_models_and_the_live_leases(self):
        self.start_runtime(loaded=["Qwen3.5-9B-MLX-4bit"])
        session = self.start_session("--9b")
        r = self.jocal("status")
        self.assertIn(f"runtime: up (http://127.0.0.1:{self.port})", r.stdout)
        self.assertIn("loaded: Qwen3.5-9B-MLX-4bit", r.stdout)
        self.assertIn(f"leases: {session.pid} (pi 9b)", r.stdout)

    def test_nothing_loaded_and_no_leases_say_none(self):
        self.start_runtime()
        r = self.jocal("status")
        self.assertIn("loaded: none", r.stdout)
        self.assertIn("leases: none", r.stdout)


class Budgets(StatusTest):
    def conf(self, extra=""):
        self.write_conf(f"MODELS_DIR={self.models} DISK_CAP_GB=10 MAX_MODELS=2\n{extra}")

    def test_disk_use_and_model_count_within_budget_are_shown_without_a_warning(self):
        self.conf()
        self.model("Qwen3.5-4B-MLX-4bit", 3)
        self.model("Qwen3.5-9B-MLX-4bit", 5.5)
        r = self.jocal("status")
        self.assertIn("models: 2 installed (MAX_MODELS=2), 8.5 GB on disk (DISK_CAP_GB=10)", r.stdout)
        self.assertEqual([w for w in self.warnings(r) if "MAX_MODELS" in w or "DISK_CAP_GB" in w], [])

    def test_a_disk_overrun_warns(self):
        self.conf()
        self.model("Qwen3.5-4B-MLX-4bit", 3)
        self.model("Qwen3.5-9B-MLX-4bit", 7.5)
        r = self.jocal("status")
        self.assertIn("warning: installed models use 10.5 GB, over DISK_CAP_GB=10", self.warnings(r))

    def test_a_model_count_overrun_warns(self):
        self.conf()
        for m in ("a-1", "b-2", "c-3"):
            self.model(m)
        r = self.jocal("status")
        self.assertIn("warning: 3 models installed, over MAX_MODELS=2", self.warnings(r))

    def test_a_candidate_under_trial_allows_one_extra_model(self):
        self.conf('MODELS="4b=a-1 9b=b-2 5b=c-3" CANDIDATE=5b:4b')
        for m in ("a-1", "b-2", "c-3"):
            self.model(m)
        r = self.jocal("status")
        self.assertIn("candidate under trial: 5b (c-3) challenges 4b (a-1)", r.stdout)
        self.assertIn("models: 3 installed (MAX_MODELS=2 + 1 candidate)", r.stdout)
        self.assertEqual([w for w in self.warnings(r) if "MAX_MODELS" in w], [])

    def test_a_candidate_still_warns_at_two_extra_models(self):
        self.conf('MODELS="4b=a-1 9b=b-2 5b=c-3" CANDIDATE=5b:4b')
        for m in ("a-1", "b-2", "c-3", "d-4"):
            self.model(m)
        r = self.jocal("status")
        self.assertIn("warning: 4 models installed, over MAX_MODELS=2 + 1 candidate", self.warnings(r))

    def test_the_disk_cap_stays_hard_during_a_trial(self):
        self.conf('MODELS="4b=a-1 9b=b-2 5b=c-3" CANDIDATE=5b:4b')
        for m in ("a-1", "b-2", "c-3"):
            self.model(m, 4)
        r = self.jocal("status")
        self.assertIn("warning: installed models use 12.0 GB, over DISK_CAP_GB=10", self.warnings(r))


class Pins(StatusTest):
    def setUp(self):
        super().setUp()
        self.write_conf(f'MODELS_DIR={self.models} PIN_OMLX=0.7.0 PIN_PI=1.3.0 PIN_CLAUDE=2.1.302\n'
                        'MODELS="4b=Small-4bit 9b=Big-4bit" PIN_MODELS="4b=org/Small-4bit@aaa111 9b=org/Big-4bit@bbb222"')
        self.model("Small-4bit", revision="org/Small-4bit@aaa111")
        self.model("Big-4bit", revision="org/Big-4bit@bbb222")

    def test_binaries_at_their_pins_are_shown_without_a_warning(self):
        r = self.jocal("status")
        self.assertIn("omlx 0.7.0, pi 1.3.0, claude 2.1.302: at their pins", r.stdout)
        self.assertEqual(self.warnings(r), [])

    def test_a_binary_off_its_pin_is_flagged_with_the_upgrade_check(self):
        for name, var in (("omlx", "PIN_OMLX"), ("pi", "PIN_PI"), ("claude", "PIN_CLAUDE")):
            with self.subTest(name):
                r = self.jocal("status", **{f"FAKE_{name.upper()}_VERSION": "9.9.9"})
                [warning] = self.warnings(r)
                self.assertIn(f"{name} is 9.9.9, but {var}=", warning)
                self.assertIn("upgrade check", warning)

    def test_models_at_their_pins_are_shown_without_a_warning(self):
        r = self.jocal("status")
        self.assertIn("4b org/Small-4bit@aaa111, 9b org/Big-4bit@bbb222: at their pins", r.stdout)
        self.assertEqual(self.warnings(r), [])

    def test_a_model_off_its_pinned_revision_is_flagged_with_the_upgrade_check(self):
        (self.models / "Big-4bit" / "REVISION").write_text("org/Big-4bit@ccc333\n")
        [warning] = self.warnings(self.jocal("status"))
        self.assertIn("model 9b (Big-4bit) is org/Big-4bit@ccc333, but PIN_MODELS has 9b=org/Big-4bit@bbb222", warning)
        self.assertIn("upgrade check", warning)

    def test_a_model_folder_without_a_recorded_revision_is_flagged(self):
        (self.models / "Big-4bit" / "REVISION").unlink()
        [warning] = self.warnings(self.jocal("status"))
        self.assertIn("model 9b (Big-4bit) has no recorded revision", warning)

    def test_a_model_key_without_a_pin_is_flagged(self):
        self.write_conf(f'MODELS_DIR={self.models}\n'
                        'MODELS="4b=Small-4bit 9b=Big-4bit" PIN_MODELS="4b=org/Small-4bit@aaa111"')
        [warning] = self.warnings(self.jocal("status"))
        self.assertIn("model 9b (Big-4bit) has no pin in PIN_MODELS", warning)
        self.assertIn("upgrade check", warning)


class Instructions(StatusTest):
    def setUp(self):
        super().setUp()
        self.write_conf(f"MODELS_DIR={self.models}")

    def test_an_oversized_agents_md_is_flagged(self):
        (self.project / "AGENTS.md").write_text("x" * 6000)   # ~1,500 tokens at chars/4
        r = self.jocal("status")
        self.assertIn("warning: AGENTS.md is ~1500 tokens; each 1K adds 3-5 s to a cold first reply "
                      f"({self.project}/AGENTS.md)", self.warnings(r))

    def test_a_small_agents_md_is_not_flagged(self):
        (self.project / "AGENTS.md").write_text("x" * 2000)
        r = self.jocal("status")
        self.assertEqual([w for w in self.warnings(r) if "AGENTS.md" in w], [])

    def test_a_file_only_pi_loads_is_flagged_once_and_one_both_load_is_flagged_once(self):
        (self.project / "CLAUDE.md").write_text("x" * 6000)   # Pi loads it; Claude Code looks only for AGENTS.md
        r = self.jocal("status")
        self.assertEqual(len([w for w in self.warnings(r) if "tokens" in w]), 1)
        self.assertIn("warning: CLAUDE.md is ~1500 tokens", r.stdout)
        (self.project / "CLAUDE.md").unlink()
        (self.project / "AGENTS.md").write_text("x" * 6000)   # both load it: one line, not two
        r = self.jocal("status")
        self.assertEqual(len([w for w in self.warnings(r) if "tokens" in w]), 1)


if __name__ == "__main__":
    unittest.main()
