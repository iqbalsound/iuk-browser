import hashlib
import json
import sys
import urllib.error
import urllib.request

import pytest

import iuk_relay as R
from iuk_browser.core import crypto
from iuk_browser.core.transport import AuthError, OtpRequired, RelayError, Transport


def test_totp_rfc6238_vectors():
    secret = b"12345678901234567890"
    for t, code8 in [(59, "94287082"), (1111111109, "07081804"), (1111111111, "14050471"), (2000000000, "69279037")]:
        assert R.hotp(secret, t // 30, 8) == code8
    assert R.hotp(secret, 59 // 30) == "287082"


def keys(secret="relay-test-secret"):
    return crypto.derive_keys("r@x.com", secret)


def totp_now(b32, clock):
    import base64
    return R.hotp(base64.b32decode(b32 + "=" * (-len(b32) % 8)), int(clock() // 30))


def test_blob_protocol_matches_the_original_relay(relay):
    k = keys(); t = Transport(relay.url, k.token)
    assert t.get_blob() is None
    body = crypto.encrypt(k.key, {"v": 2})
    assert t.put_blob(body, None) is True
    assert t.put_blob(body, None) is False                 # If-None-Match: * on existing -> 412
    etag, text = t.get_blob()
    assert text == body and etag.startswith('"')
    assert t.put_blob(crypto.encrypt(k.key, {"v": 2, "x": 1}), etag) is True
    assert t.put_blob(body, etag) is False                 # stale etag
    with pytest.raises(AuthError):
        Transport(relay.url, "0" * 63).get_blob()
    req = urllib.request.Request(relay.url + "/v1/blob", data=b"not encrypted", method="PUT",
                                 headers={"Authorization": "Bearer " + k.token, "If-None-Match": "*"})
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(req)
    assert e.value.code in (400, 412)
    t.delete_blob()
    assert t.get_blob() is None
    assert "wörld".encode() not in b"".join(p.read_bytes() for p in relay.dir.iterdir())


def test_accounts_are_isolated(relay):
    a, b = keys("secret-aaaaaaaaaaaa"), keys("secret-bbbbbbbbbbbb")
    Transport(relay.url, a.token).put_blob(crypto.encrypt(a.key, {"v": 2}), None)
    assert Transport(relay.url, b.token).get_blob() is None


def test_enroll_confirm_then_blob_requires_a_session(relay):
    k = keys(); t = Transport(relay.url, k.token)
    t.put_blob(crypto.encrypt(k.key, {"v": 2}), None)
    assert t.twofa_status() is False
    enr = t.enroll()
    assert enr["otpauth"].startswith("otpauth://totp/IUK%20Browser") and "secret=" + enr["secret"] in enr["otpauth"]
    with pytest.raises(RelayError):
        t.confirm("000000")                                          # wrong code does not enable it
    assert t.twofa_status() is False
    codes = t.confirm(totp_now(enr["secret"], relay.clock))
    assert len(codes) == 8 and t.session
    assert t.get_blob() is not None                                  # the confirming session works

    other = Transport(relay.url, k.token)                            # a thief with only the token
    with pytest.raises(OtpRequired):
        other.get_blob()
    with pytest.raises(OtpRequired):
        other.put_blob("v1.AA.AA", None)
    assert other.twofa_status() is True                              # status is the only open door

    relay.clock.advance(30)                                          # next time step (no replay of the used code)
    other.login(otp=totp_now(enr["secret"], relay.clock))
    assert other.get_blob() is not None


def test_totp_code_cannot_be_replayed_and_skew_is_tolerated(relay):
    k = keys(); t = Transport(relay.url, k.token)
    enr = t.enroll(); code = totp_now(enr["secret"], relay.clock); t.confirm(code)
    attacker = Transport(relay.url, k.token)
    with pytest.raises(RelayError):
        attacker.login(otp=code)                                     # same step already used
    relay.clock.advance(31)
    stale = totp_now(enr["secret"], relay.clock)
    relay.clock.advance(-1)                                          # device clock slightly behind: previous/next step OK
    attacker.login(otp=stale)
    assert attacker.session


def test_recovery_codes_work_once(relay):
    k = keys(); t = Transport(relay.url, k.token)
    enr = t.enroll(); codes = t.confirm(totp_now(enr["secret"], relay.clock))
    a = Transport(relay.url, k.token); a.login(recovery=codes[0]); assert a.session
    with pytest.raises(RelayError):
        Transport(relay.url, k.token).login(recovery=codes[0])       # consumed
    b = Transport(relay.url, k.token); b.login(recovery=codes[1].upper()); assert b.session   # case-insensitive


def test_brute_force_lockout(relay):
    k = keys(); t = Transport(relay.url, k.token)
    enr = t.enroll(); t.confirm(totp_now(enr["secret"], relay.clock))
    a = Transport(relay.url, k.token)
    for _ in range(5):
        with pytest.raises(RelayError):
            a.login(otp="123456")
    relay.clock.advance(1)
    good = totp_now(enr["secret"], relay.clock)
    with pytest.raises(RelayError, match="Too many"):
        a.login(otp=good)                                            # even a correct code is refused while locked out
    relay.clock.advance(R.OTP_WINDOW + 40)
    a.login(otp=totp_now(enr["secret"], relay.clock)); assert a.session


def test_sessions_expire_and_are_bound_to_one_account(relay):
    k1, k2 = keys("secret-one-one-one"), keys("secret-two-two-two")
    t1, t2 = Transport(relay.url, k1.token), Transport(relay.url, k2.token)
    e1 = t1.enroll(); t1.confirm(totp_now(e1["secret"], relay.clock))
    t2.session = t1.session                                          # another account presenting account 1's session
    t2.enroll(); e2 = t2.enroll(); t2.confirm(totp_now(e2["secret"], relay.clock))
    thief = Transport(relay.url, k2.token); thief.session = t1.session
    with pytest.raises(OtpRequired):
        thief.get_blob()
    relay.clock.advance(R.SESSION_TTL + 5)
    with pytest.raises(OtpRequired):
        t1.get_blob()


def test_disable_requires_a_code_and_restores_open_access(relay):
    k = keys(); t = Transport(relay.url, k.token)
    enr = t.enroll(); t.confirm(totp_now(enr["secret"], relay.clock))
    with pytest.raises(RelayError):
        t.disable(otp="000000")
    relay.clock.advance(30)
    t.disable(otp=totp_now(enr["secret"], relay.clock))
    assert Transport(relay.url, k.token).twofa_status() is False
    assert Transport(relay.url, k.token).get_blob() is None or True   # no 2FA gate any more


def test_rate_limit_and_health(relay):
    assert urllib.request.urlopen(relay.url + "/health").read() == b"ok"
    r = R.Relay(relay.dir / "x", rate_limit=3, clock=relay.clock)
    codes = [r.handle("GET", "/v1/blob", {"Authorization": "Bearer " + "a" * 64}, b"", "1.2.3.4")[0] for _ in range(5)]
    assert codes == [404, 404, 404, 429, 429]


@pytest.mark.skipif(sys.platform == 'win32', reason='POSIX file modes')
def test_2fa_file_is_private(relay):
    k = keys(); t = Transport(relay.url, k.token); t.enroll()
    f = next(relay.dir.glob("*.2fa.json"))
    assert (f.stat().st_mode & 0o777) == 0o600
    assert k.token not in f.read_text()


# ------------------------------------------------------------------ one-time pairing endpoints
def _pid():
    import secrets
    return secrets.token_hex(16)


def _blob(key):
    return crypto.encrypt(key, {"x": 1})


def test_pairing_blob_is_fetchable_exactly_once_and_then_gone(relay):
    k = keys(); t = Transport(relay.url, k.token); pid = _pid()
    assert t.pair_put(pid, _blob(k.key)) == R.PAIR_TTL
    assert t.pair_pending(pid) is True
    first = urllib.request.urlopen(relay.url + "/v1/pair/" + pid).read().decode()        # no Authorization header at all
    assert first.startswith("v1.")
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(relay.url + "/v1/pair/" + pid)                             # second fetch: gone
    assert e.value.code == 404
    assert t.pair_pending(pid) is False                                                   # the offering device can see it was used


def test_pairing_expires_after_two_minutes(relay):
    k = keys(); t = Transport(relay.url, k.token); pid = _pid()
    t.pair_put(pid, _blob(k.key))
    relay.clock.advance(R.PAIR_TTL + 1)
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(relay.url + "/v1/pair/" + pid)
    assert e.value.code == 404 and t.pair_pending(pid) is False


def test_pairing_limits_ownership_and_validation(relay):
    a, b = keys("pair-secret-aaaaaaa"), keys("pair-secret-bbbbbbb")
    ta, tb = Transport(relay.url, a.token), Transport(relay.url, b.token)
    pids = [_pid() for _ in range(R.PAIR_MAX_PENDING + 1)]
    for p in pids[:R.PAIR_MAX_PENDING]:
        ta.pair_put(p, _blob(a.key))
    with pytest.raises(RelayError, match="Too many"):
        ta.pair_put(pids[-1], _blob(a.key))                                               # at most 3 pending per account
    assert tb.pair_pending(pids[0]) is False                                              # others cannot even see it
    tb.pair_cancel(pids[0])                                                               # ... nor cancel it
    assert ta.pair_pending(pids[0]) is True
    ta.pair_cancel(pids[0]); assert ta.pair_pending(pids[0]) is False                     # the owner can
    with pytest.raises(RelayError):
        ta.pair_put(pids[1], _blob(a.key))                                                # id already in use (409)
    with pytest.raises(RelayError):
        ta.pair_put(_pid(), "not-encrypted")                                              # payload shape is enforced
    big = "v1." + "A" * 5000 + ".AA"
    with pytest.raises(RelayError):
        ta.pair_put(_pid(), big)
    with pytest.raises(urllib.error.HTTPError) as e:
        urllib.request.urlopen(relay.url + "/v1/pair/not-a-valid-id")
    assert e.value.code in (401, 404)


def test_pairing_needs_a_second_factor_session_when_enabled_but_the_fetch_stays_open(relay):
    k = keys(); t = Transport(relay.url, k.token)
    enr = t.enroll(); t.confirm(totp_now(enr["secret"], relay.clock))
    thief = Transport(relay.url, k.token)
    with pytest.raises(OtpRequired):
        thief.pair_put(_pid(), _blob(k.key))                                              # a stolen token cannot plant offers
    pid = _pid(); t.pair_put(pid, _blob(k.key))                                           # a logged-in device can
    assert urllib.request.urlopen(relay.url + "/v1/pair/" + pid).status == 200            # the NEW device has no session: fetch is open


def test_pairing_blobs_live_in_memory_only(relay):
    k = keys(); t = Transport(relay.url, k.token); pid = _pid()
    t.pair_put(pid, _blob(k.key))
    assert not any(pid in p.name or pid.encode() in p.read_bytes() for p in relay.dir.iterdir())
