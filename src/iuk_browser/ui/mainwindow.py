"""The browser window."""
from __future__ import annotations

import time
from pathlib import Path

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, QUrl
from PySide6.QtGui import QAction, QActionGroup, QIcon, QKeySequence
from PySide6.QtWebEngineCore import QWebEnginePage
from PySide6.QtWebEngineWidgets import QWebEngineView
from PySide6.QtWidgets import (QApplication, QCompleter, QDockWidget, QFileDialog, QFrame, QHBoxLayout, QInputDialog, QLabel, QLineEdit,
                               QMainWindow, QMenu, QMessageBox, QProgressBar, QPushButton, QTabWidget, QToolBar, QToolButton, QVBoxLayout, QWidget)

from .. import APP_NAME
from ..app import app_icon
from ..core import merge as M
from ..core.urlutil import display_url, resolve
from ..core.util import gen_password
from ..i18n import is_rtl, language, tr
from . import theme
from .dialogs import (BookmarkEditDialog, BookmarksDialog, DownloadsDialog, HistoryDialog, PairDialog, PermissionsDialog, SetupDialog,
                      UnlockDialog, VaultDialog, permission_label)
from .icons import icon
from .settings_dialog import AboutDialog, SettingsDialog
from .web import WebView

FIND_FLAGS = QWebEnginePage.FindFlag


class BrowserWindow(QMainWindow):
    def __init__(self, ctx, private: bool = False, urls: list[str] | None = None):
        super().__init__()
        self.ctx, self.private = ctx, private
        self.profile = ctx.profiles.private if private else ctx.profiles.normal
        self.setWindowIcon(app_icon())
        self.setAttribute(Qt.WidgetAttribute.WA_DeleteOnClose, True)
        self.resize(1200, 800)
        self._fullscreen_restore = None

        self.tabs = QTabWidget(documentMode=True, tabsClosable=True, movable=True)
        self.tabs.tabCloseRequested.connect(self.close_tab)
        self.tabs.currentChanged.connect(self._current_changed)
        self.progress = QProgressBar(maximumHeight=3, textVisible=False)
        self.progress.hide()
        self._build_infobar()
        self._build_findbar()
        central = QWidget()
        lay = QVBoxLayout(central)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)
        for w in (self.infobar, self.progress, self.tabs, self.findbar):
            lay.addWidget(w)
        self.setCentralWidget(central)
        self._build_toolbar()
        self._build_menu()
        self._build_status()
        self.devtools_dock = QDockWidget(tr("Developer tools"), self)
        self.devtools_view = QWebEngineView()
        self.devtools_dock.setWidget(self.devtools_view)
        self.addDockWidget(Qt.DockWidgetArea.BottomDockWidgetArea, self.devtools_dock)
        self.devtools_dock.hide()
        self.devtools_dock.visibilityChanged.connect(self._devtools_visibility)

        ctx.data_changed.connect(self._update_star)
        ctx.sync_changed.connect(self._update_sync_label)
        ctx.vault_state_changed.connect(self._update_vault_actions)
        ctx.auto_locked.connect(lambda m: self.statusBar().showMessage(tr("Passwords locked after {} minutes of inactivity.", m), 8000))
        self.on_settings_changed()
        self._update_vault_actions()
        self._update_sync_label()

        for w in [self, *self.findChildren(QWidget)]:
            ctx.watch(w)
        start = urls or (self._restore() if not private else []) or [ctx.settings["homepage"]]
        for u in start:
            self.add_tab(u)

    # ================================================================== construction
    def _ic(self, name):
        return icon(name, theme.icon_color(QApplication.instance()), 22)

    def _act(self, text, slot=None, shortcut=None, icon_name=None, checkable=False):
        a = QAction(text, self)
        if shortcut:
            a.setShortcut(QKeySequence(shortcut))
            a.setShortcutContext(Qt.ShortcutContext.WindowShortcut)
        if icon_name:
            a.setData(icon_name)
            a.setIcon(self._ic(icon_name))
        a.setCheckable(checkable)
        if slot:
            a.triggered.connect(slot)
        self.addAction(a)
        return a

    def _build_toolbar(self):
        tb = self.toolbar = QToolBar(tr("Navigation"), self)
        tb.setMovable(False)
        tb.setIconSize(QSize(20, 20))
        self.addToolBar(tb)
        self.a_back = self._act(tr("Back"), lambda: self.current() and self.current().back(), "Alt+Left", "back")
        self.a_fwd = self._act(tr("Forward"), lambda: self.current() and self.current().forward(), "Alt+Right", "forward")
        self.a_reload = self._act(tr("Reload"), self._reload_or_stop, "F5", "reload")
        self.a_home = self._act(tr("Home"), lambda: self.navigate(self.ctx.settings["homepage"]), "Alt+Home", "home")
        for a in (self.a_back, self.a_fwd, self.a_reload, self.a_home):
            tb.addAction(a)
        self.url_edit = QLineEdit()
        self.url_edit.setPlaceholderText(tr("Search or enter address"))
        self.url_edit.setClearButtonEnabled(True)
        self.completer = QCompleter([], self)
        self.completer.setCaseSensitivity(Qt.CaseSensitivity.CaseInsensitive)
        self.completer.setFilterMode(Qt.MatchFlag.MatchContains)
        self.url_edit.setCompleter(self.completer)
        self.url_edit.returnPressed.connect(lambda: self.navigate(self.url_edit.text()))
        self.url_edit.textEdited.connect(self._suggest)
        tb.addWidget(self.url_edit)
        self.a_star = self._act(tr("Bookmark this page"), self.toggle_bookmark, "Ctrl+D", "star")
        tb.addAction(self.a_star)
        self.key_menu = QMenu(self)
        key_btn = QToolButton()
        key_btn.setMenu(self.key_menu)
        key_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        key_btn.setToolTip(tr("Passwords"))
        self.key_btn = key_btn
        tb.addWidget(key_btn)
        self.main_menu = QMenu(self)
        menu_btn = QToolButton()
        menu_btn.setMenu(self.main_menu)
        menu_btn.setPopupMode(QToolButton.ToolButtonPopupMode.InstantPopup)
        menu_btn.setToolTip(tr("Menu"))
        self.menu_btn = menu_btn
        tb.addWidget(menu_btn)
        newtab = QToolButton()
        newtab.clicked.connect(lambda: self.add_tab(self.ctx.settings["homepage"]))
        self.newtab_btn = newtab
        self.tabs.setCornerWidget(newtab, Qt.Corner.TopRightCorner)

    def _build_menu(self):
        A, m = self._act, self.main_menu
        self.a_newtab = A(tr("New tab"), lambda: self.add_tab(self.ctx.settings["homepage"]), "Ctrl+T")
        self.a_closetab = A(tr("Close tab"), lambda: self.close_tab(self.tabs.currentIndex()), "Ctrl+W")
        self.a_newwin = A(tr("New window"), lambda: self.ctx.new_window(), "Ctrl+N")
        self.a_private = A(tr("New private window"), lambda: self.ctx.new_window(private=True), "Ctrl+Shift+N")
        self.a_focus = A(tr("Focus address bar"), lambda: (self.url_edit.setFocus(), self.url_edit.selectAll()), "Ctrl+L")
        self.a_reload2 = A(tr("Reload"), lambda: self.current() and self.current().reload(), "Ctrl+R")
        self.a_next = A(tr("Next tab"), lambda: self.tabs.setCurrentIndex((self.tabs.currentIndex() + 1) % max(1, self.tabs.count())), "Ctrl+PgDown")
        self.a_prev = A(tr("Previous tab"), lambda: self.tabs.setCurrentIndex((self.tabs.currentIndex() - 1) % max(1, self.tabs.count())), "Ctrl+PgUp")
        for a in (self.a_newtab, self.a_newwin, self.a_private):
            m.addAction(a)
        m.addSeparator()
        m.addAction(A(tr("Find in page"), self.show_find, "Ctrl+F"))
        self.zoom_menu = m.addMenu(tr("Zoom"))
        for text, fn, sc in ((tr("Zoom in"), lambda: self.zoom(+0.1), "Ctrl++"), (tr("Zoom out"), lambda: self.zoom(-0.1), "Ctrl+-"),
                             (tr("Reset zoom"), lambda: self.zoom(0), "Ctrl+0")):
            self.zoom_menu.addAction(A(text, fn, sc))
        m.addAction(A(tr("Full screen"), self.toggle_fullscreen, "F11"))
        m.addAction(A(tr("Print to PDF…"), self.print_pdf, "Ctrl+P"))
        m.addAction(A(tr("View page source"), self.view_source, "Ctrl+U"))
        m.addAction(A(tr("Developer tools"), self.toggle_devtools, "F12"))
        m.addSeparator()
        bm = m.addMenu(tr("Bookmarks"))
        bm.addAction(self.a_star)
        bm.addAction(A(tr("Manage bookmarks…"), self.show_bookmarks, "Ctrl+Shift+O"))
        m.addAction(A(tr("History"), self.show_history, "Ctrl+H"))
        m.addAction(A(tr("Downloads"), lambda: DownloadsDialog(self.ctx, self).exec(), "Ctrl+J"))
        m.addSeparator()
        # appearance quick toggles
        self.a_invert = A(tr("Invert page colors (all sites)"), self.toggle_invert, "Alt+Shift+I", checkable=True)
        m.addAction(self.a_invert)
        self.a_block = A(tr("Block trackers and ads"), self.toggle_blocking, None, checkable=True)
        self.a_allow_site = A(tr("Allow trackers on this site"), self.toggle_site_allowed, None, checkable=True)
        m.addAction(self.a_block)
        m.addAction(self.a_allow_site)
        self.a_sync = A(tr("Sync now"), self.ctx.sync_async, "Ctrl+Shift+S")
        m.addAction(self.a_sync)
        m.addAction(A(tr("Pair another device (QR)…"), lambda: PairDialog(self.ctx, self, "show").exec()))
        m.addAction(A(tr("Site permissions…"), lambda: PermissionsDialog(self.ctx, self).exec()))
        m.addAction(A(tr("Set as default browser…"), self.make_default))
        m.addAction(A(tr("Settings"), self.show_settings, "Ctrl+,"))
        m.addSeparator()
        m.addAction(A(tr("Check for updates"), lambda: self.ctx.check_updates(manual=True, parent=self)))
        m.addAction(A(tr("About IUK Browser"), lambda: AboutDialog(self).exec()))
        # password menu
        km = self.key_menu
        self.a_fill = A(tr("Fill login on this page"), self.fill_login, "Ctrl+Shift+L")
        self.a_vault = A(tr("Saved passwords…"), self.show_vault, "Ctrl+Shift+K")
        self.a_gen = A(tr("Generate password…"), self.generate_password)
        self.a_lock = A(tr("Lock passwords"), self.lock_vault)
        self.a_unlock = A(tr("Unlock passwords…"), self.unlock_vault)
        self.a_setup = A(tr("Set up passwords and sync…"), self.setup_vault)
        for a in (self.a_fill, self.a_vault, self.a_gen, self.a_lock, self.a_unlock, self.a_setup):
            km.addAction(a)

    def _build_status(self):
        self.sync_label = QPushButton(flat=True)
        self.sync_label.clicked.connect(self._sync_clicked)
        self.block_label = QLabel()
        self.statusBar().addPermanentWidget(self.block_label)
        self.statusBar().addPermanentWidget(self.sync_label)
        self._block_base: dict = {}
        self._block_timer = QTimer(self)
        self._block_timer.timeout.connect(self._update_block_label)
        self._block_timer.start(1000)

    def _build_infobar(self):
        self.infobar = QFrame()
        self.infobar.setFrameShape(QFrame.Shape.StyledPanel)
        self.infobar.setAutoFillBackground(True)
        row = QHBoxLayout(self.infobar)
        row.setContentsMargins(8, 4, 8, 4)
        self.info_label = QLabel()
        self.info_btn1, self.info_btn2, self.info_close = QPushButton(), QPushButton(), QPushButton("×")
        self.info_close.setFixedWidth(28)
        self.info_close.clicked.connect(self.infobar.hide)
        self._bar_cbs = {}
        self.info_btn1.clicked.connect(lambda: self._bar_cbs.get(self.info_btn1, lambda: None)())
        self.info_btn2.clicked.connect(lambda: self._bar_cbs.get(self.info_btn2, lambda: None)())
        for w in (self.info_label,):
            row.addWidget(w, 1)
        for b in (self.info_btn1, self.info_btn2, self.info_close):
            row.addWidget(b)
        self.infobar.hide()

    def _build_findbar(self):
        self.findbar = QFrame()
        row = QHBoxLayout(self.findbar)
        row.setContentsMargins(6, 3, 6, 3)
        self.find_edit = QLineEdit()
        self.find_edit.setPlaceholderText(tr("Find in page"))
        self.find_edit.textChanged.connect(lambda t: self._find(t))
        self.find_edit.returnPressed.connect(lambda: self._find(self.find_edit.text()))
        nxt, prv, cls = QPushButton(tr("Next")), QPushButton(tr("Previous")), QPushButton("×")
        nxt.clicked.connect(lambda: self._find(self.find_edit.text()))
        prv.clicked.connect(lambda: self._find(self.find_edit.text(), backward=True))
        cls.setFixedWidth(28)
        cls.clicked.connect(self.hide_find)
        self.find_result = QLabel()
        for w in (self.find_edit, prv, nxt, self.find_result, cls):
            row.addWidget(w)
        self.findbar.hide()

    # ================================================================== tabs
    def current(self) -> WebView | None:
        w = self.tabs.currentWidget()
        return w if isinstance(w, WebView) else None

    def add_tab(self, url: str | None = None, background: bool = False) -> WebView:
        v = WebView(self.profile, private=self.private)
        i = self.tabs.addTab(v, tr("New tab"))
        v.captured_cb = self._credentials_captured
        self.ctx.watch_view(v)
        v.new_tab_requested.connect(lambda holder: holder.append(self.add_tab(None)))
        v.titleChanged.connect(lambda t, v=v: self._title_changed(v, t))
        v.urlChanged.connect(lambda u, v=v: self._url_changed(v, u))
        v.iconChanged.connect(lambda ic, v=v: self.tabs.setTabIcon(self.tabs.indexOf(v), ic))
        v.loadStarted.connect(lambda v=v: self._load_started(v))
        v.loadProgress.connect(lambda p, v=v: self._load_progress(v, p))
        v.loadFinished.connect(lambda ok, v=v: self._load_finished(v, ok))
        pg = v.page()
        pg.windowCloseRequested.connect(lambda v=v: self.close_tab(self.tabs.indexOf(v)))
        pg.fullScreenRequested.connect(self._fullscreen_requested)
        if hasattr(pg, "permissionRequested"):
            pg.permissionRequested.connect(self._permission)
        pg.authenticationRequired.connect(self._auth)
        if not background:
            self.tabs.setCurrentIndex(i)
        if url:
            v.load(QUrl(resolve(url, self.ctx.settings.search_url)))
        return v

    def close_tab(self, index: int) -> None:
        w = self.tabs.widget(index)
        if w is None:
            return
        if self.tabs.count() <= 1:
            self.close()
            return
        self.tabs.removeTab(index)
        if isinstance(w, WebView):
            w.page().setDevToolsPage(None) if self.devtools_dock.isVisible() else None
            w.deleteLater()

    def _current_changed(self, _i):
        v = self.current()
        self.hide_find()
        if v is None:
            return
        self.url_edit.setText(display_url(v.url().toString()) if v.url().isValid() else "")
        self.setWindowTitle(self._window_title(v.title()))
        self._update_nav()
        self._update_star()
        if self.devtools_dock.isVisible():
            v.page().setDevToolsPage(self.devtools_view.page())
        if v.pending and time.time() - v.pending[3] < 120:
            self._offer_save(v)
        else:
            self.infobar.hide()

    def _window_title(self, t: str) -> str:
        return f"{t} — {APP_NAME}" + (f" ({tr('Private')})" if self.private else "") if t else APP_NAME + (f" ({tr('Private')})" if self.private else "")

    def _title_changed(self, v, title):
        i = self.tabs.indexOf(v)
        self.tabs.setTabText(i, (title or tr("New tab"))[:28])
        self.tabs.setTabToolTip(i, title)
        if v is self.current():
            self.setWindowTitle(self._window_title(title))

    def _url_changed(self, v, url):
        if v.pending and v.pending[0] != url.host():
            v.pending = None
            self.infobar.hide()
        if v is self.current():
            if not self.url_edit.hasFocus():
                self.url_edit.setText(display_url(url.toString()))
            self._update_star()
            self._update_nav()

    def _load_started(self, v):
        self.ctx.touch()
        self._block_base[v] = self.ctx.profiles.blocker.blocked.get(v.url().host(), 0)
        if v is self.current():
            self.progress.setValue(0)
            self.progress.show()
            self.a_reload.setIcon(self._ic("stop"))

    def _load_progress(self, v, p):
        if v is self.current():
            self.progress.setValue(p)

    def _load_finished(self, v, ok):
        self.ctx.watch_view(v)
        self.ctx.touch()
        if not self.private and ok:
            self.ctx.history.add(v.url().toString(), v.title())
        if v is self.current():
            self.progress.hide()
            self.a_reload.setIcon(self._ic("reload"))
            self._update_nav()

    def _update_nav(self):
        v = self.current()
        h = v.history() if v else None
        self.a_back.setEnabled(bool(h and h.canGoBack()))
        self.a_fwd.setEnabled(bool(h and h.canGoForward()))

    def _reload_or_stop(self):
        v = self.current()
        if v:
            v.stop() if self.progress.isVisible() else v.reload()

    # ================================================================== navigation
    def navigate(self, text: str) -> None:
        v = self.current() or self.add_tab(None)
        v.load(QUrl(resolve(text, self.ctx.settings.search_url)))
        v.setFocus()

    def _suggest(self, text: str):
        if len(text) >= 2:
            self.completer.model().setStringList(self.ctx.history.suggest(text)) if hasattr(self.completer.model(), "setStringList") else None

    def zoom(self, delta: float):
        v = self.current()
        if v:
            v.setZoomFactor(1.0 if delta == 0 else max(0.25, min(5.0, v.zoomFactor() + delta)))

    def toggle_fullscreen(self):
        self.showNormal() if self.isFullScreen() else self.showFullScreen()

    def _fullscreen_requested(self, req):
        req.accept()
        on = req.toggleOn()
        self.toolbar.setVisible(not on)
        self.tabs.tabBar().setVisible(not on)
        self.showFullScreen() if on else self.showNormal()

    def print_pdf(self):
        v = self.current()
        if v:
            path, _ = QFileDialog.getSaveFileName(self, tr("Print to PDF…"), "page.pdf", "PDF (*.pdf)")
            if path:
                v.page().printToPdf(path)

    def view_source(self):
        v = self.current()
        if v and v.url().scheme() in ("http", "https", "file"):
            self.add_tab("view-source:" + v.url().toString())

    def toggle_devtools(self):
        self.devtools_dock.setVisible(not self.devtools_dock.isVisible())

    def _devtools_visibility(self, visible):
        v = self.current()
        if v:
            v.page().setDevToolsPage(self.devtools_view.page() if visible else None)

    # ================================================================== find
    def show_find(self):
        self.findbar.show()
        self.find_edit.setFocus()
        self.find_edit.selectAll()

    def hide_find(self):
        self.findbar.hide()
        v = self.current()
        if v:
            v.findText("")

    def _find(self, text, backward=False):
        v = self.current()
        if not v:
            return
        flags = FIND_FLAGS.FindBackward if backward else FIND_FLAGS(0)
        v.findText(text, flags, lambda r: self.find_result.setText("" if not text else (tr("{} of {}", r.activeMatch(), r.numberOfMatches()) if r.numberOfMatches() else tr("Not found"))))

    # ================================================================== bookmarks
    def toggle_bookmark(self):
        v = self.current()
        if not v or not v.url().isValid() or v.url().scheme() not in ("http", "https", "file", "ftp"):
            return
        url = v.url().toString()
        item = self.ctx.store.by_url(url)
        d = BookmarkEditDialog(self.ctx.store, self, item=item, url=url, title=v.title())
        if d.exec():
            _, title, folder, tags = d.values()
            if item:
                self.ctx.store.update_bookmark(item["id"], title=title, folder=folder, tags=tags)
            else:
                self.ctx.store.add_bookmark(url, title or url, folder, tags)
            self.ctx.after_vault_change()
        elif item and QMessageBox.question(self, APP_NAME, tr("Remove this bookmark?")) == QMessageBox.StandardButton.Yes:
            self.ctx.store.remove_bookmark(item["id"])
            self.ctx.after_vault_change()
        self._update_star()

    def _update_star(self):
        v = self.current()
        on = bool(v and v.url().isValid() and self.ctx.store.by_url(v.url().toString()))
        self.a_star.setIcon(self._ic("star_on" if on else "star"))
        self.a_star.setText(tr("Edit bookmark") if on else tr("Bookmark this page"))

    def show_bookmarks(self):
        BookmarksDialog(self.ctx, self, open_cb=lambda u: self.add_tab(u)).exec()
        self._update_star()

    def show_history(self):
        HistoryDialog(self.ctx, self, open_cb=lambda u: self.add_tab(u)).exec()

    # ================================================================== passwords
    def _status(self):
        return self.ctx.account.status()

    def _update_vault_actions(self):
        st = self._status()
        self.a_setup.setVisible(not st["setup"])
        self.a_unlock.setVisible(st["setup"] and not st["unlocked"])
        self.a_lock.setVisible(st["unlocked"])
        for a in (self.a_fill, self.a_vault):
            a.setEnabled(True)
        self.a_sync.setEnabled(st["unlocked"] and bool(st["server"]))

    def setup_vault(self) -> bool:
        ok = SetupDialog(self.ctx, self).exec()
        self.ctx.vault_state_changed.emit()
        return bool(ok)

    def unlock_vault(self) -> bool:
        ok = UnlockDialog(self.ctx, self).exec()
        self.ctx.vault_state_changed.emit()
        if ok:
            self.ctx.sync_async()
        return bool(ok)

    def lock_vault(self):
        self.ctx.account.lock()
        self.ctx.clipboard.clear_now()
        self.ctx.vault_state_changed.emit()

    def _ensure_unlocked(self) -> bool:
        st = self._status()
        if not st["setup"]:
            return self.setup_vault()
        return st["unlocked"] or self.unlock_vault()

    def show_vault(self):
        if self._ensure_unlocked():
            VaultDialog(self.ctx, self).exec()

    def generate_password(self):
        pw = gen_password(20)
        box = QMessageBox(self)
        box.setWindowTitle(APP_NAME)
        box.setText(pw)
        box.setTextInteractionFlags(Qt.TextInteractionFlag.TextSelectableByMouse)
        copy = box.addButton(tr("Copy"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("Close"), QMessageBox.ButtonRole.RejectRole)
        box.exec()
        if box.clickedButton() is copy:
            self.ctx.clipboard.copy_secret(pw)

    def fill_login(self):
        v = self.current()
        if not v or v.url().scheme() not in ("http", "https"):
            return
        if not self._ensure_unlocked():
            return
        host = v.url().host()
        matches = self.ctx.account.list_logins(host)
        if not matches:
            self.statusBar().showMessage(tr("No saved logins for {}", host), 4000)
            return
        pick = matches[0]
        if len(matches) > 1:
            labels = [f"{m['username'] or tr('(no user name)')}  —  {m['host']}" for m in matches]
            label, ok = QInputDialog.getItem(self, APP_NAME, tr("Choose a login"), labels, 0, False)
            if not ok:
                return
            pick = matches[labels.index(label)]
        v.fill(pick["username"], self.ctx.account.get_password(pick["id"]))

    # ---- "save this password?" bar
    def show_bar(self, text, primary, primary_cb, secondary=None, secondary_cb=None):
        self.info_label.setText(text)
        for b, label, cb in ((self.info_btn1, primary, primary_cb), (self.info_btn2, secondary, secondary_cb)):
            self._bar_cbs[b] = cb
            b.setVisible(bool(label))
            if label:
                b.setText(label)
        self.infobar.show()

    def _credentials_captured(self, view):
        QTimer.singleShot(900, lambda: self._offer_save(view))

    def _offer_save(self, view):
        p = view.pending
        if not p or self.private or view is not self.current() or view.url().host() != p[0]:
            return
        host, user, pw, _ = p
        st = self._status()
        if not st["setup"]:
            self.show_bar(tr("Save the password for {} on {}? Set up the password manager first.", user or tr("(no user name)"), host),
                          tr("Set up…"), lambda: (self.infobar.hide(), self.setup_vault() and self._offer_save(view)), tr("Not now"), self._dismiss(view))
        elif not st["unlocked"]:
            self.show_bar(tr("Unlock to save the password for {} on {}.", user or tr("(no user name)"), host),
                          tr("Unlock…"), lambda: (self.infobar.hide(), self.unlock_vault() and self._offer_save(view)), tr("Not now"), self._dismiss(view))
        else:
            kind = self.ctx.account.find_match(host, user, pw)
            if kind == "known":
                view.pending = None
                return
            text = tr("Update the saved password for {} on {}?" if kind == "update" else "Save the password for {} on {}?", user or tr("(no user name)"), host)
            self.show_bar(text, tr("Update") if kind == "update" else tr("Save"), lambda: self._save_pending(view), tr("Not now"), self._dismiss(view))

    def _dismiss(self, view):
        def cb():
            view.pending = None
            self.infobar.hide()
        return cb

    def _save_pending(self, view):
        p = view.pending
        if p:
            self.ctx.account.save_login(p[0], p[1], p[2])
            view.pending = None
            self.ctx.after_vault_change()
        self.infobar.hide()

    # ================================================================== web permissions & auth
    def _permission(self, perm):
        kind = permission_label(perm.permissionType().name)
        origin = perm.origin().host() or perm.origin().toString()
        q = QMessageBox.question(self, APP_NAME, tr("{} wants permission: {}", origin, kind))
        perm.grant() if q == QMessageBox.StandardButton.Yes else perm.deny()

    def _auth(self, url, authenticator):
        from PySide6.QtWidgets import QDialog, QFormLayout, QDialogButtonBox
        d = QDialog(self)
        d.setWindowTitle(tr("Sign in to {}", url.host()))
        u, p = QLineEdit(), QLineEdit()
        p.setEchoMode(QLineEdit.EchoMode.Password)
        f = QFormLayout(d)
        f.addRow(tr("User name"), u)
        f.addRow(tr("Password"), p)
        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.accepted.connect(d.accept)
        bb.rejected.connect(d.reject)
        f.addRow(bb)
        if d.exec():
            authenticator.setUser(u.text())
            authenticator.setPassword(p.text())

    # ================================================================== sync status
    def _update_sync_label(self):
        s = self.ctx.sync_state
        st = self._status()
        if not st["setup"] or not st["server"]:
            self.sync_label.setText("")
            self.sync_label.hide()
            return
        self.sync_label.show()
        if s == "otp":
            self.sync_label.setText(tr("Sync: code needed"))
        elif s.startswith("error"):
            self.sync_label.setText(tr("Sync error"))
            self.sync_label.setToolTip(s)
        elif s == "syncing":
            self.sync_label.setText(tr("Syncing…"))
        else:
            ts = st["last_sync"]
            self.sync_label.setText(tr("Synced") + (" " + time.strftime("%H:%M", time.localtime(ts / 1000)) if ts else ""))
            self.sync_label.setToolTip("")

    def _sync_clicked(self):
        if self.ctx.sync_state == "otp":
            code, ok = QInputDialog.getText(self, APP_NAME, tr("Second-factor code or recovery code"))
            if ok and code.strip():
                c = code.strip()
                self.ctx.run_async(lambda: self.ctx.account.provide_otp(**({"recovery": c} if "-" in c else {"otp": c})),
                                   lambda _r, err: QMessageBox.warning(self, APP_NAME, str(err)) if err else self.ctx.sync_async())
        else:
            self.ctx.sync_async()

    def make_default(self):
        r = self.ctx.set_default_browser(self)
        QMessageBox.information(self, APP_NAME, {
            "done": tr("IUK Browser is now your default browser."),
            "settings": tr("Windows asks you to confirm the default browser in Settings. Choose IUK Browser there."),
        }.get(r, tr("Could not set the default browser automatically. Choose IUK Browser in your system settings.")))

    # ================================================================== tracker blocking
    def toggle_blocking(self):
        cfg = dict(self.ctx.settings["blocker"])
        cfg["enabled"] = not cfg["enabled"]
        self.ctx.apply_settings({"blocker": cfg})

    def toggle_site_allowed(self):
        v = self.current()
        host = WebView.host_of(v.url()) if v else ""
        if not host:
            return
        cfg = dict(self.ctx.settings["blocker"])
        sites = [h for h in cfg["allow_sites"] if h != host]
        if len(sites) == len(cfg["allow_sites"]):
            sites.append(host)
        cfg["allow_sites"] = sites
        self.ctx.apply_settings({"blocker": cfg})
        v.reload()

    def _update_block_label(self):
        v = self.current()
        host = v.url().host() if v else ""
        n = self.ctx.profiles.blocker.blocked.get(host, 0) - self._block_base.get(v, 0) if host else 0
        self.block_label.setText(tr("{} blocked", n) if n > 0 else "")
        self.a_allow_site.setChecked(bool(host) and WebView.host_of(v.url()) in self.ctx.settings["blocker"]["allow_sites"])
        self.a_allow_site.setEnabled(bool(host))

    # ================================================================== settings / theme
    def show_settings(self):
        SettingsDialog(self.ctx, self).exec()

    def toggle_invert(self):
        d = dict(self.ctx.settings["display"])
        d["mode"] = "off" if d["mode"] == "all" else "all"
        self.ctx.apply_settings({"display": d})

    def on_settings_changed(self):
        QApplication.instance().setLayoutDirection(Qt.LayoutDirection.RightToLeft if is_rtl() else Qt.LayoutDirection.LeftToRight)
        for a in self.findChildren(QAction):
            name = a.data()
            if isinstance(name, str):
                a.setIcon(self._ic(name))
        self.key_btn.setIcon(self._ic("key"))
        self.menu_btn.setIcon(self._ic("menu"))
        self.newtab_btn.setIcon(self._ic("plus"))
        self.a_home.setIcon(self._ic("home"))
        self.a_back.setIcon(self._ic("back"))
        self.a_fwd.setIcon(self._ic("forward"))
        self.a_reload.setIcon(self._ic("reload"))
        self._update_star()
        self.a_invert.setChecked(self.ctx.settings["display"]["mode"] == "all")
        self.a_block.setChecked(self.ctx.settings["blocker"]["enabled"])
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, WebView):
                w.apply_display(self.ctx.settings["display"])
        self.setWindowTitle(self._window_title(self.current().title() if self.current() else ""))

    # ================================================================== session / closing
    def _restore(self) -> list[str]:
        if not self.ctx.settings["restore_session"] or any(not w.private for w in self.ctx.windows if w is not self):
            return []
        return list(self.ctx.settings["session_urls"])

    def _session_urls(self) -> list[str]:
        out = []
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, WebView) and w.url().scheme() in ("http", "https", "file") and not w.url().isEmpty():
                out.append(w.url().toString())
        return out

    def closeEvent(self, e):
        if not self.private:
            others = [w for w in self.ctx.windows if w is not self and not w.private]
            if not others:                       # last normal window: remember the tabs
                self.ctx.settings.set("session_urls", self._session_urls())
        if self in self.ctx.windows:
            self.ctx.windows.remove(self)
        for i in range(self.tabs.count()):
            w = self.tabs.widget(i)
            if isinstance(w, WebView):
                w.page().setDevToolsPage(None)
        super().closeEvent(e)
