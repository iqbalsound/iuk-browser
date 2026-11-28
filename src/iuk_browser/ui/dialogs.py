"""Dialogs. All user-visible text goes through tr() so every dialog follows the chosen language."""
from __future__ import annotations

from PySide6.QtCore import QStandardPaths, Qt, QTimer, QUrl
from PySide6.QtGui import QDesktopServices, QImage
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QMessageBox, QPlainTextEdit, QProgressBar, QPushButton, QSplitter, QTableWidget,
                               QTableWidgetItem, QTabWidget, QTreeWidget, QTreeWidgetItem, QVBoxLayout, QWidget)

from ..core import csvio, merge as M, pairing
from ..core.account import Account, AccountError
from ..core.transport import OtpRequired, RelayError
from ..core.util import gen_password
from ..i18n import tr
from . import qrtools


def _msg(parent, text: str, error: bool = False) -> None:
    (QMessageBox.warning if error else QMessageBox.information)(parent, tr("IUK Browser"), text)


def _buttons(dlg, ok_text=None) -> QDialogButtonBox:
    bb = QDialogButtonBox(QDialogButtonBox.StandardButton.Ok | QDialogButtonBox.StandardButton.Cancel)
    bb.button(QDialogButtonBox.StandardButton.Ok).setText(ok_text or tr("OK"))
    bb.button(QDialogButtonBox.StandardButton.Cancel).setText(tr("Cancel"))
    bb.rejected.connect(dlg.reject)
    return bb


def _secret_edit(placeholder: str) -> QLineEdit:
    e = QLineEdit()
    e.setEchoMode(QLineEdit.EchoMode.Password)
    e.setPlaceholderText(placeholder)
    return e


class _Cancellable:
    """Mixin: long key derivations run in a worker with an indeterminate progress bar. Cancel (or closing the dialog)
    stops the operation before anything is stored."""
    _handle = None

    def _make_progress(self) -> QProgressBar:
        self.progress = QProgressBar()
        self.progress.setRange(0, 0)
        self.progress.setTextVisible(False)
        self.progress.setMaximumHeight(8)
        self.progress.hide()
        return self.progress

    def _start(self, fn, done):
        self.progress.show()

        def finish(res, err):
            self._handle = None
            self.progress.hide()
            done(res, err)
        self._handle = self.ctx.run_async(fn, finish)

    def _on_cancelled(self):
        pass

    def reject(self):
        if self._handle is not None:
            self._handle.cancel()
            self._handle = None
            self.progress.hide()
            self._on_cancelled()
            return
        super().reject()


# ================================================================== account: setup / unlock
class SetupDialog(_Cancellable, QDialog):
    def __init__(self, ctx, parent=None, prefill=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(tr("Set up IUK Browser sync and passwords"))
        self.setMinimumWidth(460)
        prefill = prefill or {}
        self.user = QLineEdit(prefill.get("username", ""))
        self.user.setPlaceholderText(tr("User name or e-mail (same on every device)"))
        self.secret = _secret_edit(tr("Secret connectivity key (min 12 characters)"))
        self.secret.setText(prefill.get("secret", ""))
        gen = QPushButton(tr("Generate key"))
        gen.clicked.connect(lambda: (self.secret.setEchoMode(QLineEdit.EchoMode.Normal), self.secret.setText(gen_password(32))))
        self.server = QLineEdit(prefill.get("server", ctx.settings.get("sync_server", "")))
        self.server.setPlaceholderText(tr("Sync server URL (optional), e.g. https://sync.example.com"))
        self.otp = QLineEdit()
        self.otp.setPlaceholderText(tr("Second-factor code or recovery code"))
        self.otp.hide()
        self.status = QLabel()
        self.status.setWordWrap(True)
        row = QHBoxLayout()
        row.addWidget(self.secret)
        row.addWidget(gen)
        scan = QPushButton(tr("Scan pairing QR from another device…"))
        scan.clicked.connect(self._scan)
        self.ok = _buttons(self, tr("Create vault"))
        self.ok.accepted.connect(self._go)
        lay = QVBoxLayout(self)
        note = QLabel(tr("Use the same user name and secret key on your other devices to sync. The key never leaves this device and cannot be recovered. Write it down."))
        note.setWordWrap(True)
        for w in (note, self.user):
            lay.addWidget(w)
        lay.addLayout(row)
        for w in (self.server, self.otp, self.status, self._make_progress(), scan, self.ok):
            lay.addWidget(w)

    def _on_cancelled(self):
        self.ok.setEnabled(True)
        self.status.setText(tr("Cancelled."))

    def _scan(self):
        d = PairDialog(self.ctx, self, mode="scan")
        d.paired.connect(lambda p: (self.user.setText(p.username), self.secret.setText(p.secret), self.server.setText(p.server)))
        d.exec()

    def _go(self):
        u, s, srv, code = self.user.text(), self.secret.text(), self.server.text(), self.otp.text().strip()
        self.ok.setEnabled(False)
        self.status.setText(tr("Deriving key (takes a moment)…"))

        def work(cancel):
            kw = {}
            if code:
                kw = {"recovery": code} if "-" in code else {"otp": code}
            self.ctx.account.setup(u, s, srv, cancel=cancel, **kw)

        def done(_r, err):
            self.ok.setEnabled(True)
            if isinstance(err, OtpRequired):
                self.otp.show()
                self.status.setText(tr("This account has a second factor. Enter the code from your authenticator app."))
            elif err:
                self.status.setText(str(err))
            else:
                self.ctx.settings.set("sync_server", srv.strip())
                self.accept()
        self._start(work, done)


class UnlockDialog(_Cancellable, QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(tr("Unlock IUK Browser"))
        self.setMinimumWidth(400)
        st = ctx.account.status()
        self.user = QLineEdit(st["username"])
        self.secret = _secret_edit(tr("Secret connectivity key"))
        self.status = QLabel()
        self.status.setWordWrap(True)
        self.ok = _buttons(self, tr("Unlock"))
        self.ok.accepted.connect(self._go)
        self.secret.returnPressed.connect(self._go)
        lay = QVBoxLayout(self)
        for w in (self.user, self.secret, self.status, self._make_progress(), self.ok):
            lay.addWidget(w)
        self.secret.setFocus()

    def _on_cancelled(self):
        self.ok.setEnabled(True)
        self.status.setText(tr("Cancelled."))

    def _go(self):
        if not self.ok.isEnabled():
            return
        u, s = self.user.text(), self.secret.text()
        self.ok.setEnabled(False)
        self.status.setText(tr("Unlocking…"))

        def done(_r, err):
            self.ok.setEnabled(True)
            if err:
                self.status.setText(str(err))
            else:
                self.accept()
        self._start(lambda cancel: self.ctx.account.unlock(u, s, cancel=cancel), done)


# ================================================================== passwords
class LoginEditDialog(QDialog):
    def __init__(self, parent=None, host="", username="", password="", notes=""):
        super().__init__(parent)
        self.setWindowTitle(tr("Login"))
        self.host, self.username, self.password = QLineEdit(host), QLineEdit(username), _secret_edit("")
        self.password.setText(password)
        self.notes = QLineEdit(notes)
        show = QCheckBox(tr("Show password"))
        show.toggled.connect(lambda on: self.password.setEchoMode(QLineEdit.EchoMode.Normal if on else QLineEdit.EchoMode.Password))
        gen = QPushButton(tr("Generate"))
        gen.clicked.connect(lambda: (show.setChecked(True), self.password.setText(gen_password(20))))
        pr = QHBoxLayout()
        pr.addWidget(self.password)
        pr.addWidget(gen)
        form = QFormLayout()
        form.addRow(tr("Site"), self.host)
        form.addRow(tr("User name"), self.username)
        form.addRow(tr("Password"), pr)
        form.addRow("", show)
        form.addRow(tr("Notes"), self.notes)
        bb = _buttons(self)
        bb.accepted.connect(self.accept)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(bb)

    def values(self):
        return self.host.text(), self.username.text(), self.password.text(), self.notes.text()


class VaultDialog(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(tr("Saved passwords"))
        self.resize(720, 460)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search"))
        self.search.textChanged.connect(self.refresh)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([tr("Site"), tr("User name"), tr("Notes")])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.itemDoubleClicked.connect(lambda *_: self.edit())
        side = QVBoxLayout()
        for text, fn in [(tr("Add…"), self.add), (tr("Edit…"), self.edit), (tr("Delete"), self.delete),
                         (tr("Copy user name"), self.copy_user), (tr("Copy password"), self.copy_pw),
                         (tr("Import CSV…"), self.import_csv), (tr("Export CSV…"), self.export_csv)]:
            b = QPushButton(text)
            b.clicked.connect(fn)
            side.addWidget(b)
        side.addStretch()
        self.hint = QLabel()
        self.hint.setWordWrap(True)
        body = QHBoxLayout()
        body.addWidget(self.table, 1)
        body.addLayout(side)
        lay = QVBoxLayout(self)
        lay.addWidget(self.search)
        lay.addLayout(body)
        lay.addWidget(self.hint)
        self.refresh()

    def _rows(self):
        t = self.search.text().lower()
        return [l for l in self.ctx.account.list_logins() if not t or t in (l["host"] + " " + l["username"]).lower()]

    def refresh(self):
        rows = self._rows()
        self.table.setRowCount(len(rows))
        for i, l in enumerate(rows):
            for j, v in enumerate((l["host"], l["username"], l["notes"])):
                it = QTableWidgetItem(v)
                it.setData(Qt.ItemDataRole.UserRole, l["id"])
                self.table.setItem(i, j, it)

    def _current(self):
        r = self.table.currentRow()
        return self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) if r >= 0 else None

    def add(self):
        d = LoginEditDialog(self)
        if d.exec():
            host, user, pw, notes = d.values()
            try:
                self.ctx.account.save_login(host, user, pw, notes)
            except AccountError as e:
                _msg(self, str(e), True)
            self.ctx.after_vault_change()
            self.refresh()

    def edit(self):
        lid = self._current()
        if not lid:
            return
        l = next(x for x in self.ctx.account.list_logins() if x["id"] == lid)
        d = LoginEditDialog(self, l["host"], l["username"], self.ctx.account.get_password(lid), l["notes"])
        if d.exec():
            host, user, pw, notes = d.values()
            try:
                if (host.lower(), user.lower()) != (l["host"], l["username"].lower()):
                    self.ctx.account.remove_login(lid)         # the id is host+user: a rename is delete + add
                self.ctx.account.save_login(host, user, pw, notes)
            except AccountError as e:
                _msg(self, str(e), True)
            self.ctx.after_vault_change()
            self.refresh()

    def delete(self):
        lid = self._current()
        if lid and QMessageBox.question(self, tr("IUK Browser"), tr("Delete this login?")) == QMessageBox.StandardButton.Yes:
            self.ctx.account.remove_login(lid)
            self.ctx.after_vault_change()
            self.refresh()

    def copy_user(self):
        r = self.table.currentRow()
        if r >= 0:
            self.ctx.clipboard.copy_secret(self.table.item(r, 1).text())

    def copy_pw(self):
        lid = self._current()
        if lid:
            self.ctx.clipboard.copy_secret(self.ctx.account.get_password(lid))
            secs = int(self.ctx.settings["clipboard_clear_seconds"])
            self.hint.setText(tr("Password copied. The clipboard is cleared in {} s.", secs) if secs else tr("Password copied."))

    def import_csv(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Import CSV…"), "", "CSV (*.csv)")
        if path:
            try:
                with open(path, encoding="utf-8-sig") as f:
                    n = self.ctx.account.import_logins(csvio.parse_logins(f.read()))
                self.hint.setText(tr("Imported {} logins. Delete the CSV file now: it holds plain-text passwords.", n))
            except (OSError, ValueError) as e:
                _msg(self, str(e), True)
            self.ctx.after_vault_change()
            self.refresh()

    def export_csv(self):
        if QMessageBox.question(self, tr("IUK Browser"), tr("The export contains all passwords in plain text. Continue?")) != QMessageBox.StandardButton.Yes:
            return
        path, _ = QFileDialog.getSaveFileName(self, tr("Export CSV…"), "iuk-passwords.csv", "CSV (*.csv)")
        if path:
            with open(path, "w", encoding="utf-8", newline="") as f:
                f.write(csvio.export_logins(self.ctx.account.export_logins()))


# ================================================================== bookmarks
ROOT_LABELS = lambda: {M.ROOT_TOOLBAR: tr("Bookmarks toolbar"), M.ROOT_MENU: tr("Bookmarks menu"),
                       M.ROOT_UNFILED: tr("Other bookmarks"), M.RECOVERED: tr("Recovered items")}


def folder_choices(store) -> list[tuple[str, str]]:
    """(label, folder id) for every folder, indented by depth."""
    labels, view, out = ROOT_LABELS(), store.view(), []

    def walk(node, depth):
        for ch in node["children"]:
            out.append(("    " * depth + ch["name"], ch["id"]))
            walk(ch, depth + 1)
    for rid in (M.ROOT_TOOLBAR, M.ROOT_MENU, M.ROOT_UNFILED):
        out.append((labels[rid], rid))
        walk(view[rid], 1)
    return out


class BookmarkEditDialog(QDialog):
    def __init__(self, store, parent=None, item=None, url="", title="", folder=M.ROOT_TOOLBAR):
        super().__init__(parent)
        self.store = store
        self.setWindowTitle(tr("Bookmark"))
        self.setMinimumWidth(420)
        self.url = QLineEdit(item["url"] if item else url)
        self.url.setReadOnly(bool(item))
        self.title = QLineEdit(item["title"] if item else title)
        self.folder = QComboBox()
        for label, fid in folder_choices(store):
            self.folder.addItem(label, fid)
        self.folder.setCurrentIndex(max(0, self.folder.findData(item["folder"] if item else folder)))
        self.tags = QLineEdit(", ".join(store.tags_of(item)) if item else "")
        self.tags.setPlaceholderText(tr("Tags, separated by commas"))
        existing = list(store.all_tags())
        self.hint = QLabel(tr("Existing tags: {}", ", ".join(existing[:12])) if existing else "")
        self.hint.setWordWrap(True)
        form = QFormLayout()
        form.addRow(tr("Address"), self.url)
        form.addRow(tr("Name"), self.title)
        form.addRow(tr("Folder"), self.folder)
        form.addRow(tr("Tags"), self.tags)
        bb = _buttons(self)
        bb.accepted.connect(self.accept)
        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(self.hint)
        lay.addWidget(bb)

    def values(self):
        return self.url.text().strip(), self.title.text().strip(), self.folder.currentData(), \
            [t.strip() for t in self.tags.text().split(",") if t.strip()]


class BookmarksDialog(QDialog):
    def __init__(self, ctx, parent=None, open_cb=None):
        super().__init__(parent)
        self.ctx, self.store, self.open_cb = ctx, ctx.store, open_cb
        self.setWindowTitle(tr("Bookmarks"))
        self.resize(900, 520)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search"))
        self.search.textChanged.connect(self.refresh_list)
        self.tree = QTreeWidget()
        self.tree.setHeaderHidden(True)
        self.tree.currentItemChanged.connect(lambda *_: (self.tag_list.clearSelection(), self.refresh_list()))
        self.tag_list = QListWidget()
        self.tag_list.itemSelectionChanged.connect(self.refresh_list)
        left = QSplitter(Qt.Orientation.Vertical)
        left.addWidget(self.tree)
        tw = QWidget()
        tl = QVBoxLayout(tw)
        tl.setContentsMargins(0, 0, 0, 0)
        tl.addWidget(QLabel(tr("Tags")))
        tl.addWidget(self.tag_list)
        left.addWidget(tw)
        self.table = QTableWidget(0, 4)
        self.table.setHorizontalHeaderLabels([tr("Name"), tr("Address"), tr("Tags"), tr("Folder")])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.itemDoubleClicked.connect(lambda *_: self.open())
        side = QVBoxLayout()
        for text, fn in [(tr("Open"), self.open), (tr("Edit…"), self.edit), (tr("Delete"), self.delete),
                         (tr("New folder…"), self.new_folder), (tr("Rename folder…"), self.rename_folder),
                         (tr("Delete folder"), self.delete_folder), (tr("Import HTML…"), self.import_html), (tr("Export HTML…"), self.export_html)]:
            b = QPushButton(text)
            b.clicked.connect(fn)
            side.addWidget(b)
        side.addStretch()
        split = QSplitter()
        split.addWidget(left)
        split.addWidget(self.table)
        split.setStretchFactor(1, 3)
        body = QHBoxLayout()
        body.addWidget(split, 1)
        body.addLayout(side)
        lay = QVBoxLayout(self)
        lay.addWidget(self.search)
        lay.addLayout(body)
        self.refresh()

    # ---- data
    def refresh(self):
        sel = self._folder_id()
        self.tree.blockSignals(True)
        self.tree.clear()
        labels, view = ROOT_LABELS(), self.store.view()
        all_item = QTreeWidgetItem([tr("All bookmarks")])
        all_item.setData(0, Qt.ItemDataRole.UserRole, "all")
        self.tree.addTopLevelItem(all_item)

        def add(parent, node):
            for ch in node["children"]:
                it = QTreeWidgetItem(parent, [ch["name"]])
                it.setData(0, Qt.ItemDataRole.UserRole, ch["id"])
                add(it, ch)
        for rid in (M.ROOT_TOOLBAR, M.ROOT_MENU, M.ROOT_UNFILED, M.RECOVERED):
            if rid == M.RECOVERED and not view[rid]["bookmarks"] and not view[rid]["children"]:
                continue
            it = QTreeWidgetItem([labels[rid]])
            it.setData(0, Qt.ItemDataRole.UserRole, rid)
            self.tree.addTopLevelItem(it)
            add(it, view[rid])
        self.tree.expandAll()
        self.tree.blockSignals(False)
        found = self._find(sel) or all_item
        self.tree.setCurrentItem(found)
        self.tag_list.blockSignals(True)
        self.tag_list.clear()
        for n, c in self.store.all_tags().items():
            li = QListWidgetItem(f"{n} ({c})")
            li.setData(Qt.ItemDataRole.UserRole, n)
            self.tag_list.addItem(li)
        self.tag_list.blockSignals(False)
        self.refresh_list()

    def _find(self, fid):
        it = QTreeWidgetItemIterator = None  # noqa: F841
        stack = [self.tree.topLevelItem(i) for i in range(self.tree.topLevelItemCount())]
        while stack:
            n = stack.pop()
            if n.data(0, Qt.ItemDataRole.UserRole) == fid:
                return n
            stack.extend(n.child(i) for i in range(n.childCount()))
        return None

    def _folder_id(self):
        it = self.tree.currentItem()
        return it.data(0, Qt.ItemDataRole.UserRole) if it else "all"

    def refresh_list(self):
        tags = self.tag_list.selectedItems()
        tag = tags[0].data(Qt.ItemDataRole.UserRole) if tags else None
        fid = self._folder_id()
        items = self.store.list(tag=tag, text=self.search.text() or None)
        if not tag and fid != "all":
            view = self.store.view()
            def node(n, want):
                if n["id"] == want:
                    return n
                for c in n["children"]:
                    r = node(c, want)
                    if r:
                        return r
            top = next((node(view[r], fid) for r in (M.ROOT_TOOLBAR, M.ROOT_MENU, M.ROOT_UNFILED, M.RECOVERED) if node(view[r], fid)), None)
            ids = {b["id"] for b in top["bookmarks"]} if top else set()
            items = [i for i in items if i["id"] in ids]
        labels = ROOT_LABELS()
        self.table.setRowCount(len(items))
        for r, it in enumerate(items):
            f = it["folder"]
            folder = labels.get(f) or " / ".join(self.store.folder_path(f)) or labels[M.RECOVERED]
            for c, v in enumerate((it["title"], it["url"], ", ".join(self.store.tags_of(it)), folder)):
                cell = QTableWidgetItem(v)
                cell.setData(Qt.ItemDataRole.UserRole, it["id"])
                self.table.setItem(r, c, cell)

    def _current_id(self):
        r = self.table.currentRow()
        return self.table.item(r, 0).data(Qt.ItemDataRole.UserRole) if r >= 0 else None

    # ---- actions
    def open(self):
        bid = self._current_id()
        if bid and self.open_cb:
            self.open_cb(self.store.bookmarks[bid]["url"])

    def edit(self):
        bid = self._current_id()
        if not bid:
            return
        d = BookmarkEditDialog(self.store, self, item=self.store.bookmarks[bid])
        if d.exec():
            _, title, folder, tags = d.values()
            self.store.update_bookmark(bid, title=title, folder=folder, tags=tags)
            self.ctx.after_vault_change()
            self.refresh()

    def delete(self):
        bid = self._current_id()
        if bid:
            self.store.remove_bookmark(bid)
            self.ctx.after_vault_change()
            self.refresh()

    def _real_folder(self):
        fid = self._folder_id()
        return fid if fid.startswith("f:") else None

    def new_folder(self):
        name, ok = QInputDialog.getText(self, tr("New folder…"), tr("Folder name"))
        if ok and name.strip():
            fid = self._folder_id()
            self.store.add_folder(name.strip(), fid if (fid.startswith("f:") or fid in M.ROOTS) else M.ROOT_TOOLBAR)
            self.ctx.after_vault_change()
            self.refresh()

    def rename_folder(self):
        fid = self._real_folder()
        if fid:
            name, ok = QInputDialog.getText(self, tr("Rename folder…"), tr("Folder name"), text=self.store.folders[fid]["name"])
            if ok and name.strip():
                self.store.rename_folder(fid, name.strip())
                self.ctx.after_vault_change()
                self.refresh()

    def delete_folder(self):
        fid = self._real_folder()
        if fid and QMessageBox.question(self, tr("IUK Browser"), tr("Delete this folder and everything in it?")) == QMessageBox.StandardButton.Yes:
            self.store.delete_folder(fid)
            self.ctx.after_vault_change()
            self.refresh()

    def import_html(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Import HTML…"), "", "HTML (*.html *.htm)")
        if path:
            with open(path, encoding="utf-8", errors="replace") as f:
                n = self.store.import_html(f.read())
            _msg(self, tr("Imported {} bookmarks.", n))
            self.ctx.after_vault_change()
            self.refresh()

    def export_html(self):
        path, _ = QFileDialog.getSaveFileName(self, tr("Export HTML…"), "iuk-bookmarks.html", "HTML (*.html)")
        if path:
            with open(path, "w", encoding="utf-8") as f:
                f.write(self.store.export_html())


# ================================================================== pairing (QR)
class PairDialog(_Cancellable, QDialog):
    """Show a QR for another device to scan, or scan one to join an account (camera, image file or pasted code).

    With a sync server the QR is a ONE-TIME code (IUKB2): it never contains the account key, works once and expires after
    two minutes; this dialog notices when the other device has used it. Without a server it falls back to a direct code
    (IUKB1) that does contain the key, as the 1.x extension used."""

    from PySide6.QtCore import Signal
    paired = Signal(object)

    def __init__(self, ctx, parent=None, mode="show"):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(tr("Pair devices"))
        self.setMinimumWidth(480)
        self._pid = None
        self._polling = False
        self._camera = None
        self._left = 0
        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_show(), tr("Show QR (this device)"))
        self.tabs.addTab(self._build_scan(), tr("Scan QR (new device)"))
        self.tabs.setCurrentIndex(1 if mode == "scan" else 0)
        lay = QVBoxLayout(self)
        lay.addWidget(self.tabs)
        lay.addWidget(self._make_progress())
        self._tick_timer = QTimer(self)
        self._tick_timer.setInterval(1000)
        self._tick_timer.timeout.connect(self._tick)

    # ---------------------------------------------------------------- show
    def _build_show(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        st = self.ctx.account.status()
        if not st["setup"] or not st["unlocked"]:
            lay.addWidget(QLabel(tr("Unlock IUK Browser first, then come back here.") if st["setup"] else tr("This device is not set up yet.")))
            return w
        self.one_time = bool(st["server"])
        warn = QLabel(tr("This QR works once and expires in 2 minutes. It does not contain your secret key, but anyone who scans it before your own device could join your account. Show it only to your own second device.")
                      if self.one_time else
                      tr("The QR contains your secret key. Anyone who scans it, or sees a photo or screenshot of it, gets full access to your synced bookmarks and passwords. Show it only to your own second device."))
        warn.setWordWrap(True)
        self.show_secret = _secret_edit(tr("Type your secret connectivity key again"))
        self.show_btn = QPushButton(tr("Show pairing QR"))
        self.show_btn.clicked.connect(self._show_qr)
        self.show_status = QLabel()
        self.show_status.setWordWrap(True)
        self.qr_label = QLabel()
        self.qr_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.copy_btn = QPushButton(tr("Copy code instead"))
        self.copy_btn.hide()
        self.copy_btn.clicked.connect(lambda: (self.ctx.clipboard.copy_secret(self._code), self.show_status.setText(tr("Pairing code copied. Treat it like your key."))))
        for x in (warn, self.show_secret, self.show_btn, self.show_status, self.qr_label, self.copy_btn):
            lay.addWidget(x)
        self._code = ""
        return w

    def _show_qr(self):
        s = self.show_secret.text()
        self.show_btn.setEnabled(False)
        self.show_status.setText(tr("Checking key (takes a moment)…"))

        def work(cancel):
            if self.one_time:
                return self.ctx.account.create_pairing_offer(s, cancel=cancel)
            return self.ctx.account.pairing_payload(s, cancel=cancel), None

        def done(res, err):
            self.show_btn.setEnabled(True)
            if err:
                self.show_status.setText(str(err))
                return
            code, pid = res
            self.show_secret.clear()
            self._code, self._pid = code, pid
            self.qr_label.setPixmap(qrtools.qr_pixmap(code, 320))
            self.copy_btn.show()
            self._left = pairing.TTL_SECONDS if pid else 90
            self._tick()
            self._tick_timer.start()
        self._start(work, done)

    def _on_cancelled(self):
        self.show_btn.setEnabled(True)
        self.show_status.setText(tr("Cancelled."))

    def _tick(self):
        if self._left <= 0:
            self._hide_qr(tr("QR hidden."))
            return
        self.show_status.setText(tr("Hides in {} s", self._left))
        if self._pid and self._left % 2 == 0 and not self._polling:
            self._poll()
        self._left -= 1

    def _poll(self):
        pid = self._pid
        self._polling = True

        def done(pending, err):
            self._polling = False
            if pid == self._pid and not err and pending is False:
                self._pid = None                                   # already used: nothing left to cancel
                self._hide_qr(tr("Paired. This QR no longer works."))
        self.ctx.run_async(lambda: self.ctx.account.pairing_pending(pid), done)

    def _hide_qr(self, message: str):
        self._tick_timer.stop()
        self.qr_label.clear()
        self._code = ""
        self.copy_btn.hide()
        self.show_status.setText(message)
        self._cancel_offer()

    def _cancel_offer(self):
        pid, self._pid = self._pid, None
        if pid and self.ctx.account.is_unlocked():
            self.ctx.run_async(lambda: self.ctx.account.cancel_pairing(pid), lambda *_: None)

    # ---------------------------------------------------------------- scan
    def _build_scan(self):
        w = QWidget()
        lay = QVBoxLayout(w)
        row = QHBoxLayout()
        cam, img = QPushButton(tr("Start camera")), QPushButton(tr("Choose image…"))
        cam.clicked.connect(self._start_camera)
        img.clicked.connect(self._from_image)
        row.addWidget(cam)
        row.addWidget(img)
        self.video_label = QLabel()
        self.video_label.setMinimumHeight(240)
        self.video_label.setAlignment(Qt.AlignmentFlag.AlignCenter)
        self.video_label.hide()
        self.paste = QPlainTextEdit()
        self.paste.setPlaceholderText(tr("Or paste a pairing code (starts with IUKB1: or IUKB2:)"))
        self.paste.setMaximumHeight(70)
        use = QPushButton(tr("Use pasted code"))
        use.clicked.connect(lambda: self.offer(self.paste.toPlainText()))
        self.scan_status = QLabel()
        self.scan_status.setWordWrap(True)
        self.confirm_box = QWidget()
        QVBoxLayout(self.confirm_box)
        lay.addLayout(row)
        for x in (self.video_label, self.paste, use, self.scan_status, self.confirm_box):
            lay.addWidget(x)
        return w

    def _from_image(self):
        path, _ = QFileDialog.getOpenFileName(self, tr("Choose image…"), "", "Images (*.png *.jpg *.jpeg *.bmp *.webp)")
        if path:
            text = qrtools.decode_qimage(QImage(path))
            if text:
                self.offer(text)
            else:
                self.scan_status.setText(tr("No QR code found in that image."))

    def _start_camera(self):
        try:
            from PySide6.QtMultimedia import QCamera, QMediaCaptureSession, QMediaDevices, QVideoSink
        except ImportError:
            self.scan_status.setText(tr("Camera not available. Choose an image or paste the code instead."))
            return
        dev = QMediaDevices.defaultVideoInput()
        if dev.isNull():
            self.scan_status.setText(tr("Camera not available. Choose an image or paste the code instead."))
            return
        self._camera = QCamera(dev)
        self._session = QMediaCaptureSession()
        self._sink = QVideoSink()
        self._session.setCamera(self._camera)
        self._session.setVideoSink(self._sink)
        self._sink.videoFrameChanged.connect(self._frame)
        self.video_label.show()
        self.scan_status.setText(tr("Point the camera at the QR code…"))
        self._camera.start()

    def _frame(self, frame):
        img = frame.toImage()
        if img.isNull():
            return
        from PySide6.QtGui import QPixmap
        self.video_label.setPixmap(QPixmap.fromImage(img).scaledToWidth(420))
        text = qrtools.decode_qimage(img)
        if text and pairing.kind(text):
            self.offer(text)

    def _stop_camera(self):
        if self._camera:
            self._camera.stop()
            self._camera = None
        self.video_label.hide()

    def offer(self, text):
        """Entry point for a scanned or pasted code (also used by tests)."""
        kind = pairing.kind(text)
        if not kind:
            self.scan_status.setText(tr("This is not an IUK Browser pairing code"))
            return
        self._stop_camera()                                       # stop scanning at once: a one-time code must be redeemed only once
        if kind == "direct":
            try:
                self._confirm(pairing.decode(text))
            except pairing.PairingError as e:
                self.scan_status.setText(str(e))
            return
        try:
            pairing.decode_offer(text)
        except pairing.PairingError as e:
            self.scan_status.setText(str(e))
            return
        self.scan_status.setText(tr("Checking…"))

        def done(p, err):
            if err:
                self.scan_status.setText(str(err))
            else:
                self.scan_status.clear()
                self._confirm(p)
        self.ctx.run_async(lambda: Account.redeem_pairing(text), done)

    def _confirm(self, p):
        self.scan_status.clear()
        lay = self.confirm_box.layout()
        while lay.count():
            lay.takeAt(0).widget().deleteLater()
        label = QLabel(tr("Join account {} on {}?", p.username, p.server or tr("(no sync server in the code)")))
        label.setWordWrap(True)
        join = QPushButton(tr("Join this account"))
        join.clicked.connect(lambda: (self.paired.emit(p), self.accept()))
        lay.addWidget(label)
        lay.addWidget(join)

    def done(self, r):
        self._stop_camera()
        self._tick_timer.stop()
        self._cancel_offer()                                      # closing the dialog withdraws an unused QR
        super().done(r)


# ================================================================== relay second factor
class TwoFactorDialog(QDialog):
    """Enable / disable the relay's optional TOTP second factor."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(tr("Second factor for the sync relay"))
        self.setMinimumWidth(460)
        self.lay = QVBoxLayout(self)
        self.status = QLabel(tr("Checking…"))
        self.status.setWordWrap(True)
        self.lay.addWidget(self.status)
        self.body = QVBoxLayout()
        self.lay.addLayout(self.body)
        self._t = None
        self.ctx.run_async(self._probe, self._probed)

    def _clear(self):
        while self.body.count():
            w = self.body.takeAt(0).widget()
            if w:
                w.deleteLater()

    def _probe(self):
        self._t = self.ctx.account.twofa()
        return self._t.twofa_status()

    def _probed(self, enabled, err):
        self._clear()
        if err:
            self.status.setText(str(err))
            return
        if enabled:
            self.status.setText(tr("A second factor is ON. New devices and new sessions must enter an authenticator code."))
            self.code = QLineEdit()
            self.code.setPlaceholderText(tr("Authenticator code or recovery code"))
            b = QPushButton(tr("Turn off"))
            b.clicked.connect(self._disable)
            self.body.addWidget(self.code)
            self.body.addWidget(b)
        else:
            self.status.setText(tr("Protect your sync account with an authenticator app. Even if your sync token leaks, nobody can download your encrypted data without a code."))
            b = QPushButton(tr("Turn on…"))
            b.clicked.connect(self._enroll)
            self.body.addWidget(b)

    def _enroll(self):
        def done(r, err):
            if err:
                self.status.setText(str(err))
                return
            self._clear()
            self.status.setText(tr("Scan this QR with your authenticator app (or type the secret), then enter the 6-digit code."))
            qr = QLabel()
            qr.setAlignment(Qt.AlignmentFlag.AlignCenter)
            qr.setPixmap(qrtools.qr_pixmap(r["otpauth"], 260))
            sec = QLineEdit(r["secret"])
            sec.setReadOnly(True)
            self.code = QLineEdit()
            self.code.setPlaceholderText("123456")
            ok = QPushButton(tr("Confirm"))
            ok.clicked.connect(self._confirm)
            for x in (qr, sec, self.code, ok):
                self.body.addWidget(x)
        self.ctx.run_async(lambda: self._t.enroll(), done)

    def _confirm(self):
        code = self.code.text()

        def done(codes, err):
            if err:
                self.status.setText(str(err))
                return
            self.ctx.account._relay_session = self._t.session
            self._clear()
            self.status.setText(tr("Second factor is ON. Save these recovery codes somewhere safe: each works once if you lose your phone."))
            box = QPlainTextEdit("\n".join(codes))
            box.setReadOnly(True)
            self.body.addWidget(box)
        self.ctx.run_async(lambda: self._t.confirm(code), done)

    def _disable(self):
        code = self.code.text().strip()

        def work():
            self._t.disable(**({"recovery": code} if "-" in code else {"otp": code}))

        def done(_r, err):
            if err:
                self.status.setText(str(err))
            else:
                self.ctx.account._relay_session = None
                self.ctx.run_async(self._probe, self._probed)
        self.ctx.run_async(work, done)


# ================================================================== site permissions
def permission_label(name: str) -> str:
    labels = {"Notifications": tr("Notifications"), "Geolocation": tr("Location"), "MediaVideoCapture": tr("Camera"),
              "MediaAudioCapture": tr("Microphone"), "MediaAudioVideoCapture": tr("Camera and microphone"),
              "DesktopVideoCapture": tr("Screen sharing"), "DesktopAudioVideoCapture": tr("Screen sharing"),
              "ClipboardReadWrite": tr("Clipboard"), "MouseLock": tr("Mouse pointer lock"), "LocalFontsAccess": tr("Local fonts")}
    return labels.get(name, name)


class PermissionsDialog(QDialog):
    """Per-site permissions the browser remembers (location, camera, notifications, ...): allow, block or forget each one."""

    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx, self.profile = ctx, ctx.profiles.normal
        self.setWindowTitle(tr("Site permissions"))
        self.resize(640, 420)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search"))
        self.search.textChanged.connect(self.refresh)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([tr("Site"), tr("Permission"), tr("State")])
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        side = QVBoxLayout()
        for text, fn in [(tr("Allow"), lambda: self._apply("grant")), (tr("Block"), lambda: self._apply("deny")),
                         (tr("Reset"), lambda: self._apply("reset")), (tr("Reset all"), self.reset_all)]:
            b = QPushButton(text)
            b.clicked.connect(fn)
            side.addWidget(b)
        side.addStretch()
        body = QHBoxLayout()
        body.addWidget(self.table, 1)
        body.addLayout(side)
        lay = QVBoxLayout(self)
        lay.addWidget(self.search)
        lay.addLayout(body)
        self._perms: list = []
        self.refresh()

    def refresh(self):
        text = self.search.text().lower()
        states = {"Granted": tr("Allowed"), "Denied": tr("Blocked")}
        self._perms = [p for p in self.profile.listAllPermissions() if p.state().name in states
                       and text in (p.origin().host() + " " + permission_label(p.permissionType().name)).lower()]
        self._perms.sort(key=lambda p: (p.origin().host(), p.permissionType().name))
        self.table.setRowCount(len(self._perms))
        for i, p in enumerate(self._perms):
            for j, v in enumerate((p.origin().host() or p.origin().toString(), permission_label(p.permissionType().name), states[p.state().name])):
                self.table.setItem(i, j, QTableWidgetItem(v))

    def _apply(self, action: str):
        r = self.table.currentRow()
        if 0 <= r < len(self._perms):
            getattr(self._perms[r], action)()
            self.refresh()

    def reset_all(self):
        if QMessageBox.question(self, tr("IUK Browser"), tr("Forget all saved site permissions?")) == QMessageBox.StandardButton.Yes:
            for p in self.profile.listAllPermissions():
                p.reset()
            self.refresh()


# ================================================================== small lists
class HistoryDialog(QDialog):
    def __init__(self, ctx, parent=None, open_cb=None):
        super().__init__(parent)
        self.ctx, self.open_cb = ctx, open_cb
        self.setWindowTitle(tr("History"))
        self.resize(720, 460)
        self.search = QLineEdit()
        self.search.setPlaceholderText(tr("Search"))
        self.search.textChanged.connect(self.refresh)
        self.table = QTableWidget(0, 3)
        self.table.setHorizontalHeaderLabels([tr("Name"), tr("Address"), tr("Visits")])
        self.table.setEditTriggers(QAbstractItemView.EditTrigger.NoEditTriggers)
        self.table.setSelectionBehavior(QAbstractItemView.SelectionBehavior.SelectRows)
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.ResizeMode.Stretch)
        self.table.itemDoubleClicked.connect(lambda it: open_cb and open_cb(self.table.item(it.row(), 1).text()))
        clear = QPushButton(tr("Clear history"))
        clear.clicked.connect(lambda: (ctx.history.clear(), self.refresh()))
        lay = QVBoxLayout(self)
        for w in (self.search, self.table, clear):
            lay.addWidget(w)
        self.refresh()

    def refresh(self):
        rows = self.ctx.history.search(self.search.text())
        self.table.setRowCount(len(rows))
        for i, (url, title, _last, count) in enumerate(rows):
            for j, v in enumerate((title or url, url, str(count))):
                self.table.setItem(i, j, QTableWidgetItem(v))


class DownloadsDialog(QDialog):
    def __init__(self, ctx, parent=None):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle(tr("Downloads"))
        self.resize(560, 360)
        self.list = QListWidget()
        self.list.itemDoubleClicked.connect(lambda it: QDesktopServices.openUrl(QUrl.fromLocalFile(it.data(Qt.ItemDataRole.UserRole))))
        self.bar = QProgressBar()
        lay = QVBoxLayout(self)
        lay.addWidget(self.list)
        lay.addWidget(self.bar)
        self.timer = QTimer(self)
        self.timer.timeout.connect(self.refresh)
        self.timer.start(500)
        self.refresh()

    def refresh(self):
        self.list.clear()
        for d in self.ctx.downloads:
            tot, rec = d.totalBytes(), d.receivedBytes()
            pct = f"{100 * rec // tot}%" if tot > 0 else ""
            it = QListWidgetItem(f"{d.downloadFileName()}   {pct}   {d.state().name}")
            it.setData(Qt.ItemDataRole.UserRole, f"{d.downloadDirectory()}/{d.downloadFileName()}")
            self.list.addItem(it)


def default_download_dir() -> str:
    return QStandardPaths.writableLocation(QStandardPaths.StandardLocation.DownloadLocation)
