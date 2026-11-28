"""Settings and About dialogs."""
from __future__ import annotations

from PySide6.QtCore import Qt
from PySide6.QtGui import QColor, QPixmap
from PySide6.QtWidgets import (QCheckBox, QColorDialog, QFileDialog, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout, QLabel,
                               QLineEdit, QPlainTextEdit, QPushButton, QRadioButton, QSlider, QSpinBox, QTabWidget, QVBoxLayout, QWidget)

from .. import __version__
from ..core import themes
from ..core.settings import SEARCH_ENGINES
from ..i18n import LANGS, tr
from .dialogs import PairDialog, TwoFactorDialog


class ColorButton(QPushButton):
    def __init__(self, color: str):
        super().__init__()
        self.color = color
        self.clicked.connect(self._pick)
        self._paint()

    def _paint(self):
        self.setStyleSheet(f"background:{self.color}; min-width:48px; min-height:22px; border:1px solid #888;")

    def _pick(self):
        c = QColorDialog.getColor(QColor(self.color), self)
        if c.isValid():
            self.color = c.name()
            self._paint()


def ctx_rules(ctx) -> int:
    return ctx.profiles.blocker.rule_count


class SettingsDialog(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx, s = ctx, ctx.settings
        self.setWindowTitle(tr("Settings"))
        self.resize(560, 520)
        tabs = QTabWidget()

        # ---- General
        g = QWidget()
        f = QFormLayout(g)
        self.home = QLineEdit(s["homepage"])
        self.engine = QComboBox()
        self.engine.addItems(list(SEARCH_ENGINES))
        self.engine.setCurrentText(s["search_engine"])
        self.lang = QComboBox()
        self.lang.addItem(tr("Automatic"), "auto")
        for code, name in LANGS.items():
            self.lang.addItem(name, code)
        self.lang.setCurrentIndex(max(0, self.lang.findData(s["language"])))
        self.restore = QCheckBox(tr("Reopen my tabs when the browser starts"))
        self.restore.setChecked(s["restore_session"])
        self.force_dark = QCheckBox(tr("Ask web pages for a dark appearance (Chromium)"))
        self.force_dark.setChecked(s["force_dark_pages"])
        f.addRow(tr("Home page"), self.home)
        f.addRow(tr("Search engine"), self.engine)
        f.addRow(tr("Language"), self.lang)
        f.addRow("", self.restore)
        f.addRow("", self.force_dark)
        f.addRow("", QLabel(tr("Language changes apply after a restart.")))
        tabs.addTab(g, tr("General"))

        # ---- Appearance
        a = QWidget()
        al = QVBoxLayout(a)
        th = s["theme"]
        self.theme = QComboBox()
        self.theme.addItem(tr("Follow the system"), "system")
        for t in themes.THEMES:
            self.theme.addItem(tr(t["name"]), t["id"])
        self.theme.addItem(tr("Custom"), "custom")
        self.theme.setCurrentIndex(max(0, self.theme.findData(th["id"])))
        self.c_bg, self.c_fg, self.c_acc = ColorButton(th.get("bg", "#1c1b22")), ColorButton(th.get("fg", "#fbfbfe")), ColorButton(th.get("accent", "#00ddff"))
        cr = QHBoxLayout()
        for lbl, b in ((tr("Background"), self.c_bg), (tr("Text"), self.c_fg), (tr("Accent"), self.c_acc)):
            cr.addWidget(QLabel(lbl))
            cr.addWidget(b)
        al.addWidget(QLabel(tr("Browser theme")))
        al.addWidget(self.theme)
        al.addLayout(cr)
        d = s["display"]
        al.addWidget(QLabel(tr("Color invert and page filters")))
        self.r_off, self.r_sites, self.r_all = QRadioButton(tr("Off")), QRadioButton(tr("Only on the sites listed below")), QRadioButton(tr("On all sites"))
        {"off": self.r_off, "sites": self.r_sites, "all": self.r_all}[d["mode"]].setChecked(True)
        for r in (self.r_off, self.r_sites, self.r_all):
            al.addWidget(r)
        self.sites = QPlainTextEdit("\n".join(d["sites"]))
        self.sites.setPlaceholderText(tr("one host per line, e.g. news.ycombinator.com"))
        self.sites.setMaximumHeight(70)
        al.addWidget(self.sites)
        self.keep = QCheckBox(tr("Keep images and video natural when inverted"))
        self.keep.setChecked(d["keepMedia"])
        al.addWidget(self.keep)
        self.sliders = {}
        for key, lbl, lo, hi in (("brightness", tr("Brightness"), 50, 150), ("contrast", tr("Contrast"), 50, 150), ("sepia", tr("Sepia"), 0, 100)):
            row = QHBoxLayout()
            sl = QSlider(Qt.Orientation.Horizontal)
            sl.setRange(lo, hi)
            sl.setValue(d[key])
            val = QLabel(f"{d[key]}%")
            sl.valueChanged.connect(lambda v, l=val: l.setText(f"{v}%"))
            row.addWidget(QLabel(lbl))
            row.addWidget(sl, 1)
            row.addWidget(val)
            al.addLayout(row)
            self.sliders[key] = sl
        al.addStretch()
        tabs.addTab(a, tr("Appearance"))

        # ---- Sync
        y = QWidget()
        yl = QVBoxLayout(y)
        st = ctx.account.status()
        self.server = QLineEdit(st["server"] or s.get("sync_server", ""))
        self.server.setPlaceholderText("https://sync.example.com")
        self.interval = QSpinBox()
        self.interval.setRange(1, 240)
        self.interval.setSuffix(" min")
        self.interval.setValue(s["sync_interval_minutes"])
        yf = QFormLayout()
        yf.addRow(tr("Sync server"), self.server)
        yf.addRow(tr("Sync every"), self.interval)
        yl.addLayout(yf)
        yl.addWidget(QLabel(tr("Signed in as {}", st["username"]) if st["setup"] else tr("This device is not set up yet.")))
        for text, fn in ((tr("Pair another device (QR)…"), lambda: PairDialog(ctx, self, "show").exec()),
                         (tr("Second factor for the sync relay…"), lambda: TwoFactorDialog(ctx, self).exec()),
                         (tr("Sync now"), ctx.sync_async)):
            b = QPushButton(text)
            b.clicked.connect(fn)
            b.setEnabled(st["setup"] and st["unlocked"])
            yl.addWidget(b)
        forget = QPushButton(tr("Forget this device…"))
        forget.setEnabled(st["setup"])
        forget.clicked.connect(self._forget)
        yl.addWidget(forget)
        yl.addStretch()
        tabs.addTab(y, tr("Sync"))

        # ---- Security
        c = QWidget()
        cf = QFormLayout(c)
        self.clip = QSpinBox()
        self.clip.setRange(0, 600)
        self.clip.setSuffix(" s")
        self.clip.setSpecialValueText(tr("Never"))
        self.clip.setValue(s["clipboard_clear_seconds"])
        cf.addRow(tr("Clear copied passwords after"), self.clip)
        self.autolock = QSpinBox()
        self.autolock.setRange(0, 1440)
        self.autolock.setSuffix(" min")
        self.autolock.setSpecialValueText(tr("Never"))
        self.autolock.setValue(s["auto_lock_minutes"])
        cf.addRow(tr("Lock passwords after"), self.autolock)
        bl = s["blocker"]
        self.block_on = QCheckBox(tr("Block trackers and ads"))
        self.block_on.setChecked(bl["enabled"])
        self._extra_lists = list(bl["extra_lists"])
        self.block_info = QLabel(tr("Loaded {} rules", ctx.profiles.blocker.rule_count))
        add_list = QPushButton(tr("Add filter list…"))
        add_list.clicked.connect(self._add_list)
        cf.addRow("", self.block_on)
        cf.addRow(tr("Filter lists (Adblock Plus syntax)"), add_list)
        cf.addRow("", self.block_info)
        tabs.addTab(c, tr("Security"))

        # ---- Updates
        u = QWidget()
        ul = QVBoxLayout(u)
        self.auto_upd = QCheckBox(tr("Check for updates automatically"))
        self.auto_upd.setChecked(s["check_updates"])
        self.channel = QComboBox()
        self.channel.addItems(["stable", "beta"])
        self.channel.setCurrentText(s["update_channel"])
        chk = QPushButton(tr("Check now"))
        chk.clicked.connect(lambda: ctx.check_updates(manual=True, parent=self))
        for w in (self.auto_upd, QLabel(tr("Update channel")), self.channel, chk, QLabel(tr("Version {}", __version__))):
            ul.addWidget(w)
        ul.addStretch()
        tabs.addTab(u, tr("Updates"))

        bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
        bb.button(QDialogButtonBox.StandardButton.Ok).setText(tr("OK"))
        bb.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Cancel"))
        bb.accepted.connect(self._apply)
        bb.rejected.connect(self.reject)
        lay = QVBoxLayout(self)
        lay.addWidget(tabs)
        lay.addWidget(bb)

    def _add_list(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Add filter list…"), "", "Filter lists (*.txt *.list);;All files (*)")
        if path and path not in self._extra_lists:
            self._extra_lists.append(path)
            from ..core.blocker import Blocker
            probe = Blocker()
            try:
                self.block_info.setText(tr("Loaded {} rules", ctx_rules(self.ctx) + probe.load_file(path)))
            except OSError as e:
                self.block_info.setText(str(e))

    def _forget(self):
        from PySide6.QtWidgets import QMessageBox
        if QMessageBox.question(self, tr("IUK Browser"), tr("Remove the local vault from this device? Data already on the sync server is untouched.")) == QMessageBox.StandardButton.Yes:
            self.ctx.account.wipe()
            self.ctx.vault_state_changed.emit()
            self.accept()

    def _apply(self):
        tid = self.theme.currentData()
        theme = {"id": tid} if tid != "custom" else {"id": "custom", "bg": self.c_bg.color, "fg": self.c_fg.color, "accent": self.c_acc.color}
        mode = "all" if self.r_all.isChecked() else "sites" if self.r_sites.isChecked() else "off"
        display = {"mode": mode, "sites": [x.strip().lower() for x in self.sites.toPlainText().splitlines() if x.strip()],
                   "keepMedia": self.keep.isChecked(), **{k: s.value() for k, s in self.sliders.items()}}
        self.ctx.apply_settings({
            "homepage": self.home.text().strip() or "https://duckduckgo.com/", "search_engine": self.engine.currentText(),
            "language": self.lang.currentData(), "restore_session": self.restore.isChecked(), "force_dark_pages": self.force_dark.isChecked(),
            "theme": theme, "display": display, "sync_server": self.server.text().strip(), "sync_interval_minutes": self.interval.value(),
            "clipboard_clear_seconds": self.clip.value(), "auto_lock_minutes": self.autolock.value(),
            "blocker": {"enabled": self.block_on.isChecked(), "allow_sites": self.ctx.settings["blocker"]["allow_sites"], "extra_lists": self._extra_lists}, "check_updates": self.auto_upd.isChecked(), "update_channel": self.channel.currentText(),
        })
        self.accept()


class AboutDialog(QDialog):
    def __init__(self, parent=None):
        super().__init__(parent)
        from PySide6.QtCore import qVersion
        from PySide6.QtWebEngineCore import qWebEngineChromiumVersion
        from pathlib import Path
        import PySide6
        self.setWindowTitle(tr("About IUK Browser"))
        logo = QLabel()
        logo.setPixmap(QPixmap(str(Path(__file__).resolve().parent.parent / "resources" / "icons" / "iuk-browser-128.png")))
        info = QLabel(f"<h2>IUK Browser {__version__}</h2><p>Qt {qVersion()} · PySide6 {PySide6.__version__}<br>Chromium {qWebEngineChromiumVersion()}</p>"
                      f"<p>{tr('Encrypted bookmark and password sync, built on Qt WebEngine.')}<br>MIT License</p>")
        info.setTextFormat(Qt.TextFormat.RichText)
        row = QHBoxLayout(self)
        row.addWidget(logo)
        row.addWidget(info)
