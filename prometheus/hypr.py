"""Hyprland: follow the focused window through the event socket.

`.socket2.sock` streams `event>>data` lines; on a focus or title change the
focused window is read once from `.socket.sock` (`j/activewindow`). The
instance directory is looked up again on every reconnect, so a restarted
Hyprland is picked up without restarting the daemon.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Awaitable, Callable

log = logging.getLogger("prometheus.hypr")

FOCUS_EVENTS = {"activewindow", "activewindowv2", "windowtitle", "windowtitlev2", "closewindow"}


def instance_dir() -> Path | None:
    runtime = os.environ.get("XDG_RUNTIME_DIR") or f"/run/user/{os.getuid()}"
    base = Path(runtime) / "hypr"
    sig = os.environ.get("HYPRLAND_INSTANCE_SIGNATURE")
    if sig and (base / sig / ".socket2.sock").exists():
        return base / sig
    # The signature changes when Hyprland restarts; take the newest live one.
    try:
        live = [d for d in base.iterdir() if (d / ".socket2.sock").exists()]
    except OSError:
        return None
    return max(live, key=lambda d: d.stat().st_mtime, default=None)


async def request(command: str, directory: Path) -> str | None:
    try:
        reader, writer = await asyncio.wait_for(
            asyncio.open_unix_connection(str(directory / ".socket.sock")), 2
        )
    except (OSError, asyncio.TimeoutError):
        return None
    try:
        writer.write(command.encode())
        await writer.drain()
        data = await asyncio.wait_for(reader.read(), 2)
        return data.decode(errors="replace")
    except (OSError, asyncio.TimeoutError):
        return None
    finally:
        writer.close()


async def active_window(directory: Path) -> dict | None:
    raw = await request("j/activewindow", directory)
    if not raw:
        return None
    try:
        win = json.loads(raw)
    except json.JSONDecodeError:
        return None
    if not isinstance(win, dict) or not (win.get("class") or win.get("initialClass")):
        return None
    return win


def exe_of(pid) -> str | None:
    try:
        return os.readlink(f"/proc/{int(pid)}/exe")
    except (OSError, TypeError, ValueError):
        return None


async def follow(on_window: Callable[[dict | None], Awaitable[None] | None]) -> None:
    """Call `on_window` with the focused window (or None) on every change. Never returns."""
    delay = 1.0
    while True:
        directory = instance_dir()
        if directory is None:
            await asyncio.sleep(min(delay, 30))
            delay *= 2
            continue
        try:
            reader, writer = await asyncio.open_unix_connection(str(directory / ".socket2.sock"))
        except OSError as e:
            log.warning("event socket unavailable: %s", e)
            await asyncio.sleep(min(delay, 30))
            delay *= 2
            continue
        log.info("following %s", directory.name)
        delay = 1.0
        try:
            await _emit(on_window, await active_window(directory))
            while True:
                line = await reader.readline()
                if not line:
                    break
                event = line.decode(errors="replace").split(">>", 1)[0]
                if event in FOCUS_EVENTS:
                    await _emit(on_window, await active_window(directory))
        except OSError as e:
            log.warning("event socket dropped: %s", e)
        finally:
            writer.close()
        await asyncio.sleep(1)


async def _emit(cb, win) -> None:
    result = cb(win)
    if asyncio.iscoroutine(result):
        await result
