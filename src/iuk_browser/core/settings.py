"""User settings (JSON file with defaults)."""
from __future__ import annotations

import json
from pathlib import Path

SEARCH_ENGINES = {
    "DuckDuckGo": "https://duckduckgo.com/?q={}",
    "Google": "https://www.google.com/search?q={}",
    "Bing": "https://www.bing.com/search?q={}",
    "Startpage": "https://www.startpage.com/do/search?q={}",
    "Brave": "https://search.brave.com/search?q={}",
}

DEFAULTS = {
    "homepage": "https://duckduckgo.com/",
    "sync_server": "",
    "search_engine": "DuckDuckGo",
    "language": "auto",
    "theme": {"id": "system"},
    "display": {"mode": "off", "sites": [], "brightness": 100, "contrast": 100, "sepia": 0, "keepMedia": True},
    "force_dark_pages": False,
    "blocker": {"enabled": True, "allow_sites": [], "extra_lists": []},
    "clipboard_clear_seconds": 30,
    "auto_lock_minutes": 15,
    "sync_interval_minutes": 5,
    "restore_session": True,
    "session_urls": [],
    "check_updates": True,
    "update_channel": "stable",
    "last_update_check": 0,
}


class Settings:
    def __init__(self, path: Path | None = None):
        self.path = Path(path) if path else None
        self.data = json.loads(json.dumps(DEFAULTS))
        if self.path and self.path.exists():
            try:
                self.data.update(json.loads(self.path.read_text("utf-8")))
            except (ValueError, OSError):
                pass

    def __getitem__(self, k):
        return self.data[k]

    def get(self, k, default=None):
        return self.data.get(k, default)

    def set(self, k, v) -> None:
        self.data[k] = v
        self.save()

    def save(self) -> None:
        if self.path:
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp = self.path.with_suffix(".tmp")
            tmp.write_text(json.dumps(self.data, indent=1), "utf-8")
            tmp.replace(self.path)

    def search_url(self, query: str) -> str:
        from urllib.parse import quote_plus
        tpl = SEARCH_ENGINES.get(self.data["search_engine"], SEARCH_ENGINES["DuckDuckGo"])
        return tpl.replace("{}", quote_plus(query))
