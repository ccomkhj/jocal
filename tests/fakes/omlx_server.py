"""A tiny stand-in for oMLX's HTTP API on 127.0.0.1: answers /v1/models, /v1/models/status listing the loaded models
(the ids after the port), and /v1/messages with a scripted reply.
Each /v1/messages request body is appended to $FAKE_RECORD/messages.jsonl, and the reply text is
"fake reply <n>" for the n-th request, so a test can trace each reply into later requests. With FAKE_LEASES_AT
set, each recorded body also gets "leases": the files in that directory when the request came in.
FAKE_MESSAGES_FAIL_AT=<n> answers the n-th request with a 500; FAKE_MESSAGES_DIE_AFTER=<n> exits once it has
answered the n-th, so the next one finds nothing listening."""
import json, os, sys
from http.server import BaseHTTPRequestHandler, HTTPServer
from pathlib import Path


class Handler(BaseHTTPRequestHandler):
    loaded = []

    def do_GET(self):
        if self.path == "/v1/models":
            body = {"object": "list", "data": []}
        elif self.path == "/v1/models/status":
            body = {"models": [{"id": m, "loaded": True} for m in self.loaded] + [{"id": "Idle-Model", "loaded": False}]}
        else:
            self.send_error(404)
            return
        self.reply(body)

    def do_POST(self):
        if self.path != "/v1/messages":
            self.send_error(404)
            return
        body = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
        if os.environ.get("FAKE_LEASES_AT"):
            body["leases"] = sorted(os.listdir(os.environ["FAKE_LEASES_AT"]))
        log = Path(os.environ["FAKE_RECORD"]) / "messages.jsonl"
        with open(log, "a") as f:
            f.write(json.dumps(body) + "\n")
        n = len(log.read_text().splitlines())
        if os.environ.get("FAKE_MESSAGES_FAIL_AT") == str(n):
            self.send_error(500, "fake failure")
            return
        self.reply({"id": f"msg_{n}", "type": "message", "role": "assistant", "model": body["model"],
                    "content": [{"type": "text", "text": f"fake reply {n}"}], "stop_reason": "end_turn"})
        if os.environ.get("FAKE_MESSAGES_DIE_AFTER") == str(n):
            os._exit(0)

    def reply(self, obj):
        body = json.dumps(obj).encode()
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def log_message(self, *args):
        pass


def serve(port, loaded=()):
    Handler.loaded = list(loaded)
    HTTPServer(("127.0.0.1", port), Handler).serve_forever()


if __name__ == "__main__":
    serve(int(sys.argv[1]), sys.argv[2:])
