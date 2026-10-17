"""The tool and MCP allowlist: extra tools and local-only MCP servers widen a session; a remote server never joins."""

import json
import unittest

from harness import JocalTest


class ExtraTools(JocalTest):
    def setUp(self):
        super().setUp()
        self.write_conf('PI_EXTRA_TOOLS="grep,find" CLAUDE_EXTRA_TOOLS="Grep,Glob"')
        self.start_runtime()

    def test_extra_tools_join_each_harness_tool_list(self):
        self.jocal("pi")
        argv = self.pi_run()["argv"]
        self.assertEqual(argv[argv.index("--tools") + 1], "read,edit,write,bash,grep,find")
        self.jocal("claude")
        argv = self.claude_run()["argv"]
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Edit,Write,Bash,Grep,Glob")

    def test_explain_shows_the_extra_tools(self):
        self.assertIn("--tools read,edit,write,bash,grep,find ", self.jocal("pi", "--explain").stdout)
        self.assertIn("--tools Read,Edit,Write,Bash,Grep,Glob ", self.jocal("claude", "--explain").stdout)


SERVERS = {
    "files": {"command": "npx", "args": ["-y", "@modelcontextprotocol/server-filesystem", "."]},
    "ocr": {"type": "http", "url": "http://localhost:9000/mcp"},
    "ocr6": {"type": "http", "url": "http://[::1]:9001/mcp"},
    "my-notes": {"command": "/usr/local/bin/notes-mcp"},
    "slack": {"type": "http", "url": "https://mcp.slack.com/mcp"},
    "sneaky": {"type": "http", "url": "http://127.0.0.1.evil.example/mcp"},
}


class McpAllowlist(JocalTest):
    def setUp(self):
        super().setUp()
        self.mcp_file = self.tmp / "config" / "mcp.json"
        self.mcp_file.parent.mkdir(parents=True)
        self.mcp_file.write_text(json.dumps({"mcpServers": SERVERS}))
        self.start_runtime()

    def allow(self, servers):
        self.write_conf(f'MCP_FILE={self.mcp_file} MCP_SERVERS="{servers}"')

    def test_claude_gets_only_the_allowed_servers_and_no_mcp_ban(self):
        self.allow("files ocr ocr6")
        r = self.jocal("claude")
        self.assertEqual(r.returncode, 0, r.stderr)
        run = self.claude_run()
        self.assertEqual(json.loads(run["files"]["--mcp-config"]),
                         {"mcpServers": {k: SERVERS[k] for k in ["files", "ocr", "ocr6"]}})
        self.assertIn("--strict-mcp-config", run["argv"])
        self.assertNotIn("--disallowedTools", run["argv"])

    def test_pi_gets_the_allowed_servers_with_their_tools_declared_and_no_project_servers(self):
        self.allow("files ocr my-notes")
        r = self.jocal("pi")
        self.assertEqual(r.returncode, 0, r.stderr)
        pi = self.pi_run()
        direct = {k: SERVERS[k] | {"exposure": "direct"} for k in ["files", "ocr", "my-notes"]}
        self.assertEqual(json.loads(pi["files"]["mcp.json"]), {"mcpServers": direct})
        argv = pi["argv"]
        self.assertEqual(argv[argv.index("--tools") + 1],
                         "read,edit,write,bash,mcp__files__*,mcp__ocr__*,mcp__my_notes__*")
        self.assertNotIn("--no-mcp", argv)
        self.assertIn("--no-approve", argv)   # a trusted project's .pi/mcp.json would connect under --tools

    def test_with_no_server_allowed_both_harnesses_get_the_no_mcp_flags_again(self):
        self.allow("files")
        self.jocal("pi")
        self.jocal("claude")
        self.allow("")
        self.jocal("pi")
        pi = self.pi_run()
        self.assertEqual(json.loads(pi["files"]["mcp.json"]), {"mcpServers": {}})
        self.assertIn("--no-mcp", pi["argv"])
        self.assertNotIn("--no-approve", pi["argv"])
        self.jocal("claude")
        claude = self.claude_run()
        self.assertEqual(json.loads(claude["files"]["--mcp-config"]), {"mcpServers": {}})
        self.assertEqual(claude["argv"][-2:], ["--disallowedTools", "mcp__*"])

    def test_explain_names_the_allowed_servers(self):
        self.allow("files ocr")
        for harness in ["pi", "claude"]:
            out = self.jocal(harness, "--explain").stdout
            self.assertIn(f"MCP servers: files, ocr (from {self.mcp_file})", out)
        self.allow("")
        self.assertIn("MCP servers: none", self.jocal("pi", "--explain").stdout)

    def assert_refused(self, servers, name):
        self.allow(servers)
        for harness in ["pi", "claude"]:
            r = self.jocal(harness)
            self.assertNotEqual(r.returncode, 0, harness)
            self.assertIn(f"'{name}'", r.stderr, harness)
        self.assertIsNone(self.pi_run())
        self.assertIsNone(self.claude_run())
        self.assertEqual(self.leases(), [])

    def test_a_remote_url_server_is_refused_before_start(self):
        self.assert_refused("files slack", "slack")

    def test_a_host_that_only_starts_like_localhost_is_refused(self):
        self.assert_refused("sneaky", "sneaky")

    def test_a_name_missing_from_the_mcp_file_is_refused(self):
        self.assert_refused("files jira", "jira")

    def test_a_missing_mcp_file_is_refused_naming_the_server(self):
        self.mcp_file.unlink()
        self.assert_refused("files", "files")


if __name__ == "__main__":
    unittest.main()
