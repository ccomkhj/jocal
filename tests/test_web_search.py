"""Web search: the Pi extension (`web_search.ts`) against a fake DuckDuckGo results page, run by `pi_tool.mjs`, and
the Pi profile that loads it only when WEB_SEARCH names an engine, saying in the banner where the queries go."""

import json
import shutil
import subprocess
import threading
import unittest
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import parse_qs

from harness import JocalTest, free_port

REPO = Path(__file__).resolve().parents[1]
EXTENSION = REPO / "web_search.ts"
DRIVER = Path(__file__).resolve().parent / "pi_tool.mjs"
NODE = shutil.which("node")


def result(href, title, snippet=None, extra_class=""):
    """One result block, in the markup of html.duckduckgo.com/html/."""
    snippet_html = f'<a class="result__snippet" href="{href}">{snippet}</a>' if snippet is not None else ""
    return f"""
      <div class="result results_links results_links_deep web-result {extra_class}">
        <div class="links_main links_deep result__body">
          <h2 class="result__title"><a rel="nofollow" class="result__a" href="{href}">{title}</a></h2>
          <div class="result__extras"><div class="result__extras__url">
            <a class="result__url" href="{href}">example</a></div></div>
          {snippet_html}
          <div class="clear"></div>
        </div>
      </div>"""


def page(*results):
    return f'<html><body><div id="links" class="results">{"".join(results)}</div></body></html>'


class FakeEngine(BaseHTTPRequestHandler):
    """Answers every POST with the class's `status` and `body`, and records each request's path, headers and form."""
    status, body, requests = 200, page(), []

    def do_POST(self):
        form = parse_qs(self.rfile.read(int(self.headers["Content-Length"])).decode())
        FakeEngine.requests.append({"path": self.path, "headers": dict(self.headers), "form": form})
        body = self.body.encode()
        self.send_response(self.status)
        self.send_header("Content-Type", "text/html; charset=UTF-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


@unittest.skipUnless(NODE, "node is not on PATH")
class WebSearchExtension(unittest.TestCase):
    def setUp(self):
        FakeEngine.status, FakeEngine.body, FakeEngine.requests = 200, page(), []
        self.server = ThreadingHTTPServer(("127.0.0.1", 0), FakeEngine)
        threading.Thread(target=self.server.serve_forever, daemon=True).start()
        self.url = f"http://127.0.0.1:{self.server.server_port}/html/"

    def tearDown(self):
        self.server.shutdown()
        self.server.server_close()

    def search(self, url=None, **params):
        """Runs web_search with JOCAL_WEB_SEARCH_URL=url (this test's fake engine by default; unset when "")."""
        url = self.url if url is None else url
        env = {"JOCAL_WEB_SEARCH_URL": url} if url else {}
        r = subprocess.run([NODE, str(DRIVER), EXTENSION.as_uri(), "web_search", str(REPO), json.dumps(params)],
                           env=env, capture_output=True, text=True, timeout=30)
        self.assertEqual(r.returncode, 0, r.stderr)
        out = json.loads(r.stdout)
        self.assertEqual(out["name"], "web_search")
        return out

    def test_posts_the_query_as_a_form_with_a_browser_user_agent(self):
        self.search(query="  qwen 3.5 release notes ")
        [request] = FakeEngine.requests
        self.assertEqual(request["path"], "/html/")
        self.assertEqual(request["form"], {"q": ["qwen 3.5 release notes"]})
        self.assertIn("Mozilla/5.0", request["headers"]["User-Agent"])

    def test_returns_each_result_as_title_url_and_snippet_in_plain_text(self):
        FakeEngine.body = page(
            result("https://omlx.ai/", "oMLX — LLM inference, <b>optimized</b>",
                   "<b>Apple</b> Silicon &amp; MLX, it&#x27;s &quot;fast&quot;&#39;s\n   sake"),
            result("https://github.com/jundot/omlx", "jundot/omlx", "LLM inference server"),
        )
        out = self.search(query="omlx")
        self.assertEqual(out["text"], 'Results for "omlx" (127.0.0.1:%d):\n\n'
                                      "1. oMLX — LLM inference, optimized\n   https://omlx.ai/\n"
                                      """   Apple Silicon & MLX, it's "fast"'s sake\n\n"""
                                      "2. jundot/omlx\n   https://github.com/jundot/omlx\n   LLM inference server"
                         % self.server.server_port)

    def test_a_link_through_the_engines_redirect_is_given_as_its_target(self):
        FakeEngine.body = page(result("//duckduckgo.com/l/?uddg=https%3A%2F%2Fexample.org%2Fa%3Fb%3D1&amp;rut=abc",
                                      "Example", "x"))
        self.assertIn("\n   https://example.org/a?b=1\n", self.search(query="example")["text"])

    def test_ads_are_left_out(self):
        FakeEngine.body = page(
            result("https://duckduckgo.com/y.js?ad_domain=shop.example&amp;u3=x", "Buy now", "ad", "result--ad"),
            result("https://real.example/", "Real result", "kept"),
        )
        text = self.search(query="thing")["text"]
        self.assertNotIn("Buy now", text)
        self.assertIn("1. Real result\n   https://real.example/\n   kept", text)

    def test_a_result_without_a_snippet_keeps_its_title_and_url(self):
        FakeEngine.body = page(result("https://bare.example/", "Bare"))
        self.assertTrue(self.search(query="bare")["text"].endswith("1. Bare\n   https://bare.example/"))

    def test_at_most_eight_results_come_back(self):
        FakeEngine.body = page(*(result(f"https://site{i}.example/", f"Site {i}", "s") for i in range(1, 11)))
        text = self.search(query="sites")["text"]
        self.assertIn("8. Site 8", text)
        self.assertNotIn("Site 9", text)

    def test_no_results_is_an_answer_not_an_error(self):
        FakeEngine.body = '<html><body><div class="no-results">No results.</div></body></html>'
        self.assertEqual(self.search(query="zzqx")["text"], 'No results for "zzqx".')

    def test_the_engines_bot_check_is_an_error_that_says_to_wait(self):
        FakeEngine.status, FakeEngine.body = 202, '<html><div class="anomaly-modal__modal">Unfortunately, bots</div></html>'
        out = self.search(query="omlx")
        self.assertNotIn("text", out)
        self.assertIn("took this search for a bot", out["error"])
        self.assertIn("Wait a minute", out["error"])

    def test_an_http_error_names_the_status(self):
        FakeEngine.status, FakeEngine.body = 500, "oops"
        self.assertIn("answered HTTP 500", self.search(query="omlx")["error"])

    def test_an_engine_that_cannot_be_reached_is_an_error_naming_it(self):
        port = free_port()
        out = self.search(url=f"http://127.0.0.1:{port}/html/", query="omlx")
        self.assertIn(f"web_search could not reach 127.0.0.1:{port} (ECONNREFUSED)", out["error"])

    def test_an_empty_query_is_refused_without_a_request(self):
        self.assertIn("needs a query", self.search(query="   ")["error"])
        self.assertEqual(FakeEngine.requests, [])

    def test_without_a_valid_engine_url_every_search_is_refused(self):
        for url in ["", "duckduckgo", "ftp://example.org/", "http://["]:
            out = self.search(url=url, query="omlx")
            self.assertNotIn("text", out, url)
            self.assertIn("web_search is off", out["error"])
            self.assertIn("jocal pi", out["error"])
        self.assertEqual(FakeEngine.requests, [])


class WebSearchSession(JocalTest):
    def setUp(self):
        super().setUp()
        self.start_runtime()

    def tools(self):
        argv = self.pi_run()["argv"]
        return argv[argv.index("--tools") + 1]

    def extensions(self):
        argv = self.pi_run()["argv"]
        return [argv[i + 1] for i, a in enumerate(argv) if a == "--extension"]

    def test_off_by_default_pi_gets_no_web_search(self):
        self.write_conf()
        r = self.jocal("pi")
        self.assertEqual(r.returncode, 0, r.stderr)
        pi = self.pi_run()
        self.assertEqual(self.tools(), "read,edit,write,bash")
        self.assertEqual(self.extensions(), [str(self.state / "pi" / "read.ts")])
        self.assertNotIn("JOCAL_WEB_SEARCH_URL", pi["env"])
        self.assertNotIn("web_search.ts", pi["files"])
        self.assertIn("prompts stay on this Mac \x1b[0m", r.stderr)

    def test_duckduckgo_gives_pi_the_web_search_tool_and_its_extension(self):
        self.write_conf("WEB_SEARCH=duckduckgo")
        r = self.jocal("pi")
        self.assertEqual(r.returncode, 0, r.stderr)
        pi = self.pi_run()
        self.assertEqual(self.tools(), "read,edit,write,bash,web_search")
        self.assertEqual(self.extensions(), [str(self.state / "pi" / "read.ts"), str(self.state / "pi" / "web_search.ts")])
        self.assertEqual(pi["files"]["web_search.ts"], EXTENSION.read_text())
        self.assertEqual(pi["env"]["JOCAL_WEB_SEARCH_URL"], "https://html.duckduckgo.com/html/")

    def test_the_banner_says_the_searches_leave_this_mac(self):
        self.write_conf("WEB_SEARCH=duckduckgo")
        r = self.jocal("pi")
        self.assertIn(" · prompts stay on this Mac, except web searches (html.duckduckgo.com) \x1b[0m", r.stderr)

    def test_web_search_follows_the_extra_tools(self):
        self.write_conf('WEB_SEARCH=duckduckgo PI_EXTRA_TOOLS="grep,find"')
        self.jocal("pi")
        self.assertEqual(self.tools(), "read,edit,write,bash,grep,find,web_search")

    def test_the_env_turns_it_on_for_one_session(self):
        self.write_conf()
        self.jocal("pi", WEB_SEARCH="duckduckgo")
        self.assertEqual(self.tools(), "read,edit,write,bash,web_search")
        self.jocal("pi")
        self.assertEqual(self.tools(), "read,edit,write,bash")

    def test_an_empty_env_turns_it_off_for_one_session_and_removes_the_extension(self):
        self.write_conf("WEB_SEARCH=duckduckgo")
        self.jocal("pi")
        self.assertIn("web_search.ts", self.pi_run()["files"])
        self.jocal("pi", WEB_SEARCH="")
        pi = self.pi_run()
        self.assertEqual(self.tools(), "read,edit,write,bash")
        self.assertNotIn("web_search.ts", pi["files"])
        self.assertNotIn("JOCAL_WEB_SEARCH_URL", pi["env"])

    def test_an_unknown_engine_is_refused_before_anything_starts(self):
        self.write_conf("WEB_SEARCH=google")
        r = self.jocal("pi")
        self.assertEqual(r.returncode, 2)
        self.assertIn("WEB_SEARCH=google is not a search engine jocal knows (duckduckgo", r.stderr)
        self.assertIsNone(self.pi_run())
        self.assertEqual(self.leases(), [])

    def test_explain_shows_where_the_queries_go_and_starts_nothing(self):
        self.write_conf("WEB_SEARCH=duckduckgo")
        r = self.jocal("pi", "--explain")
        self.assertEqual(r.returncode, 0, r.stderr)
        self.assertIn("prompts stay on this Mac, except web searches (html.duckduckgo.com)", r.stdout)
        self.assertIn(f"web search: duckduckgo, from {self.state}/pi/web_search.ts; the queries leave this Mac for "
                      "html.duckduckgo.com", r.stdout)
        self.assertIn("JOCAL_WEB_SEARCH_URL=https://html.duckduckgo.com/html/", r.stdout)
        self.assertIn(f"--tools read,edit,write,bash,web_search --no-mcp --extension {self.state}/pi/read.ts "
                      f"--extension {self.state}/pi/web_search.ts ", r.stdout)
        self.assertIsNone(self.pi_run())
        self.write_conf()
        self.assertIn("web search: off (WEB_SEARCH is empty)", self.jocal("pi", "--explain").stdout)

    def test_claude_gets_no_web_search_and_says_so(self):
        self.write_conf("WEB_SEARCH=duckduckgo")
        r = self.jocal("claude", "--explain")
        self.assertIn("web search: not wired into Claude Code yet (WEB_SEARCH=duckduckgo is for jocal pi)", r.stdout)
        self.assertNotIn("except web searches", r.stdout)
        r = self.jocal("claude")
        self.assertEqual(r.returncode, 0, r.stderr)
        argv = self.claude_run()["argv"]
        self.assertEqual(argv[argv.index("--tools") + 1], "Read,Edit,Write,Bash")


if __name__ == "__main__":
    unittest.main()
