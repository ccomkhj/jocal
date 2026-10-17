"""`jocal doctor`: what a first local session needs, what is missing and the command that installs it."""

from harness import JocalTest


class Doctor(JocalTest):
    def setUp(self):
        super().setUp()
        self.models = self.tmp / "models"
        self.write_conf(f"MODELS_DIR={self.models}")

    def fetched(self, folder):
        (self.models / folder).mkdir(parents=True)
        (self.models / folder / "config.json").write_text("{}")

    def lines(self, r, prefix):
        return [line for line in r.stdout.splitlines() if line.startswith(prefix)]

    def test_everything_in_place_passes_and_shows_versions(self):
        self.fetched("Qwen3.5-4B-MLX-4bit")
        r = self.jocal("doctor")
        self.assertEqual(r.returncode, 0, r.stdout + r.stderr)
        self.assertIn("ok: oMLX 0.7.0", r.stdout)
        self.assertIn("ok: Pi 1.3.0", r.stdout)
        self.assertIn("ok: model 4b (Qwen3.5-4B-MLX-4bit)", r.stdout)
        self.assertEqual(self.lines(r, "missing:"), [])

    def test_a_missing_pi_fails_and_names_its_install_command(self):
        self.fetched("Qwen3.5-4B-MLX-4bit")
        r = self.jocal("doctor", PI_BIN="/nonexistent/pi")
        self.assertEqual(r.returncode, 1)
        self.assertTrue(any("npm install -g @earendil-works/pi-coding-agent" in line
                            for line in self.lines(r, "missing: Pi")), r.stdout)

    def test_a_missing_omlx_fails_and_names_its_install_command(self):
        self.fetched("Qwen3.5-4B-MLX-4bit")
        r = self.jocal("doctor", OMLX_BIN="/nonexistent/omlx")
        self.assertEqual(r.returncode, 1)
        self.assertTrue(any("uv tool install" in line for line in self.lines(r, "missing: oMLX")), r.stdout)

    def test_a_missing_default_model_fails_and_points_at_jocal_fetch(self):
        r = self.jocal("doctor")
        self.assertEqual(r.returncode, 1)
        self.assertIn("missing: model 4b (Qwen3.5-4B-MLX-4bit): jocal fetch", r.stdout)

    def test_other_models_and_claude_code_are_optional(self):
        self.fetched("Qwen3.5-4B-MLX-4bit")
        r = self.jocal("doctor", CLAUDE_BIN="/nonexistent/claude")
        self.assertEqual(r.returncode, 0, r.stdout)
        self.assertIn("optional: model 9b (Qwen3.5-9B-MLX-4bit): jocal fetch --9b", r.stdout)
        self.assertTrue(any(line.startswith("optional: Claude Code") for line in r.stdout.splitlines()), r.stdout)

    def test_doctor_starts_nothing(self):
        self.fetched("Qwen3.5-4B-MLX-4bit")
        self.jocal("doctor")
        self.assertFalse(self.runtime_answers())
        self.assertEqual(self.omlx_calls(), [])
