from PySide6.QtCore import QEventLoop, QTimer, QUrl


def load(view, url, timeout=20000):
    loop = QEventLoop()
    ok = []
    view.loadFinished.connect(lambda v: (ok.append(v), loop.quit()))
    QTimer.singleShot(timeout, loop.quit)
    view.load(QUrl(url))
    loop.exec()
    assert ok and ok[0], f"page did not load: {url}"


def js(view, source, app_world=False, timeout=8000):
    """Evaluate JS synchronously; main world by default, application world if asked."""
    from iuk_browser.ui.web import APP_WORLD
    loop, out = QEventLoop(), []
    cb = lambda r: (out.append(r), loop.quit())
    if app_world:
        view.page().runJavaScript(source, APP_WORLD, cb)
    else:
        view.page().runJavaScript(source, cb)
    QTimer.singleShot(timeout, loop.quit)
    loop.exec()
    assert out, f"no result for {source!r}"
    return out[0]


def wait_until(cond, timeout=8000, step=50):
    from PySide6.QtTest import QTest
    waited = 0
    while not cond() and waited < timeout:
        QTest.qWait(step)
        waited += step
    return cond()
