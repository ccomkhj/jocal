"""Drives `jocal` the way a user does, against fake `pi`, `omlx` and `claude` executables, in a throwaway home.

Each test gets its own HOME, working directory, JOCAL_CONFIG, JOCAL_STATE and PORT, and a PATH whose first entry holds the
fakes, so nothing touches the real config, the network, a model or a real harness.
That PATH puts /usr/bin and /bin before anything else, so `#!/usr/bin/env bash` resolves to macOS's
bash 3.2 and the suite also checks that jocal runs on it.
"""

import json
import os
import shutil
import socket
import subprocess
import sys
import tempfile
import time
import unittest
import urllib.request
from pathlib import Path

REPO = Path(__file__).resolve().parents[1]
JOCAL = REPO / "jocal"
FAKES = Path(__file__).resolve().parent / "fakes"


def free_port():
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


class JocalTest(unittest.TestCase):
    def setUp(self):
        self.tmp = Path(tempfile.mkdtemp(prefix="jocal-test-"))
        self.home, self.record = self.tmp / "home", self.tmp / "record"
        self.project = self.tmp / "project"   # the working directory jocal runs in, so no real AGENTS.md is seen
        for d in (self.home, self.record, self.project):
            d.mkdir()
        self.config = self.tmp / "config" / "jocal.conf"
        self.state = self.tmp / "state"
        self.port = free_port()
        self.env = {
            "HOME": str(self.home),
            "PATH": os.pathsep.join([str(FAKES), "/usr/bin", "/bin", str(Path(sys.executable).parent)]),
            "JOCAL_CONFIG": str(self.config),
            "JOCAL_STATE": str(self.state),
            "FAKE_RECORD": str(self.record),
            "TERM": "xterm-256color",
        }
        self.server = None
        self.sessions = []

    def tearDown(self):
        if self.server:
            self.server.kill()
            self.server.wait()
        for proc in self.sessions:   # released, not killed: a killed jocal leaves its harness running (README)
            proc.release.touch()
            try:
                proc.wait(timeout=20)
            except subprocess.TimeoutExpired:
                proc.kill()
                proc.wait()
        pid = self.omlx_pid()
        if pid:
            try:
                os.kill(pid, 9)
            except OSError:
                pass
        shutil.rmtree(self.tmp, ignore_errors=True)

    def write_conf(self, extra=""):
        """A config with this test's PORT; `extra` lines are appended, so they win."""
        self.config.parent.mkdir(parents=True, exist_ok=True)
        self.config.write_text(f"PORT={self.port}\n{extra}\n")

    def start_runtime(self, loaded=()):
        """An oMLX that is already running on PORT, started outside jocal, with the `loaded` model ids in memory."""
        self.server = subprocess.Popen([sys.executable, str(FAKES / "omlx_server.py"), str(self.port), *loaded])
        for _ in range(100):
            try:
                urllib.request.urlopen(f"http://127.0.0.1:{self.port}/v1/models", timeout=1)
                return
            except OSError:
                time.sleep(0.05)
        raise RuntimeError("fake oMLX did not come up")

    def jocal(self, *args, cwd=None, input=None, **env):
        cwd = cwd or self.project
        stdin = {"input": input} if input is not None else {"stdin": subprocess.DEVNULL}
        return subprocess.run([str(JOCAL), *args], env=self.env | {"PWD": str(cwd)} | env, cwd=cwd, **stdin,
                              capture_output=True, text=True, timeout=20)

    def start_session(self, *args, harness="pi", **env):
        """A `jocal <harness>` that keeps running until `end_session`; returns once its lease is written."""
        release = self.tmp / f"release-{len(self.sessions)}"
        wait = {"FAKE_PI_WAIT": str(release), "FAKE_CLAUDE_WAIT": str(release)}
        proc = subprocess.Popen([str(JOCAL), harness, *args], cwd=self.project,
                                env=self.env | {"PWD": str(self.project)} | env | wait,
                                stdin=subprocess.DEVNULL, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        proc.release = release
        self.sessions.append(proc)
        started = self.record / f"{harness}.json"
        self.wait_for(lambda: (self.state / "leases" / str(proc.pid)).exists() and started.exists(), "session start")
        return proc

    def end_session(self, proc):
        proc.release.touch()
        proc.wait(timeout=20)
        self.sessions.remove(proc)
        return proc

    def wait_for(self, check, what, timeout=10):
        deadline = time.time() + timeout
        while time.time() < deadline:
            if check():
                return
            time.sleep(0.05)
        raise AssertionError(f"timed out waiting for {what}")

    def runtime_answers(self):
        try:
            urllib.request.urlopen(f"http://127.0.0.1:{self.port}/v1/models", timeout=1)
            return True
        except OSError:
            return False

    def omlx_pid(self):
        """The pid of the oMLX jocal started, from its pid file."""
        path = self.state / "omlx" / "pid"
        return int(path.read_text()) if path.exists() else None

    def leases(self):
        d = self.state / "leases"
        return sorted(p.name for p in d.iterdir()) if d.exists() else []

    def pi_run(self):
        """What the fake Pi saw: argv, env and the files in its agent dir. None if Pi never started."""
        path = self.record / "pi.json"
        return json.loads(path.read_text()) if path.exists() else None

    def claude_run(self):
        """What the fake Claude Code saw: argv, env and its --settings/--mcp-config files. None if it never started."""
        path = self.record / "claude.json"
        return json.loads(path.read_text()) if path.exists() else None

    def omlx_calls(self):
        path = self.record / "omlx.calls"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []

    def messages(self):
        """The /v1/messages requests the fake runtime got, in order."""
        path = self.record / "messages.jsonl"
        return [json.loads(line) for line in path.read_text().splitlines()] if path.exists() else []
