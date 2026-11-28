"""Application context shared by all browser windows."""
from __future__ import annotations

import inspect
import itertools
import json
import sys
import threading
from pathlib import Path

from PySide6.QtCore import QEvent, QObject, QRunnable, QStandardPaths, QThreadPool, QTimer, Signal, Slot
from PySide6.QtGui import QGuiApplication, QIcon
from PySide6.QtNetwork import QLocalServer, QLocalSocket
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QProgressDialog

from . import APP_NAME, APP_SLUG, __version__, i18n
from .core import updater as upd
from .core.account import Account
from .core.bookmarks import BookmarkStore
from .core.history import History
from .core.settings import Settings
from .core.transport import OtpRequired
from .core.update_keys import UPDATE_BASE_URL, UPDATE_PUBLIC_KEYS
from .i18n import tr
from .ui import theme
from .ui.clipboard import ClipboardGuard
from .ui.web import ProfileManager

RES = Path(__file__).resolve().parent / "resources"


def default_data_dir() -> Path:
    base = QStandardPaths.writableLocation(QStandardPaths.StandardLocation.AppDataLocation)
    return Path(base or Path.home() / f".{APP_SLUG}")


def app_icon() -> QIcon:
    ic = QIcon()
    for s in (16, 32, 48, 64, 128, 256, 512):
        ic.addFile(str(RES / "icons" / f"iuk-browser-{s}.png"))
    return ic


class TaskHandle:
    """Returned by run_async: cancel() sets the event the worker checks and drops the result callback."""

    def __init__(self, ctx, tok):
        self.event, self._ctx, self._tok = threading.Event(), ctx, tok

    def cancel(self) -> None:
        self.event.set()
        self._ctx._cbs.pop(self._tok, None)


class _ActivityFilter(QObject):
    """Installed on individual widgets (never on the QApplication: an application-wide Python event filter crashes Qt
    WebEngine). Any key, click, wheel or touch on a watched widget counts as activity for the auto-lock timer."""
    TYPES = {QEvent.Type.KeyPress, QEvent.Type.MouseButtonPress, QEvent.Type.Wheel, QEvent.Type.TouchBegin}

    def __init__(self, ctx):
        super().__init__(ctx)
        self.ctx = ctx

    def eventFilter(self, obj, ev):  # noqa: N802
        if ev.type() in self.TYPES:
            self.ctx.touch()
        return False


class AppContext(QObject):
    sync_changed = Signal()
    data_changed = Signal()            # bookmarks / logins changed (local edit or sync)
    vault_state_changed = Signal()     # locked / unlocked / forgotten
    auto_locked = Signal(int)          # minutes of inactivity that triggered the lock
    _done = Signal(int, object, object)

    def __init__(self, qapp: QApplication, data_dir: Path | None = None):
        super().__init__(qapp)
        self.qapp = qapp
        self.data_dir = Path(data_dir) if data_dir else default_data_dir()
        self.data_dir.mkdir(parents=True, exist_ok=True)
        self.settings = Settings(self.data_dir / "settings.json")
        i18n.set_language(self.settings["language"])
        self.store = BookmarkStore(self.data_dir / "bookmarks.json")
        self.account = Account(self.data_dir / "vault", self.store)
        self.history = History(self.data_dir / "history.sqlite")
        self.profiles = ProfileManager(self.data_dir, self.settings, self)
        self.clipboard = ClipboardGuard(lambda: self.settings["clipboard_clear_seconds"], self)
        self.updater = upd.Updater(UPDATE_BASE_URL, UPDATE_PUBLIC_KEYS, __version__, self.settings["update_channel"])
        self.windows: list = []
        self.downloads: list = []
        self.sync_state = ""           # "", "ok", "otp", "error: ..."
        self._syncing = False
        self._cbs: dict[int, object] = {}
        self._tok = itertools.count(1)
        self._pool = QThreadPool.globalInstance()
        self._done.connect(self._deliver)
        self._debounce = QTimer(self)
        self._debounce.setSingleShot(True)
        self._debounce.setInterval(3000)
        self._debounce.timeout.connect(self.sync_async)
        self._periodic = QTimer(self)
        self._periodic.timeout.connect(self.sync_async)
        self.auto_lock_override_ms: int | None = None      # tests
        self._lock_timer = QTimer(self)
        self._lock_timer.setSingleShot(True)
        self._lock_timer.timeout.connect(self._auto_lock)
        self._activity = _ActivityFilter(self)
        self.vault_state_changed.connect(self.touch)
        self._apply_runtime()
        for p in self.profiles.profiles():
            p.downloadRequested.connect(self.on_download)
        qapp.aboutToQuit.connect(self._shutdown)

    # ------------------------------------------------------------ async helper (worker thread -> callback on the UI thread)
    def run_async(self, fn, done=None) -> TaskHandle:
        """Runs fn in a worker thread, then done(result, error) on the UI thread. If fn takes one positional argument
        it receives the cancel event (see TaskHandle)."""
        tok = next(self._tok)
        self._cbs[tok] = done
        handle = TaskHandle(self, tok)
        required = [p for p in inspect.signature(fn).parameters.values()
                    if p.default is p.empty and p.kind in (p.POSITIONAL_ONLY, p.POSITIONAL_OR_KEYWORD)]
        takes_event = len(required) == 1

        class Task(QRunnable):
            def run(_self):  # noqa: N805
                try:
                    res, err = (fn(handle.event) if takes_event else fn()), None
                except Exception as e:  # noqa: BLE001
                    res, err = None, e
                self._done.emit(tok, res, err)
        self._pool.start(Task())
        return handle

    @Slot(int, object, object)
    def _deliver(self, tok, res, err) -> None:
        cb = self._cbs.pop(tok, None)
        if cb:
            cb(res, err)

    # ------------------------------------------------------------ auto-lock
    def touch(self) -> None:
        """(Re)arm the inactivity timer; it only runs while the vault is unlocked and the setting is not 'Never'."""
        minutes = int(self.settings["auto_lock_minutes"])
        if not self.account.is_unlocked() or (minutes <= 0 and self.auto_lock_override_ms is None):
            self._lock_timer.stop()
            return
        self._lock_timer.start(self.auto_lock_override_ms if self.auto_lock_override_ms is not None else minutes * 60_000)

    def watch(self, widget) -> None:
        """Count interaction with this widget as activity (idempotent)."""
        if widget is not None and not widget.property("iuk_watched"):
            widget.setProperty("iuk_watched", True)
            widget.installEventFilter(self._activity)

    def watch_view(self, view) -> None:
        self.watch(view)
        self.watch(view.focusProxy())      # the widget that really receives mouse and keyboard events (created lazily)

    def _auto_lock(self) -> None:
        if not self.account.is_unlocked():
            return
        if QApplication.activeModalWidget() is not None:      # a dialog (e.g. the password manager) is open: the user is here
            self.touch()
            return
        self.account.lock()
        self.clipboard.clear_now()
        self.sync_state = ""
        self.vault_state_changed.emit()
        self.auto_locked.emit(int(self.settings["auto_lock_minutes"]))

    # ------------------------------------------------------------ settings side effects
    def _apply_runtime(self) -> None:
        theme.apply_theme(self.qapp, self.settings["theme"])
        self.profiles.apply_force_dark(bool(self.settings["force_dark_pages"]))
        self._periodic.start(int(self.settings["sync_interval_minutes"]) * 60 * 1000)
        self.updater.channel = self.settings["update_channel"]
        self.touch()

    def apply_settings(self, new: dict) -> None:
        old_server = self.settings.get("sync_server", "")
        for k, v in new.items():
            self.settings.data[k] = v
        self.settings.save()
        self._apply_runtime()
        self.profiles.update_display(self.settings["display"])
        self.profiles.reload_blocker(self.settings["blocker"])
        for w in self.windows:
            w.on_settings_changed()
        if self.account.is_setup() and new.get("sync_server", old_server) != old_server:
            try:
                self.account.set_server(new["sync_server"])
                self.sync_async()
            except Exception as e:  # noqa: BLE001
                QMessageBox.warning(None, APP_NAME, str(e))

    # ------------------------------------------------------------ sync
    def after_vault_change(self) -> None:
        self.data_changed.emit()
        if self.account.is_unlocked() and self.account.status()["server"]:
            self._debounce.start()

    def sync_async(self, *_a) -> None:
        if self._syncing or not self.account.is_unlocked() or not self.account.status()["server"]:
            return
        self._syncing = True
        self.sync_state = "syncing"
        self.sync_changed.emit()

        def done(_res, err):
            self._syncing = False
            if isinstance(err, OtpRequired):
                self.sync_state = "otp"
            elif err:
                self.sync_state = "error: " + str(err)
            else:
                self.sync_state = "ok"
                self.data_changed.emit()
            self.sync_changed.emit()
        self.run_async(self.account.sync_now, done)

    # ------------------------------------------------------------ downloads
    def on_download(self, req) -> None:
        from .ui.dialogs import default_download_dir
        suggested = str(Path(default_download_dir()) / req.downloadFileName())
        path, _ = QFileDialog.getSaveFileName(self.windows[-1] if self.windows else None, tr("Save as"), suggested)
        if not path:
            req.cancel()
            return
        p = Path(path)
        req.setDownloadDirectory(str(p.parent))
        req.setDownloadFileName(p.name)
        req.accept()
        self.downloads.append(req)

    # ------------------------------------------------------------ updates
    def check_updates(self, manual: bool = False, parent=None) -> None:
        if not UPDATE_PUBLIC_KEYS:
            if manual:
                QMessageBox.information(parent, APP_NAME, tr("This build has no update signing key configured."))
            return

        def done(info, err):
            self.settings.set("last_update_check", int(__import__("time").time()))
            if err:
                if manual:
                    QMessageBox.warning(parent, APP_NAME, str(err))
            elif info is None:
                if manual:
                    QMessageBox.information(parent, APP_NAME, tr("You have the latest version ({}).", __version__))
            else:
                self._offer_update(info, parent)
        self.run_async(self.updater.check, done)

    def _offer_update(self, info, parent) -> None:
        box = QMessageBox(parent)
        box.setWindowTitle(APP_NAME)
        box.setText(tr("Version {} is available.", info.version))
        box.setInformativeText(info.notes)
        auto = info.kind == "installer" and sys.platform.startswith("win")
        install = box.addButton(tr("Install and restart") if auto else tr("Open download page") if info.url else tr("OK"), QMessageBox.ButtonRole.AcceptRole)
        box.addButton(tr("Later"), QMessageBox.ButtonRole.RejectRole)
        if not auto:
            box.setDetailedText(tr("If you installed from the apt or dnf repository, update with your package manager."))
        box.exec()
        if box.clickedButton() is not install:
            return
        if not auto:
            if info.url:
                from PySide6.QtCore import QUrl
                from PySide6.QtGui import QDesktopServices
                QDesktopServices.openUrl(QUrl(info.url))
            return
        prog = QProgressDialog(tr("Downloading update…"), tr("Cancel"), 0, 100, parent)
        prog.setWindowTitle(APP_NAME)
        prog.show()
        state = {"pct": 0}

        def work():
            return self.updater.download(info, self.data_dir / "updates", progress=lambda d, t: state.update(pct=int(100 * d / t) if t else 0))
        timer = QTimer(self)
        timer.timeout.connect(lambda: prog.setValue(state["pct"]))
        timer.start(200)

        def finished(path, err):
            timer.stop()
            prog.close()
            if err:
                QMessageBox.warning(parent, APP_NAME, str(err))
                return
            upd.run_installer(path)
            self.qapp.quit()
        self.run_async(work, finished)

    def maybe_auto_check_updates(self) -> None:
        import time
        if self.settings["check_updates"] and time.time() - self.settings["last_update_check"] > 24 * 3600:
            QTimer.singleShot(8000, lambda: self.check_updates(manual=False))

    # ------------------------------------------------------------ default browser
    def set_default_browser(self, parent=None) -> str:
        """Linux: xdg-settings (sets it directly). Windows: opens Settings > Default apps, where the user confirms.
        Returns 'done', 'settings' or 'failed' (the caller shows the message)."""
        import shutil
        import subprocess
        if sys.platform.startswith("win"):
            from PySide6.QtCore import QUrl
            from PySide6.QtGui import QDesktopServices
            QDesktopServices.openUrl(QUrl("ms-settings:defaultapps"))
            return "settings"
        if shutil.which("xdg-settings"):
            try:
                r = subprocess.run(["xdg-settings", "set", "default-web-browser", f"{APP_SLUG}.desktop"], capture_output=True, timeout=15)  # noqa: S603
                if r.returncode == 0:
                    return "done"
            except (OSError, subprocess.SubprocessError):
                pass
        return "failed"

    # ------------------------------------------------------------ windows
    def new_window(self, private: bool = False, urls: list[str] | None = None):
        from .ui.mainwindow import BrowserWindow
        w = BrowserWindow(self, private=private, urls=urls)
        self.windows.append(w)
        w.show()
        return w

    def open_urls(self, urls: list[str]) -> None:
        w = next((w for w in reversed(self.windows) if not w.private), None)
        if w is None:
            self.new_window(urls=urls)
        else:
            for u in urls:
                w.add_tab(u)
            w.raise_()
            w.activateWindow()

    def _shutdown(self) -> None:
        self.clipboard.clear_now()
        self.account.lock()
        self.history.close()


# ====================================================================== single instance (open links in the running browser)
class SingleInstance(QObject):
    urls_received = Signal(list)

    def __init__(self, key: str, parent=None):
        super().__init__(parent)
        self.name = f"{APP_SLUG}-{key}"
        self.server: QLocalServer | None = None

    def send_to_running(self, urls: list[str]) -> bool:
        s = QLocalSocket()
        s.connectToServer(self.name)
        if not s.waitForConnected(300):
            return False
        s.write(json.dumps(urls).encode() + b"\n")
        s.waitForBytesWritten(1000)
        s.disconnectFromServer()
        return True

    def listen(self) -> None:
        QLocalServer.removeServer(self.name)
        self.server = QLocalServer(self)
        self.server.newConnection.connect(self._conn)
        self.server.listen(self.name)

    def _conn(self) -> None:
        sock = self.server.nextPendingConnection()
        sock.waitForReadyRead(500)
        try:
            urls = [u for u in json.loads(bytes(sock.readAll()).decode() or "[]") if isinstance(u, str)]
        except ValueError:
            urls = []
        sock.disconnectFromServer()
        self.urls_received.emit(urls)
