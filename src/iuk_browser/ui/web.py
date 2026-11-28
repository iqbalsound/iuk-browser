"""Qt WebEngine plumbing: profiles, injected scripts (autofill, color invert), the Python bridge, the web view."""
from __future__ import annotations

import json
import time
from pathlib import Path

from PySide6.QtCore import QFile, QIODevice, QObject, Signal, Slot, QUrl
from PySide6.QtWebChannel import QWebChannel
from PySide6.QtWebEngineCore import (QWebEnginePage, QWebEngineProfile, QWebEngineScript, QWebEngineSettings, QWebEngineUrlRequestInfo,
                                     QWebEngineUrlRequestInterceptor)
from PySide6.QtWebEngineWidgets import QWebEngineView

from ..core import display
from ..core.blocker import Blocker

JS_DIR = Path(__file__).resolve().parent.parent / "resources" / "js"
APP_WORLD = QWebEngineScript.ScriptWorldId.ApplicationWorld   # isolated from page scripts: pages cannot see or tamper


BLOCKLIST_DIR = Path(__file__).resolve().parent.parent / "resources" / "blocklists"
_RT = QWebEngineUrlRequestInfo.ResourceType
_TYPE_MAP = {_RT.ResourceTypeScript: "script", _RT.ResourceTypeImage: "image", _RT.ResourceTypeStylesheet: "stylesheet",
             _RT.ResourceTypeFontResource: "font", _RT.ResourceTypeXhr: "xmlhttprequest", _RT.ResourceTypeSubFrame: "subdocument",
             _RT.ResourceTypeMedia: "media", _RT.ResourceTypePing: "ping", _RT.ResourceTypeObject: "object"}


class RequestBlocker(QWebEngineUrlRequestInterceptor):
    """Runs on Chromium's IO thread for every request. Never raises, never blocks a page navigation."""

    def __init__(self, blocker: Blocker, parent=None):
        super().__init__(parent)
        self.blocker = blocker

    def interceptRequest(self, info):  # noqa: N802
        try:
            b = self.blocker
            if not b.enabled or info.resourceType() == _RT.ResourceTypeMainFrame:
                return
            fp = info.firstPartyUrl().host()
            if b.should_block(info.requestUrl().toString(), fp, _TYPE_MAP.get(info.resourceType(), "other")):
                info.block(True)
                b.blocked[fp] = b.blocked.get(fp, 0) + 1
        except Exception:  # noqa: BLE001  (a bug in a filter must never break page loading)
            pass


def _qrc(path: str) -> str:
    f = QFile(path)
    if not f.open(QIODevice.OpenModeFlag.ReadOnly):
        raise RuntimeError(f"Qt resource {path} not found")
    data = bytes(f.readAll()).decode()
    f.close()
    return data


def _script(name: str, source: str, point) -> QWebEngineScript:
    s = QWebEngineScript()
    s.setName(name)
    s.setSourceCode(source)
    s.setInjectionPoint(point)
    s.setWorldId(APP_WORLD)
    s.setRunsOnSubFrames(False)     # top frame only: never autofill into (hidden) iframes
    return s


def display_source(settings: dict) -> str:
    return (JS_DIR / "display.js").read_text("utf-8").replace("/*SETTINGS*/{}", json.dumps(display.normalize(settings)))


class ProfileManager:
    """One persistent profile for normal windows and one off-the-record profile for private windows."""

    def __init__(self, data_dir: Path, settings, parent: QObject | None = None):
        self.settings = settings
        data_dir = Path(data_dir)
        self.normal = QWebEngineProfile("iuk-browser", parent)
        self.normal.setPersistentStoragePath(str(data_dir / "webengine"))
        self.normal.setCachePath(str(data_dir / "cache"))
        self.normal.setPersistentCookiesPolicy(QWebEngineProfile.PersistentCookiesPolicy.AllowPersistentCookies)
        self.private = QWebEngineProfile(parent)    # no name => off the record
        self.normal.setPersistentPermissionsPolicy(QWebEngineProfile.PersistentPermissionsPolicy.StoreOnDisk)
        self.private.setPersistentPermissionsPolicy(QWebEngineProfile.PersistentPermissionsPolicy.StoreInMemory)
        self._channel_js = _qrc(":/qtwebchannel/qwebchannel.js")
        self._autofill = self._channel_js + "\n" + (JS_DIR / "autofill.js").read_text("utf-8")
        self.blocker = Blocker()
        self._interceptors = []
        for p in self.profiles():
            p.scripts().insert(_script("iuk-autofill", self._autofill, QWebEngineScript.InjectionPoint.DocumentReady))
            self._set_display(p, settings["display"])
            ic = RequestBlocker(self.blocker, p)
            p.setUrlRequestInterceptor(ic)
            self._interceptors.append(ic)
        self.reload_blocker(settings["blocker"])
        self.apply_force_dark(bool(settings["force_dark_pages"]))

    def profiles(self):
        return (self.normal, self.private)

    def _set_display(self, profile: QWebEngineProfile, s: dict) -> None:
        coll = profile.scripts()
        for old in coll.find("iuk-display"):
            coll.remove(old)
        coll.insert(_script("iuk-display", display_source(s), QWebEngineScript.InjectionPoint.DocumentCreation))

    def update_display(self, s: dict) -> None:
        """New pages get the new script; pages that are already open are updated live."""
        for p in self.profiles():
            self._set_display(p, s)
        self.settings.set("display", s)

    def reload_blocker(self, cfg: dict) -> int:
        """Rebuild the filter set (starter list + the user's extra lists) and swap it in atomically. Returns the rule count."""
        new = Blocker()
        new.enabled = bool(cfg.get("enabled", True))
        new.allow_sites = {h.lower() for h in cfg.get("allow_sites", [])}
        new.blocked = self.blocker.blocked
        new.load_file(BLOCKLIST_DIR / "iuk-basic.txt")
        for path in cfg.get("extra_lists", []):
            try:
                new.load_file(path)
            except OSError:
                pass
        self.blocker = new
        for ic in self._interceptors:
            ic.blocker = new
        return new.rule_count

    def apply_force_dark(self, on: bool) -> None:
        attr = getattr(QWebEngineSettings.WebAttribute, "ForceDarkMode", None)
        if attr is not None:
            for p in self.profiles():
                p.settings().setAttribute(attr, on)


class PageBridge(QObject):
    """The only object web pages' (isolated-world) scripts can call. It takes data in and never gives secrets out."""

    credentials_captured = Signal(str, str)

    @Slot(str, str)
    def captured(self, username: str, password: str) -> None:
        if len(username) < 512 and 0 < len(password) < 1024:
            self.credentials_captured.emit(username, password)


class WebView(QWebEngineView):
    """A tab's web view. The page URL used for password matching always comes from Qt, never from page script."""

    new_tab_requested = Signal(object)

    def __init__(self, profile: QWebEngineProfile, private: bool = False, parent=None):
        super().__init__(parent)
        self.private = private
        page = QWebEnginePage(profile, self)
        self.setPage(page)
        self.bridge = PageBridge(self)
        self.channel = QWebChannel(self)
        self.channel.registerObject("iukBridge", self.bridge)
        page.setWebChannel(self.channel, APP_WORLD)
        self.pending: tuple[str, str, str, float] | None = None     # (host, username, password, time) awaiting "Save?"
        self.bridge.credentials_captured.connect(self._captured)
        self.captured_cb = None

    def _captured(self, username: str, password: str) -> None:
        host = self.url().host()
        if self.private or not host:
            return
        self.pending = (host, username, password, time.time())
        if self.captured_cb:
            self.captured_cb(self)

    def createWindow(self, _type):  # target=_blank, window.open
        holder: list = []
        self.new_tab_requested.emit(holder)
        return holder[0] if holder else None

    def run_app_js(self, source: str, callback=None) -> None:
        if callback:
            self.page().runJavaScript(source, APP_WORLD, callback)
        else:
            self.page().runJavaScript(source, APP_WORLD)

    def fill(self, username: str, password: str, callback=None) -> None:
        self.run_app_js(f"window.__iukFill({json.dumps(username)}, {json.dumps(password)})", callback)

    def apply_display(self, settings: dict) -> None:
        self.run_app_js(f"window.__iukApplyDisplay && window.__iukApplyDisplay({json.dumps(display.normalize(settings))})")

    @staticmethod
    def host_of(url: QUrl) -> str:
        return url.host().removeprefix("www.").lower()
