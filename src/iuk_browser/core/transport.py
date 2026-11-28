"""HTTP client for the sync relay, including the optional TOTP session."""
from __future__ import annotations

import json
import urllib.error
import urllib.request


class RelayError(Exception):
    pass


class AuthError(RelayError):
    pass


class OtpRequired(RelayError):
    """The account has a second factor enabled and no valid session exists yet."""


def fetch_pairing(server: str, pid: str, timeout: float = 20.0) -> str:
    """One-time, unauthenticated fetch of a pairing blob (the 128-bit id is the capability). The relay deletes it."""
    req = urllib.request.Request(server.rstrip("/") + "/v1/pair/" + pid, method="GET")
    try:
        with urllib.request.urlopen(req, timeout=timeout) as r:
            return r.read().decode()
    except urllib.error.HTTPError as e:
        if e.code == 404:
            raise RelayError("This pairing code was already used or has expired") from None
        if e.code == 429:
            raise RelayError("Too many attempts; try again later") from None
        raise RelayError(f"Server error {e.code}") from None
    except (urllib.error.URLError, TimeoutError, OSError) as e:
        raise RelayError(f"Cannot reach the sync server ({getattr(e, 'reason', e)})") from None


class Transport:
    def __init__(self, server: str, token: str, timeout: float = 20.0):
        self.server, self.token, self.timeout = server.rstrip("/"), token, timeout
        self.session: str | None = None

    def _call(self, method: str, path: str, body: bytes | None = None, headers: dict | None = None):
        req = urllib.request.Request(self.server + path, data=body, method=method)
        req.add_header("Authorization", "Bearer " + self.token)
        if self.session:
            req.add_header("X-IUK-Session", self.session)
        for k, v in (headers or {}).items():
            req.add_header(k, v)
        try:
            with urllib.request.urlopen(req, timeout=self.timeout) as r:
                return r.status, dict(r.headers), r.read()
        except urllib.error.HTTPError as e:
            data = e.read()
            if e.code == 401 and e.headers.get("X-IUK-2FA") == "required":
                self.session = None
                raise OtpRequired("A second-factor code is required") from None
            if e.code == 401:
                raise AuthError("The server rejected the sync token") from None
            return e.code, dict(e.headers), data
        except (urllib.error.URLError, TimeoutError, OSError) as e:
            raise RelayError(f"Cannot reach the sync server ({getattr(e, 'reason', e)})") from None

    def _json(self, method, path, obj=None):
        body = json.dumps(obj).encode() if obj is not None else None
        code, _, data = self._call(method, path, body, {"Content-Type": "application/json"} if body else None)
        if code == 429:
            raise RelayError("Too many attempts; try again later")
        if code >= 400:
            raise RelayError(data.decode(errors="replace") or f"Server error {code}")
        return json.loads(data or b"{}")

    # ---- blob
    def get_blob(self):
        code, hd, data = self._call("GET", "/v1/blob")
        if code == 404:
            return None
        if code != 200:
            raise RelayError(f"Server error {code}")
        return {h.lower(): v for h, v in hd.items()}.get("etag"), data.decode()

    def put_blob(self, body: str, etag: str | None) -> bool:
        code, _, _ = self._call("PUT", "/v1/blob", body.encode(), {
            "Content-Type": "text/plain", **({"If-Match": etag} if etag else {"If-None-Match": "*"})})
        if code == 412:
            return False
        if code != 200:
            raise RelayError(f"Upload failed ({code})")
        return True

    def delete_blob(self) -> None:
        self._call("DELETE", "/v1/blob")

    # ---- second factor
    def twofa_status(self) -> bool:
        return bool(self._json("GET", "/v1/2fa/status").get("enabled"))

    def login(self, otp: str | None = None, recovery: str | None = None) -> None:
        r = self._json("POST", "/v1/session", {"otp": otp} if otp else {"recovery": recovery})
        self.session = r.get("session")

    def enroll(self) -> dict:
        return self._json("POST", "/v1/2fa/enroll", {})

    def confirm(self, otp: str) -> list[str]:
        r = self._json("POST", "/v1/2fa/confirm", {"otp": otp})
        self.session = r.get("session")
        return r["recovery_codes"]

    def disable(self, otp: str | None = None, recovery: str | None = None) -> None:
        self._json("POST", "/v1/2fa/disable", {"otp": otp} if otp else {"recovery": recovery})
        self.session = None

    # ---- one-time pairing (offering side)
    def pair_put(self, pid: str, blob: str) -> int:
        code, _, data = self._call("PUT", "/v1/pair/" + pid, blob.encode(), {"Content-Type": "text/plain"})
        if code == 429:
            raise RelayError("Too many pending pairings; wait a moment")
        if code != 200:
            raise RelayError(f"Could not create the pairing ({code})")
        return int(json.loads(data).get("expires_in", 120))

    def pair_pending(self, pid: str) -> bool:
        return bool(self._json("GET", "/v1/pair/" + pid + "/status").get("pending"))

    def pair_cancel(self, pid: str) -> None:
        self._call("DELETE", "/v1/pair/" + pid)
