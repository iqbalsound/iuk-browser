"""QR code drawing (segno) and decoding (zxing-cpp) for the pairing and 2FA dialogs."""
from __future__ import annotations

import numpy as np
import segno
import zxingcpp
from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QImage, QPainter, QPixmap


def qr_pixmap(text: str, size: int = 320) -> QPixmap:
    q = segno.make(text, error="m", boost_error=False)
    rows = [list(r) for r in q.matrix]
    n, border = len(rows), 4
    scale = max(2, size // (n + 2 * border))
    side = (n + 2 * border) * scale
    pm = QPixmap(side, side)
    pm.fill(Qt.GlobalColor.white)
    p = QPainter(pm)
    p.setPen(Qt.PenStyle.NoPen)
    p.setBrush(QColor("#000000"))
    for r in range(n):
        for c in range(n):
            if rows[r][c]:
                p.drawRect((c + border) * scale, (r + border) * scale, scale, scale)
    p.end()
    return pm


def decode_qimage(img: QImage) -> str | None:
    """Text of the first QR code in the image, or None."""
    if img.isNull():
        return None
    g = img.convertToFormat(QImage.Format.Format_Grayscale8)
    buf = np.frombuffer(g.constBits(), dtype=np.uint8).reshape(g.height(), g.bytesPerLine())[:, : g.width()]
    for r in zxingcpp.read_barcodes(buf, formats=zxingcpp.BarcodeFormat.QRCode):
        return r.text
    return None
