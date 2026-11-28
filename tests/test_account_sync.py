import json

import pytest

from iuk_browser.core import crypto, merge as M, pairing
from iuk_browser.core.account import Account, AccountError, Locked, WrongKey
from iuk_browser.core.bookmarks import BookmarkStore
from iuk_browser.core.transport import OtpRequired, RelayError, Transport
from test_relay import totp_now

USER, SECRET = "me@x.com", "my-secret-connect-key"


def device(tmp_path, name):
    d = tmp_path / name
    return Account(d, BookmarkStore(d / "bookmarks.json"))


def test_two_devices_converge_bookmarks_tags_folders_and_passwords(tmp_path, relay):
    A, B = device(tmp_path, "a"), device(tmp_path, "b")
    f = A.store.add_folder("News")
    A.store.add_bookmark("https://hn.example/", "HN", f, tags=["tech", "daily"])
    A.setup(USER, SECRET, relay.url)
    A.save_login("https://www.github.com/login", "iqbal", "pw-one")
    A.sync_now()

    B.store.add_bookmark("https://b-only.example/", "Mine")
    B.setup(USER.upper(), SECRET, relay.url)                 # user name is case-insensitive
    assert {b["url"] for b in B.store.bookmarks.values()} == {"https://hn.example/", "https://b-only.example/"}
    hn = B.store.by_url("https://hn.example/")
    assert B.store.tags_of(hn) == ["daily", "tech"] and B.store.folder_path(hn["folder"]) == ["News"]
    assert B.get_password("github.com|iqbal") == "pw-one"

    # concurrent edits: B retags and changes the password, A renames the bookmark
    B.store.update_bookmark(hn["id"], tags=["tech", "daily", "read-later"])
    B.save_login("github.com", "iqbal", "pw-two")
    A.store.update_bookmark(hn["id"], title="Hacker News")
    B.sync_now(); A.sync_now(); B.sync_now()
    for acc in (A, B):
        it = acc.store.by_url("https://hn.example/")
        assert it["title"] == "Hacker News" and acc.store.tags_of(it) == ["daily", "read-later", "tech"]
        assert acc.get_password("github.com|iqbal") == "pw-two"
    assert M.docs_equal({"bookmarks": A.store.bookmarks, "folders": A.store.folders, "logins": A.logins},
                        {"bookmarks": B.store.bookmarks, "folders": B.store.folders, "logins": B.logins})


def test_deleting_propagates_and_server_holds_only_ciphertext(tmp_path, relay):
    A, B = device(tmp_path, "a"), device(tmp_path, "b")
    A.store.add_bookmark("https://secret-site.example/", "Secret site")
    A.setup(USER, SECRET, relay.url); A.save_login("bank.example", "me", "hunter2-hunter2"); A.sync_now()
    B.setup(USER, SECRET, relay.url)
    B.store.remove_bookmark(B.store.by_url("https://secret-site.example/")["id"]); B.remove_login("bank.example|me")
    B.sync_now(); A.sync_now()
    assert A.store.by_url("https://secret-site.example/") is None and A.list_logins() == []
    blob = b"".join(p.read_bytes() for p in relay.dir.iterdir())
    assert b"hunter2" not in blob and b"secret-site" not in blob and b"bank.example" not in blob


def test_wrong_key_unlock_setup_and_locking(tmp_path, relay):
    A = device(tmp_path, "a")
    A.setup(USER, SECRET, relay.url); A.save_login("a.com", "u", "p-p-p-p-p-p")
    A.lock()
    with pytest.raises(Locked):
        A.list_logins()
    with pytest.raises(WrongKey):
        A.unlock(USER, "not-the-right-key!!")
    with pytest.raises(WrongKey):
        A.unlock("someone@else.com", SECRET)
    A.unlock(USER, SECRET)
    assert A.get_password("a.com|u") == "p-p-p-p-p-p"
    assert A.list_logins("login.a.com") and not A.list_logins("evil-a.com")      # subdomain yes, look-alike no
    with pytest.raises(AccountError, match="already set up"):
        A.setup(USER, SECRET, relay.url)
    with pytest.raises(AccountError, match="12 characters"):
        device(tmp_path, "z").setup(USER, "short", "")


def test_new_device_with_wrong_key_is_a_separate_empty_account(tmp_path, relay):
    A, C = device(tmp_path, "a"), device(tmp_path, "c")
    A.setup(USER, SECRET, relay.url); A.save_login("a.com", "u", "pw-pw-pw-pw"); A.sync_now()
    C.setup(USER, "totally-other-key-123", relay.url)
    assert C.list_logins() == []
    assert len([p for p in relay.dir.glob("*.blob")]) == 2


def test_qr_pairing_flow(tmp_path, relay):
    A, B = device(tmp_path, "a"), device(tmp_path, "b")
    A.setup(USER, SECRET, relay.url); A.save_login("github.com", "iqbal", "pw-qr-pw-qr"); A.sync_now()
    with pytest.raises(WrongKey):
        A.pairing_payload("wrong-key-wrong-key")
    p = pairing.decode(A.pairing_payload(SECRET))
    assert (p.username, p.secret, p.server) == (USER, SECRET, relay.url)
    B.setup(p.username, p.secret, p.server)
    assert B.get_password("github.com|iqbal") == "pw-qr-pw-qr"
    A.lock()
    with pytest.raises(Locked):
        A.pairing_payload(SECRET)


def test_reads_data_written_by_the_firefox_extension_and_upgrades_it_to_v2(tmp_path, relay, golden):
    crypto.PARAMS.update({"memory_kib": 256, "passes": 1, "lanes": 1})
    k = crypto.derive_keys(USER, SECRET)
    doc = {"v": 1, "bookmarks": {"https://a.example/": {"url": "https://a.example/", "title": "Ä", "root": "toolbar", "path": ["News"], "updatedAt": 5, "deleted": False}},
           "logins": golden["doc"]["logins"]}
    Transport(relay.url, k.token).put_blob(crypto.encrypt(k.key, doc), None)      # as the extension 1.1 would
    A = device(tmp_path, "a")
    A.setup(USER, SECRET, relay.url)
    assert A.store.by_url("https://a.example/")["title"] == "Ä"
    assert A.get_password("a.com|me") == "pw-ü"
    _, text = Transport(relay.url, k.token).get_blob()
    assert crypto.decrypt(k.key, text)["v"] == 2                                   # rewritten as v2 (old clients now refuse)


def test_newer_document_version_is_refused_cleanly(tmp_path, relay):
    k = crypto.derive_keys(USER, SECRET)
    Transport(relay.url, k.token).put_blob(crypto.encrypt(k.key, {"v": 9}), None)
    A = device(tmp_path, "a")
    A.setup(USER, SECRET, "")
    A.set_server(relay.url)
    with pytest.raises(AccountError, match="Unsupported sync data version"):
        A.sync_now()


def test_second_factor_flow_inside_sync(tmp_path, relay):
    A, B = device(tmp_path, "a"), device(tmp_path, "b")
    A.setup(USER, SECRET, relay.url); A.save_login("a.com", "u", "pw-pw-pw-pw"); A.sync_now()
    t = A.twofa()
    enr = t.enroll(); t.confirm(totp_now(enr["secret"], relay.clock))
    A._relay_session = t.session
    A.sync_now()                                                                   # A's session works

    with pytest.raises(OtpRequired):                                               # a new device must present a code
        B.setup(USER, SECRET, relay.url)
    assert not B.is_setup()                                                        # nothing half-created
    # the UI path: it catches OtpRequired, asks for the code and retries with it
    relay.clock.advance(30)
    B2 = device(tmp_path, "b2")
    B2.setup(USER, SECRET, relay.url, otp=totp_now(enr["secret"], relay.clock))
    assert B2.get_password("a.com|u") == "pw-pw-pw-pw"
    B2.sync_now()                                                                  # the session from setup keeps working

    A.lock(); A.unlock(USER, SECRET)                                               # lock drops the relay session
    with pytest.raises(OtpRequired):
        A.sync_now()
    relay.clock.advance(30)
    A.provide_otp(totp_now(enr["secret"], relay.clock))
    A.sync_now()
    assert "second" not in A.status()["last_error"].lower()


def test_offline_and_unreachable_server_report_errors_without_data_loss(tmp_path):
    A = device(tmp_path, "a")
    A.setup(USER, SECRET, "")
    A.save_login("a.com", "u", "pw-pw-pw-pw")
    assert A.sync_now() == {"offline": True}
    A.set_server("http://127.0.0.1:1")
    from iuk_browser.core.transport import RelayError
    with pytest.raises(RelayError, match="Cannot reach"):
        A.sync_now()
    assert "Cannot reach" in A.status()["last_error"] and A.get_password("a.com|u") == "pw-pw-pw-pw"
    with pytest.raises(AccountError):
        A.set_server("ftp://nope")


def test_vault_is_encrypted_at_rest_and_survives_restart(tmp_path):
    A = device(tmp_path, "a")
    A.setup(USER, SECRET, ""); A.save_login("a.com", "me", "very-secret-pw-123")
    raw = (tmp_path / "a" / "logins.enc").read_text() + (tmp_path / "a" / "account.json").read_text()
    assert "very-secret-pw-123" not in raw and "a.com" not in raw
    A2 = Account(tmp_path / "a", BookmarkStore(tmp_path / "a" / "bookmarks.json"))
    assert A2.status()["setup"] and not A2.is_unlocked()
    A2.unlock(USER, SECRET)
    assert A2.get_password("a.com|me") == "very-secret-pw-123"
    A2.wipe()
    assert not A2.status()["setup"]


def test_capture_classification_and_csv_roundtrip(tmp_path):
    from iuk_browser.core import csvio
    A = device(tmp_path, "a"); A.setup(USER, SECRET, "")
    assert A.find_match("https://x.com/login", "u", "p") == "new"
    A.save_login("x.com", "u", "p")
    assert A.find_match("https://www.x.com/", "U", "p") == "known" and A.find_match("x.com", "u", "other") == "update"
    text = csvio.export_logins(A.export_logins())
    B = device(tmp_path, "b"); B.setup(USER, SECRET, "")
    assert B.import_logins(csvio.parse_logins(text)) == 1 and B.get_password("x.com|u") == "p"
    chrome = 'name,url,username,password,note\nGitHub,https://github.com/login,me,"p,""w""",n\n'
    assert csvio.parse_logins(chrome) == [{"host": "github.com", "username": "me", "password": 'p,"w"', "notes": "n"}]
    with pytest.raises(ValueError):
        csvio.parse_logins("a,b\n1,2\n")


def test_a_deleted_login_can_be_added_again_and_syncs_back(tmp_path, relay):
    A, B = device(tmp_path, "a"), device(tmp_path, "b")
    A.setup(USER, SECRET, relay.url); A.save_login("x.com", "u", "first-pw-123"); A.sync_now()
    B.setup(USER, SECRET, relay.url)
    A.remove_login("x.com|u"); A.sync_now(); B.sync_now()
    assert B.list_logins() == []
    A.save_login("x.com", "u", "second-pw-456"); A.sync_now(); B.sync_now()      # used to raise KeyError (silently skipped on import)
    assert B.get_password("x.com|u") == "second-pw-456"
    assert A.import_logins([{"host": "x.com", "username": "u", "password": "third-pw-789"}]) == 1


# ------------------------------------------------------------------ one-time pairing (IUKB2)
def test_one_time_pairing_end_to_end(tmp_path, relay):
    from iuk_browser.core.account import AccountError
    A, B = device(tmp_path, "a"), device(tmp_path, "b")
    A.setup(USER, SECRET, relay.url); A.save_login("github.com", "iqbal", "pw-one-time"); A.sync_now()
    code, pid = A.create_pairing_offer(SECRET)
    assert code.startswith("IUKB2:") and SECRET not in code and USER not in code and "iqbal" not in code
    assert pairing.kind(code) == "offer" and A.pairing_pending(pid) is True
    p = Account.redeem_pairing(code)
    assert (p.username, p.secret, p.server) == (USER, SECRET, relay.url)
    assert A.pairing_pending(pid) is False                                          # the showing device sees it was used
    with pytest.raises(RelayError, match="already used or has expired"):
        Account.redeem_pairing(code)                                                # a screenshot of the QR is now useless
    B.setup(p.username, p.secret, p.server)
    assert B.get_password("github.com|iqbal") == "pw-one-time"


def test_expired_or_cancelled_offers_cannot_be_redeemed(tmp_path, relay):
    A = device(tmp_path, "a"); A.setup(USER, SECRET, relay.url)
    code, pid = A.create_pairing_offer(SECRET)
    relay.clock.advance(121)
    with pytest.raises(RelayError, match="expired"):
        Account.redeem_pairing(code)
    code2, pid2 = A.create_pairing_offer(SECRET)
    A.cancel_pairing(pid2)
    with pytest.raises(RelayError, match="already used or has expired"):
        Account.redeem_pairing(code2)


def test_offer_requires_the_key_a_server_and_an_unlocked_vault(tmp_path, relay):
    from iuk_browser.core.account import AccountError
    A = device(tmp_path, "a"); A.setup(USER, SECRET, relay.url)
    with pytest.raises(WrongKey):
        A.create_pairing_offer("wrong-key-wrong-key")
    N = device(tmp_path, "n"); N.setup(USER + "x", SECRET, "")
    with pytest.raises(AccountError, match="sync server"):
        N.create_pairing_offer(SECRET)
    A.lock()
    with pytest.raises(Locked):
        A.create_pairing_offer(SECRET)


def test_offer_codes_reject_damage_and_a_wrong_one_time_key(tmp_path, relay):
    from iuk_browser.core.account import AccountError
    A = device(tmp_path, "a"); A.setup(USER, SECRET, relay.url)
    code, pid = A.create_pairing_offer(SECRET)
    off = pairing.decode_offer(code)
    forged = pairing.encode_offer(off.server, off.pid, b"\x01" * 32)                 # right id, wrong one-time key
    with pytest.raises(AccountError, match="decrypted"):
        Account.redeem_pairing(forged)
    for bad in ["IUKB2:%%%", "IUKB1:abc", pairing.encode_offer("ftp://x", "a" * 32, b"k" * 32), pairing.encode_offer("https://x", "zz" * 16, b"k" * 32)]:
        with pytest.raises(pairing.PairingError):
            pairing.decode_offer(bad)
    assert pairing.kind("IUKB1:x") == "direct" and pairing.kind("hello") == ""


def test_locking_during_a_sync_never_leaves_decrypted_logins_behind(tmp_path, relay):
    from iuk_browser.core.account import Account
    from iuk_browser.core.bookmarks import BookmarkStore
    from iuk_browser.core.transport import Transport

    class LockingTransport(Transport):
        account = None
        def get_blob(self):
            r = super().get_blob()
            if LockingTransport.account is not None:
                LockingTransport.account.lock()           # the auto-lock timer fires while the relay call is in flight
            return r

    d = tmp_path / "a"
    A = Account(d, BookmarkStore(d / "b.json"), transport_factory=LockingTransport)
    A.setup(USER, SECRET, relay.url); A.save_login("a.com", "u", "secret-pw-123"); A.sync_now()
    LockingTransport.account = A
    from iuk_browser.core.account import Locked
    with pytest.raises(Locked, match="locked during sync"):
        A.sync_now()
    assert A.logins == {} and not A.is_unlocked()
    assert "secret-pw-123" not in repr(vars(A))
