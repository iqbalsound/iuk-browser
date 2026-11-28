"""Copy secrets to the clipboard and clear them automatically."""
from __future__ import annotations

from PySide6.QtCore import QMimeData, QObject, QTimer
from PySide6.QtGui import QGuiApplication


class ClipboardGuard(QObject):
    def __init__(self, seconds_provider, parent=None):
        super().__init__(parent)
        self._seconds = seconds_provider
        self._value: str | None = None
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.timeout.connect(self.clear_now)
        self.interval_override_ms: int | None = None      # tests

    def copy_secret(self, text: str) -> None:
        mime = QMimeData()
        mime.setText(text)
        # Ask clipboard managers not to record the value (KDE Klipper, Windows clipboard history / cloud sync)
        mime.setData("x-kde-passwordManagerHint", b"secret")
        mime.setData('application/x-qt-windows-mime;value="ExcludeClipboardContentFromMonitorProcessing"', b"\x01\x00\x00\x00")
        mime.setData('application/x-qt-windows-mime;value="CanIncludeInClipboardHistory"', b"\x00\x00\x00\x00")
        mime.setData('application/x-qt-windows-mime;value="CanUploadToCloudClipboard"', b"\x00\x00\x00\x00")
        QGuiApplication.clipboard().setMimeData(mime)
        self._value = text
        ms = self.interval_override_ms if self.interval_override_ms is not None else int(self._seconds()) * 1000
        if ms > 0:
            self._timer.start(ms)
        else:
            self._timer.stop()

    def clear_now(self) -> bool:
        """Clears the clipboard only if it still holds the secret we put there (never wipes something newer)."""
        cb = QGuiApplication.clipboard()
        cleared = False
        if self._value is not None and cb.text() == self._value:
            cb.clear()
            cleared = True
        self._value = None
        self._timer.stop()
        return cleared
