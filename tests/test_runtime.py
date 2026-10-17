"""Runtime lifecycle: `jocal up`/`down`, on-demand start from a session, leases and stop on last exit."""

import os
import signal
import subprocess
import unittest

from harness import JOCAL, JocalTest


class Up(JocalTest):
    def setUp(self):
        super().setUp()
        self.write_conf(f'MODELS_DIR={self.tmp}/models RAM_GB=9 PROMPT_CACHE_GB=3 CTX=16384')

    def test_starts_omlx_with_the_budget_flags_and_offline(self):
        r = self.jocal("up")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.runtime_answers())
        [call] = self.omlx_calls()
        base = str(self.state / "omlx")
        self.assertEqual(call["argv"], ["serve", "--model-dir", f"{self.tmp}/models", "--port", str(self.port),
                                        "--no-hf-cache", "--memory-guard-gb", "9",
                                        "--paged-ssd-cache-dir", f"{base}/cache", "--paged-ssd-cache-max-size", "3GB"])
        self.assertEqual(call["env"], {"OMLX_BASE_PATH": base, "HF_HUB_OFFLINE": "1"})

    def test_writes_model_settings_for_every_model_with_thinking_forced_off(self):
        self.jocal("up")
        expected = {"max_context_window": 16384, "enable_thinking": False,
                    "chat_template_kwargs": {"enable_thinking": False}, "forced_ct_kwargs": ["enable_thinking"]}
        self.assertEqual(self.omlx_calls()[0]["settings"],
                         {"version": 1, "models": {"Qwen3.5-4B-MLX-4bit": expected, "Qwen3.5-9B-MLX-4bit": expected}})

    def test_a_second_up_is_a_no_op(self):
        self.jocal("up")
        r = self.jocal("up")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.omlx_calls()), 1)

    def test_a_runtime_that_never_gets_ready_fails_with_the_log_path(self):
        r = self.jocal("up", FAKE_OMLX_FAIL="1")
        self.assertNotEqual(r.returncode, 0)
        log = self.state / "omlx" / "serve.log"
        self.assertIn(str(log), r.stderr)
        self.assertIn("failed to load", log.read_text())

    def test_no_job_message_reaches_the_terminal(self):
        up, down = self.jocal("up"), self.jocal("down")
        for r in (up, down):
            self.assertEqual(r.stdout, "")
            self.assertNotIn("Terminated", r.stderr)
            self.assertNotIn("Killed", r.stderr)

    def test_two_ups_at_once_start_one_runtime(self):
        procs = [subprocess.Popen([str(JOCAL), "up"], env=self.env | {"FAKE_OMLX_DELAY": "1"},
                                  stdin=subprocess.DEVNULL, stderr=subprocess.PIPE) for _ in range(2)]
        for proc in procs:
            self.assertEqual(proc.wait(timeout=20), 0)
            proc.stderr.close()
        self.assertEqual(len(self.omlx_calls()), 1)
        self.jocal("down")
        self.assertFalse(self.runtime_answers())


def dead_pid():
    proc = subprocess.Popen(["true"])
    proc.wait()
    return proc.pid


class Down(JocalTest):
    def setUp(self):
        super().setUp()
        self.write_conf()
        self.jocal("up")
        self.leases_dir = self.state / "leases"
        self.leases_dir.mkdir(parents=True, exist_ok=True)

    def live_lease(self):
        holder = subprocess.Popen(["sleep", "30"])
        self.addCleanup(holder.wait)
        self.addCleanup(holder.kill)
        (self.leases_dir / str(holder.pid)).write_text("pi 4b\n")
        return holder.pid

    def test_stops_the_runtime(self):
        pid = self.omlx_pid()
        r = self.jocal("down")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.runtime_answers())
        self.assertNotEqual(subprocess.run(["kill", "-0", str(pid)], capture_output=True).returncode, 0)

    def test_refuses_with_a_live_lease_naming_it(self):
        pid = self.live_lease()
        r = self.jocal("down")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(str(pid), r.stderr)
        self.assertIn("--force", r.stderr)
        self.assertTrue(self.runtime_answers())

    def test_force_stops_it_anyway(self):
        self.live_lease()
        r = self.jocal("down", "--force")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertFalse(self.runtime_answers())

    def test_a_dead_lease_is_pruned_and_does_not_block_it(self):
        (self.leases_dir / str(dead_pid())).write_text("pi 4b\n")
        r = self.jocal("down")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(self.leases(), [])

    def test_a_stale_pid_file_is_not_reported_as_a_stop(self):
        self.jocal("down")
        (self.state / "omlx" / "pid").write_text(f"{dead_pid()}\n")
        r = self.jocal("down")
        self.assertNotEqual(r.returncode, 0)
        self.assertNotIn("oMLX stopped", r.stderr)
        self.assertIn("no oMLX started by jocal is running", r.stderr)
        self.assertIsNone(self.omlx_pid())

    def test_dead_leases_are_pruned_on_any_invocation(self):
        (self.leases_dir / str(dead_pid())).write_text("pi 4b\n")
        self.jocal("pi", "--explain")
        self.assertEqual(self.leases(), [])


class Sessions(JocalTest):
    def setUp(self):
        super().setUp()
        self.write_conf()

    def test_a_session_starts_the_runtime_when_it_is_down(self):
        r = self.jocal("pi")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertEqual(len(self.omlx_calls()), 1)
        self.assertIsNotNone(self.pi_run())

    def test_a_runtime_that_fails_to_start_starts_no_session_and_leaves_no_lease(self):
        r = self.jocal("pi", FAKE_OMLX_FAIL="1")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(str(self.state / "omlx" / "serve.log"), r.stderr)
        self.assertIsNone(self.pi_run())
        self.assertEqual(self.leases(), [])

    def test_the_session_holds_a_lease_named_after_its_pid_until_it_exits(self):
        proc = self.start_session("--9b")
        self.assertEqual(self.leases(), [str(proc.pid)])
        self.end_session(proc)
        self.assertEqual(self.leases(), [])

    def test_the_last_session_to_exit_stops_the_runtime(self):
        self.end_session(self.start_session())
        self.assertFalse(self.runtime_answers())
        self.assertIsNone(self.omlx_pid())

    def test_with_stop_runtime_manual_it_keeps_running(self):
        self.write_conf("STOP_RUNTIME=manual")
        self.end_session(self.start_session())
        self.assertTrue(self.runtime_answers())

    def test_two_sessions_on_different_models_share_one_runtime_until_both_exit(self):
        first = self.start_session()
        second = self.start_session("--9b")
        self.assertEqual(len(self.omlx_calls()), 1)
        self.end_session(first)
        self.assertTrue(self.runtime_answers())
        self.assertEqual(self.leases(), [str(second.pid)])
        self.end_session(second)
        self.assertFalse(self.runtime_answers())

    def test_a_session_starting_while_the_last_one_stops_the_runtime_gets_a_runtime(self):
        first = self.start_session(FAKE_OMLX_TERM_DELAY="2")
        first.release.touch()
        self.wait_for(lambda: self.omlx_pid() is None, "the stop to begin")   # the old oMLX still answers meanwhile
        (self.record / "pi.json").unlink()   # so start_session waits for the second Pi
        second = self.start_session()
        first.wait(timeout=20)
        self.sessions.remove(first)
        self.assertTrue(self.runtime_answers())
        self.assertEqual(len(self.omlx_calls()), 2)
        self.end_session(second)
        self.assertFalse(self.runtime_answers())

    def test_a_dead_lease_does_not_keep_the_runtime_alive(self):
        (self.state / "leases").mkdir(parents=True)
        (self.state / "leases" / str(dead_pid())).write_text("pi 4b\n")
        self.end_session(self.start_session())
        self.assertFalse(self.runtime_answers())

    def test_killing_the_wrapper_ends_the_session_and_releases_it(self):
        proc = self.start_session()
        pi_pid = self.pi_run()["pid"]
        proc.send_signal(signal.SIGTERM)
        proc.wait(timeout=20)
        self.sessions.remove(proc)
        self.assertEqual(self.leases(), [])
        self.wait_for(lambda: subprocess.run(["kill", "-0", str(pi_pid)], capture_output=True).returncode != 0,
                      "pi to exit")
        self.assertFalse(self.runtime_answers())

    def test_a_harness_orphaned_by_kill_9_of_the_wrapper_keeps_the_lease_until_it_exits(self):
        proc = self.start_session()
        pi_pid = self.pi_run()["pid"]
        self.addCleanup(lambda: subprocess.run(["kill", "-9", str(pi_pid)], capture_output=True))
        proc.kill()
        proc.wait()
        self.sessions.remove(proc)
        r = self.jocal("down")
        self.assertNotEqual(r.returncode, 0)
        self.assertIn(str(proc.pid), r.stderr)
        self.assertTrue(self.runtime_answers())
        proc.release.touch()   # the orphaned Pi exits
        self.wait_for(lambda: subprocess.run(["kill", "-0", str(pi_pid)], capture_output=True).returncode != 0,
                      "pi to exit")
        self.assertEqual(self.jocal("down").returncode, 0)
        self.assertEqual(self.leases(), [])

    def test_pi_still_reads_the_wrappers_stdin(self):
        self.jocal("pi", "-p", input="hello from stdin\n", FAKE_PI_STDIN="1")
        self.assertEqual(self.pi_run()["stdin"], "hello from stdin\n")

    def test_a_runtime_jocal_did_not_start_is_left_running(self):
        self.start_runtime()
        r = self.jocal("pi")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertTrue(self.runtime_answers())
        self.assertEqual(self.omlx_calls(), [])


if __name__ == "__main__":
    unittest.main()
