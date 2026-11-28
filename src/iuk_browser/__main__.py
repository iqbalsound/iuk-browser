"""Entry point: `iuk-browser [--private] [--data-dir DIR] [URL ...]`."""
from __future__ import annotations

import argparse
import getpass
import os
import sys

from . import APP_NAME, APP_SLUG, __version__


def main(argv: list[str] | None = None) -> int:
    ap = argparse.ArgumentParser(prog=APP_SLUG, description=f"{APP_NAME} {__version__}")
    ap.add_argument("urls", nargs="*", help="addresses to open")
    ap.add_argument("--private", action="store_true", help="open a private window")
    ap.add_argument("--data-dir", help="profile directory (default: the platform's application data folder)")
    ap.add_argument("--version", action="version", version=f"{APP_NAME} {__version__}")
    args, qt_args = ap.parse_known_args(argv if argv is not None else sys.argv[1:])

    os.environ.setdefault("QTWEBENGINE_DICTIONARIES_PATH", "")
    from PySide6.QtCore import QCoreApplication, Qt
    from PySide6.QtGui import QGuiApplication
    from PySide6.QtWidgets import QApplication

    QCoreApplication.setApplicationName(APP_SLUG)
    QCoreApplication.setApplicationVersion(__version__)
    QCoreApplication.setOrganizationName("IUK")
    QCoreApplication.setAttribute(Qt.ApplicationAttribute.AA_ShareOpenGLContexts, True)   # required before QApplication for WebEngine
    app = QApplication([sys.argv[0], *qt_args])
    QGuiApplication.setDesktopFileName(APP_SLUG)         # taskbar / minimized-window icon on Wayland and X11 matches iuk-browser.desktop
    from .app import AppContext, SingleInstance, app_icon
    app.setWindowIcon(app_icon())

    from pathlib import Path
    inst = SingleInstance((Path(args.data_dir).name if args.data_dir else "") + "-" + getpass.getuser())
    urls = [u for u in args.urls]
    if not args.private and inst.send_to_running(urls):   # another instance owns this profile: hand over the links and quit
        return 0
    ctx = AppContext(app, Path(args.data_dir) if args.data_dir else None)
    if not args.private:
        inst.listen()
        inst.urls_received.connect(lambda u: ctx.open_urls(u) if u else (ctx.windows and ctx.windows[-1].activateWindow()))
    ctx.new_window(private=args.private, urls=urls or None)
    ctx.maybe_auto_check_updates()
    return app.exec()


if __name__ == "__main__":
    raise SystemExit(main())
