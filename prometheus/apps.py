"""Window class -> the application name the launcher shows.

Window classes are slugs ("code-oss", "org.gnome.Nautilus"). The desktop
entries are indexed once: StartupWMClass is authoritative, the file name is
the fallback, and "org.gnome.Nautilus" is also reachable as "nautilus".
Ported from promethee-linux/patches/linux-active-window.js.
"""

from __future__ import annotations

import os
import re
from pathlib import Path

_NAME = re.compile(r"^Name=(.+)$", re.M)
_WMCLASS = re.compile(r"^StartupWMClass=(.+)$", re.M)
_EXEC_URL = re.compile(r"^Exec=.*?https?://([^/\s\"']+)", re.M)
# Chromium web apps: "brave-youtube.com__-Default", "chromium-mail.google.com_mail_-Default"
_WEBAPP_CLASS = re.compile(r"^[a-z][a-z-]*?-((?:[a-z0-9-]+\.)+[a-z]{2,})_", re.I)


def webapp_key(host: str) -> str:
    host = host.lower()
    return "webapp:" + (host[4:] if host.startswith("www.") else host)


def data_dirs() -> list[Path]:
    home = os.environ.get("XDG_DATA_HOME") or os.path.expanduser("~/.local/share")
    rest = os.environ.get("XDG_DATA_DIRS") or "/usr/local/share:/usr/share"
    return [Path(home)] + [Path(p) for p in rest.split(":") if p]


def build_index(dirs: list[Path] | None = None) -> dict[str, str]:
    index: dict[str, str] = {}
    for base in dirs if dirs is not None else data_dirs():
        apps = base / "applications"
        try:
            entries = sorted(apps.iterdir())
        except OSError:
            continue
        for entry in entries:
            if entry.suffix != ".desktop":
                continue
            try:
                content = entry.read_text(encoding="utf-8", errors="replace")
            except OSError:
                continue
            # Only the [Desktop Entry] group: actions redefine Name.
            parts = re.split(r"^\[", content, flags=re.M)
            main = parts[1] if len(parts) > 1 else content
            name = _NAME.search(main)
            if not name:
                continue
            name_s = name.group(1).strip()
            wm = _WMCLASS.search(main)
            stem = entry.stem.lower()
            if wm:
                index.setdefault(wm.group(1).strip().lower(), name_s)
            index.setdefault(stem, name_s)
            index.setdefault(stem.split(".")[-1], name_s)
            url = _EXEC_URL.search(main)
            if url:  # a web app: reachable by the host its window class carries
                index.setdefault(webapp_key(url.group(1)), name_s)
    return index


def title_case(slug: str) -> str:
    words = re.sub(r"[-_.]+", " ", slug).split()
    return " ".join(w[:1].upper() + w[1:] for w in words)


class AppNames:
    def __init__(self, index: dict[str, str] | None = None):
        self._index = index

    @property
    def index(self) -> dict[str, str]:
        if self._index is None:
            self._index = build_index()
        return self._index

    def refresh(self) -> None:
        self._index = None

    def name(self, wm_class: str | None, exe: str | None = None) -> str | None:
        candidates: list[str] = []
        if wm_class:
            web = _WEBAPP_CLASS.match(wm_class)
            if web:
                candidates.append(webapp_key(web.group(1)))
            candidates += [wm_class, wm_class.split(".")[-1]]
        if exe:
            candidates.append(os.path.basename(exe))
        for c in candidates:
            hit = self.index.get(c.lower())
            if hit:
                return hit
        web = _WEBAPP_CLASS.match(wm_class) if wm_class else None
        if web:
            return web.group(1)  # an unknown web app: its host reads better than the class
        fallback = wm_class or (os.path.basename(exe) if exe else "")
        return title_case(fallback) if fallback else None
