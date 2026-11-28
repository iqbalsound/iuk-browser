"""Browsing history (SQLite)."""
from __future__ import annotations

import sqlite3
import time
from pathlib import Path


class History:
    def __init__(self, path: Path | str):
        self.db = sqlite3.connect(str(path), check_same_thread=False)
        self.db.execute("CREATE TABLE IF NOT EXISTS visits (url TEXT PRIMARY KEY, title TEXT, last INTEGER, count INTEGER)")
        self.db.commit()

    def add(self, url: str, title: str = "") -> None:
        if not url.lower().startswith(("http://", "https://", "file://")):
            return
        now = int(time.time())
        self.db.execute("INSERT INTO visits(url,title,last,count) VALUES(?,?,?,1) ON CONFLICT(url) DO UPDATE SET "
                        "title=CASE WHEN excluded.title<>'' THEN excluded.title ELSE title END, last=excluded.last, count=count+1",
                        (url, title, now))
        self.db.commit()

    def search(self, text: str = "", limit: int = 500) -> list[tuple]:
        like = f"%{text}%"
        return self.db.execute("SELECT url,title,last,count FROM visits WHERE url LIKE ? OR title LIKE ? ORDER BY last DESC LIMIT ?",
                               (like, like, limit)).fetchall()

    def suggest(self, prefix: str, limit: int = 8) -> list[str]:
        return [r[0] for r in self.db.execute("SELECT url FROM visits WHERE url LIKE ? OR title LIKE ? ORDER BY count DESC, last DESC LIMIT ?",
                                              (f"%{prefix}%", f"%{prefix}%", limit))]

    def clear(self) -> None:
        self.db.execute("DELETE FROM visits")
        self.db.commit()

    def close(self) -> None:
        self.db.close()
