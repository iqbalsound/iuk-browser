"""Apply application themes (Fusion style + palette) and expose the icon color."""
from __future__ import annotations

from PySide6.QtGui import QColor, QPalette
from PySide6.QtWidgets import QApplication, QStyleFactory

from ..core import themes

_default_style: str | None = None
_default_palette: QPalette | None = None


def apply_theme(app: QApplication, setting: dict | None) -> None:
    global _default_style, _default_palette
    if _default_style is None:
        _default_style, _default_palette = app.style().objectName(), QPalette(app.palette())
    pal = themes.resolve(setting)
    if pal is None:                                   # follow the operating system
        app.setStyle(QStyleFactory.create(_default_style) or QStyleFactory.create("Fusion"))
        app.setPalette(_default_palette)
        return
    app.setStyle(QStyleFactory.create("Fusion"))
    p = QPalette()
    C = QColor
    for role, key in [(QPalette.ColorRole.Window, "window"), (QPalette.ColorRole.WindowText, "text"), (QPalette.ColorRole.Base, "base"),
                      (QPalette.ColorRole.AlternateBase, "alt_base"), (QPalette.ColorRole.ToolTipBase, "base"), (QPalette.ColorRole.ToolTipText, "text"),
                      (QPalette.ColorRole.Text, "text"), (QPalette.ColorRole.Button, "button"), (QPalette.ColorRole.ButtonText, "text"),
                      (QPalette.ColorRole.Highlight, "accent"), (QPalette.ColorRole.HighlightedText, "on_accent"), (QPalette.ColorRole.Link, "accent"),
                      (QPalette.ColorRole.PlaceholderText, "disabled")]:
        p.setColor(role, C(pal[key]))
    for role in (QPalette.ColorRole.WindowText, QPalette.ColorRole.Text, QPalette.ColorRole.ButtonText):
        p.setColor(QPalette.ColorGroup.Disabled, role, C(pal["disabled"]))
    app.setPalette(p)


def icon_color(app: QApplication) -> str:
    return app.palette().color(QPalette.ColorRole.WindowText).name()
