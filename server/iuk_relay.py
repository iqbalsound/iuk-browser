#!/usr/bin/env python3
"""IUK Browser sync relay (stdlib only).

Stores ONE opaque, end-to-end encrypted blob per account. It never sees the secret key or any plaintext.
Wire-compatible with the original Node relay used by the Firefox extension (same /v1/blob protocol).

Optional second factor (TOTP, RFC 6238), per account:
    POST /v1/2fa/enroll    -> {"secret": base32, "otpauth": uri}          (scan in any authenticator app)
    POST /v1/2fa/confirm   {"otp": "123456"} -> {"recovery_codes": [...], "session": sid}   (enables 2FA)
    POST /v1/session       {"otp": "123456"} or {"recovery": "xxxx-xxxx"} -> {"session": sid, "expires_in": s}
    POST /v1/2fa/disable   {"otp": ...} or {"recovery": ...}  (needs a session)
    GET  /v1/2fa/status    -> {"enabled": bool}
Once enabled, /v1/blob requires the header  X-IUK-Session: <sid>  (12 h). Without it the relay answers
401 with  X-IUK-2FA: required.  A stolen bearer token alone can then no longer download the ciphertext.

One-time device pairing (the QR code carries a random pairing id + a random one-time key, never the account key):
    PUT    /v1/pair/<pid>          store an encrypted pairing blob for 120 s (authenticated; max 3 pending per account)
    GET    /v1/pair/<pid>          fetch it ONCE and delete it (no auth: the 128-bit id is the capability)
    GET    /v1/pair/<pid>/status   {"pending": bool}  (owner only; lets the showing device notice the pairing finished)
    DELETE /v1/pair/<pid>          cancel (owner only)
The blob is encrypted with the one-time key from the QR, so the relay cannot read it, and it lives in memory only.

Env: PORT (8787) HOST (127.0.0.1) DATA_DIR (./data) TRUST_PROXY=1 (use X-Forwarded-For for rate limits)
Run behind HTTPS (Caddy / nginx) on the internet.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import os
import re
import secrets
import struct
import threading
import time
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from urllib.parse import quote

MAX_BODY = 5 * 1024 * 1024
SESSION_TTL = 12 * 3600
OTP_MAX_FAILS, OTP_WINDOW = 5, 600
PAIR_TTL, PAIR_MAX_BLOB, PAIR_MAX_PENDING = 120, 4096, 3
PAIR_PATH = re.compile(r"^/v1/pair/([0-9a-f]{32})(/status)?$")
BEARER = re.compile(r"^Bearer ([0-9a-f]{64})$")
PAYLOAD = re.compile(rb"^v1\.[A-Za-z0-9+/=]+\.[A-Za-z0-9+/=]+$")


# ------------------------------------------------------------------ TOTP (RFC 6238, SHA-1, 30 s)
def hotp(secret: bytes, counter: int, digits: int = 6) -> str:
    mac = hmac.new(secret, struct.pack(">Q", counter), hashlib.sha1).digest()
    off = mac[-1] & 0x0F
    code = (struct.unpack(">I", mac[off:off + 4])[0] & 0x7FFFFFFF) % (10 ** digits)
    return str(code).zfill(digits)


def b32_secret() -> str:
    return base64.b32encode(secrets.token_bytes(20)).decode().rstrip("=")


def verify_totp(b32: str, code: str, now: float, last_step: int) -> int | None:
    """Returns the accepted time step (to block replay of the same code) or None."""
    code = re.sub(r"\s", "", str(code or ""))
    if not re.fullmatch(r"\d{6}", code):
        return None
    secret = base64.b32decode(b32 + "=" * (-len(b32) % 8))
    for delta in (0, -1, 1):                       # +-30 s clock skew
        step = int(now // 30) + delta
        if step > last_step and hmac.compare_digest(hotp(secret, step), code):
            return step
    return None


# ------------------------------------------------------------------ relay core
class Relay:
    def __init__(self, data_dir, rate_limit: int = 120, trust_proxy: bool = False, clock=time.time):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.rate_limit, self.trust_proxy, self.clock = rate_limit, trust_proxy, clock
        self.lock = threading.Lock()
        self.hits: dict[str, list[float]] = {}
        self.sessions: dict[str, tuple[str, float]] = {}
        self.fails: dict[str, list[float]] = {}
        self.pairings: dict[str, dict] = {}     # pid -> {aid, blob, expires}; memory only

    # ---- storage
    def _blob(self, aid): return self.dir / f"{aid}.blob"
    def _tfp(self, aid): return self.dir / f"{aid}.2fa.json"

    def _tf(self, aid) -> dict:
        p = self._tfp(aid)
        return json.loads(p.read_text()) if p.exists() else {"enabled": False}

    def _save_tf(self, aid, tf) -> None:
        p = self._tfp(aid)
        tmp = p.with_suffix(".tmp")
        fd = os.open(tmp, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
        with os.fdopen(fd, "w") as f:
            json.dump(tf, f)
        os.replace(tmp, p)

    @staticmethod
    def _etag(buf: bytes) -> str:
        return '"' + hashlib.sha256(buf).hexdigest()[:32] + '"'

    # ---- helpers
    def _limited(self, ip) -> bool:
        now = self.clock()
        with self.lock:
            lst = [t for t in self.hits.get(ip, []) if now - t < 60]
            lst.append(now)
            self.hits[ip] = lst
            return len(lst) > self.rate_limit

    def _locked_out(self, aid) -> bool:
        now = self.clock()
        with self.lock:
            lst = [t for t in self.fails.get(aid, []) if now - t < OTP_WINDOW]
            self.fails[aid] = lst
            return len(lst) >= OTP_MAX_FAILS

    def _fail(self, aid) -> None:
        with self.lock:
            self.fails.setdefault(aid, []).append(self.clock())

    def _new_session(self, aid) -> str:
        sid = secrets.token_urlsafe(32)
        with self.lock:
            now = self.clock()
            self.sessions = {k: v for k, v in self.sessions.items() if v[1] > now}
            self.sessions[sid] = (aid, now + SESSION_TTL)
        return sid

    def _session_ok(self, aid, sid) -> bool:
        with self.lock:
            s = self.sessions.get(sid or "")
        return bool(s and s[0] == aid and s[1] > self.clock())

    def _check_second_factor(self, aid, tf, body: dict) -> tuple[bool, bool]:
        """(ok, used_recovery). Consumes a recovery code or records the TOTP step."""
        rec = str(body.get("recovery") or "").strip().lower()
        if rec:
            h = hashlib.sha256(rec.encode()).hexdigest()
            if h in tf.get("recovery", []):
                tf["recovery"].remove(h)
                self._save_tf(aid, tf)
                return True, True
            return False, False
        step = verify_totp(tf.get("secret", ""), body.get("otp"), self.clock(), tf.get("last_step", 0))
        if step is None:
            return False, False
        tf["last_step"] = step
        self._save_tf(aid, tf)
        return True, False

    # ---- one-time pairing
    def _take_pairing(self, pid):
        with self.lock:
            e = self.pairings.pop(pid, None)
        return e if e and e["expires"] > self.clock() else None

    def _pair_authed(self, method, pid, status, aid, body, out):
        now = self.clock()
        with self.lock:
            self.pairings = {k: v for k, v in self.pairings.items() if v["expires"] > now}
            entry = self.pairings.get(pid)
            if status and method == "GET":
                return out(200, js={"pending": bool(entry and entry["aid"] == aid)})
            if method == "DELETE":
                if entry and entry["aid"] == aid:
                    del self.pairings[pid]
                return out(200, "ok")
            if method == "PUT":
                if len(body) > PAIR_MAX_BLOB or not PAYLOAD.match(body.strip()):
                    return out(400, "Unexpected payload")
                if entry:
                    return out(409, "Pairing id already in use")
                if sum(1 for v in self.pairings.values() if v["aid"] == aid) >= PAIR_MAX_PENDING:
                    return out(429, "Too many pending pairings")
                self.pairings[pid] = {"aid": aid, "blob": body.strip(), "expires": now + PAIR_TTL}
                return out(200, js={"expires_in": PAIR_TTL})
        return out(405, "Method not allowed")

    # ---- request handling
    def handle(self, method: str, path: str, headers: dict, body: bytes, ip: str = "-"):
        """Returns (status, headers, body bytes). `headers` keys are case-insensitive lookups via .get()."""
        h = {k.lower(): v for k, v in headers.items()}
        path = path.split("?")[0]

        def out(code, text="", extra=None, js=None):
            hd = {"Content-Type": "text/plain", "Cache-Control": "no-store"}
            hd.update(extra or {})
            if js is not None:
                hd["Content-Type"], text = "application/json", json.dumps(js)
            return code, hd, text.encode() if isinstance(text, str) else text

        if path == "/health":
            return out(200, "ok")
        if self._limited(ip):
            return out(429, "Too many requests")
        pm = PAIR_PATH.match(path)
        if pm and method == "GET" and not pm.group(2):          # the one-time fetch: capability URL, no account auth
            entry = self._take_pairing(pm.group(1))
            return out(404, "Not found or already used") if entry is None else out(200, entry["blob"])
        m = BEARER.match(h.get("authorization", ""))
        if not m:
            return out(401, "Unauthorized")
        aid = hashlib.sha256(m.group(1).encode()).hexdigest()
        tf = self._tf(aid)
        try:
            jbody = json.loads(body or b"{}") if method == "POST" else {}
        except ValueError:
            return out(400, "Bad JSON")

        if path == "/v1/2fa/status" and method == "GET":
            return out(200, js={"enabled": bool(tf.get("enabled"))})

        if path == "/v1/session" and method == "POST":
            if not tf.get("enabled"):
                return out(200, js={"session": None, "twofa": False})
            if self._locked_out(aid):
                return out(429, "Too many failed attempts; try again later")
            ok, used_recovery = self._check_second_factor(aid, tf, jbody)
            if not ok:
                self._fail(aid)
                return out(401, "Invalid code", {"X-IUK-2FA": "required"})
            return out(200, js={"session": self._new_session(aid), "expires_in": SESSION_TTL,
                                "recovery_remaining": len(tf.get("recovery", [])) if used_recovery else None})

        # everything below needs a session when 2FA is on
        if tf.get("enabled") and not self._session_ok(aid, h.get("x-iuk-session")):
            return out(401, "Second factor required", {"X-IUK-2FA": "required"})

        if path == "/v1/2fa/enroll" and method == "POST":
            tf["pending"] = b32_secret()
            self._save_tf(aid, tf)
            label = quote("IUK Browser:relay-" + aid[:8])
            return out(200, js={"secret": tf["pending"], "otpauth":
                                f"otpauth://totp/{label}?secret={tf['pending']}&issuer={quote('IUK Browser')}&algorithm=SHA1&digits=6&period=30"})
        if path == "/v1/2fa/confirm" and method == "POST":
            if not tf.get("pending"):
                return out(409, "Call /v1/2fa/enroll first")
            step = verify_totp(tf["pending"], jbody.get("otp"), self.clock(), 0)
            if step is None:
                return out(401, "Invalid code")
            codes = [f"{secrets.token_hex(2)}-{secrets.token_hex(2)}" for _ in range(8)]
            self._save_tf(aid, {"enabled": True, "secret": tf["pending"], "last_step": step,
                                "recovery": [hashlib.sha256(c.encode()).hexdigest() for c in codes]})
            return out(200, js={"recovery_codes": codes, "session": self._new_session(aid)})
        if path == "/v1/2fa/disable" and method == "POST":
            if not tf.get("enabled"):
                return out(200, js={"enabled": False})
            if self._locked_out(aid):
                return out(429, "Too many failed attempts; try again later")
            ok, _ = self._check_second_factor(aid, tf, jbody)
            if not ok:
                self._fail(aid)
                return out(401, "Invalid code")
            self._tfp(aid).unlink(missing_ok=True)
            return out(200, js={"enabled": False})

        if pm:
            return self._pair_authed(method, pm.group(1), bool(pm.group(2)), aid, body, out)
        if path != "/v1/blob":
            return out(404, "Not found")
        f = self._blob(aid)
        cur = f.read_bytes() if f.exists() else None
        if method == "GET":
            return out(404, "No data") if cur is None else out(200, cur, {"ETag": self._etag(cur)})
        if method == "DELETE":
            f.unlink(missing_ok=True)
            return out(200, "ok")
        if method == "PUT":
            if len(body) > MAX_BODY:
                return out(413, "Too large")
            if_match, if_none = h.get("if-match"), h.get("if-none-match")
            if not if_match and if_none != "*":
                return out(428, "Precondition required")
            if if_none == "*" and cur is not None:
                return out(412, "Already exists")
            if if_match and (cur is None or if_match != self._etag(cur)):
                return out(412, "Version mismatch")
            if not PAYLOAD.match(body.strip()):
                return out(400, "Unexpected payload")
            tmp = f.with_suffix(".tmp")
            tmp.write_bytes(body)
            os.replace(tmp, f)
            return out(200, "ok", {"ETag": self._etag(body)})
        return out(405, "Method not allowed")


# ------------------------------------------------------------------ HTTP wrapper
def make_server(data_dir, host="127.0.0.1", port=0, **kw) -> ThreadingHTTPServer:
    relay = Relay(data_dir, **kw)

    class H(BaseHTTPRequestHandler):
        protocol_version = "HTTP/1.1"

        def _do(self):
            n = int(self.headers.get("Content-Length") or 0)
            if n > MAX_BODY:
                self.send_response(413); self.send_header("Content-Length", "0"); self.send_header("Connection", "close"); self.end_headers()
                return
            body = self.rfile.read(n) if n else b""
            ip = (self.headers.get("X-Forwarded-For", "").split(",")[0].strip() if relay.trust_proxy else "") or self.client_address[0]
            code, hd, data = relay.handle(self.command, self.path, dict(self.headers), body, ip)
            self.send_response(code)
            for k, v in hd.items():
                self.send_header(k, v)
            self.send_header("Content-Length", str(len(data)))
            self.end_headers()
            self.wfile.write(data)

        do_GET = do_PUT = do_POST = do_DELETE = _do

        def log_message(self, *a):  # keep the relay quiet; never log tokens
            pass

    srv = ThreadingHTTPServer((host, port), H)
    srv.daemon_threads = True
    srv.relay = relay
    return srv


def main() -> None:
    srv = make_server(os.environ.get("DATA_DIR", "./data"), os.environ.get("HOST", "127.0.0.1"),
                      int(os.environ.get("PORT", "8787")), trust_proxy=os.environ.get("TRUST_PROXY") == "1")
    print(f"IUK relay listening on http://{srv.server_address[0]}:{srv.server_address[1]}")
    try:
        srv.serve_forever()
    except KeyboardInterrupt:
        pass


if __name__ == "__main__":
    main()
