# PyInstaller spec: `pyinstaller packaging/iuk-browser.spec --noconfirm` -> dist/iuk-browser/ (binary: iuk-browser[.exe])
import os
import sys
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")   # the build machine may be headless (CI); Qt hooks import PySide6

ROOT = Path(SPECPATH).parent
PKG = ROOT / "src" / "iuk_browser"
ICON = ROOT / "branding" / "generated" / "iuk-browser.ico"

# Qt modules the browser does not use: keep the bundle (and the DEB/RPM/installer) smaller.
EXCLUDES = [
    "PySide6.Qt3DCore", "PySide6.Qt3DRender", "PySide6.Qt3DInput", "PySide6.Qt3DLogic", "PySide6.Qt3DAnimation", "PySide6.Qt3DExtras",
    "PySide6.QtCharts", "PySide6.QtDataVisualization", "PySide6.QtQuick3D", "PySide6.QtGraphs", "PySide6.QtSensors",
    "PySide6.QtBluetooth", "PySide6.QtNfc", "PySide6.QtSerialPort", "PySide6.QtSerialBus", "PySide6.QtTest",
    "PySide6.QtRemoteObjects", "PySide6.QtScxml", "PySide6.QtStateMachine", "PySide6.QtSql", "PySide6.QtHelp",
    "PySide6.QtDesigner", "PySide6.QtUiTools", "PySide6.QtPositioning", "PySide6.QtLocation", "PySide6.QtTextToSpeech",
    "tkinter", "unittest", "pytest",
]

a = Analysis(
    [str(ROOT / "packaging" / "launcher.py")],
    pathex=[str(ROOT / "src")],
    datas=[(str(PKG / "resources"), "iuk_browser/resources"), (str(PKG / "i18n"), "iuk_browser/i18n")],
    hiddenimports=["PySide6.QtWebEngineWidgets", "PySide6.QtWebEngineCore", "PySide6.QtWebChannel", "PySide6.QtMultimedia",
                   "PySide6.QtSvg", "PySide6.QtNetwork"],
    excludes=EXCLUDES,
)
pyz = PYZ(a.pure)
exe = EXE(pyz, a.scripts, [], exclude_binaries=True, name="iuk-browser", console=False,
          icon=str(ICON) if sys.platform.startswith("win") and ICON.exists() else None)
coll = COLLECT(exe, a.binaries, a.datas, strip=False, upx=False, name="iuk-browser")

if sys.platform == "darwin":
    sys.path.insert(0, str(PKG.parent))
    from iuk_browser import __version__ as VERSION

    app = BUNDLE(
        coll, name="IUK Browser.app", icon=str(ROOT / "branding" / "generated" / "iuk-browser.icns"),
        bundle_identifier="org.iuk.browser",
        info_plist={
            "CFBundleName": "IUK Browser", "CFBundleDisplayName": "IUK Browser", "CFBundleShortVersionString": VERSION,
            "CFBundleVersion": VERSION, "NSHighResolutionCapable": True,
            "NSCameraUsageDescription": "IUK Browser uses the camera to scan pairing QR codes and for web pages you allow.",
            "NSMicrophoneUsageDescription": "Web pages you allow can use the microphone.",
            "CFBundleURLTypes": [{"CFBundleURLName": "Web site URL", "CFBundleURLSchemes": ["http", "https"]}],
            "CFBundleDocumentTypes": [{"CFBundleTypeName": "HTML document", "CFBundleTypeRole": "Viewer", "LSItemContentTypes": ["public.html"]}],
        },
    )
