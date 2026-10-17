"""`jocal fetch`: download a model at its pinned commit into MODELS_DIR, recording the revision `jocal status` checks."""

from harness import JocalTest


class Fetch(JocalTest):
    def setUp(self):
        super().setUp()
        self.models = self.tmp / "models"
        self.write_conf(f"MODELS_DIR={self.models}\n"
                        'PIN_MODELS="4b=org/Four-B@c4 9b=org/Nine-B@c9"')

    def hf(self):
        return self.read_record("hf.json")

    def read_record(self, name):
        import json
        path = self.record / name
        return json.loads(path.read_text()) if path.exists() else None

    def test_the_default_model_is_fetched_at_its_pinned_commit_into_its_folder(self):
        r = self.jocal("fetch")
        self.assertEqual(r.returncode, 0, r.stderr)
        folder = self.models / "Qwen3.5-4B-MLX-4bit"
        self.assertEqual(self.hf()["argv"],
                         ["download", "org/Four-B", "--revision", "c4", "--local-dir", str(folder)])
        self.assertEqual(self.hf()["env"]["HF_HUB_DISABLE_TELEMETRY"], "1")
        self.assertEqual((folder / "REVISION").read_text(), "org/Four-B@c4\n")
        self.assertFalse((folder / ".cache").exists())

    def test_a_key_flag_fetches_that_model(self):
        r = self.jocal("fetch", "--9b")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.hf()["argv"][1:4], ["org/Nine-B", "--revision", "c9"])
        self.assertTrue((self.models / "Qwen3.5-9B-MLX-4bit" / "REVISION").exists())

    def test_the_fetched_model_is_at_its_pin_in_status(self):
        self.jocal("fetch")
        r = self.jocal("status")
        self.assertIn("4b org/Four-B@c4", r.stdout)

    def test_a_model_without_a_pin_is_refused_and_nothing_is_downloaded(self):
        self.write_conf(f'MODELS_DIR={self.models}\nPIN_MODELS="9b=org/Nine-B@c9"')
        r = self.jocal("fetch")
        self.assertEqual(r.returncode, 2)
        self.assertIn("PIN_MODELS", r.stderr)
        self.assertIsNone(self.hf())

    def test_an_unknown_key_is_refused(self):
        r = self.jocal("fetch", "--7b")
        self.assertEqual(r.returncode, 2)
        self.assertIn("known keys: 4b 9b", r.stderr)

    def test_a_failed_download_fails_and_records_no_revision(self):
        r = self.jocal("fetch", FAKE_HF_EXIT="3")
        self.assertNotEqual(r.returncode, 0)
        self.assertFalse((self.models / "Qwen3.5-4B-MLX-4bit" / "REVISION").exists())

    def test_a_missing_hf_cli_names_how_to_install_it(self):
        r = self.jocal("fetch", HF_BIN="/nonexistent/hf")
        self.assertEqual(r.returncode, 1)
        self.assertIn("huggingface_hub", r.stderr)
        self.assertIsNone(self.hf())
