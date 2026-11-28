"""Whole-application smoke tests: a real window with real WebEngine pages (headless)."""
import pytest
from PySide6.QtWidgets import QApplication

from iuk_browser import i18n
from iuk_browser.app import AppContext
from webhelpers import js, load, wait_until


@pytest.fixture
def ctx(qapp, tmp_path):
    c = AppContext(qapp, tmp_path / "profile")
    c.clipboard.interval_override_ms = 200
    yield c
    for w in list(c.windows):
        w.close()
    c.account.lock()


def open_window(ctx, qtbot, url, private=False, register=True):
    w = ctx.new_window(private=private, urls=[url])
    if register:                      # tests that close the window themselves must not let pytest-qt close it a second time
        qtbot.addWidget(w)
    v = w.current()
    assert wait_until(lambda: v.url().toString().startswith("http"), 15000)
    assert wait_until(lambda: not v.isLoading() if hasattr(v, "isLoading") else True, 15000)
    return w, v


def test_window_opens_loads_page_and_records_history(ctx, site, qtbot):
    w, v = open_window(ctx, qtbot, site.base + "/plain")
    assert wait_until(lambda: v.title() == "Plain", 15000)
    assert w.windowTitle().startswith("Plain")
    assert wait_until(lambda: bool(ctx.history.search("plain")), 8000)
    assert w.tabs.count() == 1 and w.a_back.isEnabled() is False


def test_tabs_navigation_and_address_bar(ctx, site, qtbot):
    w, v = open_window(ctx, qtbot, site.base + "/plain")
    w.navigate(site.base + "/login")
    assert wait_until(lambda: v.title() == "Login page", 15000)
    assert wait_until(lambda: w.a_back.isEnabled(), 5000)
    w.add_tab(site.base + "/plain")
    assert w.tabs.count() == 2
    assert wait_until(lambda: w.current().title() == "Plain", 15000)
    w.close_tab(1)
    assert w.tabs.count() == 1
    # typed text becomes a search
    assert w.ctx.settings.search_url("a b").startswith("https://duckduckgo.com/?q=a+b")


def test_private_window_uses_the_off_the_record_profile_and_skips_history(ctx, site, qtbot):
    w, v = open_window(ctx, qtbot, site.base + "/plain", private=True)
    assert w.private and v.page().profile().isOffTheRecord()
    assert "Private" in w.windowTitle()
    qtbot.wait(800)
    assert ctx.history.search("plain") == []


def test_bookmark_add_edit_and_star_state(ctx, site, qtbot, monkeypatch):
    from iuk_browser.ui import mainwindow
    w, v = open_window(ctx, qtbot, site.base + "/plain")
    assert wait_until(lambda: v.title() == "Plain", 15000)
    url = v.url().toString()

    class FakeDialog:
        def __init__(self, store, parent=None, item=None, url="", title="", folder=None):
            self.t = title
        def exec(self): return True
        def values(self): return (url, self.t, "root:toolbar", ["demo", "docs"])
    monkeypatch.setattr(mainwindow, "BookmarkEditDialog", FakeDialog)
    w.toggle_bookmark()
    it = ctx.store.by_url(url)
    assert it and it["title"] == "Plain" and ctx.store.tags_of(it) == ["demo", "docs"]
    assert w.a_star.text() == "Edit bookmark"


def test_fill_login_end_to_end_with_vault(ctx, site, qtbot):
    ctx.account.setup("me@x.com", "my-secret-connect-key", "")
    ctx.account.save_login("127.0.0.1", "alice", "pa55w0rd-xyz")
    w, v = open_window(ctx, qtbot, site.base + "/login")
    assert wait_until(lambda: v.title() == "Login page", 15000)
    w.fill_login()
    assert wait_until(lambda: js(v, "document.getElementById('p').value") == "pa55w0rd-xyz", 8000)
    assert js(v, "document.getElementById('u').value") == "alice"


def test_save_password_prompt_flow(ctx, site, qtbot):
    ctx.account.setup("me@x.com", "my-secret-connect-key", "")
    w, v = open_window(ctx, qtbot, site.base + "/login")
    assert wait_until(lambda: v.title() == "Login page", 15000)
    js(v, "document.getElementById('u').value='newuser'; document.getElementById('p').value='brand-new-pw'; document.getElementById('go').click(); 1")
    assert wait_until(lambda: w.infobar.isVisible() or not w.infobar.isHidden(), 6000)
    assert "newuser" in w.info_label.text() and "127.0.0.1" in w.info_label.text()
    w.info_btn1.click()                                         # "Save"
    assert ctx.account.get_password("127.0.0.1|newuser") == "brand-new-pw"
    assert w.infobar.isHidden()


def test_no_prompt_for_already_saved_password(ctx, site, qtbot):
    ctx.account.setup("me@x.com", "my-secret-connect-key", "")
    ctx.account.save_login("127.0.0.1", "same", "same-pw-123")
    w, v = open_window(ctx, qtbot, site.base + "/login")
    assert wait_until(lambda: v.title() == "Login page", 15000)
    js(v, "document.getElementById('u').value='same'; document.getElementById('p').value='same-pw-123'; document.getElementById('go').click(); 1")
    qtbot.wait(1800)
    assert w.infobar.isHidden()


def test_clipboard_is_cleared_automatically_but_never_someone_elses_text(ctx, qtbot):
    cb = QApplication.clipboard()
    ctx.clipboard.copy_secret("s3cr3t-value")
    assert cb.text() == "s3cr3t-value"
    assert wait_until(lambda: cb.text() == "", 3000)
    ctx.clipboard.copy_secret("another-secret")
    cb.setText("something the user copied later")
    qtbot.wait(500)
    assert cb.text() == "something the user copied later"
    ctx.clipboard.interval_override_ms = None
    ctx.settings.data["clipboard_clear_seconds"] = 0
    ctx.clipboard.copy_secret("never-cleared")
    qtbot.wait(300)
    assert cb.text() == "never-cleared"
    assert ctx.clipboard.clear_now() is True and cb.text() == ""


def test_theme_and_invert_settings_apply_everywhere(ctx, site, qtbot):
    w, v = open_window(ctx, qtbot, site.base + "/plain")
    assert wait_until(lambda: v.title() == "Plain", 15000)
    ctx.apply_settings({"theme": {"id": "dark"}, "display": {"mode": "all", "sites": [], "brightness": 100, "contrast": 100, "sepia": 0, "keepMedia": True}})
    assert QApplication.instance().palette().window().color().name() == "#1c1b22"
    assert wait_until(lambda: "invert" in js(v, "getComputedStyle(document.documentElement).filter"), 8000)
    assert w.a_invert.isChecked()
    ctx.apply_settings({"theme": {"id": "system"}, "display": {"mode": "off", "sites": [], "brightness": 100, "contrast": 100, "sepia": 0, "keepMedia": True}})
    assert wait_until(lambda: js(v, "getComputedStyle(document.documentElement).filter") == "none", 8000)


def test_session_is_restored_for_normal_windows(ctx, site, qtbot):
    w, v = open_window(ctx, qtbot, site.base + "/plain", register=False)
    w.add_tab(site.base + "/login")
    qtbot.wait(500)
    w.close()
    assert ctx.settings["session_urls"] == [site.base + "/plain", site.base + "/login"]
    w2 = ctx.new_window()
    qtbot.addWidget(w2)
    assert w2.tabs.count() == 2


def test_rtl_languages_flip_the_layout_and_strings_fall_back_to_english(ctx):
    i18n.set_language("ar")
    assert i18n.is_rtl() and i18n.tr("Unknown string {}", 1) == "Unknown string 1"
    i18n.set_language("en")
    assert not i18n.is_rtl()


def test_auto_lock_after_inactivity_and_activity_postpones_it(ctx, site, qtbot):
    from PySide6.QtCore import Qt
    from PySide6.QtTest import QTest
    ctx.account.setup("me@x.com", "my-secret-connect-key", "")
    w, v = open_window(ctx, qtbot, site.base + "/plain")
    ctx.auto_lock_override_ms = 700
    locked = []
    ctx.auto_locked.connect(locked.append)
    ctx.clipboard.interval_override_ms = 60000
    ctx.clipboard.copy_secret("password-on-clipboard")
    ctx.touch()
    for _ in range(5):                                         # typing keeps the vault open for >2 s in total
        QTest.qWait(300)
        QTest.keyClick(w, Qt.Key.Key_Shift)
        assert ctx.account.is_unlocked()
    assert wait_until(lambda: not ctx.account.is_unlocked(), 5000)    # then it locks by itself
    assert locked == [15]
    assert QApplication.clipboard().text() != "password-on-clipboard"  # and the copied secret is wiped too
    assert w.a_unlock.isVisible() or not w.a_lock.isVisible()
    assert "locked" in w.statusBar().currentMessage().lower()
    ctx.account.unlock("me@x.com", "my-secret-connect-key")            # unlocking re-arms the timer
    ctx.touch()
    assert wait_until(lambda: not ctx.account.is_unlocked(), 5000)


def test_auto_lock_never_setting_disables_the_timer(ctx, qtbot):
    ctx.account.setup("me@x.com", "my-secret-connect-key", "")
    ctx.apply_settings({"auto_lock_minutes": 0})
    ctx.touch()
    assert not ctx._lock_timer.isActive()
    ctx.apply_settings({"auto_lock_minutes": 5})
    ctx.touch()
    assert ctx._lock_timer.isActive() and ctx._lock_timer.interval() == 5 * 60 * 1000


def test_set_default_browser_uses_xdg_settings_or_windows_settings(ctx, monkeypatch):
    import subprocess
    import sys as _sys
    calls = []

    class R:
        returncode = 0
    monkeypatch.setattr("shutil.which", lambda name: "/usr/bin/xdg-settings")
    monkeypatch.setattr(subprocess, "run", lambda cmd, **k: (calls.append(cmd), R())[1])
    monkeypatch.setattr(_sys, "platform", "linux")
    assert ctx.set_default_browser() == "done"
    assert calls == [["xdg-settings", "set", "default-web-browser", "iuk-browser.desktop"]]
    R.returncode = 3
    assert ctx.set_default_browser() == "failed"
    monkeypatch.setattr("shutil.which", lambda name: None)
    assert ctx.set_default_browser() == "failed"
    opened = []
    from PySide6.QtGui import QDesktopServices
    monkeypatch.setattr(QDesktopServices, "openUrl", staticmethod(lambda u: opened.append(u.toString())))
    monkeypatch.setattr(_sys, "platform", "win32")
    assert ctx.set_default_browser() == "settings" and opened == ["ms-settings:defaultapps"]
