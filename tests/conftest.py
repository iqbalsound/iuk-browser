import json
import os
import sys
import threading
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("QTWEBENGINE_CHROMIUM_FLAGS", "--no-sandbox --disable-gpu --disable-dev-shm-usage")
os.environ.setdefault("QT_LOGGING_RULES", "*.debug=false;qt.webenginecontext.info=false")
ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "src"))
sys.path.insert(0, str(ROOT / "server"))

from iuk_browser.core import crypto  # noqa: E402

PROD_PARAMS = dict(crypto.PARAMS)


@pytest.fixture(autouse=True)
def fast_kdf():
    """Cheap Argon2id for tests; the known-answer test restores production parameters itself."""
    crypto.PARAMS.update({"memory_kib": 256, "passes": 1, "lanes": 1})
    yield
    crypto.PARAMS.update(PROD_PARAMS)


class FakeClock:
    def __init__(self, t=1_700_000_000.0):
        self.t = t

    def __call__(self):
        return self.t

    def advance(self, s):
        self.t += s


@pytest.fixture
def golden():
    return json.loads((ROOT / "tests" / "golden_from_extension.json").read_text())


@pytest.fixture
def relay(tmp_path):
    import iuk_relay
    clock = FakeClock()
    srv = iuk_relay.make_server(tmp_path / "relay", "127.0.0.1", 0, clock=clock)
    th = threading.Thread(target=srv.serve_forever, daemon=True)
    th.start()
    srv.url = f"http://127.0.0.1:{srv.server_address[1]}"
    srv.clock = clock
    srv.dir = tmp_path / "relay"
    yield srv
    srv.shutdown()
    srv.server_close()


LOGIN_HTML = b"""<!doctype html><html><head><title>Login page</title></head><body>
<form id="f" onsubmit="return false"><input id="u" name="username" type="text" autocomplete="username">
<input id="p" name="password" type="password"><button id="go" type="submit">Sign in</button></form>
<img id="img" width="10" height="10" src="data:image/gif;base64,R0lGODlhAQABAAAAACw="></body></html>"""


@pytest.fixture
def site():
    """A local web server: /login (a login form), /plain."""
    import http.server

    class H(http.server.BaseHTTPRequestHandler):
        def do_GET(self):
            if self.path.startswith("/download"):
                body = b"downloaded-bytes-" * 500
                self.send_response(200); self.send_header("Content-Type", "application/octet-stream")
                self.send_header("Content-Disposition", 'attachment; filename="report.bin"'); self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body)
                return
            if self.path.startswith("/pixel.gif"):
                import base64
                body = base64.b64decode("R0lGODlhAQABAIAAAAAAAP///yH5BAEAAAAALAAAAAABAAEAAAIBRAA7")
                self.send_response(200); self.send_header("Content-Type", "image/gif"); self.send_header("Content-Length", str(len(body)))
                self.end_headers(); self.wfile.write(body)
                return
            if self.path.startswith("/tracked"):
                port = self.server.server_address[1]
                body = (f"<html><title>Tracked</title><body><img id='t' src='http://localhost:{port}/pixel.gif?x=1'>"
                        f"<img id='own' src='/pixel.gif?own=1'></body></html>").encode()
            elif self.path.startswith("/long"):
                body = b"<html><title>Long</title><body>" + b"<p>needle in a haystack</p>" * 3 + b"<p>other</p></body></html>"
            elif self.path.startswith("/login"):
                body = LOGIN_HTML
            else:
                body = b"<html><title>Plain</title><body style='background:#fff'>hello world</body></html>"
            self.send_response(200); self.send_header("Content-Type", "text/html"); self.send_header("Content-Length", str(len(body))); self.end_headers()
            self.wfile.write(body)

        def log_message(self, *a):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), H)
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    srv.base = f"http://127.0.0.1:{srv.server_address[1]}"
    yield srv
    srv.shutdown(); srv.server_close()


@pytest.fixture
def site2(site):
    """Extends the local site with /download (an attachment) and /long (text to search)."""
    return site
