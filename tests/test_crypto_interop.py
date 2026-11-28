"""The Python core must be byte-compatible with the Firefox extension (same accounts, same data)."""
import pytest

from iuk_browser.core import crypto, merge as M, pairing
from conftest import PROD_PARAMS


def test_known_answer_matches_extension_and_reference_argon2(golden):
    crypto.PARAMS.update(PROD_PARAMS)
    assert PROD_PARAMS == {"memory_kib": 65536, "passes": 3, "lanes": 1}
    keys = crypto.derive_keys(golden["user"], golden["secret"])
    assert keys.token == golden["token"] == "5f0dac10d64f3e189dcb1df547cd32ddd7bcc834d51ae789cffac5f7eb21be0b"
    assert keys.kdf == "argon2id-v2"


def test_decrypts_a_blob_written_by_the_extension(golden):
    crypto.PARAMS.update(PROD_PARAMS)
    keys = crypto.derive_keys(golden["user"], golden["secret"])
    doc = crypto.decrypt(keys.key, golden["blob"])
    assert doc == golden["doc"]                                  # including non-ASCII ("Ä", "pw-ü")
    v2 = M.normalize(doc)                                        # a v1 document from the extension becomes v2
    assert v2["logins"]["a.com|me"]["password"] == "pw-ü"
    assert [b["title"] for b in v2["bookmarks"].values()] == ["Ä"]
    assert list(v2["folders"].values())[0]["name"] == "News"


def test_roundtrip_wrong_key_and_tampering():
    k1, k2 = crypto.derive_keys("a@x.com", "secret-number-one"), crypto.derive_keys("a@x.com", "secret-number-two")
    blob = crypto.encrypt(k1.key, {"hello": "wörld"})
    assert blob.startswith("v1.") and blob.count(".") == 2
    assert crypto.decrypt(k1.key, blob) == {"hello": "wörld"}
    with pytest.raises(crypto.DecryptError):
        crypto.decrypt(k2.key, blob)
    with pytest.raises(crypto.DecryptError):
        crypto.decrypt(k1.key, blob[:-4] + "AAAA")
    with pytest.raises(crypto.DecryptError):
        crypto.decrypt(k1.key, "v2.x.y")
    assert k1.token != k2.token and len(k1.token) == 64
    assert crypto.derive_keys(" A@X.com ", "secret-number-one").token == k1.token   # user name is normalised


def test_pairing_code_is_identical_to_the_extensions(golden):
    i = golden["pairing_input"]
    assert pairing.encode(i["u"], i["k"], i["s"]) == golden["pairing_code"]
    p = pairing.decode(golden["pairing_code"])
    assert (p.username, p.secret, p.server) == (i["u"], i["k"], i["s"])


@pytest.mark.parametrize("text,msg", [
    ("hello", "not an IUK"), ("IUKB1:%%%", "damaged"),
    (pairing.encode("a", "short"), "incomplete"),
    (pairing.encode("a@b.c", "k" * 12, "javascript:alert(1)"), "invalid server"),
])
def test_pairing_rejects_bad_codes(text, msg):
    with pytest.raises(pairing.PairingError, match=msg):
        pairing.decode(text)


def test_pairing_unicode_roundtrip():
    assert pairing.decode(pairing.encode("ü@x.com", "k" * 12)).username == "ü@x.com"
