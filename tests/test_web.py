import json

import pytest
from PySide6.QtCore import QUrl

from iuk_browser.core import display
from iuk_browser.core.settings import Settings
from iuk_browser.ui.web import ProfileManager, WebView
from webhelpers import js, load, wait_until


@pytest.fixture
def pm(qapp, tmp_path):
    return ProfileManager(tmp_path / "data", Settings(tmp_path / "settings.json"), qapp)


def test_scripts_installed_in_both_profiles(pm):
    for p in pm.profiles():
        names = {s.name() for s in p.scripts().toList()}
        assert {"iuk-autofill", "iuk-display"} <= names
    assert pm.private.isOffTheRecord() and not pm.normal.isOffTheRecord()


def test_autofill_fills_user_and_password_and_page_cannot_see_the_bridge(pm, site, qtbot):
    v = WebView(pm.normal); qtbot.addWidget(v)
    load(v, site.base + "/login")
    assert js(v, "document.title") == "Login page"
    assert js(v, "window.__iukHasLoginForm()", app_world=True) is True
    v.fill('alice@x.com', 's3"cret\\\'<>')
    assert wait_until(lambda: js(v, "document.getElementById('p').value") != "")
    assert js(v, "document.getElementById('u').value") == "alice@x.com"
    assert js(v, "document.getElementById('p').value") == 's3"cret\\\'<>'
    # isolated world: the page's own scripts cannot reach the autofill code or the Qt bridge
    assert js(v, "typeof window.__iukFill + '|' + typeof window.QWebChannel + '|' + typeof (window.qt && window.qt.webChannelTransport)") == "undefined|undefined|undefined"


def test_submitted_credentials_are_captured_with_the_trusted_url(pm, site, qtbot):
    v = WebView(pm.normal); qtbot.addWidget(v)
    got = []
    v.captured_cb = lambda view: got.append(view.pending)
    load(v, site.base + "/login")
    js(v, "document.getElementById('u').value='bob'; document.getElementById('p').value='pw-123'; document.getElementById('go').click(); 1")
    assert wait_until(lambda: bool(got))
    host, user, pw, _ = got[0]
    assert (host, user, pw) == ("127.0.0.1", "bob", "pw-123")


def test_private_view_never_records_credentials(pm, site, qtbot):
    v = WebView(pm.private, private=True); qtbot.addWidget(v)
    got = []
    v.captured_cb = lambda view: got.append(1)
    load(v, site.base + "/login")
    js(v, "document.getElementById('p').value='pw'; document.getElementById('go').click(); 1")
    qtbot.wait(600)
    assert not got and v.pending is None


def test_color_invert_matches_the_python_css_and_updates_live(pm, site, qtbot):
    v = WebView(pm.normal); qtbot.addWidget(v)
    load(v, site.base + "/plain")
    assert js(v, "getComputedStyle(document.documentElement).filter") == "none"
    s = {"mode": "all", "brightness": 90, "contrast": 110, "sepia": 20}
    pm.update_display(s)
    load(v, site.base + "/plain")                                          # new page: script injected at document creation
    css = js(v, "document.getElementById('iuk-display-style').textContent")
    assert css == display.css(s, "127.0.0.1")
    f = js(v, "getComputedStyle(document.documentElement).filter")
    assert "invert(1)" in f and "hue-rotate(180deg)" in f and "brightness(0.9)" in f and "sepia(0.2)" in f
    v.apply_display({"mode": "off"})                                       # live update without reload
    assert wait_until(lambda: js(v, "getComputedStyle(document.documentElement).filter") == "none")
    v.apply_display({"mode": "sites", "sites": ["127.0.0.1"]})
    assert wait_until(lambda: "invert" in js(v, "getComputedStyle(document.documentElement).filter"))
    v.apply_display({"mode": "sites", "sites": ["other.example"]})
    assert wait_until(lambda: js(v, "getComputedStyle(document.documentElement).filter") == "none")


def test_images_stay_natural_when_inverted(pm, site, qtbot):
    pm.update_display({"mode": "all", "keepMedia": True})
    v = WebView(pm.normal); qtbot.addWidget(v)
    load(v, site.base + "/login")
    assert "invert(1)" in js(v, "getComputedStyle(document.getElementById('img')).filter")
    pm.update_display({"mode": "all", "keepMedia": False})
    load(v, site.base + "/login")
    assert js(v, "getComputedStyle(document.getElementById('img')).filter") == "none"


def test_display_script_source_embeds_normalized_settings():
    from iuk_browser.ui.web import display_source
    src = display_source({"mode": "sites", "sites": ["A.com"]})
    assert '"mode": "sites"' in src and '"a.com"' in src and "/*SETTINGS*/" not in src
