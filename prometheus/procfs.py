"""What a terminal window is running: the foreground process of its tty.

The compositor only knows the terminal ("foot"). The terminal's shell owns a
pty; that pty's foreground process group (`tpgid` in /proc/<pid>/stat) is
what the user is looking at: nvim, btop, ssh. Ported from the idea in
ax1g/quickshell-screentime-plugin (python/resolve_app.py).
"""

from __future__ import annotations

import os
from collections import deque

# Window classes of terminal emulators, lowercased. Agent windows
# (org.omarchy.agent.*) are left out on purpose: they keep their own name.
TERMINAL_CLASSES = {
    "foot", "footclient", "alacritty", "kitty", "com.mitchellh.ghostty", "ghostty",
    "org.wezfurlong.wezterm", "wezterm", "xterm", "urxvt", "st", "konsole",
    "org.kde.konsole", "org.omarchy.terminal",
}

# A shell in the foreground means "just the terminal".
SHELLS = {"bash", "zsh", "fish", "sh", "dash", "ksh", "tcsh", "csh", "nu", "xonsh", "elvish", "ion"}

MAX_DEPTH = 4


def is_terminal(wm_class: str | None) -> bool:
    return bool(wm_class) and wm_class.lower() in TERMINAL_CLASSES


def stat(pid: int, proc: str = "/proc") -> dict | None:
    try:
        with open(f"{proc}/{pid}/stat", "rb") as fh:
            data = fh.read().decode(errors="replace")
    except OSError:
        return None
    try:
        comm = data[data.index("(") + 1 : data.rindex(")")]
        f = data[data.rindex(")") + 1 :].split()
        return {"comm": comm, "ppid": int(f[1]), "pgrp": int(f[2]), "tty": int(f[4]), "tpgid": int(f[5])}
    except (ValueError, IndexError):
        return None


def name(pid: int, proc: str = "/proc") -> str | None:
    """Basename of argv[0], falling back to comm; "-bash" is "bash"."""
    st = stat(pid, proc)
    if st is None:
        return None
    n = st["comm"]
    try:
        with open(f"{proc}/{pid}/cmdline", "rb") as fh:
            argv0 = fh.read().split(b"\0", 1)[0].decode(errors="replace")
        if argv0:
            n = os.path.basename(argv0)
    except OSError:
        pass
    return n.removeprefix("-") or None


def children(pid: int, proc: str = "/proc") -> list[int]:
    out: list[int] = []
    try:
        tasks = os.listdir(f"{proc}/{pid}/task")
    except OSError:
        return out
    for tid in tasks:
        try:
            with open(f"{proc}/{pid}/task/{tid}/children") as fh:
                out.extend(int(p) for p in fh.read().split())
        except (OSError, ValueError):
            continue
    return out


def foreground(terminal_pid: int, proc: str = "/proc") -> str | None:
    """Name of the foreground process in the terminal, or None for a bare shell."""
    queue = deque([(terminal_pid, 0)])
    seen = set()
    while queue:
        pid, depth = queue.popleft()
        if pid in seen:
            continue
        seen.add(pid)
        st = stat(pid, proc)
        if st is None:
            continue
        if pid != terminal_pid and st["tty"] != 0 and st["tpgid"] > 0:
            fg = name(st["tpgid"], proc)
            if fg and fg not in SHELLS:
                return fg
            return None
        if depth < MAX_DEPTH:
            queue.extend((c, depth + 1) for c in children(pid, proc))
    return None
