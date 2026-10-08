import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest

import twohelixes.client


class Recorder(ThreadingHTTPServer):
    daemon_threads = True

    def __init__(self):
        super().__init__(("127.0.0.1", 0), Handler)
        self.requests = []
        self.status = 204
        self.response = b""
        self.lock = threading.Lock()

    @property
    def url(self):
        return f"http://127.0.0.1:{self.server_address[1]}"

    def bodies(self):
        return [json.loads(r["body"]) for r in self.requests if r["method"] == "POST"]

    def events(self):
        return [e for b in self.bodies() for e in b["events"]]


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *a):
        pass

    def _handle(self):
        n = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(n) if n else b""
        with self.server.lock:
            self.server.requests.append(
                {"method": self.command, "path": self.path, "headers": dict(self.headers), "body": body}
            )
        self.send_response(self.server.status)
        self.send_header("Content-Length", str(len(self.server.response)))
        self.end_headers()
        self.wfile.write(self.server.response)

    do_GET = do_POST = _handle


@pytest.fixture
def server():
    s = Recorder()
    t = threading.Thread(target=s.serve_forever, args=(0.01,), daemon=True)
    t.start()
    yield s
    s.shutdown()
    s.server_close()


@pytest.fixture(autouse=True)
def fast_retry(monkeypatch):
    monkeypatch.setattr(twohelixes.client, "RETRY_BACKOFF", 0.01)
