"""Account: encrypted password vault + synchronisation of bookmarks and logins.

Secrets (derived key, relay token, decrypted logins) live in memory only while unlocked.
"""
from __future__ import annotations

import functools
import json
from pathlib import Path

import os

from . import crypto, merge as M, pairing
from .bookmarks import BookmarkStore
from .transport import OtpRequired, RelayError, Transport, fetch_pairing  # noqa: F401  (re-exported for the UI)
from .util import host_from, host_matches, now_ms

VERIFIER = {"ok": "iuk-browser"}


def _locked(fn):
    @functools.wraps(fn)
    def wrapper(self, *a, **kw):
        with self.store.lock:
            return fn(self, *a, **kw)
    return wrapper


class Cancelled(Exception):
    """The user cancelled a long operation before anything was stored."""


def _check(cancel) -> None:
    if cancel is not None and cancel.is_set():
        raise Cancelled()


class AccountError(Exception):
    pass


class WrongKey(AccountError):
    pass


class Locked(AccountError):
    pass


class Account:
    def __init__(self, data_dir: Path, store: BookmarkStore, transport_factory=Transport):
        self.dir = Path(data_dir)
        self.dir.mkdir(parents=True, exist_ok=True)
        self.store = store
        self._tf = transport_factory
        self._keys: crypto.Keys | None = None
        self._username = ""
        self.logins: dict[str, dict] = {}
        self._relay_session: str | None = None

    # ---- files
    @property
    def _acct(self) -> Path: return self.dir / "account.json"
    @property
    def _enc(self) -> Path: return self.dir / "logins.enc"
    @property
    def _meta(self) -> Path: return self.dir / "sync-meta.json"

    def _read(self, p: Path, default):
        return json.loads(p.read_text("utf-8")) if p.exists() else default

    def _write(self, p: Path, obj) -> None:
        tmp = p.with_suffix(p.suffix + ".tmp")
        tmp.write_text(json.dumps(obj), "utf-8")
        tmp.replace(p)

    # ---- state
    def is_setup(self) -> bool: return self._acct.exists()
    def is_unlocked(self) -> bool: return self._keys is not None

    def status(self) -> dict:
        a, m = self._read(self._acct, None), self._read(self._meta, {})
        return {"setup": bool(a), "unlocked": self.is_unlocked(), "username": a["username"] if a else "",
                "server": a.get("server", "") if a else "", "last_sync": m.get("last_sync", 0), "last_error": m.get("last_error", "")}

    def _need(self) -> crypto.Keys:
        if not self._keys:
            raise Locked("The vault is locked")
        return self._keys

    @staticmethod
    def _norm_server(url: str) -> str:
        url = (url or "").strip().rstrip("/")
        if not url:
            return ""
        if not url.lower().startswith(("http://", "https://")):
            raise AccountError("Server URL must start with http:// or https://")
        return url

    def _transport(self, server: str, keys: crypto.Keys) -> Transport:
        t = self._tf(server, keys.token)
        t.session = self._relay_session
        return t

    # ---- setup / unlock
    def setup(self, username: str, secret: str, server: str = "", otp: str | None = None, recovery: str | None = None, cancel=None) -> None:
        username = (username or "").strip()
        if not username:
            raise AccountError("Enter a user name")
        if len(secret or "") < 12:
            raise AccountError("Secret key must be at least 12 characters")
        if self.is_setup():
            raise AccountError("This device is already set up. Forget it in Settings first.")
        server = self._norm_server(server)
        keys = crypto.derive_keys(username, secret)
        _check(cancel)
        if server:   # joining existing data: make sure the key really matches before saving anything
            t = self._transport(server, keys)
            if otp or recovery:                     # the relay account has a second factor: log in first
                t.login(otp=otp, recovery=recovery)
                self._relay_session = t.session
            remote = t.get_blob()
            if remote:
                try:
                    crypto.decrypt(keys.key, remote[1])
                except crypto.DecryptError:
                    raise WrongKey("Existing synced data was encrypted with a different key") from None
        _check(cancel)                                 # last chance to stop: nothing has been written yet
        self._write(self._acct, {"username": username, "server": server, "kdf": keys.kdf,
                                 "verifier": crypto.encrypt(keys.key, VERIFIER)})
        self._keys, self._username, self.logins = keys, username, {}
        self._persist_logins()
        if server:
            self.sync_now()

    @_locked
    def unlock(self, username: str, secret: str, cancel=None) -> None:
        a = self._read(self._acct, None)
        if not a:
            raise AccountError("Not set up yet")
        if username.strip().lower() != a["username"].lower():
            raise WrongKey("Wrong user name or secret key")
        keys = crypto.derive_keys(a["username"], secret)
        _check(cancel)
        try:
            crypto.decrypt(keys.key, a["verifier"])
        except crypto.DecryptError:
            raise WrongKey("Wrong user name or secret key") from None
        self._keys, self._username = keys, a["username"]
        enc = self._enc.read_text("utf-8") if self._enc.exists() else None
        self.logins = crypto.decrypt(keys.key, enc) if enc else {}

    @_locked
    def lock(self) -> None:
        self._keys, self.logins, self._relay_session = None, {}, None

    def wipe(self) -> None:
        self.lock()
        for p in (self._acct, self._enc, self._meta):
            p.unlink(missing_ok=True)

    def set_server(self, server: str) -> str:
        a = self._read(self._acct, None)
        if not a:
            raise AccountError("Not set up yet")
        a["server"] = self._norm_server(server)
        self._write(self._acct, a)
        return a["server"]

    def _persist_logins(self) -> None:
        self._enc.write_text(crypto.encrypt(self._need().key, self.logins), "utf-8")

    # ---- logins
    @_locked
    def list_logins(self, host: str | None = None) -> list[dict]:
        self._need()
        out = [{k: l[k] for k in ("id", "host", "username", "notes", "updatedAt")} for l in self.logins.values()
               if not l.get("deleted") and (not host or host_matches(l["host"], host))]
        return sorted(out, key=lambda l: (l["host"], l["username"].lower()))

    @_locked
    def get_password(self, login_id: str) -> str:
        self._need()
        l = self.logins.get(login_id)
        if not l or l.get("deleted"):
            raise AccountError("Not found")
        return l["password"]

    def _put(self, host: str, username: str, password: str, notes: str, now: int) -> str:
        host, username = host_from(host), username or ""
        if not host or not password:
            raise AccountError("Site and password are required")
        lid = host + "|" + username.lower()
        prev = self.logins.get(lid)
        self.logins[lid] = {"id": lid, "host": host, "username": username, "password": password, "notes": notes or "",
                            "createdAt": (prev or {}).get("createdAt", now), "updatedAt": max(now, (prev or {}).get("updatedAt", 0) + 1), "deleted": False}
        return lid

    @_locked
    def save_login(self, host: str, username: str, password: str, notes: str = "") -> str:
        self._need()
        lid = self._put(host, username, password, notes, now_ms())
        self._persist_logins()
        return lid

    @_locked
    def import_logins(self, items: list[dict]) -> int:
        self._need()
        n = 0
        for it in items:
            try:
                self._put(it["host"], it.get("username", ""), it["password"], it.get("notes", ""), now_ms())
                n += 1
            except (AccountError, KeyError):
                pass
        self._persist_logins()
        return n

    @_locked
    def remove_login(self, login_id: str) -> None:
        self._need()
        prev = self.logins.get(login_id)
        if prev:
            self.logins[login_id] = {"id": login_id, "deleted": True, "createdAt": prev.get("createdAt", 0), "updatedAt": max(now_ms(), prev["updatedAt"] + 1)}
            self._persist_logins()

    @_locked
    def export_logins(self) -> list[dict]:
        self._need()
        return [{k: l[k] for k in ("host", "username", "password", "notes")} for l in self.logins.values() if not l.get("deleted")]

    @_locked
    def find_match(self, host: str, username: str, password: str) -> str:
        """'known' | 'update' | 'new' for a captured submission."""
        ex = self.logins.get(host_from(host) + "|" + (username or "").lower())
        if ex and not ex.get("deleted"):
            return "known" if ex["password"] == password else "update"
        return "new"

    # ---- pairing
    def pairing_payload(self, secret: str, cancel=None) -> str:
        keys = self._need()
        derived = crypto.derive_keys(self._username, secret or "")
        _check(cancel)
        if derived.token != keys.token:
            raise WrongKey("That is not the secret key of this vault")
        return pairing.encode(self._username, secret, self._read(self._acct, {}).get("server", ""))

    def create_pairing_offer(self, secret: str, cancel=None) -> tuple[str, str]:
        """One-time pairing: returns (code for the QR, pairing id). The account key never appears in the code."""
        keys, a = self._need(), self._read(self._acct, {})
        if not a.get("server"):
            raise AccountError("Set a sync server first to use one-time pairing codes")
        derived = crypto.derive_keys(self._username, secret or "")
        _check(cancel)
        if derived.token != keys.token:
            raise WrongKey("That is not the secret key of this vault")
        one_time_key, pid = os.urandom(32), os.urandom(16).hex()
        inner = crypto.encrypt(one_time_key, {"u": self._username, "k": secret, "s": a["server"]})
        self._transport(a["server"], keys).pair_put(pid, inner)
        return pairing.encode_offer(a["server"], pid, one_time_key), pid

    def pairing_pending(self, pid: str) -> bool:
        keys, a = self._need(), self._read(self._acct, {})
        return self._transport(a["server"], keys).pair_pending(pid)

    def cancel_pairing(self, pid: str) -> None:
        keys, a = self._need(), self._read(self._acct, {})
        self._transport(a["server"], keys).pair_cancel(pid)

    @staticmethod
    def redeem_pairing(code: str) -> pairing.Pairing:
        """Consumes a one-time code (it works exactly once) and returns the account details it carried."""
        offer = pairing.decode_offer(code)
        blob = fetch_pairing(offer.server, offer.pid)
        try:
            d = crypto.decrypt(offer.key, blob)
        except crypto.DecryptError:
            raise AccountError("The pairing data could not be decrypted") from None
        return pairing.decode(pairing.encode(d["u"], d["k"], d["s"]))

    # ---- sync
    def provide_otp(self, otp: str | None = None, recovery: str | None = None) -> None:
        """Log in to the relay's second factor; the session is kept in memory until lock()."""
        keys, server = self._need(), self._read(self._acct, {}).get("server", "")
        t = self._tf(server, keys.token)
        t.login(otp=otp, recovery=recovery)
        self._relay_session = t.session

    def sync_now(self) -> dict:
        keys, a = self._need(), self._read(self._acct, {})
        server = a.get("server", "")
        meta = self._read(self._meta, {})
        if not server:
            return {"offline": True}
        try:
            result = self._sync(server, keys)
        except (RelayError, AccountError) as e:
            self._write(self._meta, {**meta, "last_error": str(e)})
            raise
        self._write(self._meta, {"last_sync": now_ms(), "last_error": ""})
        return result

    def _sync(self, server: str, keys: crypto.Keys) -> dict:
        t = self._transport(server, keys)
        for _ in range(4):
            remote = t.get_blob()
            self._relay_session = t.session
            remote_doc, remote_was_old = None, False
            if remote:
                try:
                    raw = crypto.decrypt(keys.key, remote[1])
                except crypto.DecryptError:
                    raise WrongKey("Synced data was encrypted with a different key") from None
                remote_was_old = raw.get("v") == 1
                try:
                    remote_doc = M.normalize(raw)
                except ValueError as e:
                    raise AccountError(str(e)) from None
            with self.store.lock:            # local state only; the network calls above/below stay outside the lock
                if self._keys is not keys:   # locked (or re-keyed) while we were talking to the relay: drop everything
                    raise Locked("The vault was locked during sync")
                local = {"bookmarks": self.store.bookmarks, "folders": self.store.folders, "logins": self.logins}
                merged = M.merge_docs(local, remote_doc or M.empty_doc(), now_ms())
                before = (len(self.store.bookmarks), len(self.logins))
                self.store.replace(merged["bookmarks"], merged["folders"])
                self.logins = merged["logins"]
                self._persist_logins()
            if remote_doc is None or remote_was_old or not M.docs_equal(merged, remote_doc):
                body = crypto.encrypt(keys.key, {**merged, "kdf": keys.kdf})
                if not t.put_blob(body, remote[0] if remote else None):
                    continue   # someone wrote first: fetch and merge again
            return {"bookmarks": len(self.store.bookmarks) - before[0], "logins": len(self.logins) - before[1]}
        raise AccountError("Sync conflict, please try again")

    # ---- relay second factor management (needs a live relay session when already enabled)
    def twofa(self) -> Transport:
        keys, a = self._need(), self._read(self._acct, {})
        if not a.get("server"):
            raise AccountError("Set a sync server first")
        return self._transport(a["server"], keys)
