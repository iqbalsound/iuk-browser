import base64
import io
import json
import subprocess
import sys
import urllib.request
from pathlib import Path

import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey

from iuk_browser import i18n
from iuk_browser.core import display, themes, updater as U
from iuk_browser.core.history import History
from iuk_browser.core.settings import Settings
from iuk_browser.core.urlutil import resolve
from iuk_browser.core.util import gen_password, host_from, host_matches

ROOT = Path(__file__).resolve().parent.parent


# ------------------------------------------------------------------ url / util
@pytest.mark.parametrize("text,expected", [
    ("example.com", "https://example.com"), ("https://a.b/c", "https://a.b/c"), ("localhost:8080", "http://localhost:8080"),
    ("127.0.0.1:3000/x", "http://127.0.0.1:3000/x"), ("192.168.1.1", "http://192.168.1.1"), ("[::1]:8080", "http://[::1]:8080"),
    ("about:blank", "about:blank"), ("view-source:https://x.com", "view-source:https://x.com"), ("", "about:blank"),
    ("hello world", "S:hello world"), ("python tutorial", "S:python tutorial"), ("3.14", "S:3.14"),
    ("javascript:alert(1)", "S:javascript:alert(1)"), ("mailto:a@b.c", "S:mailto:a@b.c"),
])
def test_address_bar_resolution(text, expected):
    assert resolve(text, lambda q: "S:" + q) == expected


def test_host_helpers_and_password_generator():
    assert host_from("https://www.Example.com/a?b") == "example.com"
    assert host_matches("example.com", "login.example.com") and not host_matches("example.com", "evilexample.com")
    for _ in range(100):
        p = gen_password(20)
        assert len(p) == 20 and any(c.islower() for c in p) and any(c.isupper() for c in p) and any(c.isdigit() for c in p) and any(not c.isalnum() for c in p)
    assert len(gen_password(2)) == 8 and len(gen_password(999)) == 128


# ------------------------------------------------------------------ display + themes
def test_display_css_matches_the_extensions_rules():
    assert display.css({"mode": "off"}, "x.com") == ""
    assert "invert(1) hue-rotate(180deg)" in display.css({"mode": "all"}, "x.com")
    assert "invert" in display.css({"mode": "sites", "sites": ["X.com"]}, "x.com")
    assert display.css({"mode": "sites", "sites": ["y.com"]}, "x.com") == ""
    assert "sepia(40%)" in display.css({"mode": "off", "sepia": 40}, "x.com")
    css = display.css({"mode": "all", "keepMedia": False}, "x.com")
    assert "img," not in css and "background:#fff" in css


def test_theme_palettes():
    d = themes.make_palette("#1c1b22", "#fbfbfe", "#00ddff")
    assert d["dark"] and d["on_accent"] == "#000000" and d["window"] == "#1c1b22"
    l = themes.make_palette("#fdf6e3", "#586e75", "#268bd2")
    assert not l["dark"] and l["on_accent"] == "#ffffff"
    assert themes.resolve({"id": "system"}) is None and themes.resolve(None) is None and themes.resolve({"id": "nope"}) is None
    assert themes.resolve({"id": "custom", "bg": "#000", "fg": "#fff", "accent": "#f00"})["dark"]
    assert len(themes.THEMES) == 7


# ------------------------------------------------------------------ history + settings
def test_history_add_search_suggest_clear(tmp_path):
    h = History(tmp_path / "h.sqlite")
    h.add("https://a.example/one", "Page One"); h.add("https://a.example/one", ""); h.add("https://b.example/", "Other")
    h.add("about:blank", "x"); h.add("javascript:alert(1)", "x")
    rows = h.search("")
    assert {r[0] for r in rows} == {"https://a.example/one", "https://b.example/"}
    one = next(r for r in rows if r[0].endswith("/one"))
    assert one[1] == "Page One" and one[3] == 2                       # empty title never overwrites a known one; visit counted twice
    assert h.suggest("page")[0] == "https://a.example/one"
    h.clear(); assert h.search("") == []


def test_settings_defaults_persist_and_search(tmp_path):
    p = tmp_path / "s.json"
    s = Settings(p)
    assert s["clipboard_clear_seconds"] == 30 and s["theme"] == {"id": "system"} and s["restore_session"] is True
    s.set("search_engine", "Google"); s.set("homepage", "https://example.org/")
    s2 = Settings(p)
    assert s2["search_engine"] == "Google" and s2.search_url("a b&c").endswith("search?q=a+b%26c")
    p.write_text("{not json")
    assert Settings(p)["language"] == "auto"                          # a damaged file never prevents start-up


# ------------------------------------------------------------------ translations
def test_every_catalog_is_complete_and_placeholders_match():
    sys.path.insert(0, str(ROOT / "tools"))
    import make_catalogs
    assert make_catalogs.problems(make_catalogs.load()) == []
    for lang in make_catalogs.LANGS:
        cat = json.loads((ROOT / "src" / "iuk_browser" / "i18n" / f"{lang}.json").read_text("utf-8"))
        assert len(cat) == len(make_catalogs.extract())
        i18n.set_language(lang)
        assert i18n.tr("Settings") == cat["Settings"] != "Settings"
        assert i18n.tr("Hides in {} s", 5).count("5") == 1 or "٥" in i18n.tr("Hides in {} s", 5)
    i18n.set_language("en")
    assert i18n.tr("Settings") == "Settings" and i18n.tr("Not a known string") == "Not a known string"


def test_language_detection_and_rtl(monkeypatch):
    for env, want in [("ur_PK.UTF-8", "ur"), ("ar_SA", "ar"), ("fr_FR.UTF-8", "fr"), ("zh_TW", "zh_CN"), ("pt_BR", "en"), ("de", "de")]:
        monkeypatch.setenv("IUK_LANG", env)
        assert i18n.detect() == want
    assert i18n.set_language("ar") == "ar" and i18n.is_rtl() and i18n.is_rtl("ur") and not i18n.is_rtl("fr")
    assert i18n.set_language("xx") == "en"
    i18n.set_language("en")


# ------------------------------------------------------------------ signed updates
def keypair():
    k = Ed25519PrivateKey.generate()
    raw = k.private_bytes(serialization.Encoding.Raw, serialization.PrivateFormat.Raw, serialization.NoEncryption())
    pub = k.public_key().public_bytes(serialization.Encoding.Raw, serialization.PublicFormat.Raw)
    return k, base64.b64encode(raw).decode(), base64.b64encode(pub).decode()


def test_version_ordering():
    assert U.is_newer("2.1.1", "2.1.0") and U.is_newer("2.2.0", "2.1.9") and U.is_newer("3.0.0", "2.99.99")
    assert not U.is_newer("2.1.0", "2.1.0") and not U.is_newer("2.0.9", "2.1.0")
    assert U.is_newer("2.1.0", "2.1.0-beta.2") and not U.is_newer("2.1.0-beta.2", "2.1.0")
    with pytest.raises(U.UpdateError):
        U.parse_version("banana")


def build_manifest(tmp_path, version="2.2.0", channel="stable"):
    k, priv, pub = keypair()
    assets = tmp_path / "assets"; assets.mkdir()
    (assets / f"iuk-browser-{version}-setup.exe").write_bytes(b"MZ-fake-installer")
    notes = tmp_path / "n.md"; notes.write_text("- new things")
    out = tmp_path / "site"
    env = {"UPDATE_SIGNING_KEY": priv, "PATH": "/usr/bin:/bin"}
    r = subprocess.run([sys.executable, str(ROOT / "packaging/tools/make_update_manifest.py"), "--version", version, "--channel", channel,
                        "--assets", str(assets), "--out", str(out), "--download-base", "https://dl.example/v" + version,
                        "--page", "https://example.org/release", "--notes-file", str(notes)], env=env, capture_output=True, text=True)
    assert r.returncode == 0, r.stderr
    return out, pub


def test_manifest_tool_and_updater_check_roundtrip(tmp_path):
    out, pub = build_manifest(tmp_path)
    fetch = lambda url: (out / url.rsplit("/", 1)[1]).read_bytes()
    u = U.Updater("https://updates.example/update", [pub], current="2.1.0", fetch=fetch)
    info = u.check()
    assert info.version == "2.2.0" and info.notes == "- new things"
    if U.platform_key() == "windows-x64":
        assert info.kind == "installer" and len(info.sha256) == 64 and info.url.startswith("https://dl.example/")
    else:
        assert info.kind == "page"
    assert U.Updater("https://u/x", [pub], current="2.2.0", fetch=fetch).check() is None            # already current
    assert U.Updater("https://u/x", [pub], current="3.0.0", fetch=fetch).check() is None            # never downgrade


def test_updates_are_rejected_when_forged_or_misconfigured(tmp_path):
    out, pub = build_manifest(tmp_path)
    fetch = lambda url: (out / url.rsplit("/", 1)[1]).read_bytes()
    _, _, other_pub = keypair()
    with pytest.raises(U.UpdateError, match="not valid"):
        U.Updater("https://u/x", [other_pub], current="2.1.0", fetch=fetch).check()                  # signed by someone else
    tampered = json.loads((out / "stable.json").read_bytes()); tampered["version"] = "9.9.9"
    bad = {"stable.json": json.dumps(tampered).encode(), "stable.json.sig": (out / "stable.json.sig").read_bytes()}
    with pytest.raises(U.UpdateError, match="not valid"):
        U.Updater("https://u/x", [pub], current="2.1.0", fetch=lambda url: bad[url.rsplit("/", 1)[1]]).check()   # body changed after signing
    with pytest.raises(U.UpdateError, match="No update signing keys"):
        U.Updater("https://u/x", [], current="2.1.0", fetch=fetch).check()
    with pytest.raises(U.UpdateError, match="different channel"):
        U.Updater("https://u/x", [pub], current="2.1.0", channel="beta",
                  fetch=lambda url: (out / url.rsplit("/", 1)[1].replace("beta", "stable")).read_bytes()).check()
    r = subprocess.run([sys.executable, str(ROOT / "packaging/tools/make_update_manifest.py"), "--version", "1", "--assets", str(tmp_path),
                        "--out", str(tmp_path / "o"), "--download-base", "x", "--page", "y"], env={"PATH": "/usr/bin:/bin"}, capture_output=True, text=True)
    assert r.returncode == 2 and "unsigned" in r.stderr                                             # CI cannot publish unsigned manifests


def test_download_verifies_sha256_and_requires_https(tmp_path, monkeypatch):
    payload = b"installer-bytes" * 1000
    import hashlib
    good = hashlib.sha256(payload).hexdigest()

    class Resp(io.BytesIO):
        headers = {"Content-Length": str(len(payload))}
        def __enter__(self): return self
        def __exit__(self, *a): return False
    monkeypatch.setattr(urllib.request, "urlopen", lambda req, timeout=0: Resp(payload))
    u = U.Updater("https://u/x", ["k"])
    info = U.UpdateInfo("9.9.9", "", "https://dl.example/iuk-9.9.9-setup.exe", good, len(payload), "stable", "installer")
    seen = []
    p = u.download(info, tmp_path, progress=lambda d, t: seen.append((d, t)))
    assert p.read_bytes() == payload and seen[-1] == (len(payload), len(payload))
    info.sha256 = "0" * 64
    with pytest.raises(U.UpdateError, match="checksum"):
        u.download(info, tmp_path)
    assert not (tmp_path / "iuk-9.9.9-setup.exe").exists()                                          # a bad download is deleted
    with pytest.raises(U.UpdateError, match="non-HTTPS"):
        u.download(U.UpdateInfo("9.9.9", "", "http://dl.example/x.exe", good, 1, "stable", "installer"), tmp_path)
    with pytest.raises(U.UpdateError, match="package manager"):
        u.download(U.UpdateInfo("9.9.9", "", "https://x", "", 0, "stable", "page"), tmp_path)


def test_run_installer_is_windows_only(tmp_path):
    if not sys.platform.startswith("win"):
        with pytest.raises(U.UpdateError):
            U.run_installer(tmp_path / "x.exe")


# ------------------------------------------------------------------ translation review round trip
def test_translation_review_export_and_safe_import(tmp_path):
    import csv, shutil
    sys.path.insert(0, str(ROOT / "tools"))
    import review_translations as RT
    out = RT.export("fr", tmp_path / "fr.csv")
    rows = list(csv.DictReader(out.open(encoding="utf-8-sig", newline="")))
    assert len(rows) >= 219 and set(rows[0]) == {"english", "current", "corrected", "note"}
    assert all(r["corrected"] == "" for r in rows)
    tsv = tmp_path / "translations.tsv"; shutil.copy(RT.TSV, tsv)

    for r in rows:                                                          # a reviewer fixes two cells
        if r["english"] == "Settings":
            r["corrected"] = "Réglages"
        if r["english"] == "Hides in {} s":
            r["corrected"] = "Masqué dans {} s"
    good = tmp_path / "good.csv"
    with good.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    res = RT.import_review("fr", good, tsv)
    assert res == {"changed": 2, "accepted": 2}
    text = tsv.read_text("utf-8")
    assert "Settings | ٹھیک" not in text and " | Réglages | " in text and "Masqué dans {} s" in text

    for r in rows:                                                          # a correction that loses a placeholder is refused
        if r["english"] == "Hides in {} s":
            r["corrected"] = "Masqué bientôt"
    bad = tmp_path / "bad.csv"
    with bad.open("w", encoding="utf-8-sig", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0])); w.writeheader(); w.writerows(rows)
    before = tsv.read_text("utf-8")
    with pytest.raises(SystemExit, match="placeholder"):
        RT.import_review("fr", bad, tsv)
    assert tsv.read_text("utf-8") == before                                 # nothing was written
