"""Everyday browser features in a real window: find, zoom, view source, print to PDF, developer tools, downloads."""
import pytest
from PySide6.QtWidgets import QFileDialog

from iuk_browser.app import AppContext
from webhelpers import js, wait_until


@pytest.fixture
def ctx(qapp, tmp_path):
    c = AppContext(qapp, tmp_path / "profile")
    yield c
    for w in list(c.windows):
        w.close()
    c.clipboard.clear_now()


def open_window(ctx, qtbot, url):
    w = ctx.new_window(urls=[url])
    qtbot.addWidget(w)
    v = w.current()
    assert wait_until(lambda: v.url().toString().startswith("http") and v.title() != "", 15000)
    return w, v


def test_find_in_page_counts_matches_and_next_previous(ctx, site, qtbot):
    w, v = open_window(ctx, qtbot, site.base + "/long")
    assert wait_until(lambda: "needle" in js(v, "document.body.innerText"), 8000)     # laid out before we search
    w.show_find()
    assert w.findbar.isVisible()

    def found():
        w._find("needle")                      # pressing Enter again, as a user would on a slow first search
        qtbot.wait(150)
        return "3" in w.find_result.text()
    w.find_edit.setText("needle")
    assert wait_until(found, 8000)                                               # "1 of 3"
    w.find_edit.setText("zebra")
    assert wait_until(lambda: w.find_result.text() == "Not found", 6000)
    w.hide_find()
    assert not w.findbar.isVisible()


def test_zoom_in_out_reset(ctx, site, qtbot):
    w, v = open_window(ctx, qtbot, site.base + "/plain")
    w.zoom(+0.1); w.zoom(+0.1)
    assert round(v.zoomFactor(), 1) == 1.2
    w.zoom(-0.5); assert round(v.zoomFactor(), 1) == 0.7
    w.zoom(0); assert v.zoomFactor() == 1.0
    for _ in range(100):
        w.zoom(+1)
    assert v.zoomFactor() == pytest.approx(5.0)                            # clamped


def test_view_source_opens_a_new_tab(ctx, site, qtbot):
    w, v = open_window(ctx, qtbot, site.base + "/plain")
    w.view_source()
    assert w.tabs.count() == 2
    assert wait_until(lambda: w.current().url().toString().startswith("view-source:http"), 8000)
    assert wait_until(lambda: "hello world" in js(w.current(), "document.body.innerText"), 8000)


def test_print_to_pdf_writes_a_pdf(ctx, site, qtbot, tmp_path, monkeypatch):
    w, v = open_window(ctx, qtbot, site.base + "/long")
    out = tmp_path / "page.pdf"
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(out), "")))
    w.print_pdf()
    assert wait_until(lambda: out.exists() and out.stat().st_size > 500, 10000)
    assert out.read_bytes().startswith(b"%PDF")


def test_developer_tools_attach_and_detach(ctx, site, qtbot):
    w, v = open_window(ctx, qtbot, site.base + "/plain")
    w.show()
    w.toggle_devtools()
    assert w.devtools_dock.isVisible()
    assert wait_until(lambda: v.page().devToolsPage() is not None, 5000)
    w.toggle_devtools()
    assert not w.devtools_dock.isVisible()


def test_download_is_saved_where_the_user_chooses(ctx, site, qtbot, tmp_path, monkeypatch):
    dest = tmp_path / "saved" / "my-report.bin"
    dest.parent.mkdir()
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: (str(dest), "")))
    w, v = open_window(ctx, qtbot, site.base + "/plain")
    w.navigate(site.base + "/download")
    assert wait_until(lambda: dest.exists() and dest.stat().st_size == len(b"downloaded-bytes-") * 500, 12000)
    assert ctx.downloads and ctx.downloads[0].downloadFileName() == "my-report.bin"


def test_cancelling_the_save_dialog_cancels_the_download(ctx, site, qtbot, tmp_path, monkeypatch):
    monkeypatch.setattr(QFileDialog, "getSaveFileName", staticmethod(lambda *a, **k: ("", "")))
    w, v = open_window(ctx, qtbot, site.base + "/plain")
    w.navigate(site.base + "/download")
    qtbot.wait(1500)
    assert ctx.downloads == [] and not list(tmp_path.glob("**/report.bin"))


def test_new_window_and_private_window_actions(ctx, site, qtbot):
    w, v = open_window(ctx, qtbot, site.base + "/plain")
    n = len(ctx.windows)
    w.a_newwin.trigger(); w.a_private.trigger()
    assert len(ctx.windows) == n + 2
    assert sum(1 for x in ctx.windows if x.private) == 1
    for x in ctx.windows[n:]:
        qtbot.addWidget(x)


def test_site_permissions_are_remembered_and_manageable(ctx, site, qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    from iuk_browser.ui.dialogs import PermissionsDialog
    asked = []
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: (asked.append(a[2]), QMessageBox.StandardButton.Yes)[1]))
    w, v = open_window(ctx, qtbot, site.base + "/plain")
    w.show()
    v.page().runJavaScript("Notification.requestPermission(); 1")
    assert wait_until(lambda: bool(asked), 8000)
    assert "127.0.0.1" in asked[0] and "Notifications" in asked[0]                       # a readable prompt, not an enum name
    prof = ctx.profiles.normal
    assert wait_until(lambda: any(p.state().name == "Granted" for p in prof.listAllPermissions()), 8000)

    d = PermissionsDialog(ctx); qtbot.addWidget(d); d.show()
    assert d.table.rowCount() == 1
    assert [d.table.item(0, c).text() for c in range(3)] == ["127.0.0.1", "Notifications", "Allowed"]
    d.table.selectRow(0); d._apply("deny")
    assert d.table.item(0, 2).text() == "Blocked"                                         # allow -> block
    d.table.selectRow(0); d._apply("grant")
    assert d.table.item(0, 2).text() == "Allowed"
    d.search.setText("nomatch"); assert d.table.rowCount() == 0
    d.search.setText("")
    d.table.selectRow(0); d._apply("reset")                                               # forget it
    assert d.table.rowCount() == 0
    asked.clear()
    v.page().runJavaScript("Notification.requestPermission(); 1")
    assert wait_until(lambda: bool(asked), 8000)                                          # after a reset the site is asked again


def test_private_windows_do_not_persist_permissions(ctx, site, qtbot, monkeypatch):
    from PySide6.QtWidgets import QMessageBox
    monkeypatch.setattr(QMessageBox, "question", staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    w = ctx.new_window(private=True, urls=[site.base + "/plain"]); qtbot.addWidget(w)
    assert wait_until(lambda: w.current().title() == "Plain", 15000)
    w.show()
    w.current().page().runJavaScript("Notification.requestPermission(); 1")
    assert wait_until(lambda: any(p.state().name == "Granted" for p in ctx.profiles.private.listAllPermissions()), 8000)
    assert not any(p.state().name == "Granted" for p in ctx.profiles.normal.listAllPermissions())
