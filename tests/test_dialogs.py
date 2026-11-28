import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QApplication, QFileDialog, QInputDialog, QMessageBox

from iuk_browser.app import AppContext
from iuk_browser.core import merge as M, pairing
from iuk_browser.core.transport import Transport
from iuk_browser.ui import dialogs, qrtools, settings_dialog
from test_relay import totp_now
from webhelpers import wait_until

USER, SECRET = "me@x.com", "my-secret-connect-key"


@pytest.fixture
def ctx(qapp, tmp_path):
    c = AppContext(qapp, tmp_path / "profile")
    yield c
    c.clipboard.clear_now()
    c.account.lock()


@pytest.fixture
def ready(ctx, relay):
    ctx.account.setup(USER, SECRET, relay.url)
    ctx.settings.data["sync_server"] = relay.url
    return ctx


def test_qr_roundtrip_is_decodable(qapp):
    code = pairing.encode(USER, "abcdefghijklmnopqrstuvwxyz123456", "https://sync.example.com")
    pm = qrtools.qr_pixmap(code, 320)
    assert qrtools.decode_qimage(pm.toImage()) == code
    assert qrtools.decode_qimage(qrtools.qr_pixmap("hello", 100).toImage()) == "hello"


def test_setup_dialog_creates_account_and_joins_existing_with_second_factor(ctx, relay, qtbot, tmp_path):
    d = dialogs.SetupDialog(ctx); qtbot.addWidget(d); d.show()
    d.user.setText(USER); d.secret.setText("short")
    d.ok.accepted.emit()
    assert wait_until(lambda: "12 characters" in d.status.text(), 8000)
    d.secret.setText(SECRET); d.server.setText(relay.url)
    d.ok.accepted.emit()
    assert wait_until(lambda: ctx.account.is_unlocked(), 15000)
    assert wait_until(lambda: ctx.settings["sync_server"] == relay.url, 8000)

    # relay gets a second factor; a new device must be asked for the code
    t = ctx.account.twofa(); enr = t.enroll(); t.confirm(totp_now(enr["secret"], relay.clock))
    ctx2 = AppContext(ctx.qapp, tmp_path / "second")
    d2 = dialogs.SetupDialog(ctx2); qtbot.addWidget(d2); d2.show()
    d2.user.setText(USER); d2.secret.setText(SECRET); d2.server.setText(relay.url)
    d2.ok.accepted.emit()
    assert wait_until(lambda: not d2.otp.isHidden(), 15000)
    relay.clock.advance(30)
    d2.otp.setText(totp_now(enr["secret"], relay.clock))
    d2.ok.accepted.emit()
    assert wait_until(lambda: ctx2.account.is_unlocked(), 15000)


def test_unlock_dialog_wrong_and_right_key(ctx, qtbot):
    ctx.account.setup(USER, SECRET, ""); ctx.account.lock()
    d = dialogs.UnlockDialog(ctx); qtbot.addWidget(d); d.show()
    d.secret.setText("not-the-right-key!!")
    d.ok.accepted.emit()
    assert wait_until(lambda: "Wrong" in d.status.text(), 15000) and not ctx.account.is_unlocked()
    d.secret.setText(SECRET)
    d.ok.accepted.emit()
    assert wait_until(lambda: ctx.account.is_unlocked(), 15000)


def test_pair_dialog_show_and_scan_between_two_devices(ready, relay, qtbot, tmp_path, monkeypatch):
    ready.account.save_login("github.com", "iqbal", "pw-qr-pw-qr"); ready.account.sync_now()
    d = dialogs.PairDialog(ready, mode="show"); qtbot.addWidget(d); d.show()
    assert d.one_time
    d.show_secret.setText("wrong-key-wrong-key"); d.show_btn.click()
    assert wait_until(lambda: "not the secret key" in d.show_status.text(), 15000)
    d.show_secret.setText(SECRET); d.show_btn.click()
    assert wait_until(lambda: not d.qr_label.pixmap().isNull(), 15000)
    shown = qrtools.decode_qimage(d.qr_label.pixmap().toImage())
    assert shown.startswith("IUKB2:") and SECRET not in shown and USER not in shown          # the QR never carries the account key
    assert d.copy_btn.isVisible() and d._pid

    # the new device scans the saved QR image, redeems it (once), confirms and joins
    img = tmp_path / "qr.png"; qrtools.qr_pixmap(shown, 400).save(str(img))
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(img), "")))
    got = []
    s = dialogs.PairDialog(AppContext(ready.qapp, tmp_path / "newdev"), mode="scan"); qtbot.addWidget(s); s.show()
    s.paired.connect(got.append)
    s._from_image()
    assert wait_until(lambda: s.confirm_box.layout().count() == 2, 8000)
    assert USER in s.confirm_box.layout().itemAt(0).widget().text()
    s.confirm_box.layout().itemAt(1).widget().click()
    assert got and (got[0].username, got[0].secret) == (USER, SECRET)

    # the showing device notices the pairing happened and withdraws the QR by itself
    d._left = 4                                                                              # next tick polls the relay
    assert wait_until(lambda: d.qr_label.pixmap() is None or d.qr_label.pixmap().isNull(), 8000)
    assert "Paired" in d.show_status.text() and d._code == ""

    # scanning the same QR again (a screenshot) no longer works
    s2 = dialogs.PairDialog(AppContext(ready.qapp, tmp_path / "thief"), mode="scan"); qtbot.addWidget(s2); s2.show()
    s2.offer(shown)
    assert wait_until(lambda: "already used" in s2.scan_status.text(), 8000)
    assert s2.confirm_box.layout().count() == 0
    # a pasted code works too; bad ones are explained
    s3 = dialogs.PairDialog(ready, mode="scan"); qtbot.addWidget(s3)
    s3.offer("IUKB1:%%%"); assert "damaged" in s3.scan_status.text()
    s3.offer("hello"); assert "not an IUK Browser pairing code" in s3.scan_status.text()


def test_pair_dialog_closing_withdraws_the_qr_and_expiry_hides_it(ready, relay, qtbot):
    d = dialogs.PairDialog(ready, mode="show"); qtbot.addWidget(d); d.show()
    d.show_secret.setText(SECRET); d.show_btn.click()
    assert wait_until(lambda: not d.qr_label.pixmap().isNull(), 15000)
    pid = d._pid
    assert Transport(relay.url, ready.account._keys.token).pair_pending(pid) is True
    d.close()                                                                                # closing the window withdraws the offer
    assert wait_until(lambda: Transport(relay.url, ready.account._keys.token).pair_pending(pid) is False, 8000)
    d2 = dialogs.PairDialog(ready, mode="show"); qtbot.addWidget(d2); d2.show()
    d2.show_secret.setText(SECRET); d2.show_btn.click()
    assert wait_until(lambda: not d2.qr_label.pixmap().isNull(), 15000)
    d2._left = 1
    assert wait_until(lambda: d2.qr_label.pixmap() is None or d2.qr_label.pixmap().isNull(), 6000)
    assert d2._code == "" and "hidden" in d2.show_status.text()


def test_pair_dialog_without_a_server_falls_back_to_the_direct_code(ctx, qtbot):
    ctx.account.setup(USER, SECRET, "")
    d = dialogs.PairDialog(ctx, mode="show"); qtbot.addWidget(d); d.show()
    assert not d.one_time
    d.show_secret.setText(SECRET); d.show_btn.click()
    assert wait_until(lambda: not d.qr_label.pixmap().isNull(), 15000)
    assert qrtools.decode_qimage(d.qr_label.pixmap().toImage()).startswith("IUKB1:")        # compatible with the 1.x extension


def test_setup_and_unlock_can_be_cancelled_before_anything_is_stored(ctx, qtbot):
    from iuk_browser.core import crypto
    crypto.PARAMS.update({"memory_kib": 65536, "passes": 3, "lanes": 1})                   # slow enough to cancel in time
    d = dialogs.SetupDialog(ctx); qtbot.addWidget(d); d.show()
    d.user.setText(USER); d.secret.setText(SECRET)
    d.ok.accepted.emit()
    assert d.progress.isVisible() and not d.ok.isEnabled()
    d.reject()                                                                               # Cancel while deriving
    assert "Cancelled" in d.status.text() and d.ok.isEnabled() and not d.progress.isVisible()
    qtbot.wait(2500)                                                                         # the worker finishes in the background ...
    assert not ctx.account.is_setup() and not ctx.account.is_unlocked()                      # ... but stored nothing
    assert d.isVisible()                                                                     # first Cancel only stops the work
    d.reject()
    assert not d.isVisible()

    crypto.PARAMS.update({"memory_kib": 256, "passes": 1, "lanes": 1})
    ctx.account.setup(USER, SECRET, ""); ctx.account.lock()
    crypto.PARAMS.update({"memory_kib": 65536, "passes": 3, "lanes": 1})
    u = dialogs.UnlockDialog(ctx); qtbot.addWidget(u); u.show()
    u.secret.setText(SECRET); u.ok.accepted.emit(); u.reject()
    qtbot.wait(2500)
    assert not ctx.account.is_unlocked() and "Cancelled" in u.status.text()


def test_two_factor_dialog_enable_confirm_recovery_codes_disable(ready, relay, qtbot):
    d = dialogs.TwoFactorDialog(ready); qtbot.addWidget(d); d.show()
    assert wait_until(lambda: d.body.count() == 1 and "Turn on" in d.body.itemAt(0).widget().text(), 10000)
    d.body.itemAt(0).widget().click()
    assert wait_until(lambda: d.body.count() == 4, 10000)
    secret = d.body.itemAt(1).widget().text()
    d.code.setText(totp_now(secret, relay.clock))
    d.body.itemAt(3).widget().click()
    assert wait_until(lambda: d.body.count() == 1 and d.body.itemAt(0).widget().toPlainText().count("-") == 8, 10000)
    assert Transport(relay.url, ready.account._keys.token).twofa_status() is True
    ready.account.sync_now()                                          # the session created at confirm still works
    d2 = dialogs.TwoFactorDialog(ready); qtbot.addWidget(d2); d2.show()
    assert wait_until(lambda: d2.body.count() == 2, 10000)
    relay.clock.advance(30)
    d2.code.setText(totp_now(secret, relay.clock))
    d2.body.itemAt(1).widget().click()
    assert wait_until(lambda: Transport(relay.url, ready.account._keys.token).twofa_status() is False, 10000)


def test_vault_dialog_add_edit_delete_copy_and_csv(ready, qtbot, monkeypatch, tmp_path):
    class Fake:
        queue = []
        def __init__(self, *a, **k): pass
        def exec(self): return True
        def values(self): return Fake.queue.pop(0)
    monkeypatch.setattr(dialogs, "LoginEditDialog", Fake)
    d = dialogs.VaultDialog(ready); qtbot.addWidget(d); d.show()
    Fake.queue = [("https://www.example.com/login", "ann", "pw-ann-123", "work")]
    d.add()
    assert d.table.rowCount() == 1 and d.table.item(0, 0).text() == "example.com"
    d.table.selectRow(0)
    Fake.queue = [("example.com", "ann", "pw-changed-456", "work")]
    d.edit()
    assert ready.account.get_password("example.com|ann") == "pw-changed-456"
    d.copy_pw()
    assert QApplication.clipboard().text() == "pw-changed-456" and "cleared" in d.hint.text()
    d.search.setText("zzz"); assert d.table.rowCount() == 0
    d.search.setText("")
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    out = tmp_path / "pw.csv"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    d.export_csv()
    assert "pw-changed-456" in out.read_text()
    d.table.selectRow(0); d.delete()
    assert d.table.rowCount() == 0
    monkeypatch.setattr(QFileDialog, "getOpenFileName", staticmethod(lambda *a, **k: (str(out), "")))
    d.import_csv()
    assert d.table.rowCount() == 1 and "Imported 1" in d.hint.text()


def test_bookmarks_dialog_tree_tags_folders_and_recovery(ready, qtbot, monkeypatch):
    st = ready.store
    f = st.add_folder("Reading"); g = st.add_folder("Python", f)
    st.add_bookmark("https://a.example/", "Alpha", f, ["lang"])
    st.add_bookmark("https://b.example/", "Beta", g, ["lang", "docs"])
    st.add_bookmark("https://c.example/", "Gamma")
    st.add_bookmark("https://lost.example/", "Lost", "f:deleted-elsewhere")           # folder removed on another device
    d = dialogs.BookmarksDialog(ready, open_cb=lambda u: opened.append(u)); qtbot.addWidget(d); d.show()
    opened = []
    assert d.table.rowCount() == 4                                                    # "All bookmarks"
    names = [d.tree.topLevelItem(i).text(0) for i in range(d.tree.topLevelItemCount())]
    assert "Recovered items" in names and "Bookmarks toolbar" in names
    assert [d.tag_list.item(i).text() for i in range(d.tag_list.count())] == ["docs (1)", "lang (2)"]
    d.tag_list.setCurrentRow(1)
    assert wait_until(lambda: d.table.rowCount() == 2, 3000)
    d.tag_list.clearSelection()
    d.search.setText("gam"); assert d.table.rowCount() == 1; d.search.setText("")
    d.table.selectRow(0); d.open(); assert opened
    # rename + delete folder through the UI helpers
    monkeypatch.setattr(QInputDialog, "getText", staticmethod(lambda *a, **k: ("Books", True)))
    d.tree.setCurrentItem(d._find(f)); d.rename_folder()
    assert st.folders[f]["name"] == "Books"
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    d.tree.setCurrentItem(d._find(f)); d.delete_folder()
    assert st.by_url("https://a.example/") is None and st.by_url("https://b.example/") is None and st.by_url("https://c.example/")


def test_bookmark_edit_dialog_lists_nested_folders(ready, qtbot):
    f = ready.store.add_folder("One"); ready.store.add_folder("Two", f)
    d = dialogs.BookmarkEditDialog(ready.store, url="https://x.example/", title="X"); qtbot.addWidget(d)
    labels = [d.folder.itemText(i) for i in range(d.folder.count())]
    assert "    One" in labels and "        Two" in labels
    d.tags.setText("a, b ,, c")
    assert d.values()[3] == ["a", "b", "c"]


def test_settings_dialog_applies_everything(ready, qtbot):
    d = settings_dialog.SettingsDialog(ready); qtbot.addWidget(d)
    d.theme.setCurrentIndex(d.theme.findData("nord")); d.r_sites.setChecked(True)
    d.sites.setPlainText("News.Example.com\n\nother.example"); d.sliders["sepia"].setValue(15)
    d.clip.setValue(45); d.lang.setCurrentIndex(d.lang.findData("fr")); d.force_dark.setChecked(True)
    d.interval.setValue(10); d.home.setText("https://example.org/")
    d._apply()
    s = ready.settings
    assert s["theme"] == {"id": "nord"} and s["display"]["mode"] == "sites"
    assert s["display"]["sites"] == ["news.example.com", "other.example"] and s["display"]["sepia"] == 15
    assert s["clipboard_clear_seconds"] == 45 and s["language"] == "fr" and s["force_dark_pages"] is True
    assert s["sync_interval_minutes"] == 10 and s["homepage"] == "https://example.org/"
    assert QApplication.instance().palette().window().color().name() == "#2e3440"
    assert (ready.data_dir / "settings.json").exists()
    from iuk_browser import i18n
    i18n.set_language("en")


def test_forget_device_wipes_the_vault(ready, qtbot, monkeypatch):
    d = settings_dialog.SettingsDialog(ready); qtbot.addWidget(d)
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    d._forget()
    assert not ready.account.status()["setup"]


def test_history_and_about_dialogs_open(ready, qtbot):
    ready.history.add("https://example.com/x", "Example X")
    h = dialogs.HistoryDialog(ready); qtbot.addWidget(h)
    assert h.table.rowCount() == 1 and h.table.item(0, 0).text() == "Example X"
    h.search.setText("nomatch"); assert h.table.rowCount() == 0
    a = settings_dialog.AboutDialog(); qtbot.addWidget(a)
    assert a.windowTitle()
